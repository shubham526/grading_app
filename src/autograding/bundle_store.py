"""Immutable filesystem store for validated instructor autograding bundles.

Layout::

    <assessment workspace>/
        autograding/
            <assessment-component>/
                bundles/
                    index.json
                    <bundle-component>/
                        bundle.json
                        originals/
                            autograder.json
                            tests/...
                            support/...          # optional
                            requirements.txt     # optional

Bundle directories and original bytes are immutable after a successful commit.
Only the small per-assessment ``index.json`` is updated when a new distinct
bundle is imported.
"""

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.submissions.file_store import (
    atomic_write_json,
    compute_file_sha256,
    copy_regular_file,
    read_json_object,
    reject_symlink,
    safe_path_component,
    sha256_json,
)

from .config import load_autograding_config
from .bundles import (
    BundleFile,
    BundleImportResult,
    StoredTestBundle,
    TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION,
    TEST_BUNDLE_MANIFEST_SCHEMA_VERSION,
    ValidatedTestBundle,
    validate_test_bundle,
)
from .errors import (
    AutogradingBundleIntegrityError,
    AutogradingBundleStorageError,
    AutogradingBundleValidationError,
)
from .ids import generate_test_bundle_id
from .models import TestBundleReference
from .validation import normalize_bundle_relative_path, reject_symlink_chain


AUTOGRADING_DIRECTORY = "autograding"
BUNDLES_DIRECTORY = "bundles"
BUNDLE_INDEX_FILENAME = "index.json"
BUNDLE_MANIFEST_FILENAME = "bundle.json"
BUNDLE_ORIGINALS_DIRECTORY = "originals"
BUNDLE_INDEX_SCHEMA_VERSION = "1.0"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_text(value, name):
    text = "" if value is None else str(value).strip()
    if not text:
        raise AutogradingBundleValidationError("%s must not be empty" % name)
    return text


