"""
Submission ingestion for the Rubric Grading Tool.

v2.2.0 commits 1-2 provide two intentionally separate paths:

* normal submissions: canonical LaTeX source, app-compiled visual PDF;
* explicit PDF accommodations: original PDF is authoritative, pages are rendered
  at a deterministic DPI, and any selectable text is assistive only.

This package intentionally has no PyQt dependency so its backend can be tested
and reused independently of the desktop UI.
"""

from .compiler import ALLOWED_ENGINES, cleanup_compilation_artifacts, compile_tex_to_pdf
from .latex import extract_text_from_tex, strip_latex_comment
from .matcher import (
    discover_submissions,
    match_student_directory,
    normalize_student_id,
    record_from_latex_file,
)
from .models import (
    CompilationResult,
    ParsedSubmission,
    PdfPageArtifact,
    PdfRenderResult,
    SOURCE_LATEX,
    SOURCE_NONE,
    SOURCE_PDF,
    SUBMISSION_MODE_LATEX,
    SUBMISSION_MODE_PDF_ACCOMMODATION,
    SubmissionRecord,
)
from .parser import (
    parse_pdf_accommodation,
    parse_pdf_accommodations,
    parse_submission,
    parse_submissions_folder,
)
from .pdf import (
    DEFAULT_MAX_PAGE_PIXELS,
    DEFAULT_MAX_PDF_BYTES,
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    DEFAULT_RENDER_DPI,
    MAX_RENDER_DPI,
    MIN_RENDER_DPI,
    cleanup_pdf_render_artifacts,
    extract_text_from_pdf,
    record_from_pdf_accommodation,
    render_pdf_pages,
)
from .splitter import FULL_SUBMISSION, normalize_heading_question_id, split_answers_by_question

__all__ = [
    "ALLOWED_ENGINES",
    "CompilationResult",
    "DEFAULT_MAX_PAGE_PIXELS",
    "DEFAULT_MAX_PDF_BYTES",
    "DEFAULT_MAX_PDF_PAGES",
    "DEFAULT_MIN_TEXT_CHARS_PER_PAGE",
    "DEFAULT_RENDER_DPI",
    "FULL_SUBMISSION",
    "MAX_RENDER_DPI",
    "MIN_RENDER_DPI",
    "ParsedSubmission",
    "PdfPageArtifact",
    "PdfRenderResult",
    "SOURCE_LATEX",
    "SOURCE_NONE",
    "SOURCE_PDF",
    "SUBMISSION_MODE_LATEX",
    "SUBMISSION_MODE_PDF_ACCOMMODATION",
    "SubmissionRecord",
    "cleanup_compilation_artifacts",
    "cleanup_pdf_render_artifacts",
    "compile_tex_to_pdf",
    "discover_submissions",
    "extract_text_from_pdf",
    "extract_text_from_tex",
    "match_student_directory",
    "normalize_heading_question_id",
    "normalize_student_id",
    "parse_pdf_accommodation",
    "parse_pdf_accommodations",
    "parse_submission",
    "parse_submissions_folder",
    "record_from_latex_file",
    "record_from_pdf_accommodation",
    "render_pdf_pages",
    "split_answers_by_question",
    "strip_latex_comment",
]
