"""Embedding primitives, scoring, and on-disk cache for advanced similarity review.

The module depends only on :class:`EmbeddingProvider`; the heavy production
backend remains optional.  Question-level scoring compares only matching
question IDs and batches each unique student/question text once before cheap
pairwise cosine comparisons.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from .embedding_provider import EmbeddingProvider
from .hashing import compute_text_sha256
from .shingles import tokenize_for_similarity


_CACHE_SCHEMA_VERSION = 1
_CACHE_DIRECTORY_NAME = "similarity_embeddings"

DEFAULT_EMBEDDING_THRESHOLDS: dict[str, float] = {
    "embedding_medium": 0.88,
    "embedding_high": 0.93,
    "embedding_exact": 0.98,
}

DEFAULT_LOW_TEXTUAL_OVERLAP_THRESHOLD = 0.50
DEFAULT_EMBEDDING_SHORT_ANSWER_TOKEN_THRESHOLD = 30


# ---------------------------------------------------------------------------
# Existing Commit-1 provider/cache primitives
# ---------------------------------------------------------------------------


def _validate_provider_identity(provider: EmbeddingProvider) -> tuple[str, str]:
    provider_name = str(provider.provider_name() or "").strip()
    model_name = str(provider.model_name() or "").strip()
    if not provider_name:
        raise ValueError("Embedding provider name must be non-empty.")
    if not model_name:
        raise ValueError("Embedding model name must be non-empty.")
    return provider_name, model_name


def _validate_embedding(vector: Sequence[float]) -> list[float]:
    if isinstance(vector, (str, bytes)):
        raise TypeError("Embedding vector must be a numeric sequence.")

    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Embedding vector contains a non-finite value.")
    return values


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Return non-negative cosine similarity in the inclusive range [0, 1]."""
    a = _validate_embedding(vec_a)
    b = _validate_embedding(vec_b)

    if not a or not b:
        return 0.0
    if len(a) != len(b):
        raise ValueError(
            "Embedding vectors must have the same dimension: "
            f"{len(a)} != {len(b)}"
        )

    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    raw = sum(left * right for left, right in zip(a, b)) / (norm_a * norm_b)
    raw = max(-1.0, min(1.0, raw))
    return max(0.0, raw)


def default_embedding_cache_dir() -> Path:
    """Return the platform-appropriate application cache directory."""
    explicit = os.environ.get("GRADING_APP_CACHE_DIR")
    if explicit:
        return Path(explicit).expanduser() / _CACHE_DIRECTORY_NAME

    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "grading_app"
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = (
            Path(local_app_data).expanduser() / "grading_app"
            if local_app_data
            else Path.home() / "AppData" / "Local" / "grading_app"
        )
    else:
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
        root = (
            Path(xdg_cache_home).expanduser() / "grading_app"
            if xdg_cache_home
            else Path.home() / ".cache" / "grading_app"
        )

    return root / _CACHE_DIRECTORY_NAME