def _bundle_fingerprint_from_files(files):
    return sha256_json(
        {
            "schema_version": TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION,
            "files": [
                {
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in sorted(files, key=lambda item: item.relative_path.casefold())
            ],
        }
    )


class TestBundleStore:
    """Workspace-scoped immutable repository for instructor test bundles."""

    def __init__(
        self,
        workspace_root,
        create=True,
        now_fn=None,
        bundle_id_factory=None,
    ):
        if not workspace_root:
            raise AutogradingBundleValidationError("workspace_root is required")
        requested = Path(workspace_root).expanduser()
        reject_symlink_chain(requested, "assessment workspace")
        reject_symlink(requested, "assessment workspace")
        self._workspace_root = requested.resolve()
        self._root = self._workspace_root / AUTOGRADING_DIRECTORY
        self._lock = threading.RLock()
        self._now_fn = now_fn or _utc_now_iso
        self._bundle_id_factory = bundle_id_factory or generate_test_bundle_id

        reject_symlink(self._root, "autograding storage root")
        if create:
            self._workspace_root.mkdir(parents=True, exist_ok=True)
            self._root.mkdir(parents=True, exist_ok=True)

    @property
    def workspace_root(self):
        return str(self._workspace_root)

    @property
    def root(self):
        return str(self._root)

    def _assessment_dir(self, assessment_id, create=False):
        assessment_id = _required_text(assessment_id, "assessment_id")
        path = self._root / safe_path_component(assessment_id)
        reject_symlink(path, "autograding assessment directory")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _bundles_dir(self, assessment_id, create=False):
        path = self._assessment_dir(assessment_id, create=create) / BUNDLES_DIRECTORY
        reject_symlink(path, "test bundle directory")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self, assessment_id):
        return self._bundles_dir(assessment_id, create=False) / BUNDLE_INDEX_FILENAME

    def _bundle_dir(self, assessment_id, bundle_id):
        bundle_id = _required_text(bundle_id, "bundle_id")
        return self._bundles_dir(assessment_id, create=False) / safe_path_component(bundle_id)

    def _manifest_path(self, assessment_id, bundle_id):
        return self._bundle_dir(assessment_id, bundle_id) / BUNDLE_MANIFEST_FILENAME

    def _default_index(self, assessment_id):
        return {
            "schema_version": BUNDLE_INDEX_SCHEMA_VERSION,
            "assessment_id": assessment_id,
            "bundles": [],
        }

    def _load_index(self, assessment_id, allow_missing=True):
        assessment_id = _required_text(assessment_id, "assessment_id")
        path = self._index_path(assessment_id)
        if not path.exists():
            if allow_missing:
                return self._default_index(assessment_id)
            raise FileNotFoundError(str(path))
        index = read_json_object(path)
        if str(index.get("schema_version", "")) != BUNDLE_INDEX_SCHEMA_VERSION:
            raise AutogradingBundleIntegrityError(
                "Unsupported bundle index schema %r" % index.get("schema_version")
            )
        if str(index.get("assessment_id", "")) != assessment_id:
            raise AutogradingBundleIntegrityError(
                "Bundle index assessment mismatch"
            )
        entries = index.get("bundles")
        if not isinstance(entries, list):
            raise AutogradingBundleIntegrityError("Bundle index bundles must be a list")
        seen_ids = set()
        seen_hashes = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise AutogradingBundleIntegrityError(
                    "Bundle index entries must be objects"
                )
            reference = TestBundleReference.from_dict(entry)
            if reference.assessment_id != assessment_id:
                raise AutogradingBundleIntegrityError(
                    "Bundle index contains a reference for another assessment"
                )
            if reference.bundle_id in seen_ids:
                raise AutogradingBundleIntegrityError(
                    "Duplicate bundle_id in bundle index: %s" % reference.bundle_id
                )
            if reference.bundle_sha256 in seen_hashes:
                raise AutogradingBundleIntegrityError(
                    "Duplicate bundle_sha256 in bundle index: %s"
                    % reference.bundle_sha256
                )
            seen_ids.add(reference.bundle_id)
            seen_hashes.add(reference.bundle_sha256)
        return deepcopy(index)

    def _write_index(self, assessment_id, index):
        assessment_id = _required_text(assessment_id, "assessment_id")
        bundles_dir = self._bundles_dir(assessment_id, create=True)
        payload = deepcopy(dict(index))
        payload["schema_version"] = BUNDLE_INDEX_SCHEMA_VERSION
        payload["assessment_id"] = assessment_id
        entries = payload.get("bundles", [])
        payload["bundles"] = sorted(
            list(entries),
            key=lambda item: (
                str(item.get("imported_at") or ""),
                str(item.get("bundle_id") or ""),
            ),
        )
        atomic_write_json(bundles_dir / BUNDLE_INDEX_FILENAME, payload)

    def list_bundle_references(self, assessment_id):
        """Return immutable bundle references in import order."""

        with self._lock:
            index = self._load_index(assessment_id, allow_missing=True)
            return tuple(
                TestBundleReference.from_dict(entry)
                for entry in index.get("bundles", [])
            )

    def find_by_fingerprint(self, assessment_id, bundle_sha256):
        digest = str(bundle_sha256 or "").strip().lower()
        for reference in self.list_bundle_references(assessment_id):
            if reference.bundle_sha256 == digest:
                return reference
        return None

    def _load_manifest(self, assessment_id, bundle_id):
        path = self._manifest_path(assessment_id, bundle_id)
        if not path.exists():
            raise FileNotFoundError(str(path))
        manifest = read_json_object(path)
        bundle = StoredTestBundle.from_manifest_dict(
            manifest,
            bundle_dir=str(path.parent),
        )
        if bundle.reference.assessment_id != assessment_id:
            raise AutogradingBundleIntegrityError(
                "Bundle manifest assessment mismatch"
            )
        if bundle.reference.bundle_id != bundle_id:
            raise AutogradingBundleIntegrityError("Bundle manifest ID mismatch")
        return bundle

    def load_bundle(self, assessment_id, bundle_id, verify_hashes=True):
        """Load one committed bundle and cross-check index + manifest identity."""

        with self._lock:
            bundle = self._load_manifest(assessment_id, bundle_id)
            index = self._load_index(assessment_id, allow_missing=False)
            indexed = None
            for entry in index.get("bundles", []):
                reference = TestBundleReference.from_dict(entry)
                if reference.bundle_id == bundle_id:
                    indexed = reference
                    break
            if indexed is None:
                raise AutogradingBundleIntegrityError(
                    "Bundle manifest exists but bundle_id is missing from index: %s"
                    % bundle_id
                )
            if indexed != bundle.reference:
                raise AutogradingBundleIntegrityError(
                    "Bundle index/reference does not match bundle manifest"
                )
            if verify_hashes:
                self.verify_bundle(bundle)
            return bundle

    def verify_bundle(self, bundle):
        """Verify manifest/config/fingerprint and exact committed original files."""

        if not isinstance(bundle, StoredTestBundle):
            raise TypeError("bundle must be a StoredTestBundle")
        bundle_dir = Path(bundle.bundle_dir)
        try:
            reject_symlink_chain(bundle_dir, "stored test bundle")
        except AutogradingBundleValidationError as exc:
            raise AutogradingBundleIntegrityError(str(exc))
        if bundle_dir.is_symlink() or not bundle_dir.is_dir():
            raise AutogradingBundleIntegrityError(
                "Stored bundle directory is missing or symlinked: %s" % bundle_dir
            )

        config_files = [
            item for item in bundle.files if item.relative_path == "autograder.json"
        ]
        if len(config_files) != 1:
            raise AutogradingBundleIntegrityError(
                "Stored bundle must contain exactly one autograder.json file record"
            )
        if config_files[0].sha256 != bundle.reference.config_sha256:
            raise AutogradingBundleIntegrityError(
                "Stored bundle config SHA-256 does not match manifest"
            )
        normalized_expected = bundle.metadata.get("normalized_config_sha256")
        if normalized_expected is not None:
            normalized_actual = sha256_json(bundle.config.to_dict())
            if str(normalized_expected) != normalized_actual:
                raise AutogradingBundleIntegrityError(
                    "Stored normalized config SHA-256 does not match manifest"
                )

        computed_bundle = _bundle_fingerprint_from_files(bundle.files)
        if computed_bundle != bundle.reference.bundle_sha256:
            raise AutogradingBundleIntegrityError(
                "Stored bundle fingerprint does not match manifest"
            )

        expected_stored = set()
        for item in bundle.files:
            if not item.stored_relative_path:
                raise AutogradingBundleIntegrityError(
                    "Stored bundle file %r has no stored_relative_path"
                    % item.relative_path
                )
            stored_path = bundle_dir / item.stored_relative_path
            try:
                reject_symlink_chain(stored_path, "stored bundle file")
            except AutogradingBundleValidationError as exc:
                raise AutogradingBundleIntegrityError(str(exc))
            if stored_path.is_symlink() or not stored_path.is_file():
                raise AutogradingBundleIntegrityError(
                    "Stored bundle file is missing or symlinked: %s" % stored_path
                )
            actual_size = stored_path.stat().st_size
            if actual_size != item.size_bytes:
                raise AutogradingBundleIntegrityError(
                    "Stored bundle file size mismatch for %s" % item.relative_path
                )
            actual_hash = compute_file_sha256(str(stored_path))
            if actual_hash != item.sha256:
                raise AutogradingBundleIntegrityError(
                    "Stored bundle file hash mismatch for %s" % item.relative_path
                )
            expected_stored.add(Path(item.stored_relative_path).as_posix())

        stored_config_path = bundle_dir / config_files[0].stored_relative_path
        try:
            stored_config = load_autograding_config(str(stored_config_path))
        except Exception as exc:
            raise AutogradingBundleIntegrityError(
                "Stored original autograder.json could not be validated: %s" % exc
            )
        if stored_config.to_dict() != bundle.config.to_dict():
            raise AutogradingBundleIntegrityError(
                "Bundle manifest config does not match stored original autograder.json"
            )

        originals = bundle_dir / BUNDLE_ORIGINALS_DIRECTORY
        if originals.exists():
            actual_files = set()
            for path in originals.rglob("*"):
                if path.is_symlink():
                    raise AutogradingBundleIntegrityError(
                        "Symlink found in stored bundle originals: %s" % path
                    )
                if path.is_file():
                    actual_files.add(path.relative_to(bundle_dir).as_posix())
                elif not path.is_dir():
                    raise AutogradingBundleIntegrityError(
                        "Non-regular stored bundle entry: %s" % path
                    )
            extras = sorted(actual_files - expected_stored)
            missing = sorted(expected_stored - actual_files)
            if extras or missing:
                raise AutogradingBundleIntegrityError(
                    "Stored bundle originals do not match manifest; extra=%r missing=%r"
                    % (extras, missing)
                )
        else:
            raise AutogradingBundleIntegrityError(
                "Stored bundle originals directory is missing"
            )
        return True

    def _make_stored_files(self, candidate_files):
        result = []
        for item in candidate_files:
            result.append(
                BundleFile(
                    relative_path=item.relative_path,
                    role=item.role,
                    size_bytes=item.size_bytes,
                    sha256=item.sha256,
                    stored_relative_path=(
                        BUNDLE_ORIGINALS_DIRECTORY + "/" + item.relative_path
                    ),
                )
            )
        return tuple(result)

    def _write_new_bundle(self, candidate, bundle_id, imported_at, display_version):
        assessment_id = candidate.assessment_id
        bundles_dir = self._bundles_dir(assessment_id, create=True)
        final_dir = bundles_dir / safe_path_component(bundle_id)
        if final_dir.exists():
            raise AutogradingBundleStorageError(
                "Generated bundle destination already exists: %s" % final_dir
            )

        staging = Path(
            tempfile.mkdtemp(prefix=".bundle-staging-", dir=str(bundles_dir))
        )
        committed_dir = False
        try:
            originals = staging / BUNDLE_ORIGINALS_DIRECTORY
            originals.mkdir(parents=True, exist_ok=False)

            for item in candidate.files:
                if not item.source_path:
                    raise AutogradingBundleStorageError(
                        "Validated source file %r has no source_path"
                        % item.relative_path
                    )
                destination = originals / Path(item.relative_path)
                copy_regular_file(item.source_path, destination, overwrite=False)
                if compute_file_sha256(str(destination)) != item.sha256:
                    raise AutogradingBundleIntegrityError(
                        "Hash mismatch while copying bundle file %s"
                        % item.relative_path
                    )
                # API-level immutability plus a practical guard against accidental edits.
                try:
                    destination.chmod(0o444)
                except OSError:
                    pass

            reference = TestBundleReference(
                bundle_id=bundle_id,
                assessment_id=assessment_id,
                bundle_sha256=candidate.bundle_sha256,
                config_sha256=candidate.config_sha256,
                imported_at=imported_at,
                display_version=display_version,
                metadata={
                    "source_directory_name": candidate.metadata.get(
                        "source_directory_name"
                    ),
                    "file_count": len(candidate.files),
                    "total_bytes": candidate.total_bytes,
                },
            )
            stored_files = self._make_stored_files(candidate.files)
            bundle = StoredTestBundle(
                reference=reference,
                config=candidate.config,
                files=stored_files,
                bundle_dir=str(staging),
                total_bytes=candidate.total_bytes,
                metadata={
                    "fingerprint_schema_version": TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION,
                    "manifest_schema_version": TEST_BUNDLE_MANIFEST_SCHEMA_VERSION,
                    "normalized_config_sha256": candidate.metadata.get(
                        "normalized_config_sha256"
                    ),
                },
            )
            manifest_path = staging / BUNDLE_MANIFEST_FILENAME
            atomic_write_json(manifest_path, bundle.to_manifest_dict(), overwrite=False)
            try:
                manifest_path.chmod(0o444)
            except OSError:
                pass

            # Rename is atomic on the same filesystem and never replaces an
            # existing committed bundle directory.
            os.rename(str(staging), str(final_dir))
            staging = None
            committed_dir = True
            committed = StoredTestBundle(
                reference=bundle.reference,
                config=bundle.config,
                files=bundle.files,
                bundle_dir=str(final_dir),
                total_bytes=bundle.total_bytes,
                metadata=bundle.metadata,
            )
            self.verify_bundle(committed)
            return committed
        except Exception:
            if committed_dir and final_dir.exists():
                shutil.rmtree(str(final_dir), ignore_errors=True)
            raise
        finally:
            if staging is not None and Path(staging).exists():
                shutil.rmtree(str(staging), ignore_errors=True)

    def import_bundle(
        self,
        source_dir,
        expected_assessment_id=None,
        display_version=None,
    ):
        """Validate and idempotently commit one instructor test bundle.

        Re-importing byte-identical bundle contents for the same assessment
        returns the already-committed bundle with ``created=False`` rather than
        creating redundant provenance versions.
        """

        candidate = validate_test_bundle(
            source_dir,
            expected_assessment_id=expected_assessment_id,
        )
        if display_version is None:
            raw_version = candidate.config.metadata.get("version")
            display_version = None if raw_version is None else str(raw_version).strip() or None
        elif not str(display_version).strip():
            display_version = None
        else:
            display_version = str(display_version).strip()

        with self._lock:
            index = self._load_index(candidate.assessment_id, allow_missing=True)
            for entry in index.get("bundles", []):
                reference = TestBundleReference.from_dict(entry)
                if reference.bundle_sha256 == candidate.bundle_sha256:
                    existing = self.load_bundle(
                        candidate.assessment_id,
                        reference.bundle_id,
                        verify_hashes=True,
                    )
                    return BundleImportResult(bundle=existing, created=False)

            bundle_id = _required_text(self._bundle_id_factory(), "generated bundle_id")
            imported_at = _required_text(self._now_fn(), "imported_at")
            committed = None
            try:
                committed = self._write_new_bundle(
                    candidate,
                    bundle_id,
                    imported_at,
                    display_version,
                )
                entries = list(index.get("bundles", []))
                entries.append(committed.reference.to_dict())
                index["bundles"] = entries
                self._write_index(candidate.assessment_id, index)
            except Exception:
                if committed is not None:
                    try:
                        shutil.rmtree(committed.bundle_dir)
                    except OSError:
                        pass
                raise
            return BundleImportResult(bundle=committed, created=True)


__all__ = [
    "AUTOGRADING_DIRECTORY",
    "BUNDLES_DIRECTORY",
    "BUNDLE_INDEX_FILENAME",
    "BUNDLE_INDEX_SCHEMA_VERSION",
    "BUNDLE_MANIFEST_FILENAME",
    "BUNDLE_ORIGINALS_DIRECTORY",
    "TestBundleStore",
]
