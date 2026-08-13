"""Model-agnostic handwriting-transcription interface and orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
import time
from typing import List, Optional, Sequence

from .models import (
    PageTranscription,
    TranscriptionBatchResult,
    TranscriptionPreflightResult,
    TranscriptionStatus,
)


class TranscriptionBackend(ABC):
    """Abstract page-transcription backend.

    Concrete backends must return structured failures rather than raising for
    ordinary service/model/inference errors.  Programming/configuration errors
    may still raise at construction time.
    """

    @property
    @abstractmethod
    def backend_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def prompt_version(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def preflight(self, *, force: bool = False) -> TranscriptionPreflightResult:
        """Check whether the configured service/model can be used."""
        raise NotImplementedError

    @abstractmethod
    def transcribe_page(
        self,
        image_path: str,
        *,
        page_number: Optional[int] = None,
    ) -> PageTranscription:
        """Transcribe one page image as assistive evidence."""
        raise NotImplementedError

    def cache_identity(self) -> dict:
        """Return output-relevant identity used for persistent cache keys.

        Backends may override this to include generation parameters and prompt
        hashes.  Service location, credentials, timeouts, and keep-alive settings
        should not be included because they do not define the expected model
        output.
        """
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "prompt_version": self.prompt_version,
        }


def _preflight_failure_status(result: TranscriptionPreflightResult) -> TranscriptionStatus:
    if result.error_code in {
        "model_not_installed",
        "model_not_vision_capable",
        "model_load_failure",
    }:
        return TranscriptionStatus.MODEL_LOAD_FAILURE
    return TranscriptionStatus.UNAVAILABLE


def transcribe_page_images(
    backend: TranscriptionBackend,
    image_paths: Sequence[str],
) -> TranscriptionBatchResult:
    """Transcribe rendered page images in order with failure isolation.

    Preflight runs once.  If it fails, page-aligned structured failures are
    returned for every image.  If one inference fails, later pages are still
    attempted; however, ``combined_text()`` remains unavailable unless every
    page succeeds.
    """
    started = time.monotonic()
    paths = [str(path) for path in image_paths]
    preflight = backend.preflight()

    if not preflight.ok:
        status = _preflight_failure_status(preflight)
        warning = preflight.error_code or "transcription_unavailable"
        pages = [
            PageTranscription(
                page_number=index,
                source_image=path,
                text="",
                status=status,
                backend=backend.backend_name,
                model=backend.model_name,
                prompt_version=backend.prompt_version,
                warning=warning,
                metadata={"preflight_error": preflight.error_message},
            )
            for index, path in enumerate(paths, start=1)
        ]
        return TranscriptionBatchResult(
            backend=backend.backend_name,
            model=backend.model_name,
            prompt_version=backend.prompt_version,
            pages=pages,
            preflight=preflight,
            duration_seconds=time.monotonic() - started,
            warnings=[warning],
        )

    pages: List[PageTranscription] = []
    warnings: List[str] = []
    for index, path in enumerate(paths, start=1):
        try:
            result = backend.transcribe_page(path, page_number=index)
        except Exception as exc:  # defensive isolation for third-party backends
            result = PageTranscription(
                page_number=index,
                source_image=path,
                text="",
                status=TranscriptionStatus.INFERENCE_FAILURE,
                backend=backend.backend_name,
                model=backend.model_name,
                prompt_version=backend.prompt_version,
                warning="transcription_backend_exception",
                metadata={"exception": str(exc)},
            )
        pages.append(result)
        if result.warning:
            warnings.append(f"page_{index}:{result.warning}")

    if pages and not all(page.usable for page in pages):
        warnings.append("transcription_incomplete")

    return TranscriptionBatchResult(
        backend=backend.backend_name,
        model=backend.model_name,
        prompt_version=backend.prompt_version,
        pages=pages,
        preflight=preflight,
        duration_seconds=time.monotonic() - started,
        warnings=list(dict.fromkeys(warnings)),
    )


__all__ = [
    "TranscriptionBackend",
    "transcribe_page_images",
]
