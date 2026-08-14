"""Embedding-provider abstraction for advanced similarity review.

The similarity package depends on this small interface rather than on any
specific embedding library.  Production providers (for example a local
SentenceTransformers backend) can therefore remain optional dependencies,
while tests use the deterministic mock provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Minimal interface implemented by semantic embedding backends."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector for every input text, in input order."""
        raise NotImplementedError

    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable provider identifier used in reports and cache keys."""
        raise NotImplementedError

    @abstractmethod
    def model_name(self) -> str:
        """Return a stable model identifier used in reports and cache keys."""
        raise NotImplementedError