def embedding_cache_key(text: str, provider: str, model: str) -> str:
    """Build a stable cache key from text hash, provider name, and model name."""
    if not isinstance(text, str):
        raise TypeError("Embedding cache text must be a string.")

    provider = str(provider or "").strip()
    model = str(model or "").strip()
    if not provider:
        raise ValueError("Embedding cache provider must be non-empty.")
    if not model:
        raise ValueError("Embedding cache model must be non-empty.")

    text_hash = compute_text_sha256(text)
    identity = "\x00".join(
        [
            f"v{_CACHE_SCHEMA_VERSION}",
            provider,
            model,
            text_hash,
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _cache_path(
    text: str,
    provider: str,
    model: str,
    cache_dir: str | Path | None,
) -> Path:
    root = (
        Path(cache_dir).expanduser()
        if cache_dir is not None
        else default_embedding_cache_dir()
    )
    return root / f"{embedding_cache_key(text, provider, model)}.json"


def load_cached_embedding(
    text: str,
    provider: str,
    model: str,
    *,
    cache_dir: str | Path | None = None,
) -> list[float] | None:
    """Load a validated cached vector, returning ``None`` on cache miss/corruption."""
    path = _cache_path(text, provider, model, cache_dir)
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
            return None
        if payload.get("provider") != provider:
            return None
        if payload.get("model") != model:
            return None
        if payload.get("text_hash") != compute_text_sha256(text):
            return None
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            return None
        return _validate_embedding(embedding)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_cached_embedding(
    text: str,
    provider: str,
    model: str,
    embedding: Sequence[float],
    *,
    cache_dir: str | Path | None = None,
) -> Path:
    """Persist one embedding atomically and return the cache file path."""
    vector = _validate_embedding(embedding)
    path = _cache_path(text, provider, model, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "provider": provider,
        "model": model,
        "text_hash": compute_text_sha256(text),
        "embedding": vector,
    }

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            tmp_name = handle.name
        Path(tmp_name).replace(path)
    finally:
        if tmp_name:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    return path


def get_embeddings(
    texts: Sequence[str],
    provider: EmbeddingProvider,
    *,
    cache_enabled: bool = True,
    cache_dir: str | Path | None = None,
) -> list[list[float]]:
    """Return embeddings in input order, batching only uncached unique texts."""
    if isinstance(texts, (str, bytes)):
        raise TypeError("texts must be a sequence of strings, not one string.")

    ordered_texts = list(texts)
    for text in ordered_texts:
        if not isinstance(text, str):
            raise TypeError("All embedding inputs must be strings.")

    if not ordered_texts:
        return []

    provider_name, model_name = _validate_provider_identity(provider)

    unique_texts = list(dict.fromkeys(ordered_texts))
    vectors_by_text: dict[str, list[float]] = {}
    missing: list[str] = []

    for text in unique_texts:
        cached = None
        if cache_enabled:
            cached = load_cached_embedding(
                text,
                provider_name,
                model_name,
                cache_dir=cache_dir,
            )
        if cached is None:
            missing.append(text)
        else:
            vectors_by_text[text] = cached

    if missing:
        computed = provider.embed_texts(missing)
        if len(computed) != len(missing):
            raise ValueError(
                "Embedding provider returned an unexpected number of vectors: "
                f"expected {len(missing)}, received {len(computed)}."
            )

        for text, vector in zip(missing, computed):
            validated = _validate_embedding(vector)
            vectors_by_text[text] = validated
            if cache_enabled:
                save_cached_embedding(
                    text,
                    provider_name,
                    model_name,
                    validated,
                    cache_dir=cache_dir,
                )

    return [list(vectors_by_text[text]) for text in ordered_texts]


# ---------------------------------------------------------------------------
# v2.3.1 question-level semantic scoring
# ---------------------------------------------------------------------------


def resolve_embedding_thresholds(
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Resolve and validate configurable embedding review thresholds."""

    merged = dict(DEFAULT_EMBEDDING_THRESHOLDS)
    if thresholds is not None:
        unknown = set(thresholds) - set(DEFAULT_EMBEDDING_THRESHOLDS)
        if unknown:
            raise ValueError(
                "Unsupported embedding threshold key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        for key, value in thresholds.items():
            merged[key] = float(value)

    values = [
        merged["embedding_medium"],
        merged["embedding_high"],
        merged["embedding_exact"],
    ]
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("Embedding thresholds must be between 0.0 and 1.0.")
    if values != sorted(values):
        raise ValueError(
            "Embedding thresholds must satisfy medium <= high <= exact."
        )
    return merged


def embedding_flag_for_score(
    score: float,
    thresholds: Mapping[str, Any] | None = None,
) -> str:
    """Map one cosine score to a conservative semantic review flag."""

    value = float(score)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError("Embedding similarity score must be between 0.0 and 1.0.")

    resolved = resolve_embedding_thresholds(thresholds)
    if value >= resolved["embedding_exact"]:
        return "exact"
    if value >= resolved["embedding_high"]:
        return "high"
    if value >= resolved["embedding_medium"]:
        return "medium"
    return "none"


def embedding_review_warnings(
    answer_a: str,
    answer_b: str,
    score: float,
    *,
    ngram_score: float | None = None,
    thresholds: Mapping[str, Any] | None = None,
    short_answer_token_threshold: int = DEFAULT_EMBEDDING_SHORT_ANSWER_TOKEN_THRESHOLD,
    low_textual_overlap_threshold: float = DEFAULT_LOW_TEXTUAL_OVERLAP_THRESHOLD,
) -> list[str]:
    """Return instructor-review warnings for potentially ambiguous semantic flags."""

    if short_answer_token_threshold <= 0:
        raise ValueError("short_answer_token_threshold must be positive.")
    if not 0.0 <= float(low_textual_overlap_threshold) <= 1.0:
        raise ValueError("low_textual_overlap_threshold must be between 0.0 and 1.0.")

    flag = embedding_flag_for_score(score, thresholds)
    if flag not in {"high", "exact"}:
        return []

    warnings: list[str] = []
    if ngram_score is not None and float(ngram_score) < float(low_textual_overlap_threshold):
        warnings.append("high_semantic_similarity_low_textual_overlap")

    tokens_a = tokenize_for_similarity(str(answer_a or ""))
    tokens_b = tokenize_for_similarity(str(answer_b or ""))
    if (
        len(tokens_a) < short_answer_token_threshold
        or len(tokens_b) < short_answer_token_threshold
    ):
        warnings.append("short_answer_embedding_unreliable")

    return warnings


def _clean_question_ids(question_ids: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in question_ids:
        question_id = str(raw or "").strip()
        if question_id and question_id not in seen:
            seen.add(question_id)
            cleaned.append(question_id)
    return cleaned


def compute_question_embedding_similarity(
    answers_by_student: Mapping[str, Mapping[str, str]],
    question_ids: Sequence[str],
    provider: EmbeddingProvider,
    *,
    cache_enabled: bool = True,
    cache_dir: str | Path | None = None,
) -> dict[tuple[str, str], dict[str, float]]:
    """Compute same-question semantic similarity for every unique student pair.

    Each non-empty student/question answer is embedded at most once in the
    batch.  The resulting vectors are then reused for all pairwise cosine
    comparisons.  Missing or blank answers are omitted rather than represented
    as a misleading zero-similarity signal.
    """

    if not isinstance(answers_by_student, Mapping):
        raise TypeError("answers_by_student must be a mapping.")

    normalized_students: dict[str, Mapping[str, str]] = {}
    for raw_student_id, raw_answers in answers_by_student.items():
        student_id = str(raw_student_id or "").strip()
        if not student_id:
            raise ValueError("Student IDs for embedding comparison must be non-empty.")
        if student_id in normalized_students:
            raise ValueError(f"Duplicate student ID after normalization: {student_id!r}")
        if not isinstance(raw_answers, Mapping):
            raise TypeError(
                f"Answers for student {student_id!r} must be a question mapping."
            )
        normalized_students[student_id] = raw_answers

    ordered_students = sorted(normalized_students)
    ordered_questions = _clean_question_ids(question_ids)

    texts: list[str] = []
    keys: list[tuple[str, str]] = []
    for student_id in ordered_students:
        raw_answers = normalized_students[student_id]
        for question_id in ordered_questions:
            if question_id not in raw_answers:
                continue
            text = str(raw_answers.get(question_id, "") or "")
            if not text.strip():
                continue
            keys.append((student_id, question_id))
            texts.append(text)

    vectors = get_embeddings(
        texts,
        provider,
        cache_enabled=cache_enabled,
        cache_dir=cache_dir,
    )
    vectors_by_key = {key: vector for key, vector in zip(keys, vectors)}

    result: dict[tuple[str, str], dict[str, float]] = {}
    for student_a, student_b in combinations(ordered_students, 2):
        per_question: dict[str, float] = {}
        for question_id in ordered_questions:
            vector_a = vectors_by_key.get((student_a, question_id))
            vector_b = vectors_by_key.get((student_b, question_id))
            if vector_a is None or vector_b is None:
                continue
            per_question[question_id] = cosine_similarity(vector_a, vector_b)
        if per_question:
            result[(student_a, student_b)] = per_question

    return result


__all__ = [
    "DEFAULT_EMBEDDING_THRESHOLDS",
    "DEFAULT_LOW_TEXTUAL_OVERLAP_THRESHOLD",
    "DEFAULT_EMBEDDING_SHORT_ANSWER_TOKEN_THRESHOLD",
    "cosine_similarity",
    "default_embedding_cache_dir",
    "embedding_cache_key",
    "load_cached_embedding",
    "save_cached_embedding",
    "get_embeddings",
    "resolve_embedding_thresholds",
    "embedding_flag_for_score",
    "embedding_review_warnings",
    "compute_question_embedding_similarity",
]
