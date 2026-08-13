"""Assistive handwriting transcription backends for v2.2.0."""

from .base import TranscriptionBackend, transcribe_page_images
from .models import (
    PageTranscription,
    TranscriptionBatchResult,
    TranscriptionPreflightResult,
    TranscriptionStatus,
)
from .ollama import (
    DEFAULT_HANDWRITING_MODEL,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_PREDICT,
    DEFAULT_OLLAMA_URL,
    DEFAULT_SEED,
    DEFAULT_TEMPERATURE,
    OllamaTranscriptionBackend,
    detect_degenerate_repetition,
)
from .prompt import (
    HANDWRITING_PROMPT_SHA256,
    HANDWRITING_PROMPT_VERSION,
    HANDWRITING_TRANSCRIPTION_PROMPT,
)

__all__ = [
    "DEFAULT_HANDWRITING_MODEL",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_NUM_CTX",
    "DEFAULT_NUM_PREDICT",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_SEED",
    "DEFAULT_TEMPERATURE",
    "HANDWRITING_PROMPT_SHA256",
    "HANDWRITING_PROMPT_VERSION",
    "HANDWRITING_TRANSCRIPTION_PROMPT",
    "OllamaTranscriptionBackend",
    "PageTranscription",
    "TranscriptionBackend",
    "TranscriptionBatchResult",
    "TranscriptionPreflightResult",
    "TranscriptionStatus",
    "detect_degenerate_repetition",
    "transcribe_page_images",
]
