"""Pairwise deterministic submission-similarity computation.

v2.3.0 intentionally uses explainable, offline signals only:

* byte-for-byte source-file SHA256 equality,
* normalized-text SHA256 equality,
* matching-question word-shingle Jaccard overlap.

This module does not make plagiarism, cheating, or misconduct determinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .hashing import compute_file_sha256, compute_text_sha256
from .models import FLAG_RANK, PairSimilarity, QuestionSimilarity, SimilaritySignal
from .normalize import normalize_for_similarity
from .shingles import jaccard_similarity, make_word_shingles, tokenize_for_similarity


DEFAULT_THRESHOLDS: dict[str, float] = {
    "ngram_low": 0.50,
    "ngram_medium": 0.65,
    "ngram_high": 0.80,
    "ngram_exact": 0.95,
}

SHORT_ANSWER_TOKEN_THRESHOLD = 30

# Exact-file comparison is restricted to source-like student artifacts.  In
# particular, ``compiled_pdf`` is derived evidence for LaTeX submissions and is
# not used as a byte-for-byte student-source signal.
_EXACT_FILE_KEYS = (
    "latex",
    "pdf",
    "text",
    "txt",
    "markdown",
    "md",
)


@dataclass(frozen=True)
class _SubmissionView:
    student_id: str
    answers: dict[str, str]
    raw_text: str
    files: dict[str, str]
    file_hashes: dict[str, str]
    warnings: tuple[str, ...]


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_dict(value: Any) -> dict[str, str]:
    mapping = _as_mapping(value)
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if item is None:
            continue
        result[str(key)] = str(item)
    return result


def _submission_view(submission: Any) -> _SubmissionView:
    """Adapt ParsedSubmission-like objects or saved assessment dictionaries."""

    if isinstance(submission, Mapping):
        student_id = str(
            submission.get("student_id")
            or _as_mapping(submission.get("submission_meta")).get("student_id")
            or ""
        ).strip()

        answers = _string_dict(
            submission.get("extracted_answers")
            or submission.get("answers_by_question")
            or {}
        )
        raw_text = str(submission.get("raw_text") or "")

        meta = _as_mapping(submission.get("submission_meta"))
        files = _string_dict(meta.get("files") or submission.get("files") or {})
        file_hashes = _string_dict(meta.get("file_hashes") or submission.get("file_hashes") or {})

        raw_warnings = meta.get("warnings") or submission.get("warnings") or []
    else:
        student_id = str(getattr(submission, "student_id", "") or "").strip()
        answers = _string_dict(getattr(submission, "answers_by_question", {}) or {})
        raw_text = str(getattr(submission, "raw_text", "") or "")
        files = _string_dict(getattr(submission, "files", {}) or {})

        metadata = _as_mapping(getattr(submission, "metadata", {}) or {})
        evidence = _as_mapping(metadata.get("evidence"))
        file_hashes = _string_dict(evidence.get("file_hashes") or {})
        raw_warnings = getattr(submission, "warnings", []) or []

    if not student_id:
        raise ValueError("Submission similarity comparison requires a student_id.")

    if isinstance(raw_warnings, (list, tuple, set)):
        warnings = tuple(str(item) for item in raw_warnings)
    else:
        warnings = (str(raw_warnings),)

    return _SubmissionView(
        student_id=student_id,
        answers=answers,
        raw_text=raw_text,
        files=files,
        file_hashes=file_hashes,
        warnings=warnings,
    )


def _validate_thresholds(thresholds: Mapping[str, Any] | None) -> dict[str, float]:
    merged = dict(DEFAULT_THRESHOLDS)
    if thresholds is not None:
        unknown = set(thresholds) - set(DEFAULT_THRESHOLDS)
        if unknown:
            raise ValueError(
                "Unsupported similarity threshold key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        for key, value in thresholds.items():
            merged[key] = float(value)

    values = [
        merged["ngram_low"],
        merged["ngram_medium"],
        merged["ngram_high"],
        merged["ngram_exact"],
    ]
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("Similarity thresholds must be between 0.0 and 1.0.")
    if values != sorted(values):
        raise ValueError(
            "Similarity thresholds must satisfy low <= medium <= high <= exact."
        )
    return merged


def _flag_for_ngram(score: float, thresholds: Mapping[str, float]) -> str:
    if score >= thresholds["ngram_exact"]:
        return "exact"
    if score >= thresholds["ngram_high"]:
        return "high"
    if score >= thresholds["ngram_medium"]:
        return "medium"
    if score >= thresholds["ngram_low"]:
        return "low"
    return "none"


def _downgrade_flag_one_level(flag_level: str) -> str:
    order = ("none", "low", "medium", "high", "exact")
    index = order.index(flag_level)
    return order[max(0, index - 1)]


def _max_flag(*levels: str) -> str:
    return max(levels, key=lambda level: FLAG_RANK[level])


def _canonical_hash_key(logical_file_key: str) -> str:
    return f"{logical_file_key}_sha256"


def _hash_for_logical_file(view: _SubmissionView, logical_key: str) -> str | None:
    """Return a stored hash or compute one from an available source path."""

    hash_key = _canonical_hash_key(logical_key)
    stored = view.file_hashes.get(hash_key)
    if stored:
        return stored.lower()

    path_text = view.files.get(logical_key)
    if not path_text:
        return None

    path = Path(path_text).expanduser()
    if not path.is_file():
        return None

    return compute_file_sha256(path).lower()


def _find_exact_file_match(
    view_a: _SubmissionView,
    view_b: _SubmissionView,
) -> SimilaritySignal | None:
    """Compare only equivalent logical source-file types."""

    for logical_key in _EXACT_FILE_KEYS:
        hash_a = _hash_for_logical_file(view_a, logical_key)
        hash_b = _hash_for_logical_file(view_b, logical_key)
        if hash_a and hash_b and hash_a == hash_b:
            return SimilaritySignal(
                method="exact_file_hash",
                score=1.0,
                details={
                    "matching_file_type": logical_key,
                    "hash": hash_a,
                },
            )
    return None


def _normalized_question_hashes(
    answers: Mapping[str, str],
    question_ids: Sequence[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for question_id in question_ids:
        text = str(answers.get(question_id, "") or "")
        normalized = normalize_for_similarity(text)
        if not normalized:
            continue
        result[question_id] = compute_text_sha256(normalized)
    return result


def _find_normalized_text_matches(
    view_a: _SubmissionView,
    view_b: _SubmissionView,
    question_ids: Sequence[str],
) -> list[str]:
    """Return matching question IDs with identical non-empty normalized text."""

    hashes_a = _normalized_question_hashes(view_a.answers, question_ids)
    hashes_b = _normalized_question_hashes(view_b.answers, question_ids)

    matches = [
        question_id
        for question_id in question_ids
        if hashes_a.get(question_id)
        and hashes_a.get(question_id) == hashes_b.get(question_id)
    ]
    if matches:
        return matches

    # Raw-text fallback is intentionally used only when question-level extracted
    # answers are unavailable for both submissions.
    if not hashes_a and not hashes_b:
        normalized_a = normalize_for_similarity(view_a.raw_text)
        normalized_b = normalize_for_similarity(view_b.raw_text)
        if normalized_a and normalized_b:
            if compute_text_sha256(normalized_a) == compute_text_sha256(normalized_b):
                return ["__FULL_SUBMISSION__"]

    return []


def _question_similarity(
    answer_a: str,
    answer_b: str,
    question_id: str,
    n: int,
    thresholds: Mapping[str, float],
    short_answer_token_threshold: int,
) -> QuestionSimilarity:
    tokens_a = tokenize_for_similarity(answer_a)
    tokens_b = tokenize_for_similarity(answer_b)

    shingles_a = make_word_shingles(tokens_a, n=n)
    shingles_b = make_word_shingles(tokens_b, n=n)

    score = jaccard_similarity(shingles_a, shingles_b)
    shared_count = len(shingles_a & shingles_b)
    union_count = len(shingles_a | shingles_b)

    raw_flag = _flag_for_ngram(score, thresholds)
    flag = raw_flag
    warnings: list[str] = []

    both_short = (
        len(tokens_a) < short_answer_token_threshold
        and len(tokens_b) < short_answer_token_threshold
    )
    if both_short and raw_flag != "none":
        warnings.append("short_answer_high_similarity")
        flag = _downgrade_flag_one_level(raw_flag)

    return QuestionSimilarity(
        question_id=question_id,
        ngram_jaccard=score,
        shared_shingle_count=shared_count,
        total_shingle_count=union_count,
        shared_spans=[],
        flag_level=flag,
        warnings=warnings,
    )


def compute_question_ngram_similarity(
    answers_a: Mapping[str, str],
    answers_b: Mapping[str, str],
    question_ids: Sequence[str],
    n: int = 5,
) -> dict[str, float]:
    """Compute Jaccard overlap only for matching requested question IDs."""

    if n <= 0:
        raise ValueError("n must be a positive integer")

    scores: dict[str, float] = {}
    for raw_question_id in question_ids:
        question_id = str(raw_question_id)
        if question_id not in answers_a or question_id not in answers_b:
            continue

        tokens_a = tokenize_for_similarity(str(answers_a.get(question_id, "") or ""))
        tokens_b = tokenize_for_similarity(str(answers_b.get(question_id, "") or ""))
        shingles_a = make_word_shingles(tokens_a, n=n)
        shingles_b = make_word_shingles(tokens_b, n=n)
        scores[question_id] = jaccard_similarity(shingles_a, shingles_b)

    return scores


def compare_submissions(
    student_a: Any,
    student_b: Any,
    question_ids: Sequence[str],
    thresholds: Mapping[str, Any] | None = None,
    *,
    n: int = 5,
    short_answer_token_threshold: int = SHORT_ANSWER_TOKEN_THRESHOLD,
) -> PairSimilarity:
    """Compare two submissions with deterministic, explainable signals.

    ``student_a`` and ``student_b`` may be ParsedSubmission-like objects or
    saved assessment dictionaries containing ``submission_meta`` and
    ``extracted_answers``.
    """

    if n <= 0:
        raise ValueError("n must be a positive integer")
    if short_answer_token_threshold <= 0:
        raise ValueError("short_answer_token_threshold must be positive")

    resolved_thresholds = _validate_thresholds(thresholds)
    view_a = _submission_view(student_a)
    view_b = _submission_view(student_b)

    if view_a.student_id == view_b.student_id:
        raise ValueError("Cannot compare a submission with itself.")

    ordered_question_ids: list[str] = []
    seen: set[str] = set()
    for value in question_ids:
        question_id = str(value)
        if question_id and question_id not in seen:
            seen.add(question_id)
            ordered_question_ids.append(question_id)

    question_results: dict[str, QuestionSimilarity] = {}
    notes: list[str] = []

    for question_id in ordered_question_ids:
        if question_id not in view_a.answers or question_id not in view_b.answers:
            notes.append(f"missing_comparable_question:{question_id}")
            continue

        result = _question_similarity(
            view_a.answers.get(question_id, ""),
            view_b.answers.get(question_id, ""),
            question_id,
            n,
            resolved_thresholds,
            short_answer_token_threshold,
        )
        question_results[question_id] = result
        for warning in result.warnings:
            if warning not in notes:
                notes.append(warning)

    exact_signal = _find_exact_file_match(view_a, view_b)
    exact_file_match = exact_signal is not None

    normalized_matches = _find_normalized_text_matches(
        view_a,
        view_b,
        ordered_question_ids,
    )
    normalized_text_match = bool(normalized_matches)

    signals: dict[str, Any] = {}
    if exact_signal is not None:
        signals["exact_file_hash"] = exact_signal.to_dict()

    if normalized_matches:
        normalized_signal = SimilaritySignal(
            method="normalized_text_hash",
            score=1.0,
            details={
                "matching_questions": [
                    item for item in normalized_matches if item != "__FULL_SUBMISSION__"
                ],
                "assignment_level_fallback": "__FULL_SUBMISSION__" in normalized_matches,
            },
        )
        signals["normalized_text_hash"] = normalized_signal.to_dict()

    signals["ngram_jaccard"] = {
        question_id: result.ngram_jaccard
        for question_id, result in question_results.items()
    }

    strongest_question: str | None = None
    strongest_score = 0.0
    strongest_question_flag = "none"
    for question_id in ordered_question_ids:
        result = question_results.get(question_id)
        if result is None:
            continue
        if (
            strongest_question is None
            or result.ngram_jaccard > strongest_score
        ):
            strongest_question = question_id
            strongest_score = result.ngram_jaccard
        strongest_question_flag = _max_flag(strongest_question_flag, result.flag_level)

    # A normalized question match is deterministic identity after normalization,
    # but it is deliberately framed as "high", not an accusation-equivalent
    # "exact" verdict.  Only byte-for-byte file identity or the configured
    # n-gram exact threshold can produce exact.
    overall_flag = strongest_question_flag
    if normalized_text_match:
        overall_flag = _max_flag(overall_flag, "high")
    if exact_file_match:
        overall_flag = "exact"

    overall_score = strongest_score
    if normalized_text_match or exact_file_match:
        overall_score = 1.0

    if strongest_question is None and normalized_matches:
        question_matches = [
            item for item in normalized_matches if item != "__FULL_SUBMISSION__"
        ]
        if question_matches:
            strongest_question = question_matches[0]

    if not question_results and not normalized_text_match and not exact_file_match:
        notes.append("no_comparable_text")

    return PairSimilarity(
        student_a=view_a.student_id,
        student_b=view_b.student_id,
        overall_score=overall_score,
        flag_level=overall_flag,
        most_similar_question=strongest_question,
        exact_file_match=exact_file_match,
        normalized_text_match=normalized_text_match,
        question_similarities=question_results,
        signals=signals,
        notes=notes,
    )


__all__ = [
    "DEFAULT_THRESHOLDS",
    "SHORT_ANSWER_TOKEN_THRESHOLD",
    "compare_submissions",
    "compute_question_ngram_similarity",
]
