"""
Data models for submission ingestion.

The submission package is intentionally independent of the PyQt UI and scoring
modules. Its objects describe source files, parsed question answers, LaTeX
compilation results, PDF page-rendering artifacts, and references to assistive
transcription metadata without changing rubric or assessment semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


SUBMISSION_MODE_LATEX = "latex"
SUBMISSION_MODE_PDF_ACCOMMODATION = "pdf_accommodation"

SOURCE_NONE = "none"
SOURCE_LATEX = "latex"
SOURCE_PDF = "pdf"


@dataclass
class SubmissionRecord:
    """Files discovered or explicitly supplied for one student submission.

    ``files`` uses stable logical keys rather than filename extensions. Normal
    submissions use ``latex`` plus an optional student ``pdf`` reference. PDF
    accommodations use ``pdf`` as the authoritative submitted artifact.

    ``accommodation_mode`` is intentionally generic. The application must not
    persist medical, disability, or other accommodation-reason details.
    """

    student_id: str
    files: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    submission_root: Optional[str] = None
    submission_mode: str = SUBMISSION_MODE_LATEX
    accommodation_mode: bool = False

    @property
    def latex_path(self) -> Optional[str]:
        return self.files.get("latex")

    @property
    def pdf_path(self) -> Optional[str]:
        return self.files.get("pdf")


@dataclass
class CompilationResult:
    """Result of compiling one LaTeX submission to PDF."""

    success: bool
    source_path: str
    engine: str
    pdf_path: Optional[str] = None
    build_dir: Optional[str] = None
    temporary_output: bool = False
    return_code: Optional[int] = None
    passes_completed: int = 0
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    warnings: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_metadata(self, include_logs: bool = False) -> Dict[str, Any]:
        """Return a JSON-friendly representation suitable for parser metadata."""
        data = asdict(self)
        if not include_logs:
            data.pop("stdout", None)
            data.pop("stderr", None)
        return data


@dataclass(frozen=True)
class PdfPageArtifact:
    """One rendered page derived from an authoritative accommodation PDF."""

    page_number: int
    image_path: str
    width_px: int
    height_px: int
    dpi: int
    text_length: int = 0

    def to_metadata(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PdfRenderResult:
    """Result of rendering a PDF into page-aligned PNG images."""

    success: bool
    source_path: str
    dpi: int
    output_dir: Optional[str] = None
    temporary_output: bool = False
    page_count: int = 0
    pages: List[PdfPageArtifact] = field(default_factory=list)
    duration_seconds: float = 0.0
    renderer: Optional[str] = None
    renderer_version: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source_path": self.source_path,
            "dpi": self.dpi,
            "output_dir": self.output_dir,
            "temporary_output": self.temporary_output,
            "page_count": self.page_count,
            "pages": [page.to_metadata() for page in self.pages],
            "duration_seconds": self.duration_seconds,
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass
class ParsedSubmission:
    """General-purpose parsed representation of a student submission."""

    student_id: str
    source_used: str = SOURCE_NONE
    raw_text: str = ""
    answers_by_question: Dict[str, str] = field(default_factory=dict)
    files: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    submission_mode: str = SUBMISSION_MODE_LATEX
    accommodation_mode: bool = False

    def get_answer(self, question_id: str) -> Optional[str]:
        """Return the extracted answer for ``question_id`` if present."""
        return self.answers_by_question.get(question_id)

    @property
    def page_image_paths(self) -> List[str]:
        """Return rendered PDF page-image paths, if this submission has them."""
        rendering = self.metadata.get("rendering", {})
        pages = rendering.get("pages", []) if isinstance(rendering, dict) else []
        paths: List[str] = []
        for page in pages:
            if isinstance(page, dict) and page.get("image_path"):
                paths.append(str(page["image_path"]))
        return paths

    @property
    def transcription_metadata(self) -> Dict[str, Any]:
        """Return JSON-friendly assistive transcription metadata, if present."""
        value = self.metadata.get("transcription", {})
        return value if isinstance(value, dict) else {}

    @property
    def page_transcriptions(self) -> List[Dict[str, Any]]:
        """Return page-aligned transcription records without making them canonical."""
        pages = self.transcription_metadata.get("pages", [])
        if not isinstance(pages, list):
            return []
        return [page for page in pages if isinstance(page, dict)]


__all__ = [
    "CompilationResult",
    "ParsedSubmission",
    "PdfPageArtifact",
    "PdfRenderResult",
    "SOURCE_LATEX",
    "SOURCE_NONE",
    "SOURCE_PDF",
    "SUBMISSION_MODE_LATEX",
    "SUBMISSION_MODE_PDF_ACCOMMODATION",
    "SubmissionRecord",
]
