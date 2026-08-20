"""Validated instructor test-bundle ingestion for v2.3.3 Commit 2.

This module inspects a source directory, validates its configuration and static
bundle structure, computes exact per-file hashes, and returns an immutable
``ValidatedTestBundle`` ready for ``TestBundleStore`` to commit.

It never imports or executes instructor test modules.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from src.submissions.file_store import compute_file_sha256, sha256_json

from .config import AutogradingConfig, load_autograding_config
from .errors import AutogradingBundleValidationError, AutogradingSerializationError
from .models import TestBundleReference
from .validation import (
    ALLOWED_TOP_LEVEL_ENTRIES,
    AUTOGRADER_CONFIG_FILENAME,
    DEFAULT_MAX_BUNDLE_FILE_BYTES,
    DEFAULT_MAX_BUNDLE_FILES,
    DEFAULT_MAX_BUNDLE_TOTAL_BYTES,
    IGNORED_BUNDLE_METADATA_FILENAMES,
    REQUIREMENTS_FILENAME,
    SUPPORT_DIRECTORY,
    TESTS_DIRECTORY,
    classify_bundle_file,
    normalize_bundle_relative_path,
    reject_symlink_chain,
    validate_declared_test_ids,
    validate_requirements_text,
)


TEST_BUNDLE_MANIFEST_SCHEMA_VERSION = "1.0"
TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class BundleFile:
    """One exact source file inside a validated or stored grader bundle."""

    relative_path: str
    role: str
    size_bytes: int
    sha256: str
    source_path: Optional[str] = None
    stored_relative_path: Optional[str] = None

    def __post_init__(self):
        relative_path = normalize_bundle_relative_path(
            self.relative_path,
            "bundle file relative_path",
        )
        role = str(self.role or "").strip()
        if role not in ("config", "test", "support", "requirements"):
            raise AutogradingBundleValidationError(
                "Unsupported bundle file role %r" % role
            )
        if isinstance(self.size_bytes, bool):
            raise AutogradingBundleValidationError("size_bytes must be an integer")
        try:
            size = int(self.size_bytes)
        except (TypeError, ValueError):
            raise AutogradingBundleValidationError("size_bytes must be an integer")
        if size < 0:
            raise AutogradingBundleValidationError("size_bytes must be non-negative")
        digest = str(self.sha256 or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise AutogradingBundleValidationError(
                "sha256 must be a 64-character hexadecimal digest"
            )
        source_path = None if self.source_path is None else str(self.source_path)
        stored = (
            None
            if self.stored_relative_path is None
            else normalize_bundle_relative_path(
                self.stored_relative_path,
                "stored_relative_path",
            )
        )

        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "stored_relative_path", stored)

    def to_dict(self, include_source_path=False):
        result = {
            "relative_path": self.relative_path,
            "role": self.role,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "stored_relative_path": self.stored_relative_path,
        }
        if include_source_path:
            result["source_path"] = self.source_path
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("BundleFile data must be a mapping")
        return cls(
            relative_path=data.get("relative_path"),
            role=data.get("role"),
            size_bytes=data.get("size_bytes"),
            sha256=data.get("sha256"),
            source_path=data.get("source_path"),
            stored_relative_path=data.get("stored_relative_path"),
        )


@dataclass(frozen=True)
class ValidatedTestBundle:
    """Static, hash-complete bundle candidate validated before storage."""

    source_root: str
    config: AutogradingConfig
    files: Tuple[BundleFile, ...]
    config_sha256: str
    bundle_sha256: str
    total_bytes: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        source_root = str(self.source_root or "").strip()
        if not source_root:
            raise AutogradingBundleValidationError("source_root must not be empty")
        if not isinstance(self.config, AutogradingConfig):
            raise TypeError("config must be an AutogradingConfig")
        files = tuple(self.files or ())
        if not files or not all(isinstance(item, BundleFile) for item in files):
            raise AutogradingBundleValidationError(
                "files must contain at least one BundleFile"
            )
        paths = [item.relative_path for item in files]
        if len(paths) != len(set(path.casefold() for path in paths)):
            raise AutogradingBundleValidationError(
                "bundle file paths must be unique case-insensitively"
            )
        for name, value in (
            ("config_sha256", self.config_sha256),
            ("bundle_sha256", self.bundle_sha256),
        ):
            digest = str(value or "").strip().lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise AutogradingBundleValidationError(
                    "%s must be a SHA-256 digest" % name
                )
            object.__setattr__(self, name, digest)
        if isinstance(self.total_bytes, bool):
            raise AutogradingBundleValidationError("total_bytes must be an integer")
        total_bytes = int(self.total_bytes)
        if total_bytes < 0:
            raise AutogradingBundleValidationError("total_bytes must be non-negative")
        if total_bytes != sum(item.size_bytes for item in files):
            raise AutogradingBundleValidationError(
                "total_bytes does not match bundle files"
            )
        if not isinstance(self.metadata, Mapping):
            raise AutogradingBundleValidationError("metadata must be a mapping")

        object.__setattr__(self, "source_root", source_root)
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "total_bytes", total_bytes)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def assessment_id(self):
        return self.config.assessment_id

    def file_by_path(self, relative_path):
        target = normalize_bundle_relative_path(relative_path)
        for item in self.files:
            if item.relative_path == target:
                return item
        return None


@dataclass(frozen=True)
class StoredTestBundle:
    """One committed immutable bundle reconstructed from ``bundle.json``."""

    reference: TestBundleReference
    config: AutogradingConfig
    files: Tuple[BundleFile, ...]
    bundle_dir: str
    total_bytes: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.reference, TestBundleReference):
            raise TypeError("reference must be a TestBundleReference")
        if not isinstance(self.config, AutogradingConfig):
            raise TypeError("config must be an AutogradingConfig")
        files = tuple(self.files or ())
        if not files or not all(isinstance(item, BundleFile) for item in files):
            raise AutogradingBundleValidationError(
                "files must contain at least one BundleFile"
            )
        if self.config.assessment_id != self.reference.assessment_id:
            raise AutogradingBundleValidationError(
                "bundle config/reference assessment mismatch"
            )
        total = int(self.total_bytes)
        if total != sum(item.size_bytes for item in files):
            raise AutogradingBundleValidationError(
                "stored bundle total_bytes does not match files"
            )
        if not isinstance(self.metadata, Mapping):
            raise AutogradingBundleValidationError("metadata must be a mapping")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "bundle_dir", str(self.bundle_dir))
        object.__setattr__(self, "total_bytes", total)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def original_path(self, relative_path):
        item = None
        target = normalize_bundle_relative_path(relative_path)
        for candidate in self.files:
            if candidate.relative_path == target:
                item = candidate
                break
        if item is None or not item.stored_relative_path:
            raise KeyError(target)
        return str(Path(self.bundle_dir) / item.stored_relative_path)

    def to_manifest_dict(self):
        return {
            "schema_version": TEST_BUNDLE_MANIFEST_SCHEMA_VERSION,
            "reference": self.reference.to_dict(),
            "config": self.config.to_dict(),
            "files": [item.to_dict() for item in self.files],
            "total_bytes": self.total_bytes,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_manifest_dict(cls, data, bundle_dir):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("bundle manifest must be a mapping")
        version = str(data.get("schema_version", ""))
        if version != TEST_BUNDLE_MANIFEST_SCHEMA_VERSION:
            raise AutogradingSerializationError(
                "Unsupported bundle manifest schema %r; expected %r"
                % (version, TEST_BUNDLE_MANIFEST_SCHEMA_VERSION)
            )
        files = tuple(BundleFile.from_dict(item) for item in (data.get("files") or ()))
        return cls(
            reference=TestBundleReference.from_dict(data.get("reference") or {}),
            config=AutogradingConfig.from_dict(data.get("config") or {}),
            files=files,
            bundle_dir=str(bundle_dir),
            total_bytes=data.get("total_bytes", sum(item.size_bytes for item in files)),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class BundleImportResult:
    """Result of an idempotent bundle-store import."""

    bundle: StoredTestBundle
    created: bool

    @property
    def duplicate(self):
        return not self.created


def _bundle_fingerprint(files):
    payload = {
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
    return sha256_json(payload)


def _normalized_config_hash(config):
    return sha256_json(config.to_dict())


def _read_utf8(path, label):
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise AutogradingBundleValidationError(
            "%s is not valid UTF-8: %s" % (label, exc)
        )


def validate_test_bundle(
    source_dir,
    expected_assessment_id=None,
    max_files=DEFAULT_MAX_BUNDLE_FILES,
    max_file_bytes=DEFAULT_MAX_BUNDLE_FILE_BYTES,
    max_total_bytes=DEFAULT_MAX_BUNDLE_TOTAL_BYTES,
):
    """Validate and fingerprint one instructor-authored test-bundle directory."""

    for name, value in (
        ("max_files", max_files),
        ("max_file_bytes", max_file_bytes),
        ("max_total_bytes", max_total_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AutogradingBundleValidationError("%s must be a positive integer" % name)

    requested = Path(source_dir).expanduser()
    reject_symlink_chain(requested, "test bundle path")
    root = requested.resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    # Strict top-level allowlist prevents accidental import of .env, venvs,
    # caches, repositories, or unrelated instructor files.
    top_level = sorted(root.iterdir(), key=lambda item: item.name.casefold())
    for child in top_level:
        if child.name in IGNORED_BUNDLE_METADATA_FILENAMES:
            continue
        if child.is_symlink():
            raise AutogradingBundleValidationError(
                "Symlinked bundle entry is not accepted: %s" % child
            )
        if child.name not in ALLOWED_TOP_LEVEL_ENTRIES:
            raise AutogradingBundleValidationError(
                "Unsupported top-level bundle entry %r; allowed entries are: %s"
                % (child.name, ", ".join(ALLOWED_TOP_LEVEL_ENTRIES))
            )

    config_path = root / AUTOGRADER_CONFIG_FILENAME
    if not config_path.exists():
        raise AutogradingBundleValidationError(
            "Test bundle is missing %s" % AUTOGRADER_CONFIG_FILENAME
        )
    if not config_path.is_file():
        raise AutogradingBundleValidationError(
            "%s must be a regular file" % AUTOGRADER_CONFIG_FILENAME
        )

    tests_dir = root / TESTS_DIRECTORY
    if not tests_dir.exists() or not tests_dir.is_dir():
        raise AutogradingBundleValidationError(
            "Test bundle must contain a tests/ directory"
        )

    support_dir = root / SUPPORT_DIRECTORY
    if support_dir.exists() and not support_dir.is_dir():
        raise AutogradingBundleValidationError("support must be a directory")

    requirements_path = root / REQUIREMENTS_FILENAME
    if requirements_path.exists() and not requirements_path.is_file():
        raise AutogradingBundleValidationError(
            "%s must be a regular file" % REQUIREMENTS_FILENAME
        )

    config = load_autograding_config(str(config_path))
    if expected_assessment_id is not None:
        expected = str(expected_assessment_id or "").strip()
        if not expected:
            raise AutogradingBundleValidationError(
                "expected_assessment_id must not be empty"
            )
        if config.assessment_id != expected:
            raise AutogradingBundleValidationError(
                "Bundle assessment_id %r does not match expected assessment %r"
                % (config.assessment_id, expected)
            )

    file_records = []
    seen_casefold = {}
    total_bytes = 0
    python_test_text_by_path = {}

    for path in sorted(root.rglob("*"), key=lambda item: str(item.relative_to(root)).casefold()):
        if path.name in IGNORED_BUNDLE_METADATA_FILENAMES and path.is_file():
            continue
        if path.is_symlink():
            raise AutogradingBundleValidationError(
                "Symlinked bundle entry is not accepted: %s" % path
            )
        if path.is_dir():
            if path.name.startswith("."):
                raise AutogradingBundleValidationError(
                    "Hidden bundle directories are not accepted: %s" % path
                )
            continue
        if not path.is_file():
            raise AutogradingBundleValidationError(
                "Bundle contains a non-regular filesystem entry: %s" % path
            )

        relative = normalize_bundle_relative_path(
            path.relative_to(root).as_posix(),
            "bundle file path",
        )
        top = relative.split("/", 1)[0]
        if top not in ALLOWED_TOP_LEVEL_ENTRIES:
            raise AutogradingBundleValidationError(
                "Bundle file %r is outside the accepted layout" % relative
            )
        if top in (AUTOGRADER_CONFIG_FILENAME, REQUIREMENTS_FILENAME) and "/" in relative:
            raise AutogradingBundleValidationError(
                "Bundle file %r has an invalid top-level layout" % relative
            )

        folded = relative.casefold()
        previous = seen_casefold.get(folded)
        if previous is not None and previous != relative:
            raise AutogradingBundleValidationError(
                "Bundle contains case-insensitive path collision: %r and %r"
                % (previous, relative)
            )
        seen_casefold[folded] = relative

        size = path.stat().st_size
        if size > max_file_bytes:
            raise AutogradingBundleValidationError(
                "Bundle file %r exceeds the %d-byte limit" % (relative, max_file_bytes)
            )
        total_bytes += size
        if total_bytes > max_total_bytes:
            raise AutogradingBundleValidationError(
                "Test bundle exceeds the %d-byte total-size limit" % max_total_bytes
            )

        record = BundleFile(
            relative_path=relative,
            role=classify_bundle_file(relative),
            size_bytes=size,
            sha256=compute_file_sha256(str(path)),
            source_path=str(path),
        )
        file_records.append(record)
        if len(file_records) > max_files:
            raise AutogradingBundleValidationError(
                "Test bundle exceeds the %d-file limit" % max_files
            )

        if relative.startswith(TESTS_DIRECTORY + "/") and relative.endswith(".py"):
            python_test_text_by_path[relative] = _read_utf8(path, relative)

    if AUTOGRADER_CONFIG_FILENAME not in seen_casefold.values():
        raise AutogradingBundleValidationError(
            "Test bundle is missing %s" % AUTOGRADER_CONFIG_FILENAME
        )
    if not python_test_text_by_path:
        raise AutogradingBundleValidationError(
            "tests/ must contain at least one Python test file"
        )

    if requirements_path.exists():
        validate_requirements_text(
            _read_utf8(requirements_path, REQUIREMENTS_FILENAME)
        )

    validate_declared_test_ids(config, python_test_text_by_path)

    files = tuple(sorted(file_records, key=lambda item: item.relative_path.casefold()))
    config_file = next(
        item for item in files if item.relative_path == AUTOGRADER_CONFIG_FILENAME
    )
    config_sha256 = config_file.sha256
    normalized_config_sha256 = _normalized_config_hash(config)
    bundle_sha256 = _bundle_fingerprint(files)

    return ValidatedTestBundle(
        source_root=str(root),
        config=config,
        files=files,
        config_sha256=config_sha256,
        bundle_sha256=bundle_sha256,
        total_bytes=total_bytes,
        metadata={
            "source_directory_name": root.name,
            "fingerprint_schema_version": TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION,
            "normalized_config_sha256": normalized_config_sha256,
        },
    )


__all__ = [
    "BundleFile",
    "BundleImportResult",
    "StoredTestBundle",
    "TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION",
    "TEST_BUNDLE_MANIFEST_SCHEMA_VERSION",
    "ValidatedTestBundle",
    "validate_test_bundle",
]
