"""Deterministic submission-similarity primitives for v2.3.0.

This package intentionally contains no LLM, embedding, OCR, network, or
misconduct-classification logic.
"""

from .compare import (
    DEFAULT_THRESHOLDS,
    SHORT_ANSWER_TOKEN_THRESHOLD,
    compare_submissions,
    compute_question_ngram_similarity,
    resolve_similarity_thresholds,
)
from .hashing import compute_file_sha256, compute_text_sha256
from .models import (
    FLAG_LEVELS,
    FLAG_RANK,
    PairSimilarity,
    QuestionSimilarity,
    SimilarityReport,
    SimilaritySignal,
)
from .normalize import normalize_for_similarity
from .report import DEFAULT_METHODS, generate_similarity_report
from .shingles import (
    jaccard_similarity,
    make_word_shingles,
    tokenize_for_similarity,
)

__all__ = [
    "FLAG_LEVELS",
    "FLAG_RANK",
    "SimilaritySignal",
    "QuestionSimilarity",
    "PairSimilarity",
    "SimilarityReport",
    "DEFAULT_THRESHOLDS",
    "SHORT_ANSWER_TOKEN_THRESHOLD",
    "compare_submissions",
    "compute_question_ngram_similarity",
    "resolve_similarity_thresholds",
    "DEFAULT_METHODS",
    "generate_similarity_report",
    "compute_file_sha256",
    "compute_text_sha256",
    "normalize_for_similarity",
    "tokenize_for_similarity",
    "make_word_shingles",
    "jaccard_similarity",
]
