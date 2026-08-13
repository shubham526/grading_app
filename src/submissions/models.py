"""
Data models for submission ingestion.

The submission package is intentionally independent of the PyQt UI and scoring
modules.  Its objects describe source files, parsed question answers, and
LaTeX compilation results without changing rubric or assessment semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


SUBMISSION_MODE_LATEX = "latex"
SOURCE_NONE = "none"
SOURCE_LATEX = "latex"


@dataclass
class SubmissionRecord:
    """Files discovered for one student submission.

    ``files`` uses stable logical keys rather than filename extensions.  For
    commit 1 the normal path recognizes ``latex`` and an optional student
    ``pdf`` reference.  The application-generated compiled PDF is added later
    by the parser under ``compiled_pdf``.
    """

    student_id: str
    files: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    submission_root: Optional[str] = None

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

    def get_answer(self, question_id: str) -> Optional[str]:
        """Return the extracted answer for ``question_id`` if present."""
        return self.answers_by_question.get(question_id)


__all__ = [
    "CompilationResult",
    "ParsedSubmission",
    "SOURCE_LATEX",
    "SOURCE_NONE",
    "SUBMISSION_MODE_LATEX",
    "SubmissionRecord",
]
