"""Cross-assignment similarity-trend analysis.

A trend is a repeated qualifying similarity pair across multiple assignments.
This module aggregates existing similarity reports only; it does not recompute
submission similarity and does not make academic-misconduct determinations.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import json
import math
from pathlib import Path
from typing import Any

from .models import (
    FLAG_RANK,
    PairSimilarity,
    QuestionSimilarity,
    SimilarityReport,
)


DEFAULT_TREND_MIN_FLAG_LEVEL = "high"
DEFAULT_TREND_MIN_ASSIGNMENT_COUNT = 2
TRENDS_REVIEW_WARNING = "trends_are_not_misconduct_evidence"


def _validate_min_flag_level(min_flag_level: str) -> str:
    level = str(min_flag_level or "").strip().lower()
    if level not in FLAG_RANK:
        allowed = ", ".join(FLAG_RANK)
        raise ValueError(
            f"Unsupported trend minimum flag level {min_flag_level!r}; "
            f"expected one of: {allowed}"
        )
    return level


def _validate_min_assignment_count(value: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("min_assignment_count must be a positive integer.") from exc
    if count <= 0:
        raise ValueError("min_assignment_count must be a positive integer.")
    return count


def _question_from_mapping(
    question_id: str,
    payload: Mapping[str, Any],
) -> QuestionSimilarity:
    return QuestionSimilarity(
        question_id=str(payload.get("question_id") or question_id),
        ngram_jaccard=float(payload.get("ngram_jaccard", 0.0) or 0.0),
        shared_shingle_count=int(payload.get("shared_shingle_count", 0) or 0),
        total_shingle_count=int(payload.get("total_shingle_count", 0) or 0),
        shared_spans=list(payload.get("shared_spans", []) or []),
        flag_level=str(payload.get("flag_level", "none") or "none"),
        warnings=list(payload.get("warnings", []) or []),
        embedding_cosine=payload.get("embedding_cosine"),
        pseudocode_similarity=payload.get("pseudocode_similarity"),
        advanced_flags=list(payload.get("advanced_flags", []) or []),
    )


def _pair_from_mapping(payload: Mapping[str, Any]) -> PairSimilarity:
    raw_questions = payload.get("question_similarities", {}) or {}
    if not isinstance(raw_questions, Mapping):
        raise ValueError("Pair question_similarities must be a mapping.")

    questions: dict[str, QuestionSimilarity] = {}
    for raw_qid, raw_question in raw_questions.items():
        qid = str(raw_qid)
        if isinstance(raw_question, QuestionSimilarity):
            questions[qid] = raw_question
        elif isinstance(raw_question, Mapping):
            questions[qid] = _question_from_mapping(qid, raw_question)
        else:
            raise ValueError(
                f"Question similarity payload for {qid!r} must be a mapping."
            )

    return PairSimilarity(
        student_a=str(payload.get("student_a") or ""),
        student_b=str(payload.get("student_b") or ""),
        overall_score=float(payload.get("overall_score", 0.0) or 0.0),
        flag_level=str(payload.get("flag_level", "none") or "none"),
        most_similar_question=payload.get("most_similar_question"),
        exact_file_match=bool(payload.get("exact_file_match", False)),
        normalized_text_match=bool(payload.get("normalized_text_match", False)),
        question_similarities=questions,
        signals=dict(payload.get("signals", {}) or {}),
        notes=list(payload.get("notes", []) or []),
        embedding_max_similarity=payload.get("embedding_max_similarity"),
        pseudocode_max_similarity=payload.get("pseudocode_max_similarity"),
        cluster_ids=list(payload.get("cluster_ids", []) or []),
        trend_flags=list(payload.get("trend_flags", []) or []),
    )


def similarity_report_from_dict(payload: Mapping[str, Any]) -> SimilarityReport:
    """Deserialize a v2.3.x similarity-report mapping.

    Unknown future report-level keys are intentionally ignored here; the trend
    layer only needs the stable base-report fields.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("Similarity report payload must be a mapping.")

    raw_pairs = payload.get("pairs", []) or []
    if not isinstance(raw_pairs, list):
        raise ValueError("Similarity report pairs must be a list.")

    pairs: list[PairSimilarity] = []
    for raw_pair in raw_pairs:
        if isinstance(raw_pair, PairSimilarity):
            pairs.append(raw_pair)
        elif isinstance(raw_pair, Mapping):
            pairs.append(_pair_from_mapping(raw_pair))
        else:
            raise ValueError("Similarity report pair entries must be mappings.")

    return SimilarityReport(
        assignment_id=str(payload.get("assignment_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        methods=list(payload.get("methods", []) or []),
        students=list(payload.get("students", []) or []),
        pairs=pairs,
        thresholds=dict(payload.get("thresholds", {}) or {}),
        warnings=list(payload.get("warnings", []) or []),
        report_type=str(payload.get("report_type") or "submission_similarity"),
    )


def load_similarity_reports(folder: str | Path) -> list[SimilarityReport]:
    """Load all nested ``similarity_report.json`` files under ``folder``.

    Reports are returned in deterministic assignment-ID order. Duplicate
    assignment IDs are rejected because they would otherwise inflate trend
    counts ambiguously.
    """

    root = Path(folder).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Similarity report folder does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Similarity report path is not a folder: {root}")

    paths = sorted(
        path for path in root.rglob("similarity_report.json") if path.is_file()
    )

    reports: list[SimilarityReport] = []
    seen_assignments: dict[str, Path] = {}

    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid similarity report JSON in {path}: {exc}"
            ) from exc

        report = similarity_report_from_dict(payload)
        previous = seen_assignments.get(report.assignment_id)
        if previous is not None:
            raise ValueError(
                "Duplicate assignment_id in similarity reports: "
                f"{report.assignment_id!r} ({previous} and {path})"
            )

        seen_assignments[report.assignment_id] = path
        reports.append(report)

    reports.sort(key=lambda report: report.assignment_id)
    return reports


def _as_report(report: SimilarityReport | Mapping[str, Any]) -> SimilarityReport:
    if isinstance(report, SimilarityReport):
        return report
    if isinstance(report, Mapping):
        return similarity_report_from_dict(report)
    raise TypeError(
        "reports must contain SimilarityReport instances or report mappings."
    )


def _canonical_student_pair(pair: PairSimilarity) -> tuple[str, str]:
    return tuple(sorted((pair.student_a, pair.student_b)))


def _qualifies(pair: PairSimilarity, min_flag_level: str) -> bool:
    return FLAG_RANK[pair.flag_level] >= FLAG_RANK[min_flag_level]


def _pair_questions(
    pair: PairSimilarity,
    min_flag_level: str,
) -> list[str]:
    """Return question IDs supporting the qualifying pair when available."""

    threshold_rank = FLAG_RANK[min_flag_level]
    questions: set[str] = set()

    for qid, question in pair.question_similarities.items():
        if FLAG_RANK[question.flag_level] >= threshold_rank:
            questions.add(str(qid))

        # Advanced semantic/structural scores may be present before advanced
        # report integration updates the question flag. Keep their question ID
        # when the pair's advanced signal is registered.
        if question.embedding_cosine is not None and "embedding_cosine" in pair.signals:
            questions.add(str(qid))
        if (
            question.pseudocode_similarity is not None
            and "pseudocode_structure" in pair.signals
        ):
            questions.add(str(qid))

    normalized = pair.signals.get("normalized_text_hash")
    if isinstance(normalized, Mapping):
        details = normalized.get("details")
        if isinstance(details, Mapping):
            matching = details.get("matching_questions")
            if isinstance(matching, (list, tuple, set)):
                questions.update(
                    str(qid)
                    for qid in matching
                    if str(qid).strip()
                )

    if not questions and pair.most_similar_question:
        questions.add(str(pair.most_similar_question))

    return sorted(questions)


def _pair_signals(pair: PairSimilarity) -> list[str]:
    """Return stable signal names represented in a qualifying pair."""

    signals: set[str] = set()

    if pair.exact_file_match:
        signals.add("exact_file_hash")
    if pair.normalized_text_match:
        signals.add("normalized_text_hash")
    if pair.question_similarities:
        # Only call n-gram a contributor when at least one stored question
        # actually has non-zero n-gram evidence or the method exists in signals.
        if (
            "ngram_jaccard" in pair.signals
            or any(q.ngram_jaccard > 0.0 for q in pair.question_similarities.values())
        ):
            signals.add("ngram_jaccard")

    for method in ("embedding_cosine", "pseudocode_structure"):
        if method in pair.signals:
            signals.add(method)

    # Preserve any future explicitly registered advanced signal method without
    # guessing from numeric fields.
    for raw_method in pair.signals:
        method = str(raw_method or "").strip()
        if method:
            signals.add(method)

    return sorted(signals)


def analyze_similarity_trends(
    reports: Iterable[SimilarityReport | Mapping[str, Any]],
    min_flag_level: str = DEFAULT_TREND_MIN_FLAG_LEVEL,
    min_assignment_count: int = DEFAULT_TREND_MIN_ASSIGNMENT_COUNT,
) -> list[dict[str, Any]]:
    """Find repeated qualifying student pairs across assignments.

    By default a trend requires at least two assignments with a pair flagged
    ``high`` or ``exact``. Set ``min_assignment_count=1`` explicitly to surface
    one-off qualifying pairs.

    Returned trend records are deterministic and are intended for instructor
    review only.
    """

    level = _validate_min_flag_level(min_flag_level)
    required_count = _validate_min_assignment_count(min_assignment_count)

    normalized_reports = [_as_report(report) for report in reports]

    seen_assignment_ids: set[str] = set()
    for report in normalized_reports:
        if report.assignment_id in seen_assignment_ids:
            raise ValueError(
                "Duplicate assignment_id in trend input: "
                f"{report.assignment_id!r}"
            )
        seen_assignment_ids.add(report.assignment_id)

    # pair -> assignment -> pair result. A base report should contain each
    # unordered pair once, but canonicalization makes the trend layer robust to
    # historical reports that might reverse student order.
    occurrences: dict[
        tuple[str, str],
        dict[str, PairSimilarity],
    ] = defaultdict(dict)

    for report in sorted(normalized_reports, key=lambda item: item.assignment_id):
        for pair in report.pairs:
            if not _qualifies(pair, level):
                continue

            key = _canonical_student_pair(pair)
            if report.assignment_id in occurrences[key]:
                raise ValueError(
                    "Duplicate student pair within assignment "
                    f"{report.assignment_id!r}: {key[0]!r}, {key[1]!r}"
                )
            occurrences[key][report.assignment_id] = pair

    trends: list[dict[str, Any]] = []

    for (student_a, student_b), by_assignment in occurrences.items():
        assignments = sorted(by_assignment)
        if len(assignments) < required_count:
            continue

        max_similarity = max(
            float(by_assignment[assignment].overall_score)
            for assignment in assignments
        )
        if not math.isfinite(max_similarity):
            raise ValueError(
                f"Non-finite similarity score for trend {student_a!r}, {student_b!r}"
            )

        questions = {
            assignment: _pair_questions(by_assignment[assignment], level)
            for assignment in assignments
        }

        signals: set[str] = set()
        for assignment in assignments:
            signals.update(_pair_signals(by_assignment[assignment]))

        trends.append(
            {
                "student_a": student_a,
                "student_b": student_b,
                "assignments": assignments,
                "count": len(assignments),
                "max_similarity": max_similarity,
                "questions": questions,
                "signals": sorted(signals),
            }
        )

    trends.sort(
        key=lambda trend: (
            -int(trend["count"]),
            -float(trend["max_similarity"]),
            str(trend["student_a"]),
            str(trend["student_b"]),
        )
    )
    return trends


__all__ = [
    "DEFAULT_TREND_MIN_FLAG_LEVEL",
    "DEFAULT_TREND_MIN_ASSIGNMENT_COUNT",
    "TRENDS_REVIEW_WARNING",
    "similarity_report_from_dict",
    "load_similarity_reports",
    "analyze_similarity_trends",
]
