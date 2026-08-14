"""Advanced v2.3.1 similarity-report orchestration.

This layer augments an existing deterministic v2.3.0 ``SimilarityReport`` with
optional semantic embeddings, pseudocode/algorithm-structure similarity,
connected-component clusters, and cross-assignment trend annotations.

The deterministic report remains intact: advanced methods are added as
separate, inspectable signals rather than replacing exact hashes, normalized
text, or n-gram overlap. All outputs are instructor-review signals only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .clustering import DEFAULT_CLUSTER_MIN_FLAG_LEVEL, find_similarity_clusters
from .embedding_provider import EmbeddingProvider
from .embeddings import (
    DEFAULT_EMBEDDING_THRESHOLDS,
    compute_question_embedding_similarity,
    embedding_flag_for_score,
    embedding_review_warnings,
    resolve_embedding_thresholds,
)
from .models import FLAG_RANK, PairSimilarity, QuestionSimilarity, SimilarityReport, SimilaritySignal
from .pseudocode import (
    DEFAULT_PSEUDOCODE_THRESHOLDS,
    PSEUDOCODE_REVIEW_WARNING,
    compute_question_pseudocode_similarity,
    pseudocode_flag_for_score,
    resolve_pseudocode_thresholds,
)
from .trends import TRENDS_REVIEW_WARNING


EMBEDDING_REVIEW_WARNING = "embedding_similarity_may_overflag_standard_solutions"
ASSISTIVE_TRANSCRIPTION_REVIEW_WARNING = "assistive_transcription_used_for_advanced_similarity"
CROSS_ASSIGNMENT_TREND_FLAG = "cross_assignment_trend"


def _append_once(target: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in target:
        target.append(value)


def _max_flag(left: str, right: str) -> str:
    return left if FLAG_RANK[left] >= FLAG_RANK[right] else right


def _clean_question_ids(question_ids: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in question_ids:
        question_id = str(raw or "").strip()
        if question_id and question_id not in seen:
            seen.add(question_id)
            cleaned.append(question_id)
    return cleaned


def _submission_answers(submission: Any) -> dict[str, str]:
    if isinstance(submission, Mapping):
        raw = (
            submission.get("extracted_answers")
            or submission.get("answers_by_question")
            or {}
        )
    else:
        raw = getattr(submission, "answers_by_question", {}) or {}

    if not isinstance(raw, Mapping):
        return {}
    return {
        str(question_id): str(answer or "")
        for question_id, answer in raw.items()
    }


def _submission_student_id(mapping_key: Any, submission: Any) -> str:
    if isinstance(submission, Mapping):
        meta = submission.get("submission_meta")
        if not isinstance(meta, Mapping):
            meta = {}
        raw = submission.get("student_id") or meta.get("student_id") or mapping_key
    else:
        raw = getattr(submission, "student_id", None) or mapping_key
    return str(raw or "").strip()


def _transcription_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        return {}

    keep = (
        "status",
        "provider",
        "model",
        "page_count",
        "complete",
        "cache_status",
    )
    return {
        key: deepcopy(value[key])
        for key in keep
        if key in value
    }


def submission_similarity_provenance(submission: Any) -> dict[str, Any]:
    """Return compact provenance for the text consumed by similarity methods.

    v2.3.1 does not perform PDF/OCR/handwriting ingestion itself. This helper
    merely preserves the v2.2 provenance already attached to ``ParsedSubmission``
    or saved assessment JSON so later exports/UI can distinguish direct source
    text from assistive machine transcription.
    """

    if isinstance(submission, Mapping):
        meta = submission.get("submission_meta")
        if not isinstance(meta, Mapping):
            meta = {}
        metadata = submission.get("metadata")
        if not isinstance(metadata, Mapping):
            metadata = {}

        source_used = meta.get("source_used") or submission.get("source_used")
        submission_mode = meta.get("submission_mode") or submission.get("submission_mode")
        accommodation_mode = bool(
            meta.get("accommodation_mode", submission.get("accommodation_mode", False))
        )
        authoritative_source = (
            meta.get("authoritative_source")
            or metadata.get("authoritative_source")
        )
        assistive_text_source = (
            meta.get("assistive_text_source")
            or metadata.get("assistive_text_source")
        )
        transcription = meta.get("transcription") or metadata.get("transcription") or {}
        warnings = meta.get("warnings") or submission.get("warnings") or []
    else:
        metadata = getattr(submission, "metadata", {}) or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        source_used = getattr(submission, "source_used", None)
        submission_mode = getattr(submission, "submission_mode", None)
        accommodation_mode = bool(getattr(submission, "accommodation_mode", False))
        authoritative_source = metadata.get("authoritative_source")
        assistive_text_source = metadata.get("assistive_text_source")
        transcription = metadata.get("transcription") or {}
        warnings = getattr(submission, "warnings", []) or []

    if isinstance(warnings, str):
        warnings = [warnings]
    elif not isinstance(warnings, (list, tuple, set)):
        warnings = [str(warnings)] if warnings else []

    analysis_text_source = assistive_text_source or source_used
    source_text = str(analysis_text_source or "").strip().lower()
    uses_assistive_transcription = (
        "transcription" in source_text
        or (
            accommodation_mode
            and isinstance(transcription, Mapping)
            and bool(transcription)
            and source_text not in {"pdf_selectable_text", "selectable_pdf_text"}
        )
    )

    return {
        "source_used": str(source_used) if source_used is not None else None,
        "submission_mode": (
            str(submission_mode) if submission_mode is not None else None
        ),
        "accommodation_mode": accommodation_mode,
        "authoritative_source": (
            str(authoritative_source) if authoritative_source is not None else None
        ),
        "assistive_text_source": (
            str(assistive_text_source) if assistive_text_source is not None else None
        ),
        "analysis_text_source": (
            str(analysis_text_source) if analysis_text_source is not None else None
        ),
        "uses_assistive_transcription": bool(uses_assistive_transcription),
        "transcription": _transcription_summary(transcription),
        "warnings": [str(item) for item in warnings if str(item).strip()],
    }


def _normalize_submissions(
    submissions: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    if not isinstance(submissions, Mapping):
        raise TypeError("parsed_submissions must be a mapping.")

    by_student: dict[str, Any] = {}
    answers_by_student: dict[str, dict[str, str]] = {}
    provenance: dict[str, dict[str, Any]] = {}

    for mapping_key, submission in submissions.items():
        student_id = _submission_student_id(mapping_key, submission)
        if not student_id:
            raise ValueError("Advanced similarity submissions require non-empty student IDs.")
        if student_id in by_student:
            raise ValueError(
                f"Duplicate advanced-similarity student ID: {student_id!r}"
            )
        by_student[student_id] = submission
        answers_by_student[student_id] = _submission_answers(submission)
        provenance[student_id] = submission_similarity_provenance(submission)

    return by_student, answers_by_student, provenance


def _advanced_thresholds(
    thresholds: Mapping[str, Any] | None,
) -> tuple[dict[str, float], dict[str, float]]:
    payload = dict(thresholds or {})
    allowed = set(DEFAULT_EMBEDDING_THRESHOLDS) | set(DEFAULT_PSEUDOCODE_THRESHOLDS)
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "Unsupported advanced similarity threshold key(s): "
            + ", ".join(sorted(str(item) for item in unknown))
        )

    embedding = resolve_embedding_thresholds(
        {key: payload[key] for key in DEFAULT_EMBEDDING_THRESHOLDS if key in payload}
    )
    pseudocode = resolve_pseudocode_thresholds(
        {key: payload[key] for key in DEFAULT_PSEUDOCODE_THRESHOLDS if key in payload}
    )
    return embedding, pseudocode


def _ensure_question(pair: PairSimilarity, question_id: str) -> QuestionSimilarity:
    question = pair.question_similarities.get(question_id)
    if question is None:
        question = QuestionSimilarity(question_id=question_id)
        pair.question_similarities[question_id] = question
    return question


def _register_advanced_flag(question: QuestionSimilarity, method: str, level: str) -> None:
    if level == "none":
        return
    _append_once(question.advanced_flags, f"{method}_{level}")


def _maybe_update_pair_score_and_question(
    pair: PairSimilarity,
    score: float,
    question_id: str | None,
) -> None:
    score = float(score)
    previous = float(pair.overall_score)
    if score > previous:
        pair.overall_score = score
        if question_id:
            pair.most_similar_question = question_id
    elif pair.most_similar_question is None and question_id and score == previous:
        pair.most_similar_question = question_id


def _pair_lookup(report: SimilarityReport) -> dict[tuple[str, str], PairSimilarity]:
    lookup: dict[tuple[str, str], PairSimilarity] = {}
    for pair in report.pairs:
        key = tuple(sorted((pair.student_a, pair.student_b)))
        lookup[key] = pair
    return lookup


def _attach_pair_provenance(
    report: SimilarityReport,
    provenance: Mapping[str, dict[str, Any]],
) -> None:
    report.submission_provenance = {
        student_id: deepcopy(provenance[student_id])
        for student_id in sorted(provenance)
    }
    for pair in report.pairs:
        pair.submission_provenance = {
            student_id: deepcopy(provenance.get(student_id, {}))
            for student_id in (pair.student_a, pair.student_b)
        }


def _mark_assistive_provenance_note(pair: PairSimilarity) -> None:
    if "embedding_cosine" not in pair.signals and "pseudocode_structure" not in pair.signals:
        return
    for student_id, provenance in pair.submission_provenance.items():
        if provenance.get("uses_assistive_transcription"):
            _append_once(
                pair.notes,
                f"{ASSISTIVE_TRANSCRIPTION_REVIEW_WARNING}:{student_id}",
            )


def _apply_embedding_signals(
    report: SimilarityReport,
    answers_by_student: Mapping[str, Mapping[str, str]],
    question_ids: Sequence[str],
    provider: EmbeddingProvider,
    thresholds: Mapping[str, float],
    *,
    cache_enabled: bool,
    cache_dir: str | Path | None,
) -> None:
    scores_by_pair = compute_question_embedding_similarity(
        answers_by_student,
        question_ids,
        provider,
        cache_enabled=cache_enabled,
        cache_dir=cache_dir,
    )
    lookup = _pair_lookup(report)

    for raw_pair, question_scores in scores_by_pair.items():
        pair = lookup.get(tuple(sorted(raw_pair)))
        if pair is None or not question_scores:
            continue

        flags: dict[str, str] = {}
        all_warnings: list[str] = []
        max_question = None
        max_score = -1.0
        max_flag = "none"

        answers_a = answers_by_student.get(pair.student_a, {})
        answers_b = answers_by_student.get(pair.student_b, {})

        for question_id in question_ids:
            if question_id not in question_scores:
                continue
            score = float(question_scores[question_id])
            question = _ensure_question(pair, question_id)
            question.embedding_cosine = score

            flag = embedding_flag_for_score(score, thresholds)
            flags[question_id] = flag
            _register_advanced_flag(question, "embedding", flag)
            max_flag = _max_flag(max_flag, flag)

            ngram_score = None
            ngram_signal = pair.signals.get("ngram_jaccard")
            if isinstance(ngram_signal, Mapping) and question_id in ngram_signal:
                ngram_score = question.ngram_jaccard

            warnings = embedding_review_warnings(
                str(answers_a.get(question_id, "") or ""),
                str(answers_b.get(question_id, "") or ""),
                score,
                ngram_score=ngram_score,
                thresholds=thresholds,
            )
            for warning in warnings:
                _append_once(question.warnings, warning)
                _append_once(all_warnings, warning)
                _append_once(pair.notes, warning)
                _append_once(report.warnings, warning)

            if max_question is None or score > max_score:
                max_question = question_id
                max_score = score

        if max_question is None:
            continue

        pair.embedding_max_similarity = max_score
        pair.signals["embedding_cosine"] = SimilaritySignal(
            method="embedding_cosine",
            score=max_score,
            details={
                "provider": str(provider.provider_name()),
                "model": str(provider.model_name()),
                "questions": {
                    question_id: float(question_scores[question_id])
                    for question_id in question_ids
                    if question_id in question_scores
                },
                "flags": flags,
                "warnings": all_warnings,
            },
        ).to_dict()
        pair.flag_level = _max_flag(pair.flag_level, max_flag)
        _maybe_update_pair_score_and_question(pair, max_score, max_question)


def _apply_pseudocode_signals(
    report: SimilarityReport,
    answers_by_student: Mapping[str, Mapping[str, str]],
    question_ids: Sequence[str],
    thresholds: Mapping[str, float],
) -> None:
    for pair in report.pairs:
        answers_a = answers_by_student.get(pair.student_a)
        answers_b = answers_by_student.get(pair.student_b)
        if answers_a is None or answers_b is None:
            continue

        question_scores = compute_question_pseudocode_similarity(
            answers_a,
            answers_b,
            question_ids,
        )
        if not question_scores:
            continue

        flags: dict[str, str] = {}
        max_question = None
        max_score = -1.0
        max_flag = "none"

        for question_id in question_ids:
            if question_id not in question_scores:
                continue
            score = float(question_scores[question_id])
            question = _ensure_question(pair, question_id)
            question.pseudocode_similarity = score

            flag = pseudocode_flag_for_score(score, thresholds)
            flags[question_id] = flag
            _register_advanced_flag(question, "pseudocode", flag)
            max_flag = _max_flag(max_flag, flag)

            if flag != "none":
                _append_once(question.warnings, PSEUDOCODE_REVIEW_WARNING)

            if max_question is None or score > max_score:
                max_question = question_id
                max_score = score

        if max_question is None:
            continue

        pair.pseudocode_max_similarity = max_score
        pair.signals["pseudocode_structure"] = SimilaritySignal(
            method="pseudocode_structure",
            score=max_score,
            details={
                "method": "normalized_token_3gram_jaccard",
                "questions": {
                    question_id: float(question_scores[question_id])
                    for question_id in question_ids
                    if question_id in question_scores
                },
                "flags": flags,
            },
        ).to_dict()
        pair.flag_level = _max_flag(pair.flag_level, max_flag)
        _maybe_update_pair_score_and_question(pair, max_score, max_question)
        if max_flag != "none":
            _append_once(pair.notes, PSEUDOCODE_REVIEW_WARNING)


def _apply_clusters(
    report: SimilarityReport,
    *,
    min_flag_level: str,
) -> None:
    clusters = find_similarity_clusters(
        report.pairs,
        min_flag_level=min_flag_level,
    )
    report.clusters = deepcopy(clusters)

    for pair in report.pairs:
        pair.cluster_ids = []

    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or "").strip()
        students = {
            str(student)
            for student in cluster.get("students", [])
            if str(student).strip()
        }
        if not cluster_id or len(students) < 2:
            continue
        for pair in report.pairs:
            if pair.student_a in students and pair.student_b in students:
                _append_once(pair.cluster_ids, cluster_id)


def _normalize_trend_records(
    trend_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for record in trend_records:
        if not isinstance(record, Mapping):
            raise TypeError("trend_records must contain mappings.")
        student_a = str(record.get("student_a") or "").strip()
        student_b = str(record.get("student_b") or "").strip()
        if not student_a or not student_b or student_a == student_b:
            raise ValueError("Trend records require two distinct student IDs.")
        assignments = sorted(
            {
                str(item).strip()
                for item in (record.get("assignments", []) or [])
                if str(item).strip()
            }
        )
        payload = deepcopy(dict(record))
        payload["student_a"], payload["student_b"] = sorted((student_a, student_b))
        payload["assignments"] = assignments
        payload["count"] = int(payload.get("count", len(assignments)) or 0)
        payload["max_similarity"] = float(payload.get("max_similarity", 0.0) or 0.0)
        normalized.append(payload)

    normalized.sort(
        key=lambda item: (
            -int(item.get("count", 0)),
            -float(item.get("max_similarity", 0.0)),
            str(item.get("student_a", "")),
            str(item.get("student_b", "")),
        )
    )
    return normalized


def _apply_trends(
    report: SimilarityReport,
    trend_records: Sequence[Mapping[str, Any]],
    *,
    trend_flag_level: str,
) -> None:
    if trend_flag_level not in FLAG_RANK:
        raise ValueError(
            f"Unsupported trend_flag_level {trend_flag_level!r}; "
            f"expected one of: {', '.join(FLAG_RANK)}"
        )

    normalized = _normalize_trend_records(trend_records)
    report.trends = deepcopy(normalized)
    lookup = _pair_lookup(report)

    for trend in normalized:
        assignments = trend.get("assignments", []) or []
        if report.assignment_id not in assignments:
            continue

        key = tuple(sorted((str(trend["student_a"]), str(trend["student_b"]))))
        pair = lookup.get(key)
        if pair is None:
            continue

        _append_once(pair.trend_flags, CROSS_ASSIGNMENT_TREND_FLAG)
        _append_once(pair.notes, TRENDS_REVIEW_WARNING)
        pair.signals["cross_assignment_trend"] = SimilaritySignal(
            method="cross_assignment_trend",
            score=float(trend.get("max_similarity", 0.0) or 0.0),
            details={
                **deepcopy(trend),
                "flag_level": trend_flag_level,
            },
        ).to_dict()
        pair.flag_level = _max_flag(pair.flag_level, trend_flag_level)


def generate_advanced_similarity_report(
    base_report: SimilarityReport,
    parsed_submissions: Mapping[str, Any],
    question_ids: Sequence[str],
    embedding_provider: EmbeddingProvider | None = None,
    include_pseudocode: bool = True,
    include_clustering: bool = True,
    thresholds: Mapping[str, Any] | None = None,
    *,
    embedding_cache_enabled: bool = True,
    embedding_cache_dir: str | Path | None = None,
    cluster_min_flag_level: str = DEFAULT_CLUSTER_MIN_FLAG_LEVEL,
    trend_records: Sequence[Mapping[str, Any]] | None = None,
    trend_flag_level: str = "high",
) -> SimilarityReport:
    """Return a v2.3.1 report built by augmenting a v2.3.0 base report.

    ``base_report`` is deep-copied and never mutated. Deterministic v2.3.0
    fields/signals remain present. Embeddings are computed only when a provider
    is explicitly supplied; tests can therefore remain fully offline.
    """

    if not isinstance(base_report, SimilarityReport):
        raise TypeError("base_report must be a SimilarityReport.")

    ordered_question_ids = _clean_question_ids(question_ids)
    report = deepcopy(base_report)
    by_student, answers_by_student, provenance = _normalize_submissions(parsed_submissions)
    embedding_thresholds, pseudocode_thresholds = _advanced_thresholds(thresholds)

    report.advanced_methods = []
    report.clusters = []
    report.trends = []

    _attach_pair_provenance(report, provenance)

    for student_id in report.students:
        if student_id not in by_student:
            _append_once(report.warnings, f"advanced_submission_missing:{student_id}")

    # Keep base deterministic thresholds intact while making advanced threshold
    # values visible in the same machine-readable report.
    report.thresholds = dict(report.thresholds)
    report.thresholds.update(embedding_thresholds)
    report.thresholds.update(pseudocode_thresholds)

    report.embedding_config = {
        "enabled": embedding_provider is not None,
        "provider": (
            str(embedding_provider.provider_name())
            if embedding_provider is not None
            else None
        ),
        "model": (
            str(embedding_provider.model_name())
            if embedding_provider is not None
            else None
        ),
        "cache_enabled": bool(embedding_cache_enabled),
        "cache_dir": (
            str(Path(embedding_cache_dir).expanduser())
            if embedding_cache_dir is not None
            else None
        ),
        "thresholds": dict(embedding_thresholds),
    }
    report.pseudocode_config = {
        "enabled": bool(include_pseudocode),
        "method": "normalized_token_3gram_jaccard",
        "thresholds": dict(pseudocode_thresholds),
    }

    if embedding_provider is not None:
        report.advanced_methods.append("embedding_cosine")
        _append_once(report.warnings, EMBEDDING_REVIEW_WARNING)
        _apply_embedding_signals(
            report,
            answers_by_student,
            ordered_question_ids,
            embedding_provider,
            embedding_thresholds,
            cache_enabled=embedding_cache_enabled,
            cache_dir=embedding_cache_dir,
        )

    if include_pseudocode:
        report.advanced_methods.append("pseudocode_structure")
        _append_once(report.warnings, PSEUDOCODE_REVIEW_WARNING)
        _apply_pseudocode_signals(
            report,
            answers_by_student,
            ordered_question_ids,
            pseudocode_thresholds,
        )

    for pair in report.pairs:
        _mark_assistive_provenance_note(pair)

    if include_clustering:
        report.advanced_methods.append("clustering")
        _apply_clusters(report, min_flag_level=cluster_min_flag_level)
    else:
        for pair in report.pairs:
            pair.cluster_ids = []

    if trend_records is not None:
        report.advanced_methods.append("cross_assignment_trends")
        _append_once(report.warnings, TRENDS_REVIEW_WARNING)
        _apply_trends(
            report,
            trend_records,
            trend_flag_level=trend_flag_level,
        )
    else:
        for pair in report.pairs:
            pair.trend_flags = []

    # Preserve deterministic ordering after advanced methods may change scores
    # and flags.
    report.pairs.sort(
        key=lambda pair: (
            -FLAG_RANK[pair.flag_level],
            -float(pair.overall_score),
            str(pair.most_similar_question or ""),
            pair.student_a,
            pair.student_b,
        )
    )
    return report


__all__ = [
    "EMBEDDING_REVIEW_WARNING",
    "ASSISTIVE_TRANSCRIPTION_REVIEW_WARNING",
    "CROSS_ASSIGNMENT_TREND_FLAG",
    "submission_similarity_provenance",
    "generate_advanced_similarity_report",
]
