"""Source-agnostic canonical submission import orchestration for v2.3.2.

Commit 3 introduces the preview/commit boundary used by local files now and by
future Canvas/Git adapters later.  Discovery adapters produce ``ImportCandidate``
objects.  ``SubmissionImporter`` then:

* resolves candidates conservatively against the existing roster;
* validates assessment/student identity;
* detects exact duplicates and changed re-submissions;
* proposes deterministic attempt numbers;
* commits approved candidates through ``SubmissionRepository``.

Nothing in this module parses student answers or changes grading state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from .domain import (
    MATCH_STATUS_AMBIGUOUS,
    MATCH_STATUS_MATCHED,
    MATCH_STATUS_UNMATCHED,
    VALIDATION_STATUS_DUPLICATE,
    VALIDATION_STATUS_ERROR,
    VALIDATION_STATUS_INVALID,
    VALIDATION_STATUS_NEEDS_MAPPING,
    VALIDATION_STATUS_READY,
    CandidateFile,
    ImportBatch,
    ImportCandidate,
    Submission,
    generate_import_batch_id,
)
from .repository import SubmissionRepository
from .sources.base import SubmissionSourceAdapter


DUPLICATE_STATUS_NONE = "none"
DUPLICATE_STATUS_EXACT_ACTIVE = "exact_active_submission"
DUPLICATE_STATUS_EXACT_HISTORICAL = "exact_historical_submission"
DUPLICATE_STATUS_IN_BATCH_EXACT = "in_batch_exact_duplicate"
DUPLICATE_STATUS_SAME_FILENAMES_CHANGED = "same_filenames_different_bytes"
DUPLICATE_STATUS_EXISTING_NEW_ATTEMPT = "existing_submission_new_attempt"
DUPLICATE_STATUS_NOT_CHECKED = "not_checked"


_IDENTITY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STUDENT_KEY_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _RosterRecord:
    student_id: str
    student_name: str


def _normalize_student_key(value: object) -> str:
    """Mirror core.roster.normalize_student_key without importing core.__init__."""
    if value is None:
        return ""
    return _STUDENT_KEY_RE.sub("", str(value).casefold())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _candidate_copy(candidate: ImportCandidate) -> ImportCandidate:
    if not isinstance(candidate, ImportCandidate):
        raise TypeError("candidate must be ImportCandidate")
    return ImportCandidate.from_dict(candidate.to_dict())


def _tokens(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    return tuple(_IDENTITY_TOKEN_RE.findall(str(value).casefold()))


def _candidate_hints(candidate: ImportCandidate) -> List[str]:
    hints: List[str] = []
    metadata_hints = candidate.metadata.get("identity_hints", [])
    if isinstance(metadata_hints, (list, tuple)):
        hints.extend(str(value).strip() for value in metadata_hints if str(value).strip())

    for candidate_file in candidate.files:
        stem = candidate_file.original_filename.rsplit(".", 1)[0].strip()
        if stem:
            hints.append(stem)

    if candidate.source_locator:
        locator = str(candidate.source_locator).replace("\\", "/").rstrip("/")
        if locator:
            hints.append(locator.rsplit("/", 1)[-1])

    return list(dict.fromkeys(value for value in hints if value))


def _record_match_score(record: _RosterRecord, hints: Sequence[str]) -> int:
    """Return a conservative filename/directory match score for one student."""
    student_id_key = _normalize_student_key(record.student_id)
    student_name_key = _normalize_student_key(record.student_name)
    student_id_tokens = _tokens(record.student_id)
    student_name_tokens = tuple(
        token for token in _tokens(record.student_name) if len(token) >= 2
    )

    best = 0
    for hint in hints:
        hint_key = _normalize_student_key(hint)
        hint_tokens = set(_tokens(hint))

        if student_id_key and hint_key == student_id_key:
            best = max(best, 100)
        if student_name_key and hint_key == student_name_key:
            best = max(best, 95)

        # Stable IDs often appear as one delimited filename token:
        # ``abc123_PS1.tex``.
        if (
            student_id_key
            and student_id_tokens
            and len(student_id_tokens) == 1
            and student_id_tokens[0] in hint_tokens
        ):
            best = max(best, 90)

        # Names may be written in either order (``lastname_firstname`` or
        # ``firstname_lastname``).  Requiring all name tokens avoids substring
        # guessing and remains conservative when names are ambiguous.
        if student_name_tokens and set(student_name_tokens).issubset(hint_tokens):
            best = max(best, 80 if len(student_name_tokens) >= 2 else 70)

    return best


def _artifact_fingerprint_from_files(
    files: Sequence[CandidateFile],
) -> Optional[Tuple[Tuple[str, int], ...]]:
    values: List[Tuple[str, int]] = []
    for item in files:
        if item.sha256 is None or item.size_bytes is None:
            return None
        values.append((item.sha256, item.size_bytes))
    return tuple(sorted(values))


def _artifact_fingerprint_from_submission(
    submission: Submission,
) -> Tuple[Tuple[str, int], ...]:
    return tuple(
        sorted((artifact.sha256, artifact.size_bytes) for artifact in submission.artifacts)
    )


def _filename_signature_from_files(files: Sequence[CandidateFile]) -> Tuple[str, ...]:
    return tuple(sorted(item.original_filename.casefold() for item in files))


def _filename_signature_from_submission(submission: Submission) -> Tuple[str, ...]:
    return tuple(sorted(item.original_filename.casefold() for item in submission.artifacts))


@dataclass
class ImportCommitResult:
    """Result of committing a prepared import batch."""

    batch: ImportBatch
    submissions: List[Submission] = field(default_factory=list)
    skipped_candidate_ids: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)


class SubmissionImporter:
    """Prepare and commit source-agnostic import candidates."""

    def __init__(
        self,
        repository: SubmissionRepository,
        *,
        assessment_id: str,
        roster: Sequence[Any],
    ) -> None:
        if not isinstance(repository, SubmissionRepository):
            raise TypeError("repository must be SubmissionRepository")

        assessment_id = str(assessment_id or "").strip()
        if not assessment_id:
            raise ValueError("assessment_id is required")

        self.repository = repository
        self.assessment_id = assessment_id
        self.roster: List[_RosterRecord] = []
        for record in roster:
            if not hasattr(record, "student_id") or not hasattr(record, "student_name"):
                raise TypeError(
                    "roster entries must provide student_id and student_name attributes"
                )
            self.roster.append(
                _RosterRecord(
                    student_id=str(getattr(record, "student_id") or "").strip(),
                    student_name=str(getattr(record, "student_name") or "").strip(),
                )
            )

        self._records_by_id: Dict[str, _RosterRecord] = {}
        for record in self.roster:
            key = _normalize_student_key(record.student_id)
            if not key:
                raise ValueError("Roster contains a student with no stable student_id")
            if key in self._records_by_id:
                raise ValueError(f"Duplicate roster student_id: {record.student_id!r}")
            self._records_by_id[key] = record

    def _resolve_override(self, student_id: str) -> _RosterRecord:
        key = _normalize_student_key(student_id)
        record = self._records_by_id.get(key)
        if record is None:
            raise KeyError(f"Unknown roster student_id: {student_id!r}")
        return record

    def _match_student(self, candidate: ImportCandidate) -> Tuple[Optional[_RosterRecord], str]:
        # A source adapter may already provide a stable internal student ID.  Use
        # it only if that ID exists in the current roster.
        if candidate.proposed_student_id:
            key = _normalize_student_key(candidate.proposed_student_id)
            if key in self._records_by_id:
                return self._records_by_id[key], MATCH_STATUS_MATCHED

        hints = _candidate_hints(candidate)
        scored: List[Tuple[int, _RosterRecord]] = []
        for record in self.roster:
            score = _record_match_score(record, hints)
            if score > 0:
                scored.append((score, record))

        if not scored:
            return None, MATCH_STATUS_UNMATCHED

        best_score = max(score for score, _ in scored)
        best_records = [record for score, record in scored if score == best_score]
        if len(best_records) != 1:
            return None, MATCH_STATUS_AMBIGUOUS

        return best_records[0], MATCH_STATUS_MATCHED

    def _analyze_repository_duplicate(
        self,
        candidate: ImportCandidate,
    ) -> Tuple[str, Optional[str]]:
        if not candidate.proposed_student_id or not candidate.proposed_assessment_id:
            return DUPLICATE_STATUS_NOT_CHECKED, None

        fingerprint = _artifact_fingerprint_from_files(candidate.files)
        history = self.repository.list_submissions(
            candidate.proposed_assessment_id,
            candidate.proposed_student_id,
        )

        if fingerprint is not None:
            for submission in history:
                if _artifact_fingerprint_from_submission(submission) == fingerprint:
                    return (
                        DUPLICATE_STATUS_EXACT_ACTIVE
                        if submission.is_active_attempt
                        else DUPLICATE_STATUS_EXACT_HISTORICAL,
                        submission.submission_id,
                    )

        if history:
            active = next((item for item in history if item.is_active_attempt), None)
            if (
                active is not None
                and _filename_signature_from_submission(active)
                == _filename_signature_from_files(candidate.files)
            ):
                return DUPLICATE_STATUS_SAME_FILENAMES_CHANGED, active.submission_id
            return DUPLICATE_STATUS_EXISTING_NEW_ATTEMPT, active.submission_id if active else None

        return DUPLICATE_STATUS_NONE, None

    def prepare_candidate(
        self,
        candidate: ImportCandidate,
        *,
        student_override: Optional[str] = None,
    ) -> ImportCandidate:
        """Return a prepared copy suitable for preview or commit."""
        prepared = _candidate_copy(candidate)
        prepared.errors = list(prepared.errors)
        prepared.warnings = list(prepared.warnings)

        if prepared.proposed_assessment_id and prepared.proposed_assessment_id != self.assessment_id:
            prepared.errors.append(
                "assessment_mismatch:"
                f"{prepared.proposed_assessment_id}!={self.assessment_id}"
            )
            prepared.validation_status = VALIDATION_STATUS_INVALID
            return prepared
        prepared.proposed_assessment_id = self.assessment_id

        if not prepared.files:
            prepared.errors.append("no_candidate_files")
            prepared.validation_status = VALIDATION_STATUS_INVALID
            return prepared

        if student_override is not None:
            try:
                record = self._resolve_override(student_override)
            except KeyError as exc:
                prepared.errors.append(str(exc))
                prepared.match_status = MATCH_STATUS_UNMATCHED
                prepared.validation_status = VALIDATION_STATUS_NEEDS_MAPPING
                return prepared
            prepared.proposed_student_id = record.student_id
            prepared.match_status = MATCH_STATUS_MATCHED
            prepared.metadata["student_match"] = {
                "method": "manual_override",
                "student_id": record.student_id,
            }
        else:
            record, match_status = self._match_student(prepared)
            prepared.match_status = match_status
            if record is not None:
                prepared.proposed_student_id = record.student_id
                prepared.metadata["student_match"] = {
                    "method": "conservative_identity_hints",
                    "student_id": record.student_id,
                }

        if prepared.match_status != MATCH_STATUS_MATCHED or not prepared.proposed_student_id:
            prepared.validation_status = VALIDATION_STATUS_NEEDS_MAPPING
            return prepared

        try:
            history = self.repository.list_submissions(
                self.assessment_id,
                prepared.proposed_student_id,
            )
        except (OSError, ValueError) as exc:
            prepared.errors.append(f"repository_read_error:{exc}")
            prepared.validation_status = VALIDATION_STATUS_ERROR
            return prepared

        if prepared.proposed_attempt is not None:
            colliding = next(
                (item for item in history if item.attempt == prepared.proposed_attempt),
                None,
            )
            if colliding is not None:
                fingerprint = _artifact_fingerprint_from_files(prepared.files)
                if (
                    fingerprint is not None
                    and _artifact_fingerprint_from_submission(colliding) == fingerprint
                ):
                    prepared.metadata["duplicate_status"] = (
                        DUPLICATE_STATUS_EXACT_ACTIVE
                        if colliding.is_active_attempt
                        else DUPLICATE_STATUS_EXACT_HISTORICAL
                    )
                    prepared.metadata["duplicate_submission_id"] = colliding.submission_id
                    prepared.validation_status = VALIDATION_STATUS_DUPLICATE
                    return prepared

                prepared.errors.append(
                    f"attempt_conflict:{prepared.proposed_attempt}:"
                    f"{colliding.submission_id}"
                )
                prepared.validation_status = VALIDATION_STATUS_INVALID
                return prepared

        duplicate_status, duplicate_submission_id = self._analyze_repository_duplicate(prepared)
        prepared.metadata["duplicate_status"] = duplicate_status
        if duplicate_submission_id:
            prepared.metadata["duplicate_submission_id"] = duplicate_submission_id

        if duplicate_status in {
            DUPLICATE_STATUS_EXACT_ACTIVE,
            DUPLICATE_STATUS_EXACT_HISTORICAL,
        }:
            prepared.validation_status = VALIDATION_STATUS_DUPLICATE
            return prepared

        if duplicate_status == DUPLICATE_STATUS_SAME_FILENAMES_CHANGED:
            prepared.warnings.append("same_filenames_different_bytes")
        elif duplicate_status == DUPLICATE_STATUS_EXISTING_NEW_ATTEMPT:
            prepared.warnings.append("existing_submission_new_attempt")

        if prepared.proposed_attempt is None:
            prepared.proposed_attempt = self.repository.next_attempt_number(
                self.assessment_id,
                prepared.proposed_student_id,
            )

        prepared.validation_status = VALIDATION_STATUS_READY
        prepared.warnings = list(dict.fromkeys(prepared.warnings))
        prepared.errors = list(dict.fromkeys(prepared.errors))
        return prepared

    def prepare_candidates(
        self,
        candidates: Sequence[ImportCandidate],
        *,
        student_overrides: Optional[Mapping[str, str]] = None,
    ) -> List[ImportCandidate]:
        """Prepare a batch and assign non-conflicting attempts deterministically."""
        overrides = dict(student_overrides or {})
        prepared: List[ImportCandidate] = []
        next_attempt_by_identity: Dict[Tuple[str, str], int] = {}
        used_attempts: Dict[Tuple[str, str], set] = {}
        seen_fingerprints: Dict[
            Tuple[str, str, Tuple[Tuple[str, int], ...]],
            str,
        ] = {}

        for candidate in candidates:
            item = self.prepare_candidate(
                candidate,
                student_override=overrides.get(candidate.candidate_id),
            )

            if (
                item.validation_status == VALIDATION_STATUS_READY
                and item.proposed_student_id
                and item.proposed_assessment_id
            ):
                identity = (item.proposed_assessment_id, item.proposed_student_id)
                fingerprint = _artifact_fingerprint_from_files(item.files)

                if fingerprint is not None:
                    batch_key = (identity[0], identity[1], fingerprint)
                    if batch_key in seen_fingerprints:
                        item.metadata["duplicate_status"] = DUPLICATE_STATUS_IN_BATCH_EXACT
                        item.metadata["duplicate_candidate_id"] = seen_fingerprints[batch_key]
                        item.validation_status = VALIDATION_STATUS_DUPLICATE
                        prepared.append(item)
                        continue
                    seen_fingerprints[batch_key] = item.candidate_id

                if identity not in next_attempt_by_identity:
                    next_attempt_by_identity[identity] = self.repository.next_attempt_number(*identity)
                    existing = self.repository.list_submissions(*identity)
                    used_attempts[identity] = {
                        entry.attempt for entry in existing if entry.attempt is not None
                    }

                desired = item.proposed_attempt
                if desired is None or desired in used_attempts[identity]:
                    desired = next_attempt_by_identity[identity]
                    while desired in used_attempts[identity]:
                        desired += 1
                    item.proposed_attempt = desired

                used_attempts[identity].add(item.proposed_attempt)
                next_attempt_by_identity[identity] = max(
                    next_attempt_by_identity[identity],
                    item.proposed_attempt + 1,
                )

            prepared.append(item)

        return prepared

    def prepare_from_adapter(
        self,
        adapter: SubmissionSourceAdapter,
        *,
        student_overrides: Optional[Mapping[str, str]] = None,
    ) -> List[ImportCandidate]:
        """Discover through an adapter and prepare the resulting candidates."""
        if not isinstance(adapter, SubmissionSourceAdapter):
            raise TypeError("adapter does not implement SubmissionSourceAdapter")
        candidates = adapter.discover(assessment_id=self.assessment_id)
        return self.prepare_candidates(
            candidates,
            student_overrides=student_overrides,
        )

    def commit_candidate(
        self,
        candidate: ImportCandidate,
        *,
        adapter: Optional[SubmissionSourceAdapter] = None,
        make_active: bool = True,
        force_duplicate: bool = False,
    ) -> Submission:
        """Commit one prepared candidate through ``SubmissionRepository``."""
        item = _candidate_copy(candidate)

        if not item.proposed_student_id or not item.proposed_assessment_id:
            raise ValueError("candidate must have resolved student and assessment IDs")
        if item.proposed_assessment_id != self.assessment_id:
            raise ValueError("candidate assessment does not match importer assessment")

        if item.validation_status == VALIDATION_STATUS_DUPLICATE:
            if not force_duplicate:
                raise ValueError("candidate is an exact duplicate; force_duplicate is required")
            item.proposed_attempt = self.repository.next_attempt_number(
                item.proposed_assessment_id,
                item.proposed_student_id,
            )
        elif item.validation_status != VALIDATION_STATUS_READY:
            raise ValueError(
                f"candidate is not ready for commit: {item.validation_status}"
            )

        files = list(item.files)
        if adapter is not None:
            if not isinstance(adapter, SubmissionSourceAdapter):
                raise TypeError("adapter does not implement SubmissionSourceAdapter")
            if adapter.source_system != item.source_system:
                raise ValueError("adapter source does not match candidate source")
            files = adapter.fetch(item)

        metadata = deepcopy(item.metadata)
        metadata.update(
            {
                "import_candidate_id": item.candidate_id,
                "import_source_locator": item.source_locator,
                "import_warnings": list(item.warnings),
            }
        )

        return self.repository.create_submission(
            assessment_id=item.proposed_assessment_id,
            student_id=item.proposed_student_id,
            source_system=item.source_system,
            files=files,
            attempt=item.proposed_attempt,
            make_active=make_active,
            metadata=metadata,
        )

    def commit_candidates(
        self,
        candidates: Sequence[ImportCandidate],
        *,
        adapter: Optional[SubmissionSourceAdapter] = None,
        created_by: Optional[str] = None,
        make_active: bool = True,
        skip_unready: bool = True,
    ) -> ImportCommitResult:
        """Commit every ready candidate independently and return a batch summary."""
        started_at = _utc_now_iso()
        submissions: List[Submission] = []
        skipped: List[str] = []
        errors: Dict[str, str] = {}

        for candidate in candidates:
            if candidate.validation_status != VALIDATION_STATUS_READY:
                if skip_unready:
                    skipped.append(candidate.candidate_id)
                    continue
                errors[candidate.candidate_id] = (
                    f"candidate_not_ready:{candidate.validation_status}"
                )
                continue

            try:
                submissions.append(
                    self.commit_candidate(
                        candidate,
                        adapter=adapter,
                        make_active=make_active,
                    )
                )
            except Exception as exc:
                errors[candidate.candidate_id] = str(exc)

        status = "completed" if not errors else "completed_with_errors"
        batch = ImportBatch(
            import_batch_id=generate_import_batch_id(),
            source_system=(
                adapter.source_system
                if adapter is not None
                else (
                    candidates[0].source_system
                    if candidates
                    else "local_upload"
                )
            ),
            started_at=started_at,
            completed_at=_utc_now_iso(),
            created_by=created_by,
            candidate_count=len(candidates),
            imported_count=len(submissions),
            skipped_count=len(skipped),
            error_count=len(errors),
            status=status,
            metadata={
                "assessment_id": self.assessment_id,
                "submission_ids": [item.submission_id for item in submissions],
            },
        )

        return ImportCommitResult(
            batch=batch,
            submissions=submissions,
            skipped_candidate_ids=skipped,
            errors=errors,
        )


__all__ = [
    "DUPLICATE_STATUS_EXACT_ACTIVE",
    "DUPLICATE_STATUS_EXACT_HISTORICAL",
    "DUPLICATE_STATUS_EXISTING_NEW_ATTEMPT",
    "DUPLICATE_STATUS_IN_BATCH_EXACT",
    "DUPLICATE_STATUS_NONE",
    "DUPLICATE_STATUS_NOT_CHECKED",
    "DUPLICATE_STATUS_SAME_FILENAMES_CHANGED",
    "ImportCommitResult",
    "SubmissionImporter",
]
