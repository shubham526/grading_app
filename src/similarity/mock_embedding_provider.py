"""Deterministic embedding provider used by the v2.3.1 test suite.

This provider intentionally performs no network access, model loading, or API
calls.  Tests may supply exact vectors for chosen strings; all other strings
receive a small deterministic hash-derived vector.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping

from .embedding_provider import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """Fast, offline, deterministic embedding provider for automated tests."""

    def __init__(
        self,
        vectors: Mapping[str, list[float]] | None = None,
        *,
        dimension: int = 16,
    ) -> None:
        if int(dimension) <= 0:
            raise ValueError("Mock embedding dimension must be positive.")

        self.dimension = int(dimension)
        self.vectors = {
            str(text): [float(value) for value in vector]
            for text, vector in (vectors or {}).items()
        }

        for text, vector in self.vectors.items():
            if not all(math.isfinite(value) for value in vector):
                raise ValueError(
                    f"Mock embedding for {text!r} contains a non-finite value."
                )

    def provider_name(self) -> str:
        return "mock"

    def model_name(self) -> str:
        return "mock-embedding"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            if not isinstance(text, str):
                raise TypeError("MockEmbeddingProvider expects string inputs.")
            if text in self.vectors:
                result.append(list(self.vectors[text]))
            else:
                result.append(self._hash_embedding(text))
        return result

    def _hash_embedding(self, text: str) -> list[float]:
        """Create a stable unit vector from SHA-256 bytes.

        Components are centered around zero rather than kept non-negative so
        unrelated fallback texts do not become artificially similar merely
        because every vector component has the same sign.
        """
        seed = text.encode("utf-8")
        values: list[float] = []
        counter = 0

        while len(values) < self.dimension:
            digest = hashlib.sha256(
                seed + b"\x00" + str(counter).encode("ascii")
            ).digest()
            for byte in digest:
                values.append((float(byte) - 127.5) / 127.5)
                if len(values) == self.dimension:
                    break
            counter += 1

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            return [0.0] * self.dimension
        return [value / norm for value in values]
