"""Embedding primitives and on-disk cache for advanced similarity review.

This module contains no dependency on SentenceTransformers or any other real
embedding backend.  It operates only on the :class:`EmbeddingProvider`
interface, keeping v2.3.1 offline-testable and allowing production providers
to be installed optionally.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .embedding_provider import EmbeddingProvider
from .hashing import compute_text_sha256


_CACHE_SCHEMA_VERSION = 1
_CACHE_DIRECTORY_NAME = "similarity_embeddings"


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
    """Return non-negative cosine similarity in the inclusive range [0, 1].

    Empty or zero-norm vectors yield 0.0.  Dimension mismatches are treated as
    invalid provider output and raise ``ValueError`` rather than silently
    truncating vectors with ``zip``.

    Raw negative cosine values are clamped to 0.0.  Positive cosine values are
    left on their ordinary scale, which keeps future model-specific thresholds
    interpretable while still presenting a non-negative review signal.
    """
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
    # Floating-point arithmetic can produce tiny excursions outside [-1, 1].
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
    """Return embeddings in input order, batching only uncached unique texts.

    Identical texts are embedded once per call.  With caching enabled, only
    cache misses are sent to the provider, and newly computed vectors are saved
    under keys containing the exact text hash, provider, and model identity.
    """
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
