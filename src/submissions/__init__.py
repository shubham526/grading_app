"""
Submission ingestion for the Rubric Grading Tool.

v2.2.0 commit 1 provides the normal LaTeX-first path: discover canonical .tex
sources, extract faithful grading text, split it using the same Q1/Q1A question
identity convention introduced in v2.1.0, and compile a visual PDF in a
restricted workspace.

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
    SOURCE_LATEX,
    SOURCE_NONE,
    SUBMISSION_MODE_LATEX,
    SubmissionRecord,
)
from .parser import parse_submission, parse_submissions_folder
from .splitter import FULL_SUBMISSION, normalize_heading_question_id, split_answers_by_question

__all__ = [
    "ALLOWED_ENGINES",
    "CompilationResult",
    "FULL_SUBMISSION",
    "ParsedSubmission",
    "SOURCE_LATEX",
    "SOURCE_NONE",
    "SUBMISSION_MODE_LATEX",
    "SubmissionRecord",
    "cleanup_compilation_artifacts",
    "compile_tex_to_pdf",
    "discover_submissions",
    "extract_text_from_tex",
    "match_student_directory",
    "normalize_heading_question_id",
    "normalize_student_id",
    "parse_submission",
    "parse_submissions_folder",
    "record_from_latex_file",
    "split_answers_by_question",
    "strip_latex_comment",
]
