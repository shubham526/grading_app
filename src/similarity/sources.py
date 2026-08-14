"""Submission-source adapters for v2.3.0 similarity review.

This module deliberately reuses the v2.2.0 submission-ingestion and evidence
formats.  It does not reimplement LaTeX extraction, PDF handling, submission
matching, question splitting, or persisted-evidence loading.

The UI can obtain a ``SimilaritySourceResult`` from one of three sources:

* already-loaded ParsedSubmission objects,
* a normal LaTeX submissions folder parsed by the v2.2 backend,
* a saved assessment folder containing submission_meta + extracted_answers.

PDF accommodations remain explicit. A raw submissions folder is the normal
LaTeX path; already-loaded or saved-assessment sources can include explicit PDF
accommodation submissions created by v2.2.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any, Callable, Mapping, Sequence

from src.submissions import (
    FULL_SUBMISSION,
    ParsedSubmission,
    load_persisted_submission,
    normalize_student_id,
    parse_submissions_folder,
)


SOURCE_LOADED = "loaded"
SOURCE_SUBMISSIONS_FOLDER = "submissions_folder"
SOURCE_ASSESSMENT_FOLDER = "assessment_folder"

VALID_SOURCE_TYPES = (
    SOURCE_LOADED,
    SOURCE_SUBMISSIONS_FOLDER,
    SOURCE_ASSESSMENT_FOLDER,
)


@dataclass
class SimilaritySourceResult:
    """Normalized input bundle for assignment-level similarity review."""

    source_type: str
    submissions: dict[str, Any] = field(default_factory=dict)
    question_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_path: str | None = None

    def __post_init__(self) -> None:
        if self.source_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Unsupported similarity source type {self.source_type!r}; "
                f"expected one of: {', '.join(VALID_SOURCE_TYPES)}"
            )

    @property
    def student_ids(self) -> list[str]:
        return sorted(self.submissions)


def _append_warning_once(target: list[str], warning: str) -> None:
    warning = str(warning).strip()
    if warning and warning not in target:
        target.append(warning)


def _clean_question_ids(question_ids: Sequence[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in question_ids or ():
        question_id = str(raw or "").strip()
        if not question_id or question_id == FULL_SUBMISSION or question_id in seen:
            continue
        seen.add(question_id)
        cleaned.append(question_id)
    return cleaned


def _answers_from_submission(submission: Any) -> Mapping[str, Any]:
    if isinstance(submission, ParsedSubmission):
        return submission.answers_by_question or {}

    if isinstance(submission, Mapping):
        value = (
            submission.get("extracted_answers")
            or submission.get("answers_by_question")
            or {}
        )
        return value if isinstance(value, Mapping) else {}

    value = getattr(submission, "answers_by_question", {})
    return value if isinstance(value, Mapping) else {}


def infer_similarity_question_ids(
    submissions: Mapping[str, Any],
    preferred: Sequence[str] | None = None,
) -> list[str]:
    """Return stable question IDs, preferring rubric-provided order when given."""

    preferred_ids = _clean_question_ids(preferred)
    if preferred_ids:
        return preferred_ids

    discovered: set[str] = set()
    for submission in submissions.values():
        for raw_question_id in _answers_from_submission(submission):
            question_id = str(raw_question_id or "").strip()
            if question_id and question_id != FULL_SUBMISSION:
                discovered.add(question_id)

    # Lexical order is deterministic and sufficient when rubric order is absent.
    return sorted(discovered)


def _student_id_from_submission(submission: Any) -> str:
    if isinstance(submission, ParsedSubmission):
        raw = submission.student_id
    elif isinstance(submission, Mapping):
        meta = submission.get("submission_meta")
        if not isinstance(meta, Mapping):
            meta = {}
        raw = submission.get("student_id") or meta.get("student_id")
    else:
        raw = getattr(submission, "student_id", None)

    return normalize_student_id(str(raw or ""))


def _register_source_submission(
    target: dict[str, Any],
    warnings: list[str],
    *,
    mapping_key: Any,
    submission: Any,
    origin: str,
) -> None:
    """Register one source object without mutating the original object."""

    internal_id = _student_id_from_submission(submission)
    key_id = normalize_student_id(str(mapping_key or ""))

    if not internal_id:
        _append_warning_once(warnings, f"missing_student_id:{origin}")
        return

    if key_id and key_id != internal_id:
        _append_warning_once(
            warnings,
            f"student_id_key_mismatch:{origin}:{key_id}:{internal_id}",
        )

    if internal_id in target:
        _append_warning_once(
            warnings,
            f"duplicate_student_id:{origin}:{internal_id}",
        )
        return

    target[internal_id] = submission

    raw_warnings = (
        submission.warnings
        if isinstance(submission, ParsedSubmission)
        else (
            submission.get("submission_meta", {}).get("warnings", [])
            if isinstance(submission, Mapping)
            and isinstance(submission.get("submission_meta"), Mapping)
            else []
        )
    )
    if isinstance(raw_warnings, str):
        raw_warnings = [raw_warnings]
    if isinstance(raw_warnings, (list, tuple, set)):
        for item in raw_warnings:
            _append_warning_once(
                warnings,
                f"submission_warning:{internal_id}:{item}",
            )


def collect_loaded_similarity_submissions(
    loaded_submissions: Mapping[str, Any],
    *,
    question_ids: Sequence[str] | None = None,
) -> SimilaritySourceResult:
    """Adapt already-loaded v2.2 submission objects for similarity review."""

    if not isinstance(loaded_submissions, Mapping):
        raise TypeError("loaded_submissions must be a mapping.")

    submissions: dict[str, Any] = {}
    warnings: list[str] = []

    for key in sorted(loaded_submissions, key=lambda value: str(value)):
        submission = loaded_submissions[key]
        _register_source_submission(
            submissions,
            warnings,
            mapping_key=key,
            submission=submission,
            origin="loaded",
        )

    if not submissions:
        _append_warning_once(warnings, "no_loaded_submissions")

    return SimilaritySourceResult(
        source_type=SOURCE_LOADED,
        submissions=submissions,
        question_ids=infer_similarity_question_ids(submissions, question_ids),
        warnings=warnings,
        source_path=None,
    )


def collect_similarity_submissions_folder(
    submissions_dir: str,
    *,
    question_ids: Sequence[str] | None = None,
    parse_folder_fn: Callable[..., Mapping[str, ParsedSubmission]] = parse_submissions_folder,
) -> SimilaritySourceResult:
    """Parse a normal LaTeX submissions folder through the v2.2 backend.

    Compilation and evidence persistence are disabled because similarity review
    needs canonical extracted text/source files, not a newly compiled display
    PDF or a second persisted evidence copy.
    """

    root = Path(submissions_dir).expanduser()
    if root.is_symlink():
        raise ValueError(f"Symlinked submissions folders are not accepted: {root}")
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    requested_questions = _clean_question_ids(question_ids)

    parsed_by_student = parse_folder_fn(
        str(root),
        requested_questions or None,
        compile_pdf=False,
        evidence_dir=None,
    )
    if not isinstance(parsed_by_student, Mapping):
        raise TypeError("parse_submissions_folder must return a student mapping.")

    submissions: dict[str, Any] = {}
    warnings: list[str] = []

    for key in sorted(parsed_by_student, key=lambda value: str(value)):
        _register_source_submission(
            submissions,
            warnings,
            mapping_key=key,
            submission=parsed_by_student[key],
            origin=f"submissions_folder:{root.name}",
        )

    if not submissions:
        _append_warning_once(warnings, "no_normal_latex_submissions_found")

    return SimilaritySourceResult(
        source_type=SOURCE_SUBMISSIONS_FOLDER,
        submissions=submissions,
        question_ids=infer_similarity_question_ids(
            submissions,
            requested_questions,
        ),
        warnings=warnings,
        source_path=str(root),
    )


def _is_student_assessment(payload: Any) -> bool:
    return (
        isinstance(payload, Mapping)
        and isinstance(payload.get("criteria"), list)
    )


def _has_similarity_evidence(payload: Mapping[str, Any]) -> bool:
    return (
        isinstance(payload.get("submission_meta"), Mapping)
        or isinstance(payload.get("extracted_answers"), Mapping)
    )


def _try_load_persisted_assessment_submission(
    assessment: Mapping[str, Any],
    *,
    load_persisted_fn: Callable[..., ParsedSubmission],
) -> tuple[ParsedSubmission | None, str | None]:
    """Prefer verified persisted v2.2 evidence when the assessment references it."""

    meta = assessment.get("submission_meta")
    if not isinstance(meta, Mapping):
        return None, None

    raw_student_id = meta.get("student_id") or assessment.get("student_id")
    student_id = normalize_student_id(str(raw_student_id or ""))
    if not student_id:
        return None, None

    evidence_dir = meta.get("evidence_dir")
    if not isinstance(evidence_dir, str) or not evidence_dir.strip():
        return None, None

    student_dir = Path(evidence_dir).expanduser()
    if student_dir.is_symlink():
        return None, "persisted_evidence_symlink_rejected"
    student_dir = student_dir.resolve()

    try:
        parsed = load_persisted_fn(
            str(student_dir.parent),
            student_id,
            verify_hashes=True,
        )
    except FileNotFoundError:
        return None, "persisted_evidence_unavailable"
    except (OSError, ValueError, TypeError) as exc:
        return None, f"persisted_evidence_unreadable:{type(exc).__name__}:{exc}"

    return parsed, None


def collect_similarity_assessment_folder(
    assessments_dir: str,
    *,
    question_ids: Sequence[str] | None = None,
    load_persisted_fn: Callable[..., ParsedSubmission] = load_persisted_submission,
) -> SimilaritySourceResult:
    """Load saved student assessments containing v2.2 submission evidence.

    Only top-level JSON files with a student-assessment ``criteria`` list are
    considered. Existing report/config JSON files are ignored rather than
    misclassified as students.

    When ``submission_meta.evidence_dir`` is available, the persisted v2.2
    evidence bundle is loaded and hash-verified. If it is unavailable, the
    saved assessment's ``submission_meta`` + ``extracted_answers`` remain a
    valid fallback source.
    """

    root = Path(assessments_dir).expanduser()
    if root.is_symlink():
        raise ValueError(f"Symlinked assessment folders are not accepted: {root}")
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    submissions: dict[str, Any] = {}
    warnings: list[str] = []

    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        if path.is_symlink() or not path.is_file():
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            _append_warning_once(
                warnings,
                f"assessment_file_unreadable:{path.name}:{type(exc).__name__}:{exc}",
            )
            continue

        # Ignore semester reports/configs and other JSON artifacts.
        if not _is_student_assessment(payload):
            continue

        if not _has_similarity_evidence(payload):
            _append_warning_once(
                warnings,
                f"assessment_missing_submission_evidence:{path.name}",
            )
            continue

        student_id = _student_id_from_submission(payload)
        if not student_id:
            _append_warning_once(
                warnings,
                f"missing_student_id:assessment:{path.name}",
            )
            continue

        persisted, persisted_warning = _try_load_persisted_assessment_submission(
            payload,
            load_persisted_fn=load_persisted_fn,
        )

        submission: Any = persisted if persisted is not None else payload

        if persisted_warning:
            _append_warning_once(
                warnings,
                f"{persisted_warning}:{path.name}:{student_id}",
            )

        _register_source_submission(
            submissions,
            warnings,
            mapping_key=student_id,
            submission=submission,
            origin=f"assessment:{path.name}",
        )

    if not submissions:
        _append_warning_once(warnings, "no_assessments_with_submission_evidence")

    requested_questions = _clean_question_ids(question_ids)

    return SimilaritySourceResult(
        source_type=SOURCE_ASSESSMENT_FOLDER,
        submissions=submissions,
        question_ids=infer_similarity_question_ids(
            submissions,
            requested_questions,
        ),
        warnings=warnings,
        source_path=str(root),
    )


def collect_similarity_source(
    source_type: str,
    *,
    question_ids: Sequence[str] | None = None,
    loaded_submissions: Mapping[str, Any] | None = None,
    path: str | None = None,
    parse_folder_fn: Callable[..., Mapping[str, ParsedSubmission]] = parse_submissions_folder,
    load_persisted_fn: Callable[..., ParsedSubmission] = load_persisted_submission,
) -> SimilaritySourceResult:
    """Dispatch one of the three v2.3.0 submission-source modes."""

    source_type = str(source_type or "").strip()

    if source_type == SOURCE_LOADED:
        if loaded_submissions is None:
            loaded_submissions = {}
        return collect_loaded_similarity_submissions(
            loaded_submissions,
            question_ids=question_ids,
        )

    if source_type == SOURCE_SUBMISSIONS_FOLDER:
        if not path:
            raise ValueError("path is required for submissions_folder source.")
        return collect_similarity_submissions_folder(
            path,
            question_ids=question_ids,
            parse_folder_fn=parse_folder_fn,
        )

    if source_type == SOURCE_ASSESSMENT_FOLDER:
        if not path:
            raise ValueError("path is required for assessment_folder source.")
        return collect_similarity_assessment_folder(
            path,
            question_ids=question_ids,
            load_persisted_fn=load_persisted_fn,
        )

    raise ValueError(
        f"Unsupported similarity source type {source_type!r}; "
        f"expected one of: {', '.join(VALID_SOURCE_TYPES)}"
    )


__all__ = [
    "SOURCE_LOADED",
    "SOURCE_SUBMISSIONS_FOLDER",
    "SOURCE_ASSESSMENT_FOLDER",
    "VALID_SOURCE_TYPES",
    "SimilaritySourceResult",
    "infer_similarity_question_ids",
    "collect_loaded_similarity_submissions",
    "collect_similarity_submissions_folder",
    "collect_similarity_assessment_folder",
    "collect_similarity_source",
]
