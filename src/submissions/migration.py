"""Legacy v2.2 evidence compatibility and canonical migration for v2.3.2.

The v2.2 evidence store remains readable and is never destructively rewritten
into the canonical repository.  This module can materialize an immutable
canonical ``Submission`` from one legacy evidence bundle while preserving the
legacy files in place.

Migration is idempotent for an unchanged legacy manifest.  If the legacy bundle
is later refreshed, its manifest fingerprint changes and a new canonical attempt
may be created, preserving the older canonical bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_TEXT,
    SOURCE_SYSTEM_LEGACY_LOCAL,
    CandidateFile,
    Submission,
)
from .file_store import compute_file_sha256, read_json_object, sha256_json
from .models import SUBMISSION_MODE_PDF_ACCOMMODATION
from .repository import SubmissionRepository
from .storage import (
    EVIDENCE_SCHEMA_VERSION,
    evidence_storage_paths,
    load_persisted_submission,
)


LEGACY_MIGRATION_SCHEMA_VERSION = "1.0"

MIGRATION_STATUS_CREATED = "created"
MIGRATION_STATUS_EXISTING = "existing"
MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT = "canonical_already_present"


class LegacySubmissionMigrationError(ValueError):
    """Base class for legacy-to-canonical migration failures."""


class LegacyEvidenceVerificationError(LegacySubmissionMigrationError):
    """Raised when legacy evidence fails its existing SHA-256 verification."""


class LegacyEvidenceUnsupportedError(LegacySubmissionMigrationError):
    """Raised when a legacy evidence bundle has no migratable original files."""


@dataclass(frozen=True)
class LegacyMigrationResult:
    """Result of ensuring/migrating one legacy evidence bundle."""

    status: str
    submission: Submission
    migration_key: Optional[str] = None
    legacy_manifest_sha256: Optional[str] = None
    created: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "submission_id": self.submission.submission_id,
            "assessment_id": self.submission.assessment_id,
            "student_id": self.submission.student_id,
            "attempt": self.submission.attempt,
            "migration_key": self.migration_key,
            "legacy_manifest_sha256": self.legacy_manifest_sha256,
            "created": self.created,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_text(value: object, name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _original_basename(value: object, fallback: str) -> str:
    """Return a basename from POSIX or Windows-style provenance paths."""
    raw = "" if value is None else str(value).strip()
    raw = raw.replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].strip() if raw else ""
    return name or fallback


def _legacy_manifest(storage_root: str, student_id: str) -> Dict[str, Any]:
    paths = evidence_storage_paths(storage_root, student_id, create=False)
    path = Path(paths.meta_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    manifest = read_json_object(path)
    schema = str(manifest.get("schema_version", ""))
    if schema != EVIDENCE_SCHEMA_VERSION:
        raise LegacySubmissionMigrationError(
            f"Unsupported legacy evidence schema {schema!r}; expected "
            f"{EVIDENCE_SCHEMA_VERSION!r}."
        )
    return manifest


def _migration_key(
    *,
    assessment_id: str,
    student_id: str,
    submission_mode: str,
    source_used: str,
    candidates: List[CandidateFile],
) -> str:
    # The key intentionally ignores volatile legacy metadata such as persisted_at
    # and derived page/compiled-PDF hashes.  Re-persisting unchanged source bytes
    # therefore remains idempotent, while changed official source bytes create a
    # new canonical attempt.
    artifact_fingerprints = []
    for candidate in candidates:
        artifact_fingerprints.append(
            {
                "logical_name": candidate.metadata.get("legacy_logical_name"),
                "artifact_type": candidate.artifact_type,
                "role": candidate.role,
                "original_filename": candidate.original_filename,
                "sha256": compute_file_sha256(candidate.source_path),
            }
        )

    artifact_fingerprints.sort(
        key=lambda item: (
            str(item.get("logical_name") or ""),
            str(item.get("original_filename") or ""),
            str(item.get("sha256") or ""),
        )
    )

    return sha256_json(
        {
            "schema_version": LEGACY_MIGRATION_SCHEMA_VERSION,
            "assessment_id": assessment_id,
            "student_id": student_id,
            "submission_mode": submission_mode,
            "source_used": source_used,
            "artifacts": artifact_fingerprints,
        }
    )


def _candidate_files(
    parsed,
    manifest: Mapping[str, Any],
) -> List[CandidateFile]:
    """Return only original/submitted legacy files, never derived render output."""
    original_files = manifest.get("original_files", {})
    if not isinstance(original_files, Mapping):
        original_files = {}

    candidates: List[CandidateFile] = []

    latex_path = parsed.files.get("latex")
    if latex_path:
        candidates.append(
            CandidateFile(
                source_path=str(latex_path),
                original_filename=_original_basename(
                    original_files.get("latex"),
                    Path(str(latex_path)).name,
                ),
                artifact_type=ARTIFACT_TYPE_TEX,
                role=ARTIFACT_ROLE_PRIMARY,
                metadata={"legacy_logical_name": "latex"},
            )
        )

    pdf_path = parsed.files.get("pdf")
    if pdf_path:
        pdf_role = (
            ARTIFACT_ROLE_PRIMARY
            if parsed.submission_mode == SUBMISSION_MODE_PDF_ACCOMMODATION
            else ARTIFACT_ROLE_RENDERED
        )
        candidates.append(
            CandidateFile(
                source_path=str(pdf_path),
                original_filename=_original_basename(
                    original_files.get("pdf"),
                    Path(str(pdf_path)).name,
                ),
                artifact_type=ARTIFACT_TYPE_PDF,
                role=pdf_role,
                metadata={"legacy_logical_name": "pdf"},
            )
        )

    # Older/custom evidence can contain text/markdown logical sources.  Preserve
    # them as canonical text artifacts even though no v2.3.2 grading handler is
    # installed for them.
    for logical_name in ("markdown", "text"):
        source_path = parsed.files.get(logical_name)
        if not source_path:
            continue
        candidates.append(
            CandidateFile(
                source_path=str(source_path),
                original_filename=_original_basename(
                    original_files.get(logical_name),
                    Path(str(source_path)).name,
                ),
                artifact_type=ARTIFACT_TYPE_TEXT,
                role=ARTIFACT_ROLE_PRIMARY,
                metadata={"legacy_logical_name": logical_name},
            )
        )

    return candidates


def _existing_migration(
    repository: SubmissionRepository,
    *,
    assessment_id: str,
    student_id: str,
    migration_key: str,
) -> Optional[Submission]:
    for submission in repository.list_submissions(assessment_id, student_id):
        metadata = submission.metadata.get("legacy_migration", {})
        if not isinstance(metadata, Mapping):
            continue
        if str(metadata.get("migration_key") or "") == migration_key:
            return submission
    return None



def _linked_canonical_submission(
    repository: SubmissionRepository,
    *,
    assessment_id: str,
    student_id: str,
    manifest: Mapping[str, Any],
) -> Optional[Submission]:
    """Return a canonical submission already linked from legacy metadata."""
    link = manifest.get("canonical_submission", {})
    if not isinstance(link, Mapping):
        return None

    submission_id = str(link.get("submission_id") or "").strip()
    if not submission_id:
        return None

    try:
        submission = repository.get_submission(
            submission_id,
            assessment_id=assessment_id,
            student_id=student_id,
        )
    except (KeyError, FileNotFoundError, ValueError):
        return None

    return submission


def migrate_legacy_submission(
    storage_root: str,
    assessment_id: str,
    student_id: str,
    *,
    repository: Optional[SubmissionRepository] = None,
    make_active: bool = True,
    verify_hashes: bool = True,
    require_verified: bool = True,
    attempt: Optional[int] = None,
) -> LegacyMigrationResult:
    """Create/reuse one canonical attempt from v2.2 persisted evidence.

    The legacy evidence directory is never deleted or moved.  An unchanged
    legacy manifest is migrated at most once; repeated calls return the same
    canonical submission.
    """
    assessment_id = _required_text(assessment_id, "assessment_id")
    student_id = _required_text(student_id, "student_id")

    if not isinstance(make_active, bool):
        raise TypeError("make_active must be a bool")
    if not isinstance(verify_hashes, bool):
        raise TypeError("verify_hashes must be a bool")
    if not isinstance(require_verified, bool):
        raise TypeError("require_verified must be a bool")

    if repository is None:
        repository = SubmissionRepository(storage_root)
    elif not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be SubmissionRepository or None")
    else:
        expected = Path(storage_root).expanduser().resolve()
        actual = Path(repository.storage_root).expanduser().resolve()
        if expected != actual:
            raise ValueError(
                "repository.storage_root must match the legacy evidence storage_root"
            )

    manifest = _legacy_manifest(storage_root, student_id)
    manifest_sha = sha256_json(manifest)

    linked = _linked_canonical_submission(
        repository,
        assessment_id=assessment_id,
        student_id=student_id,
        manifest=manifest,
    )
    if linked is not None:
        if make_active and not linked.is_active_attempt:
            linked = repository.set_active_submission(
                assessment_id,
                student_id,
                linked.submission_id,
            )
        return LegacyMigrationResult(
            status=MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT,
            submission=linked,
            created=False,
        )

    parsed = load_persisted_submission(
        storage_root,
        student_id,
        verify_hashes=verify_hashes,
    )

    verification = parsed.evidence_metadata.get("verification", {})
    if (
        require_verified
        and verify_hashes
        and isinstance(verification, Mapping)
        and verification.get("performed")
        and not verification.get("ok")
    ):
        raise LegacyEvidenceVerificationError(
            "Legacy submission evidence failed SHA-256 verification and will not "
            "be promoted into immutable canonical storage."
        )

    candidates = _candidate_files(parsed, manifest)
    if not candidates:
        raise LegacyEvidenceUnsupportedError(
            "Legacy evidence contains no original source artifact that can be "
            "migrated into canonical storage."
        )

    key = _migration_key(
        assessment_id=assessment_id,
        student_id=student_id,
        submission_mode=parsed.submission_mode,
        source_used=parsed.source_used,
        candidates=candidates,
    )

    existing = _existing_migration(
        repository,
        assessment_id=assessment_id,
        student_id=student_id,
        migration_key=key,
    )
    if existing is not None:
        if make_active and not existing.is_active_attempt:
            existing = repository.set_active_submission(
                assessment_id,
                student_id,
                existing.submission_id,
            )
        return LegacyMigrationResult(
            status=MIGRATION_STATUS_EXISTING,
            submission=existing,
            migration_key=key,
            legacy_manifest_sha256=manifest_sha,
            created=False,
        )

    paths = evidence_storage_paths(storage_root, student_id, create=False)
    legacy_metadata = {
        "schema_version": LEGACY_MIGRATION_SCHEMA_VERSION,
        "migration_key": key,
        "legacy_evidence_schema_version": manifest.get("schema_version"),
        "legacy_manifest_sha256": manifest_sha,
        "legacy_student_dirname": Path(paths.student_dir).name,
        "legacy_persisted_at": manifest.get("persisted_at"),
        "legacy_submission_mode": parsed.submission_mode,
        "legacy_source_used": parsed.source_used,
        "migrated_at": _utc_now_iso(),
    }

    submission = repository.create_submission(
        assessment_id=assessment_id,
        student_id=student_id,
        source_system=SOURCE_SYSTEM_LEGACY_LOCAL,
        files=candidates,
        attempt=attempt,
        make_active=make_active,
        submitted_at=None,
        metadata={"legacy_migration": legacy_metadata},
    )

    return LegacyMigrationResult(
        status=MIGRATION_STATUS_CREATED,
        submission=submission,
        migration_key=key,
        legacy_manifest_sha256=manifest_sha,
        created=True,
    )


def ensure_canonical_submission(
    storage_root: str,
    assessment_id: str,
    student_id: str,
    *,
    repository: Optional[SubmissionRepository] = None,
    migrate_legacy: bool = True,
    verify_hashes: bool = True,
    require_verified: bool = True,
) -> Optional[LegacyMigrationResult]:
    """Return an active canonical submission, optionally migrating legacy data.

    This is the compatibility entry point intended for Commit 6/controller use.
    It never rewrites an existing canonical submission and never deletes legacy
    evidence.
    """
    assessment_id = _required_text(assessment_id, "assessment_id")
    student_id = _required_text(student_id, "student_id")

    if not isinstance(migrate_legacy, bool):
        raise TypeError("migrate_legacy must be a bool")

    if repository is None:
        repository = SubmissionRepository(storage_root)
    elif not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be SubmissionRepository or None")
    else:
        expected = Path(storage_root).expanduser().resolve()
        actual = Path(repository.storage_root).expanduser().resolve()
        if expected != actual:
            raise ValueError(
                "repository.storage_root must match the legacy evidence storage_root"
            )

    active = repository.get_active_submission(assessment_id, student_id)
    if active is not None:
        return LegacyMigrationResult(
            status=MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT,
            submission=active,
            created=False,
        )

    if not migrate_legacy:
        return None

    paths = evidence_storage_paths(storage_root, student_id, create=False)
    if not Path(paths.meta_path).exists():
        return None

    return migrate_legacy_submission(
        storage_root,
        assessment_id,
        student_id,
        repository=repository,
        make_active=True,
        verify_hashes=verify_hashes,
        require_verified=require_verified,
    )


__all__ = [
    "LEGACY_MIGRATION_SCHEMA_VERSION",
    "MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT",
    "MIGRATION_STATUS_CREATED",
    "MIGRATION_STATUS_EXISTING",
    "LegacyEvidenceUnsupportedError",
    "LegacyEvidenceVerificationError",
    "LegacyMigrationResult",
    "LegacySubmissionMigrationError",
    "ensure_canonical_submission",
    "migrate_legacy_submission",
]
