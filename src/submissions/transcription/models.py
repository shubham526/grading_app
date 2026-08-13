"""Data models for assistive handwriting transcription.

Machine transcription is derived evidence only.  The original accommodation
PDF and its rendered page image remain the authoritative evidence presented to
the grader.  These models deliberately encode that distinction so later UI and
persistence code cannot accidentally treat VLM output as canonical student work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TranscriptionStatus(str, Enum):
    """Page-level transcription outcome.

    Only ``SUCCESSFUL`` is considered usable for automatic question-boundary
    assistance.  Degraded outputs are retained for inspection but must not be
    silently consumed as complete student work.
    """

    SUCCESSFUL = "successful"
    UNAVAILABLE = "unavailable"
    MODEL_LOAD_FAILURE = "model_load_failure"
    INFERENCE_FAILURE = "inference_failure"
    EMPTY_OUTPUT = "empty_output"
    GENERATION_LIMIT = "generation_limit"
    DEGENERATE_REPETITION = "degenerate_repetition"


@dataclass
class TranscriptionPreflightResult:
    """Availability check for one configured transcription backend/model."""

    ok: bool
    backend: str
    model: str
    server_url: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PageTranscription:
    """Assistive transcription for one rendered accommodation-PDF page."""

    page_number: int
    source_image: str
    text: str
    status: TranscriptionStatus
    backend: str
    model: str
    prompt_version: str
    duration_seconds: float = 0.0
    generated_tokens: Optional[int] = None
    done_reason: Optional[str] = None
    warning: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    assistive_only: bool = True
    authoritative: bool = False

    @property
    def usable(self) -> bool:
        """Whether this page may be used for assistive question splitting."""
        return self.status == TranscriptionStatus.SUCCESSFUL and bool(self.text.strip())

    def to_metadata(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["usable"] = self.usable
        return data


@dataclass
class TranscriptionBatchResult:
    """Page-aligned result for a rendered PDF transcription pass."""

    backend: str
    model: str
    prompt_version: str
    pages: List[PageTranscription] = field(default_factory=list)
    preflight: Optional[TranscriptionPreflightResult] = None
    duration_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)
    assistive_only: bool = True
    authoritative: bool = False

    @property
    def all_pages_usable(self) -> bool:
        return bool(self.pages) and all(page.usable for page in self.pages)

    @property
    def any_page_usable(self) -> bool:
        return any(page.usable for page in self.pages)

    @property
    def status(self) -> str:
        if self.all_pages_usable:
            return "successful"
        if self.any_page_usable:
            return "partial"
        if self.pages and all(page.status == TranscriptionStatus.UNAVAILABLE for page in self.pages):
            return "unavailable"
        if not self.pages:
            return "unavailable"
        return "failed"

    def combined_text(self) -> str:
        """Return page text only when every page is complete and usable.

        This intentionally refuses to build a partial pseudo-submission.  If one
        page is missing, capped, empty, or degenerate, the UI may still display
        individual page results, but automatic answer splitting must not infer a
        complete submission from an incomplete transcription.
        """
        if not self.all_pages_usable:
            return ""
        return "\n\n".join(page.text.strip() for page in self.pages).strip()

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "all_pages_usable": self.all_pages_usable,
            "any_page_usable": self.any_page_usable,
            "duration_seconds": self.duration_seconds,
            "warnings": list(self.warnings),
            "assistive_only": self.assistive_only,
            "authoritative": self.authoritative,
            "preflight": self.preflight.to_metadata() if self.preflight else None,
            "pages": [page.to_metadata() for page in self.pages],
        }


__all__ = [
    "PageTranscription",
    "TranscriptionBatchResult",
    "TranscriptionPreflightResult",
    "TranscriptionStatus",
]
