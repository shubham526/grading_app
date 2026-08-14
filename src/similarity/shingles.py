"""Tokenization, word shingles, and Jaccard similarity."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .normalize import normalize_for_similarity


_TOKEN_RE = re.compile(r"<=|>=|!=|==|[a-z0-9]+(?:\.[0-9]+)?|[+\-*/=<>]")


def tokenize_for_similarity(text: str) -> list[str]:
    """Normalize text and split it into deterministic word/math-like tokens."""
    normalized = normalize_for_similarity(text)
    if not normalized:
        return []
    return _TOKEN_RE.findall(normalized)


def _effective_shingle_size(token_count: int, requested_n: int) -> int:
    if requested_n <= 0:
        raise ValueError("n must be a positive integer")
    if token_count <= 0:
        return requested_n
    if token_count < 10:
        return min(3, token_count)
    return requested_n


def make_word_shingles(tokens: Iterable[str], n: int = 5) -> set[tuple[str, ...]]:
    """Generate unique word n-grams.

    The default is 5-grams. Answers shorter than ten tokens use 3-grams;
    one- and two-token inputs use the largest possible shingle rather than
    manufacturing tokens or returning a misleading empty comparison.
    """
    token_list = [str(token) for token in tokens if str(token)]
    if not token_list:
        return set()

    effective_n = _effective_shingle_size(len(token_list), int(n))
    if len(token_list) < effective_n:
        return set()

    return {
        tuple(token_list[index : index + effective_n])
        for index in range(len(token_list) - effective_n + 1)
    }


def jaccard_similarity(a: set, b: set) -> float:
    """Return |A ∩ B| / |A ∪ B|, with empty/empty defined as 0.0."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
