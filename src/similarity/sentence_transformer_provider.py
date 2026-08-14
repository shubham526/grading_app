"""Local SentenceTransformers embedding backend for advanced similarity review.

The provider keeps the heavy ``sentence-transformers`` dependency optional:
importing the grading application does not import or initialize the library.
The model is loaded lazily on the first embedding request.  Automated tests
inject a lightweight fake model and therefore require no model download.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .embedding_provider import EmbeddingProvider


DEFAULT_SENTENCE_TRANSFORMER_MODEL = "Alibaba-NLP/gte-modernbert-base"


class SentenceTransformerUnavailableError(RuntimeError):
    """Raised when the optional SentenceTransformers backend cannot be used."""


def sentence_transformers_available() -> bool:
    """Return whether the optional package is installed without importing it."""

    return importlib.util.find_spec("sentence_transformers") is not None


def _default_model_factory(model_name: str, **kwargs: Any) -> Any:
    """Load ``SentenceTransformer`` lazily so core app imports stay lightweight."""

    try:
        module = importlib.import_module("sentence_transformers")
        sentence_transformer_cls = getattr(module, "SentenceTransformer")
    except (ImportError, ModuleNotFoundError, AttributeError) as exc:
        raise SentenceTransformerUnavailableError(
            "Embedding similarity requires the optional 'sentence-transformers' "
            "package. Install it in the grading-app environment before using "
            "the local embedding provider."
        ) from exc

    try:
        return sentence_transformer_cls(model_name, **kwargs)
    except Exception as exc:  # provider/model loader owns third-party failures
        raise SentenceTransformerUnavailableError(
            f"Could not load SentenceTransformers model {model_name!r}: {exc}"
        ) from exc


def _coerce_matrix(value: Any) -> list[list[float]]:
    """Convert NumPy/Torch/list-like model output into validated Python lists."""

    if hasattr(value, "tolist"):
        value = value.tolist()

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("SentenceTransformer.encode returned an invalid embedding matrix.")

    result: list[list[float]] = []
    expected_dim: int | None = None
    for raw_vector in value:
        if hasattr(raw_vector, "tolist"):
            raw_vector = raw_vector.tolist()
        if isinstance(raw_vector, (str, bytes)) or not isinstance(raw_vector, Sequence):
            raise ValueError("SentenceTransformer.encode returned an invalid vector.")

        vector = [float(item) for item in raw_vector]
        if not vector:
            raise ValueError("SentenceTransformer returned an empty embedding vector.")
        if not all(math.isfinite(item) for item in vector):
            raise ValueError("SentenceTransformer returned a non-finite embedding value.")

        if expected_dim is None:
            expected_dim = len(vector)
        elif len(vector) != expected_dim:
            raise ValueError("SentenceTransformer returned inconsistent embedding dimensions.")
        result.append(vector)

    return result


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Real local embedding provider backed by SentenceTransformers.

    The default model is ``Alibaba-NLP/gte-modernbert-base``.  Model inference
    runs locally.  Unless ``local_files_only=True`` is requested, the underlying
    library may download the model from Hugging Face the first time it is used.
    Subsequent loads use the normal local model cache.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_SENTENCE_TRANSFORMER_MODEL,
        *,
        device: str | None = None,
        batch_size: int = 32,
        model_cache_dir: str | Path | None = None,
        local_files_only: bool = False,
        revision: str | None = None,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        model: Any | None = None,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        model_name = str(model_name or "").strip()
        if not model_name:
            raise ValueError("SentenceTransformer model_name must be non-empty.")
        if int(batch_size) <= 0:
            raise ValueError("SentenceTransformer batch_size must be positive.")

        self._model_name = model_name
        self.device = str(device).strip() if device is not None else None
        self.batch_size = int(batch_size)
        self.model_cache_dir = (
            str(Path(model_cache_dir).expanduser())
            if model_cache_dir is not None
            else None
        )
        self.local_files_only = bool(local_files_only)
        self.revision = str(revision).strip() if revision is not None else None
        self.normalize_embeddings = bool(normalize_embeddings)
        self.show_progress_bar = bool(show_progress_bar)
        self._model = model
        self._model_factory = model_factory or _default_model_factory

    def provider_name(self) -> str:
        return "sentence_transformers"

    def model_name(self) -> str:
        return self._model_name

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        kwargs: dict[str, Any] = {
            "device": self.device,
            "cache_folder": self.model_cache_dir,
            "trust_remote_code": False,
            "local_files_only": self.local_files_only,
        }
        if self.revision:
            kwargs["revision"] = self.revision

        # Avoid passing explicit None values unless the library documents them.
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        self._model = self._model_factory(self._model_name, **kwargs)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        for text in texts:
            if not isinstance(text, str):
                raise TypeError("SentenceTransformerEmbeddingProvider expects string inputs.")
        if not texts:
            return []

        model = self._load_model()
        try:
            matrix = model.encode(
                list(texts),
                batch_size=self.batch_size,
                show_progress_bar=self.show_progress_bar,
                convert_to_numpy=True,
                normalize_embeddings=self.normalize_embeddings,
            )
        except Exception as exc:
            raise SentenceTransformerUnavailableError(
                f"SentenceTransformer embedding failed for model {self._model_name!r}: {exc}"
            ) from exc

        vectors = _coerce_matrix(matrix)
        if len(vectors) != len(texts):
            raise ValueError(
                "SentenceTransformer returned an unexpected number of vectors: "
                f"expected {len(texts)}, received {len(vectors)}."
            )
        return vectors


__all__ = [
    "DEFAULT_SENTENCE_TRANSFORMER_MODEL",
    "SentenceTransformerUnavailableError",
    "SentenceTransformerEmbeddingProvider",
    "sentence_transformers_available",
]
