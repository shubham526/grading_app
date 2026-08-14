"""Assignment-level deterministic similarity-report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Mapping, Sequence

from .compare import compare_submissions, resolve_similarity_thresholds
from .models import FLAG_RANK, PairSimilarity, SimilarityReport


DEFAULT_METHODS = [
    "exact_file_hash",
    "normalized_text_hash",
    "ngram_jaccard",
]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _submission_warnings(submission: Any) -> list[str]:
    """Read existing ingestion warnings without coupling to ParsedSubmission."""

    if isinstance(submission, Mapping):
        meta = submission.get("submission_meta")
        if not isinstance(meta, Mapping):
            meta = {}

        raw = meta.get("warnings")
        if raw is None:
            raw = submission.get("warnings", [])
    else:
        raw = getattr(submission, "warnings", []) or []

    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        return [str(item) for item in raw if str(item).strip()]
    return [str(raw)]


def _pair_sort_key(pair: PairSimilarity) -> tuple:
    """Sort strongest review flags first with deterministic tie breaking."""

    return (
        -FLAG_RANK[pair.flag_level],
        -float(pair.overall_score),
        str(pair.most_similar_question or ""),
        pair.student_a,
        pair.student_b,
    )


def _append_warning_once(target: list[str], warning: str) -> None:
    warning = str(warning).strip()
    if warning and warning not in target:
        target.append(warning)


def generate_similarity_report(
    submissions: Mapping[str, Any],
    assignment_id: str,
    question_ids: Sequence[str],
    thresholds: Mapping[str, Any] | None = None,
) -> SimilarityReport:
    """Compare all unique student pairs for one assignment.

    Parameters
    ----------
    submissions:
        Mapping from stable student ID to ParsedSubmission-like objects or saved
        assessment dictionaries containing ``submission_meta`` and
        ``extracted_answers``.
    assignment_id:
        Stable assignment identifier included in the report.
    question_ids:
        Matching question IDs to compare. Q1 is only compared with Q1, etc.
    thresholds:
        Optional partial/full override of the default n-gram thresholds.

    Returns
    -------
    SimilarityReport
        Deterministically ordered assignment-level review report.

    Notes
    -----
    The function records non-fatal comparison problems as report warnings and
    continues with other pairs. Similarity flags are review indicators only.
    """

    if not isinstance(submissions, Mapping):
        raise TypeError("submissions must be a mapping from student ID to submission.")

    assignment_id = str(assignment_id or "").strip()
    if not assignment_id:
        raise ValueError("assignment_id must be non-empty.")

    resolved_thresholds = resolve_similarity_thresholds(thresholds)

    ordered_question_ids: list[str] = []
    seen_questions: set[str] = set()
    for raw_question_id in question_ids:
        question_id = str(raw_question_id or "").strip()
        if question_id and question_id not in seen_questions:
            seen_questions.add(question_id)
            ordered_question_ids.append(question_id)

    # Mapping keys are the assignment roster/submission keys and are used for
    # deterministic pair enumeration. compare_submissions still validates the
    # student_id stored in the underlying object/data.
    ordered_items = sorted(
        ((str(key), value) for key, value in submissions.items()),
        key=lambda item: item[0],
    )
    students = [key for key, _ in ordered_items]

    warnings: list[str] = []

    for key, submission in ordered_items:
        for warning in _submission_warnings(submission):
            _append_warning_once(
                warnings,
                f"submission_warning:{key}:{warning}",
            )

    pairs: list[PairSimilarity] = []

    for (key_a, submission_a), (key_b, submission_b) in combinations(ordered_items, 2):
        try:
            pair = compare_submissions(
                submission_a,
                submission_b,
                ordered_question_ids,
                thresholds=resolved_thresholds,
            )
        except (ValueError, TypeError, FileNotFoundError, OSError) as exc:
            _append_warning_once(
                warnings,
                f"comparison_failed:{key_a}:{key_b}:{type(exc).__name__}:{exc}",
            )
            continue

        pairs.append(pair)

        for note in pair.notes:
            _append_warning_once(
                warnings,
                f"pair_warning:{pair.student_a}:{pair.student_b}:{note}",
            )

    pairs.sort(key=_pair_sort_key)

    return SimilarityReport(
        report_type="submission_similarity",
        assignment_id=assignment_id,
        generated_at=_utc_timestamp(),
        methods=list(DEFAULT_METHODS),
        students=students,
        pairs=pairs,
        thresholds=resolved_thresholds,
        warnings=warnings,
    )


__all__ = [
    "DEFAULT_METHODS",
    "generate_similarity_report",
]
