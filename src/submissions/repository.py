"""
Canonical immutable submission repository for v2.3.2.

The repository persists source-agnostic ``Submission`` records underneath the
existing v2.2 evidence root without replacing the legacy evidence layout.

Layout::

    <evidence_root>/
        <legacy v2.2 student directories remain untouched>
        canonical/
            <assessment-component>/
                <student-component>/
                    index.json
                    <submission-component>/
                        submission.json
                        originals/
                        derived/

Original artifact bytes and each submission manifest are immutable after a
successful commit.  The per-student ``index.json`` is the only mutable record
needed to choose which historical attempt is currently active.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import mimetypes
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from .domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_TYPE_UNKNOWN,
    SOURCE_SYSTEM_LOCAL_UPLOAD,
    SUBMISSION_STATUS_IMPORTED,
    ArtifactFile,
    CandidateFile,
    ExternalReference,
    Submission,
    generate_artifact_id,
    generate_submission_id,
)
from .file_store import (
    atomic_write_json,
    compute_file_sha256,
    copy_regular_file,
    read_json_object,
    reject_symlink,
    safe_path_component,
    safe_storage_filename,
)


CANONICAL_DIRNAME = "canonical"
CANONICAL_REPOSITORY_SCHEMA_VERSION = "1.0"
STUDENT_INDEX_FILENAME = "index.json"
SUBMISSION_MANIFEST_FILENAME = "submission.json"
ORIGINALS_DIRNAME = "originals"
DERIVED_DIRNAME = "derived"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_text(value: object, name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class CanonicalStoragePaths:
    """Stable canonical paths for one student/assessment pair."""

    storage_root: str
    canonical_root: str
    assessment_dir: str
    student_dir: str
    index_path: str

    def to_metadata(self) -> Dict[str, str]:
        return {
            "storage_root": self.storage_root,
            "canonical_root": self.canonical_root,
            "assessment_dir": self.assessment_dir,
            "student_dir": self.student_dir,
            "index_path": self.index_path,
        }


def canonical_storage_paths(
    storage_root: str,
    assessment_id: str,
    student_id: str,
    *,
    create: bool = False,
) -> CanonicalStoragePaths:
    """Return deterministic canonical paths for one assessment/student."""
    assessment_id = _required_text(assessment_id, "assessment_id")
    student_id = _required_text(student_id, "student_id")

    requested_root = Path(storage_root).expanduser()
    reject_symlink(requested_root, "submission evidence root")
    root = requested_root.resolve()

    canonical_root = root / CANONICAL_DIRNAME
    assessment_dir = canonical_root / safe_path_component(assessment_id)
    student_dir = assessment_dir / safe_path_component(student_id)

    for path, label in (
        (canonical_root, "canonical repository root"),
        (assessment_dir, "canonical assessment directory"),
        (student_dir, "canonical student directory"),
    ):
        reject_symlink(path, label)

    if create:
        root.mkdir(parents=True, exist_ok=True)
        canonical_root.mkdir(parents=True, exist_ok=True)
        assessment_dir.mkdir(parents=True, exist_ok=True)
        student_dir.mkdir(parents=True, exist_ok=True)

    return CanonicalStoragePaths(
        storage_root=str(root),
        canonical_root=str(canonical_root),
        assessment_dir=str(assessment_dir),
        student_dir=str(student_dir),
        index_path=str(student_dir / STUDENT_INDEX_FILENAME),
    )


class SubmissionRepository:
    """
    Filesystem-backed canonical submission repository.

    The repository is source-agnostic.  Commit 3's local importer and future
    Canvas adapters will both commit artifacts through this class.
    """

    def __init__(
        self,
        storage_root: str,
        *,
        create: bool = True,
    ) -> None:
        if not storage_root:
            raise ValueError("storage_root is required")

        requested = Path(storage_root).expanduser()
        reject_symlink(requested, "submission evidence root")
        self._storage_root = requested.resolve()
        self._canonical_root = self._storage_root / CANONICAL_DIRNAME
        self._lock = threading.RLock()

        reject_symlink(self._canonical_root, "canonical repository root")

        if create:
            self._storage_root.mkdir(parents=True, exist_ok=True)
            self._canonical_root.mkdir(parents=True, exist_ok=True)

    @property
    def storage_root(self) -> str:
        return str(self._storage_root)

    @property
    def canonical_root(self) -> str:
        return str(self._canonical_root)

    def paths(
        self,
        assessment_id: str,
        student_id: str,
        *,
        create: bool = False,
    ) -> CanonicalStoragePaths:
        return canonical_storage_paths(
            str(self._storage_root),
            assessment_id,
            student_id,
            create=create,
        )

    def _default_index(
        self,
        assessment_id: str,
        student_id: str,
    ) -> Dict[str, Any]:
        return {
            "schema_version": CANONICAL_REPOSITORY_SCHEMA_VERSION,
            "assessment_id": assessment_id,
            "student_id": student_id,
            "active_submission_id": None,
            "submissions": [],
        }

    def _load_index(
        self,
        assessment_id: str,
        student_id: str,
        *,
        allow_missing: bool = True,
    ) -> Dict[str, Any]:
        assessment_id = _required_text(assessment_id, "assessment_id")
        student_id = _required_text(student_id, "student_id")
        paths = self.paths(assessment_id, student_id, create=False)
        index_path = Path(paths.index_path)

        if not index_path.exists():
            if allow_missing:
                return self._default_index(assessment_id, student_id)
            raise FileNotFoundError(str(index_path))

        index = read_json_object(index_path)

        if str(index.get("schema_version", "")) != CANONICAL_REPOSITORY_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported canonical repository schema "
                f"{index.get('schema_version')!r}; expected "
                f"{CANONICAL_REPOSITORY_SCHEMA_VERSION!r}."
            )

        if str(index.get("assessment_id", "")) != assessment_id:
            raise ValueError(
                f"Canonical index assessment mismatch: "
                f"{index.get('assessment_id')!r} != {assessment_id!r}"
            )

        if str(index.get("student_id", "")) != student_id:
            raise ValueError(
                f"Canonical index student mismatch: "
                f"{index.get('student_id')!r} != {student_id!r}"
            )

        entries = index.get("submissions", [])
        if not isinstance(entries, list):
            raise ValueError("Canonical index submissions must be a list")

        seen_ids = set()
        seen_attempts = set()

        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Canonical index submission entry must be an object")

            submission_id = _required_text(
                entry.get("submission_id"),
                "submission_id",
            )
            if submission_id in seen_ids:
                raise ValueError(
                    f"Duplicate submission_id in canonical index: {submission_id}"
                )
            seen_ids.add(submission_id)

            attempt = entry.get("attempt")
            if attempt is not None:
                if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
                    raise ValueError(
                        f"Invalid canonical submission attempt: {attempt!r}"
                    )
                if attempt in seen_attempts:
                    raise ValueError(
                        f"Duplicate attempt in canonical index: {attempt}"
                    )
                seen_attempts.add(attempt)

        active = index.get("active_submission_id")
        if active is not None and str(active) not in seen_ids:
            raise ValueError(
                f"Canonical active_submission_id {active!r} is not in submissions"
            )

        return deepcopy(index)

    def _write_index(
        self,
        assessment_id: str,
        student_id: str,
        index: Mapping[str, Any],
    ) -> None:
        paths = self.paths(
            assessment_id,
            student_id,
            create=True,
        )
        payload = deepcopy(dict(index))
        payload["schema_version"] = CANONICAL_REPOSITORY_SCHEMA_VERSION
        payload["assessment_id"] = assessment_id
        payload["student_id"] = student_id

        entries = payload.get("submissions", [])
        payload["submissions"] = sorted(
            list(entries),
            key=lambda entry: (
                entry.get("attempt") is None,
                entry.get("attempt") or 0,
                str(entry.get("imported_at") or ""),
                str(entry.get("submission_id") or ""),
            ),
        )

        atomic_write_json(Path(paths.index_path), payload)

    def _submission_dir(
        self,
        assessment_id: str,
        student_id: str,
        submission_id: str,
    ) -> Path:
        paths = self.paths(
            assessment_id,
            student_id,
            create=False,
        )
        return Path(paths.student_dir) / safe_path_component(submission_id)

    def _manifest_path(
        self,
        assessment_id: str,
        student_id: str,
        submission_id: str,
    ) -> Path:
        return self._submission_dir(
            assessment_id,
            student_id,
            submission_id,
        ) / SUBMISSION_MANIFEST_FILENAME

    def _load_manifest_submission(
        self,
        assessment_id: str,
        student_id: str,
        submission_id: str,
        *,
        active_submission_id: Optional[str],
    ) -> Submission:
        manifest_path = self._manifest_path(
            assessment_id,
            student_id,
            submission_id,
        )

        if not manifest_path.exists():
            raise FileNotFoundError(str(manifest_path))

        payload = read_json_object(manifest_path)

        if str(payload.get("repository_schema_version", "")) != CANONICAL_REPOSITORY_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported canonical submission manifest schema "
                f"{payload.get('repository_schema_version')!r}; expected "
                f"{CANONICAL_REPOSITORY_SCHEMA_VERSION!r}."
            )

        submission_data = payload.get("submission")
        if not isinstance(submission_data, dict):
            raise ValueError(
                f"Canonical submission manifest is missing 'submission': "
                f"{manifest_path}"
            )

        submission = Submission.from_dict(submission_data)

        if submission.submission_id != submission_id:
            raise ValueError(
                f"Submission manifest ID mismatch: "
                f"{submission.submission_id!r} != {submission_id!r}"
            )
        if submission.assessment_id != assessment_id:
            raise ValueError(
                f"Submission manifest assessment mismatch: "
                f"{submission.assessment_id!r} != {assessment_id!r}"
            )
        if submission.student_id != student_id:
            raise ValueError(
                f"Submission manifest student mismatch: "
                f"{submission.student_id!r} != {student_id!r}"
            )

        # The manifest is immutable.  Active-attempt state is owned by index.json
        # and is overlaid only in the returned in-memory object.
        submission.is_active_attempt = (
            submission.submission_id == active_submission_id
        )
        return submission

    def next_attempt_number(
        self,
        assessment_id: str,
        student_id: str,
    ) -> int:
        """Return the next positive attempt number for this student/assessment."""
        with self._lock:
            index = self._load_index(
                assessment_id,
                student_id,
                allow_missing=True,
            )
            attempts = [
                entry.get("attempt")
                for entry in index["submissions"]
                if isinstance(entry.get("attempt"), int)
                and not isinstance(entry.get("attempt"), bool)
            ]
            return (max(attempts) + 1) if attempts else 1

    def create_submission(
        self,
        *,
        assessment_id: str,
        student_id: str,
        source_system: str = SOURCE_SYSTEM_LOCAL_UPLOAD,
        files: Sequence[Union[CandidateFile, Mapping[str, Any]]] = (),
        attempt: Optional[int] = None,
        make_active: bool = True,
        submitted_at: Optional[str] = None,
        imported_at: Optional[str] = None,
        status: str = SUBMISSION_STATUS_IMPORTED,
        external_refs: Sequence[
            Union[ExternalReference, Mapping[str, Any]]
        ] = (),
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Submission:
        """
        Atomically commit one new canonical submission and its original files.

        The source files are copied into a temporary sibling directory first.
        The immutable submission directory becomes visible only after all files,
        hashes, and the manifest have been written successfully.
        """
        assessment_id = _required_text(assessment_id, "assessment_id")
        student_id = _required_text(student_id, "student_id")
        source_system = _required_text(source_system, "source_system")
        status = _required_text(status, "status")
        imported_at = _optional_text(imported_at) or _utc_now_iso()
        submitted_at = _optional_text(submitted_at)

        if not isinstance(make_active, bool):
            raise TypeError("make_active must be a bool")

        candidate_files: List[CandidateFile] = []
        for value in files:
            if isinstance(value, CandidateFile):
                candidate_files.append(value)
            elif isinstance(value, Mapping):
                candidate_files.append(CandidateFile.from_dict(value))
            else:
                raise TypeError(
                    "files must contain CandidateFile objects or mappings"
                )

        refs: List[ExternalReference] = []
        for value in external_refs:
            if isinstance(value, ExternalReference):
                refs.append(value)
            elif isinstance(value, Mapping):
                refs.append(ExternalReference.from_dict(value))
            else:
                raise TypeError(
                    "external_refs must contain ExternalReference objects or mappings"
                )

        metadata_dict = deepcopy(dict(metadata or {}))

        with self._lock:
            paths = self.paths(
                assessment_id,
                student_id,
                create=True,
            )
            index = self._load_index(
                assessment_id,
                student_id,
                allow_missing=True,
            )

            if attempt is None:
                attempts = [
                    entry.get("attempt")
                    for entry in index["submissions"]
                    if isinstance(entry.get("attempt"), int)
                    and not isinstance(entry.get("attempt"), bool)
                ]
                attempt = (max(attempts) + 1) if attempts else 1
            else:
                if isinstance(attempt, bool) or not isinstance(attempt, int):
                    raise TypeError("attempt must be an integer or None")
                if attempt <= 0:
                    raise ValueError("attempt must be positive")
                if any(
                    entry.get("attempt") == attempt
                    for entry in index["submissions"]
                ):
                    raise ValueError(
                        f"Attempt {attempt} already exists for "
                        f"{student_id!r} / {assessment_id!r}"
                    )

            submission_id = generate_submission_id()
            student_dir = Path(paths.student_dir)
            staging_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{submission_id}.",
                    dir=str(student_dir),
                )
            )
            final_dir = self._submission_dir(
                assessment_id,
                student_id,
                submission_id,
            )

            if final_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise FileExistsError(str(final_dir))

            committed_final = False

            try:
                originals_dir = staging_dir / ORIGINALS_DIRNAME
                derived_dir = staging_dir / DERIVED_DIRNAME
                originals_dir.mkdir(parents=True, exist_ok=False)
                derived_dir.mkdir(parents=True, exist_ok=False)

                artifacts: List[ArtifactFile] = []

                for candidate in candidate_files:
                    artifact_id = generate_artifact_id()
                    safe_name = safe_storage_filename(
                        candidate.original_filename
                    )
                    stored_name = f"{artifact_id}__{safe_name}"
                    target = originals_dir / stored_name

                    copied = copy_regular_file(
                        candidate.source_path,
                        target,
                        overwrite=False,
                    )

                    size_bytes = Path(copied).stat().st_size
                    digest = compute_file_sha256(copied)

                    # Candidate size/hash are discovery hints.  If present, they
                    # must still agree with the bytes committed now.
                    if (
                        candidate.size_bytes is not None
                        and candidate.size_bytes != size_bytes
                    ):
                        raise ValueError(
                            f"Source file changed during import: "
                            f"{candidate.original_filename!r} size "
                            f"{candidate.size_bytes} -> {size_bytes}"
                        )
                    if (
                        candidate.sha256 is not None
                        and candidate.sha256 != digest
                    ):
                        raise ValueError(
                            f"Source file changed during import: "
                            f"{candidate.original_filename!r} SHA-256 mismatch"
                        )

                    mime_type = mimetypes.guess_type(
                        candidate.original_filename
                    )[0]

                    artifacts.append(
                        ArtifactFile(
                            artifact_id=artifact_id,
                            submission_id=submission_id,
                            role=candidate.role or ARTIFACT_ROLE_PRIMARY,
                            artifact_type=(
                                candidate.artifact_type
                                or ARTIFACT_TYPE_UNKNOWN
                            ),
                            original_filename=candidate.original_filename,
                            stored_relative_path=str(
                                Path(ORIGINALS_DIRNAME) / stored_name
                            ),
                            size_bytes=size_bytes,
                            sha256=digest,
                            mime_type=mime_type,
                            metadata=deepcopy(candidate.metadata),
                        )
                    )

                active_now = bool(
                    make_active
                    or not index.get("active_submission_id")
                )

                submission = Submission(
                    submission_id=submission_id,
                    assessment_id=assessment_id,
                    student_id=student_id,
                    source_system=source_system,
                    imported_at=imported_at,
                    submitted_at=submitted_at,
                    attempt=attempt,
                    is_active_attempt=active_now,
                    status=status,
                    artifacts=artifacts,
                    external_refs=refs,
                    metadata=metadata_dict,
                )

                manifest = {
                    "repository_schema_version": (
                        CANONICAL_REPOSITORY_SCHEMA_VERSION
                    ),
                    "submission": submission.to_dict(),
                }

                # The manifest is written once inside staging and never modified
                # after the directory is committed.
                atomic_write_json(
                    staging_dir / SUBMISSION_MANIFEST_FILENAME,
                    manifest,
                    overwrite=False,
                )

                os.replace(str(staging_dir), str(final_dir))
                committed_final = True

                entry = {
                    "submission_id": submission_id,
                    "attempt": attempt,
                    "imported_at": imported_at,
                    "submitted_at": submitted_at,
                    "source_system": source_system,
                }
                index["submissions"].append(entry)

                if active_now:
                    index["active_submission_id"] = submission_id

                try:
                    self._write_index(
                        assessment_id,
                        student_id,
                        index,
                    )
                except Exception:
                    # The new immutable submission is not yet referenced by an
                    # index, so rollback is safe and avoids an orphan directory.
                    shutil.rmtree(final_dir, ignore_errors=True)
                    committed_final = False
                    raise

                return self.get_submission(
                    submission_id,
                    assessment_id=assessment_id,
                    student_id=student_id,
                )

            except Exception:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
                if not committed_final and final_dir.exists():
                    # Only remove a directory created by this failed operation.
                    # Existing immutable submissions are never targeted here
                    # because submission IDs are newly generated above.
                    shutil.rmtree(final_dir, ignore_errors=True)
                raise

    def list_submissions(
        self,
        assessment_id: str,
        student_id: str,
    ) -> List[Submission]:
        """Return all historical submissions in attempt/import order."""
        with self._lock:
            index = self._load_index(
                assessment_id,
                student_id,
                allow_missing=True,
            )
            active = index.get("active_submission_id")
            results = []

            for entry in index["submissions"]:
                results.append(
                    self._load_manifest_submission(
                        assessment_id,
                        student_id,
                        str(entry["submission_id"]),
                        active_submission_id=(
                            str(active)
                            if active is not None
                            else None
                        ),
                    )
                )

            return results

    def get_active_submission(
        self,
        assessment_id: str,
        student_id: str,
    ) -> Optional[Submission]:
        """Return the active historical attempt, or ``None`` if none exists."""
        with self._lock:
            index = self._load_index(
                assessment_id,
                student_id,
                allow_missing=True,
            )
            active = index.get("active_submission_id")
            if not active:
                return None

            return self._load_manifest_submission(
                assessment_id,
                student_id,
                str(active),
                active_submission_id=str(active),
            )

    def set_active_submission(
        self,
        assessment_id: str,
        student_id: str,
        submission_id: str,
    ) -> Submission:
        """Select a historical submission without modifying its manifest."""
        assessment_id = _required_text(assessment_id, "assessment_id")
        student_id = _required_text(student_id, "student_id")
        submission_id = _required_text(submission_id, "submission_id")

        with self._lock:
            index = self._load_index(
                assessment_id,
                student_id,
                allow_missing=False,
            )
            ids = {
                str(entry.get("submission_id"))
                for entry in index["submissions"]
            }
            if submission_id not in ids:
                raise KeyError(
                    f"Unknown submission_id for student/assessment: "
                    f"{submission_id}"
                )

            # Validate the manifest before changing the mutable active pointer.
            self._load_manifest_submission(
                assessment_id,
                student_id,
                submission_id,
                active_submission_id=submission_id,
            )

            index["active_submission_id"] = submission_id
            self._write_index(
                assessment_id,
                student_id,
                index,
            )

            return self._load_manifest_submission(
                assessment_id,
                student_id,
                submission_id,
                active_submission_id=submission_id,
            )

    def get_submission(
        self,
        submission_id: str,
        *,
        assessment_id: Optional[str] = None,
        student_id: Optional[str] = None,
    ) -> Submission:
        """
        Load a submission by internal ID.

        Supplying both assessment/student IDs avoids a repository scan.  The
        scan fallback is intentionally supported so later services can keep only
        the opaque ``submission_id`` as their primary reference.
        """
        submission_id = _required_text(submission_id, "submission_id")

        if (assessment_id is None) != (student_id is None):
            raise ValueError(
                "assessment_id and student_id must be supplied together"
            )

        with self._lock:
            if assessment_id is not None and student_id is not None:
                assessment_id = _required_text(
                    assessment_id,
                    "assessment_id",
                )
                student_id = _required_text(
                    student_id,
                    "student_id",
                )
                index = self._load_index(
                    assessment_id,
                    student_id,
                    allow_missing=False,
                )
                ids = {
                    str(entry.get("submission_id"))
                    for entry in index["submissions"]
                }
                if submission_id not in ids:
                    raise KeyError(submission_id)

                active = index.get("active_submission_id")
                return self._load_manifest_submission(
                    assessment_id,
                    student_id,
                    submission_id,
                    active_submission_id=(
                        str(active)
                        if active is not None
                        else None
                    ),
                )

            if not self._canonical_root.exists():
                raise KeyError(submission_id)

            for index_path in sorted(
                self._canonical_root.rglob(STUDENT_INDEX_FILENAME)
            ):
                if index_path.is_symlink():
                    continue
                try:
                    index = read_json_object(index_path)
                except (OSError, ValueError):
                    continue

                entries = index.get("submissions", [])
                if not isinstance(entries, list):
                    continue
                if not any(
                    isinstance(entry, dict)
                    and str(entry.get("submission_id")) == submission_id
                    for entry in entries
                ):
                    continue

                found_assessment = str(index.get("assessment_id") or "")
                found_student = str(index.get("student_id") or "")
                if not found_assessment or not found_student:
                    continue

                validated_index = self._load_index(
                    found_assessment,
                    found_student,
                    allow_missing=False,
                )
                active = validated_index.get("active_submission_id")

                return self._load_manifest_submission(
                    found_assessment,
                    found_student,
                    submission_id,
                    active_submission_id=(
                        str(active)
                        if active is not None
                        else None
                    ),
                )

        raise KeyError(submission_id)

    def submission_exists(
        self,
        submission_id: str,
        *,
        assessment_id: Optional[str] = None,
        student_id: Optional[str] = None,
    ) -> bool:
        try:
            self.get_submission(
                submission_id,
                assessment_id=assessment_id,
                student_id=student_id,
            )
            return True
        except (KeyError, FileNotFoundError):
            return False

    def submission_directory(
        self,
        submission: Submission,
    ) -> str:
        """Return the verified canonical directory for a loaded submission."""
        directory = self._submission_dir(
            submission.assessment_id,
            submission.student_id,
            submission.submission_id,
        )
        if not directory.exists() or not directory.is_dir():
            raise FileNotFoundError(str(directory))
        reject_symlink(directory, "canonical submission directory")
        return str(directory.resolve())

    def artifact_path(
        self,
        submission: Submission,
        artifact: Union[ArtifactFile, str],
    ) -> str:
        """Resolve and validate one canonical artifact path."""
        if isinstance(artifact, str):
            found = submission.artifact_by_id(artifact)
            if found is None:
                raise KeyError(artifact)
            artifact = found
        elif not isinstance(artifact, ArtifactFile):
            raise TypeError("artifact must be ArtifactFile or artifact_id")

        if artifact.submission_id != submission.submission_id:
            raise ValueError(
                "artifact does not belong to the supplied submission"
            )

        submission_dir = Path(self.submission_directory(submission))
        relative = Path(artifact.stored_relative_path)

        if relative.is_absolute():
            raise ValueError(
                "canonical artifact stored_relative_path must be relative"
            )

        target = (submission_dir / relative).resolve()

        try:
            target.relative_to(submission_dir)
        except ValueError as exc:
            raise ValueError(
                "canonical artifact path escapes submission directory"
            ) from exc

        if target.is_symlink():
            raise ValueError(
                f"Symlinked canonical artifacts are not accepted: {target}"
            )
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(str(target))

        return str(target)

    def verify_submission(
        self,
        submission: Submission,
    ) -> Dict[str, Any]:
        """Verify committed original artifact sizes and SHA-256 digests."""
        artifact_results: Dict[str, Dict[str, Any]] = {}
        ok = True

        for artifact in submission.artifacts:
            result: Dict[str, Any] = {
                "expected_sha256": artifact.sha256,
                "expected_size_bytes": artifact.size_bytes,
                "ok": True,
            }

            try:
                path = self.artifact_path(
                    submission,
                    artifact,
                )
                actual_size = Path(path).stat().st_size
                actual_sha = compute_file_sha256(path)
                result.update(
                    {
                        "path": path,
                        "actual_size_bytes": actual_size,
                        "actual_sha256": actual_sha,
                    }
                )

                if (
                    actual_size != artifact.size_bytes
                    or actual_sha != artifact.sha256
                ):
                    result["ok"] = False
                    ok = False
            except (OSError, ValueError) as exc:
                result["ok"] = False
                result["error"] = str(exc)
                ok = False

            artifact_results[artifact.artifact_id] = result

        return {
            "submission_id": submission.submission_id,
            "ok": ok,
            "artifacts": artifact_results,
        }


__all__ = [
    "CANONICAL_DIRNAME",
    "CANONICAL_REPOSITORY_SCHEMA_VERSION",
    "CanonicalStoragePaths",
    "DERIVED_DIRNAME",
    "ORIGINALS_DIRNAME",
    "STUDENT_INDEX_FILENAME",
    "SUBMISSION_MANIFEST_FILENAME",
    "SubmissionRepository",
    "canonical_storage_paths",
]
