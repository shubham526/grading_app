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

    @classmethod
    def from_metadata(cls, data: Dict[str, Any]) -> "TranscriptionPreflightResult":
        if not isinstance(data, dict):
            raise TypeError("preflight metadata must be a dictionary")
        return cls(
            ok=bool(data.get("ok", False)),
            backend=str(data.get("backend", "")),
            model=str(data.get("model", "")),
            server_url=data.get("server_url"),
            capabilities=[str(v) for v in data.get("capabilities", [])],
            warnings=[str(v) for v in data.get("warnings", [])],
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            metadata=dict(data.get("metadata", {}) or {}),
        )


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

    @classmethod
    def from_metadata(cls, data: Dict[str, Any]) -> "PageTranscription":
        if not isinstance(data, dict):
            raise TypeError("page transcription metadata must be a dictionary")
        raw_status = data.get("status", TranscriptionStatus.INFERENCE_FAILURE.value)
        try:
            status = TranscriptionStatus(str(raw_status))
        except ValueError as exc:
            raise ValueError(f"Unknown transcription status: {raw_status!r}") from exc
        return cls(
            page_number=int(data.get("page_number", 0)),
            source_image=str(data.get("source_image", "")),
            text=str(data.get("text", "")),
            status=status,
            backend=str(data.get("backend", "")),
            model=str(data.get("model", "")),
            prompt_version=str(data.get("prompt_version", "")),
            duration_seconds=float(data.get("duration_seconds", 0.0) or 0.0),
            generated_tokens=(
                int(data["generated_tokens"])
                if data.get("generated_tokens") is not None
                else None
            ),
            done_reason=data.get("done_reason"),
            warning=data.get("warning"),
            metadata=dict(data.get("metadata", {}) or {}),
            assistive_only=bool(data.get("assistive_only", True)),
            authoritative=bool(data.get("authoritative", False)),
        )


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

    @classmethod
    def from_metadata(cls, data: Dict[str, Any]) -> "TranscriptionBatchResult":
        if not isinstance(data, dict):
            raise TypeError("transcription batch metadata must be a dictionary")
        raw_pages = data.get("pages", [])
        if not isinstance(raw_pages, list):
            raise TypeError("transcription batch pages must be a list")
        pages = [PageTranscription.from_metadata(page) for page in raw_pages]
        raw_preflight = data.get("preflight")
        preflight = (
            TranscriptionPreflightResult.from_metadata(raw_preflight)
            if isinstance(raw_preflight, dict)
            else None
        )
        return cls(
            backend=str(data.get("backend", "")),
            model=str(data.get("model", "")),
            prompt_version=str(data.get("prompt_version", "")),
            pages=pages,
            preflight=preflight,
            duration_seconds=float(data.get("duration_seconds", 0.0) or 0.0),
            warnings=[str(v) for v in data.get("warnings", [])],
            assistive_only=bool(data.get("assistive_only", True)),
            authoritative=bool(data.get("authoritative", False)),
        )


__all__ = [
    "PageTranscription",
    "TranscriptionBatchResult",
    "TranscriptionPreflightResult",
    "TranscriptionStatus",
]
