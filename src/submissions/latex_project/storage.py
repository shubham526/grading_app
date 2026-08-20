"""Transactional immutable storage for safely extracted LaTeX project ZIPs."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import threading
from typing import Optional

from .archive import compute_manifest_sha256, safe_extract_latex_project_zip
from .config import LatexProjectIngestionConfig
from .errors import (
    LatexProjectArchiveRejectedError,
    LatexProjectIntegrityError,
    LatexProjectStorageError,
)
from .models import (
    ARCHIVE_VALIDATION_VALID,
    DIAGNOSTIC_BLOCKING,
    LatexProjectArchive,
    LatexProjectDiagnostic,
    LatexProjectManifest,
    generate_latex_project_id,
)
from ..file_store import (
    atomic_write_json,
    compute_file_sha256,
    copy_regular_file,
    read_json_object,
    reject_symlink,
    safe_path_component,
)


ARCHIVE_METADATA_FILENAME = "archive.json"
MANIFEST_FILENAME = "manifest.json"
ORIGINAL_DIRNAME = "original"
ORIGINAL_ARCHIVE_FILENAME = "submission.zip"
EXTRACTED_DIRNAME = "extracted"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StoredLatexProject:
    """Verified host paths plus portable domain metadata for one stored project."""

    project_id: str
    project_dir: str
    original_archive_path: str
    extracted_root: str
    archive_metadata_path: str
    manifest_path: str
    archive: LatexProjectArchive
    manifest: LatexProjectManifest


def _ensure_regular_source(path):
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise LatexProjectStorageError(
            "Symlinked ZIP archives are not accepted: %s" % requested
        )
    source = requested.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    return source


def _ensure_no_symlink_chain(root, target):
    root = Path(root)
    target = Path(target)
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise LatexProjectIntegrityError(
            "Persisted project path escapes extraction root: %s" % target
        )
    cursor = root
    reject_symlink(cursor, "extracted project root")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise LatexProjectIntegrityError(
                "Symlink detected in persisted project tree: %s" % cursor
            )

def verify_stored_latex_project(stored):
    """Verify original ZIP, manifest, and extracted bytes before use."""
    if not isinstance(stored, StoredLatexProject):
        raise TypeError("stored must be StoredLatexProject")
    project_dir = Path(stored.project_dir)
    archive_path = Path(stored.original_archive_path)
    extracted_root = Path(stored.extracted_root)
    reject_symlink(project_dir, "LaTeX-project directory")
    reject_symlink(archive_path, "stored ZIP archive")
    reject_symlink(extracted_root, "extracted project root")
    if not archive_path.exists() or not archive_path.is_file():
        raise LatexProjectIntegrityError("Stored original ZIP is missing")
    if not extracted_root.exists() or not extracted_root.is_dir():
        raise LatexProjectIntegrityError("Stored extracted project is missing")

    if archive_path.stat().st_size != stored.archive.archive_size_bytes:
        raise LatexProjectIntegrityError("Stored ZIP size does not match provenance")
    try:
        archive_digest = compute_file_sha256(str(archive_path))
    except (ValueError, OSError) as exc:
        raise LatexProjectIntegrityError(str(exc)) from exc
    if archive_digest != stored.archive.archive_sha256:
        raise LatexProjectIntegrityError("Stored ZIP SHA-256 does not match provenance")

    if stored.manifest.manifest_sha256 is None:
        raise LatexProjectIntegrityError("Stored project manifest has no SHA-256")
    if compute_manifest_sha256(stored.manifest) != stored.manifest.manifest_sha256:
        raise LatexProjectIntegrityError("Stored project manifest SHA-256 is invalid")

    expected = {item.relative_path: item for item in stored.manifest.files}
    actual = set()
    for path in extracted_root.rglob("*"):
        _ensure_no_symlink_chain(extracted_root, path)
        if path.is_dir():
            continue
        if not path.is_file():
            raise LatexProjectIntegrityError(
                "Unexpected non-regular object in extracted project: %s" % path
            )
        relative = path.relative_to(extracted_root).as_posix()
        actual.add(relative)

    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise LatexProjectIntegrityError(
            "Extracted project file set does not match manifest "
            "(missing=%r, extra=%r)" % (missing, extra)
        )

    for relative, item in expected.items():
        target = extracted_root.joinpath(*PurePosixPath(relative).parts)
        _ensure_no_symlink_chain(extracted_root, target)
        if target.stat().st_size != item.size_bytes:
            raise LatexProjectIntegrityError(
                "Extracted file size does not match manifest: %s" % relative
            )
        try:
            digest = compute_file_sha256(str(target))
        except (ValueError, OSError) as exc:
            raise LatexProjectIntegrityError(str(exc)) from exc
        if digest != item.sha256:
            raise LatexProjectIntegrityError(
                "Extracted file SHA-256 does not match manifest: %s" % relative
            )
    return True



class LatexProjectArchiveStore:
    """Filesystem-backed immutable store for original ZIP + extracted project.

    ``storage_root`` is intentionally caller-selected.  Commit 5 will place the
    store beneath the appropriate canonical submission evidence directory.  A
    successful project directory is never overwritten by this API.
    """

    def __init__(self, storage_root, create=True):
        if not storage_root:
            raise ValueError("storage_root is required")
        requested = Path(storage_root).expanduser()
        reject_symlink(requested, "LaTeX-project storage root")
        self._root = requested.resolve()
        self._lock = threading.RLock()
        if create:
            self._root.mkdir(parents=True, exist_ok=True)

    @property
    def storage_root(self):
        return str(self._root)

    def project_dir(self, project_id):
        return self._root / safe_path_component(project_id)

    def ingest_zip(
        self,
        archive_path,
        source_artifact_id,
        config=None,
        project_id=None,
        imported_at=None,
    ):
        if config is None:
            config = LatexProjectIngestionConfig()
        elif not isinstance(config, LatexProjectIngestionConfig):
            raise TypeError("config must be LatexProjectIngestionConfig")
        source_artifact_id = str(source_artifact_id or "").strip()
        if not source_artifact_id:
            raise ValueError("source_artifact_id is required")
        source = _ensure_regular_source(archive_path)
        source_size = source.stat().st_size
        if source_size > config.limits.max_archive_bytes:
            diagnostic = LatexProjectDiagnostic(
                code="archive_size_limit_exceeded",
                message="ZIP archive exceeds the %d-byte limit"
                % config.limits.max_archive_bytes,
                severity=DIAGNOSTIC_BLOCKING,
                metadata={
                    "archive_size_bytes": source_size,
                    "limit": config.limits.max_archive_bytes,
                },
            )
            raise LatexProjectArchiveRejectedError(
                diagnostic.message,
                diagnostics=(diagnostic,),
            )
        if project_id is None:
            project_id = generate_latex_project_id()
        project_id = str(project_id).strip()
        if not project_id:
            raise ValueError("project_id is required")
        imported_at = str(imported_at or _utc_now_iso()).strip()

        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            reject_symlink(self._root, "LaTeX-project storage root")
            target = self.project_dir(project_id)
            if target.exists() or target.is_symlink():
                raise FileExistsError(str(target))

            staging = Path(
                tempfile.mkdtemp(prefix=".latex-project-", dir=str(self._root))
            )
            try:
                original_dir = staging / ORIGINAL_DIRNAME
                extracted_dir = staging / EXTRACTED_DIRNAME
                original_dir.mkdir(parents=True, exist_ok=False)
                extracted_dir.mkdir(parents=True, exist_ok=False)
                stored_archive = original_dir / ORIGINAL_ARCHIVE_FILENAME
                copy_regular_file(str(source), stored_archive, overwrite=False)

                archive_size = stored_archive.stat().st_size
                archive_sha256 = compute_file_sha256(str(stored_archive))
                summary = safe_extract_latex_project_zip(
                    stored_archive,
                    extracted_dir,
                    project_id,
                    config=config,
                )

                archive = LatexProjectArchive(
                    project_id=project_id,
                    source_artifact_id=source_artifact_id,
                    original_filename=source.name,
                    archive_sha256=archive_sha256,
                    archive_size_bytes=archive_size,
                    validation_status=ARCHIVE_VALIDATION_VALID,
                    imported_at=imported_at,
                    diagnostics=(),
                    metadata={
                        "stored_relative_path": "%s/%s"
                        % (ORIGINAL_DIRNAME, ORIGINAL_ARCHIVE_FILENAME),
                        "extracted_relative_path": EXTRACTED_DIRNAME,
                        "zip_member_count": summary.zip_member_count,
                        "regular_member_count": summary.regular_member_count,
                        "ignored_members": list(summary.ignored_members),
                    },
                )
                atomic_write_json(
                    staging / ARCHIVE_METADATA_FILENAME,
                    archive.to_dict(),
                    overwrite=False,
                )
                atomic_write_json(
                    staging / MANIFEST_FILENAME,
                    summary.manifest.to_dict(),
                    overwrite=False,
                )

                if target.exists() or target.is_symlink():
                    raise FileExistsError(str(target))
                staging.rename(target)
                staging = None
            finally:
                if staging is not None and staging.exists():
                    shutil.rmtree(str(staging), ignore_errors=True)

        return self.load(project_id, verify=True)

    def load(self, project_id, verify=True):
        project_id = str(project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required")
        project_dir = self.project_dir(project_id)
        if project_dir.is_symlink():
            raise LatexProjectIntegrityError(
                "Symlinked project directories are not accepted: %s" % project_dir
            )
        if not project_dir.exists() or not project_dir.is_dir():
            raise FileNotFoundError(str(project_dir))

        archive_path = project_dir / ORIGINAL_DIRNAME / ORIGINAL_ARCHIVE_FILENAME
        extracted_root = project_dir / EXTRACTED_DIRNAME
        archive_metadata_path = project_dir / ARCHIVE_METADATA_FILENAME
        manifest_path = project_dir / MANIFEST_FILENAME

        try:
            archive = LatexProjectArchive.from_dict(
                read_json_object(archive_metadata_path)
            )
            manifest = LatexProjectManifest.from_dict(read_json_object(manifest_path))
        except (ValueError, OSError) as exc:
            raise LatexProjectIntegrityError(
                "Could not read persisted LaTeX-project metadata: %s" % exc
            ) from exc

        if archive.project_id != project_id or manifest.project_id != project_id:
            raise LatexProjectIntegrityError(
                "Persisted LaTeX-project identity does not match storage key"
            )
        if archive.validation_status != ARCHIVE_VALIDATION_VALID:
            raise LatexProjectIntegrityError(
                "Persisted LaTeX-project archive is not marked valid"
            )

        stored = StoredLatexProject(
            project_id=project_id,
            project_dir=str(project_dir.absolute()),
            original_archive_path=str(archive_path.absolute()),
            extracted_root=str(extracted_root.absolute()),
            archive_metadata_path=str(archive_metadata_path.absolute()),
            manifest_path=str(manifest_path.absolute()),
            archive=archive,
            manifest=manifest,
        )
        if verify:
            self.verify(stored)
        return stored

    def verify(self, stored):
        return verify_stored_latex_project(stored)



__all__ = [
    "ARCHIVE_METADATA_FILENAME",
    "EXTRACTED_DIRNAME",
    "LatexProjectArchiveStore",
    "MANIFEST_FILENAME",
    "ORIGINAL_ARCHIVE_FILENAME",
    "ORIGINAL_DIRNAME",
    "StoredLatexProject",
    "verify_stored_latex_project",
]
