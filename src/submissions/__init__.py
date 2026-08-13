"""Submission ingestion for the Rubric Grading Tool.

v2.2.0 commits 1-4 provide four intentionally separated backend layers:

* normal submissions: canonical LaTeX source, app-compiled visual PDF;
* explicit PDF accommodations: original PDF is authoritative and pages are
  rendered at a deterministic DPI;
* optional assistive handwriting transcription: page-aligned VLM output that
  never replaces the original PDF or rendered page evidence;
* persistent evidence/provenance storage with SHA-256 validation and reusable
  transcription caches.

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
from .storage import (
    EVIDENCE_SCHEMA_VERSION,
    EXTRACTED_ANSWERS_FILENAME,
    EvidenceStoragePaths,
    RAW_TEXT_FILENAME,
    SUBMISSION_META_FILENAME,
    TRANSCRIPTION_CACHE_FILENAME,
    TRANSCRIPTION_CACHE_SCHEMA_VERSION,
    TRANSCRIPTION_FILENAME,
    assessment_submission_fields,
    build_transcription_cache_inputs,
    compute_file_sha256,
    evidence_storage_paths,
    load_cached_transcription,
    load_persisted_submission,
    persist_submission_evidence,
    save_transcription_cache,
    transcription_cache_key,
)
from .transcription import (
    DEFAULT_HANDWRITING_MODEL,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_PREDICT,
    DEFAULT_OLLAMA_URL,
    DEFAULT_SEED,
    DEFAULT_TEMPERATURE,
    HANDWRITING_PROMPT_SHA256,
    HANDWRITING_PROMPT_VERSION,
    HANDWRITING_TRANSCRIPTION_PROMPT,
    OllamaTranscriptionBackend,
    PageTranscription,
    TranscriptionBackend,
    TranscriptionBatchResult,
    TranscriptionPreflightResult,
    TranscriptionStatus,
    detect_degenerate_repetition,
    transcribe_page_images,
)

__all__ = [
    "ALLOWED_ENGINES",
    "CompilationResult",
    "DEFAULT_HANDWRITING_MODEL",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_MAX_PAGE_PIXELS",
    "DEFAULT_MAX_PDF_BYTES",
    "DEFAULT_MAX_PDF_PAGES",
    "DEFAULT_MIN_TEXT_CHARS_PER_PAGE",
    "DEFAULT_NUM_CTX",
    "DEFAULT_NUM_PREDICT",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_RENDER_DPI",
    "DEFAULT_SEED",
    "DEFAULT_TEMPERATURE",
    "EVIDENCE_SCHEMA_VERSION",
    "EXTRACTED_ANSWERS_FILENAME",
    "EvidenceStoragePaths",
    "FULL_SUBMISSION",
    "HANDWRITING_PROMPT_SHA256",
    "HANDWRITING_PROMPT_VERSION",
    "HANDWRITING_TRANSCRIPTION_PROMPT",
    "MAX_RENDER_DPI",
    "MIN_RENDER_DPI",
    "RAW_TEXT_FILENAME",
    "SUBMISSION_META_FILENAME",
    "TRANSCRIPTION_CACHE_FILENAME",
    "TRANSCRIPTION_CACHE_SCHEMA_VERSION",
    "TRANSCRIPTION_FILENAME",
    "OllamaTranscriptionBackend",
    "PageTranscription",
    "ParsedSubmission",
    "PdfPageArtifact",
    "PdfRenderResult",
    "SOURCE_LATEX",
    "SOURCE_NONE",
    "SOURCE_PDF",
    "SUBMISSION_MODE_LATEX",
    "SUBMISSION_MODE_PDF_ACCOMMODATION",
    "SubmissionRecord",
    "TranscriptionBackend",
    "TranscriptionBatchResult",
    "TranscriptionPreflightResult",
    "TranscriptionStatus",
    "assessment_submission_fields",
    "build_transcription_cache_inputs",
    "cleanup_compilation_artifacts",
    "cleanup_pdf_render_artifacts",
    "compute_file_sha256",
    "compile_tex_to_pdf",
    "detect_degenerate_repetition",
    "discover_submissions",
    "evidence_storage_paths",
    "extract_text_from_pdf",
    "extract_text_from_tex",
    "load_cached_transcription",
    "load_persisted_submission",
    "match_student_directory",
    "normalize_heading_question_id",
    "normalize_student_id",
    "parse_pdf_accommodation",
    "parse_pdf_accommodations",
    "parse_submission",
    "parse_submissions_folder",
    "persist_submission_evidence",
    "record_from_latex_file",
    "record_from_pdf_accommodation",
    "render_pdf_pages",
    "save_transcription_cache",
    "split_answers_by_question",
    "strip_latex_comment",
    "transcribe_page_images",
    "transcription_cache_key",
]
