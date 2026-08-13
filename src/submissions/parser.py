"""
High-level submission parsing APIs.

Normal submissions are LaTeX-first. PDF-only submissions are accepted only
through an explicit accommodation path; the original PDF remains authoritative
and rendered page images / selectable text are derived evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .compiler import compile_tex_to_pdf
from .latex import extract_text_from_tex
from .matcher import (
    discover_submissions,
    match_student_directory,
    normalize_student_id,
    record_from_latex_file,
)
from .models import (
    ParsedSubmission,
    SOURCE_LATEX,
    SOURCE_PDF,
    SUBMISSION_MODE_LATEX,
    SUBMISSION_MODE_PDF_ACCOMMODATION,
    SubmissionRecord,
)
from .pdf import (
    DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    DEFAULT_RENDER_DPI,
    extract_text_from_pdf,
    record_from_pdf_accommodation,
    render_pdf_pages,
)
from .splitter import FULL_SUBMISSION, split_answers_by_question


def _split_status(answers: Dict[str, str], warnings: Sequence[str]) -> str:
    if FULL_SUBMISSION in answers:
        return "unsplit"
    if any(warning.startswith("missing_answer_for_") for warning in warnings):
        return "partial"
    return "success"


def _parse_record(
    record: SubmissionRecord,
    *,
    question_ids: Optional[Sequence[str]],
    compile_pdf: bool,
    compilation_dir: Optional[str],
    compiler_options: Optional[Dict[str, Any]],
) -> ParsedSubmission:
    latex_path = record.latex_path
    if not latex_path:
        raise ValueError(f"Normal submission for {record.student_id!r} has no LaTeX source")

    text, extraction_meta = extract_text_from_tex(latex_path)
    answers, split_warnings = split_answers_by_question(text, question_ids)

    warnings = list(record.warnings)
    warnings.extend(extraction_meta.get("warnings", []))
    warnings.extend(split_warnings)

    files = dict(record.files)
    metadata: Dict[str, Any] = {
        "source_priority": ["latex"],
        "canonical_source": "latex",
        "authoritative_source": "latex",
        "text_length": len(text),
        "question_ids_detected": [qid for qid in answers if qid != FULL_SUBMISSION],
        "question_split_status": _split_status(answers, split_warnings),
        "extraction": extraction_meta,
    }

    if compile_pdf:
        options = dict(compiler_options or {})
        if compilation_dir is not None:
            student_output_dir = Path(compilation_dir).expanduser().resolve() / record.student_id
            options["output_dir"] = str(student_output_dir)
        elif "output_dir" in options:
            options["output_dir"] = str(Path(options["output_dir"]).expanduser().resolve())

        compilation = compile_tex_to_pdf(latex_path, **options)
        metadata["compilation"] = compilation.to_metadata(include_logs=False)
        if compilation.success and compilation.pdf_path:
            files["compiled_pdf"] = compilation.pdf_path
        else:
            warnings.append(compilation.error_code or "latex_compilation_failed")

    return ParsedSubmission(
        student_id=record.student_id,
        submission_mode=SUBMISSION_MODE_LATEX,
        accommodation_mode=False,
        source_used=SOURCE_LATEX,
        raw_text=text,
        answers_by_question=answers,
        files=files,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
    )


def _parse_pdf_accommodation_record(
    record: SubmissionRecord,
    *,
    question_ids: Optional[Sequence[str]],
    render_dir: Optional[str],
    render_dpi: int,
    min_text_chars_per_page: int,
    pdf_options: Optional[Dict[str, Any]],
) -> ParsedSubmission:
    pdf_path = record.pdf_path
    if not pdf_path:
        raise ValueError(f"PDF accommodation for {record.student_id!r} has no PDF file")

    options = dict(pdf_options or {})
    text_options = {
        key: value
        for key, value in options.items()
        if key in {"max_pdf_bytes", "max_pages"}
    }
    text_options["min_chars_per_page"] = min_text_chars_per_page
    text, extraction_meta = extract_text_from_pdf(pdf_path, **text_options)

    warnings = list(record.warnings)
    warnings.extend(extraction_meta.get("warnings", []))

    # Sparse/no text is common for handwritten scans. Do not split a tiny text
    # layer (often only a printed header) into answer content: that risks showing
    # the grader the wrong evidence. Commit 3 will add explicit VLM transcription.
    split_warnings = []
    if extraction_meta.get("selectable_text") and text.strip():
        answers, split_warnings = split_answers_by_question(text, question_ids)
        question_split_status = _split_status(answers, split_warnings)
        answer_text_source = "pdf_selectable_text"
        warnings.extend(split_warnings)
    else:
        answers = {}
        question_split_status = "unavailable"
        answer_text_source = None

    render_options = {
        key: value
        for key, value in options.items()
        if key in {"max_pdf_bytes", "max_pages", "max_page_pixels"}
    }
    if render_dir is not None:
        student_render_dir = Path(render_dir).expanduser().resolve() / record.student_id
        render_options["output_dir"] = str(student_render_dir)
    elif "output_dir" in options:
        render_options["output_dir"] = str(Path(options["output_dir"]).expanduser().resolve())
    render_options["dpi"] = render_dpi

    rendering = render_pdf_pages(pdf_path, **render_options)
    warnings.extend(rendering.warnings)
    if not rendering.success:
        warnings.append(rendering.error_code or "pdf_rendering_failed")

    files = dict(record.files)
    if rendering.success and rendering.output_dir:
        files["rendered_pages_dir"] = rendering.output_dir

    metadata: Dict[str, Any] = {
        "source_priority": ["pdf"],
        "canonical_source": "pdf",
        "authoritative_source": "original_pdf",
        "original_pdf_authoritative": True,
        "assistive_text_source": answer_text_source,
        "text_length": len(text),
        "question_ids_detected": [qid for qid in answers if qid != FULL_SUBMISSION],
        "question_split_status": question_split_status,
        "extraction": extraction_meta,
        "rendering": rendering.to_metadata(),
        "accommodation_mode": True,
    }

    return ParsedSubmission(
        student_id=record.student_id,
        submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
        accommodation_mode=True,
        source_used=SOURCE_PDF,
        raw_text=text,
        answers_by_question=answers,
        files=files,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
    )


def parse_pdf_accommodation(
    submission_path: str,
    question_ids: Optional[Sequence[str]] = None,
    *,
    student_id: Optional[str] = None,
    render_dir: Optional[str] = None,
    render_dpi: int = DEFAULT_RENDER_DPI,
    min_text_chars_per_page: int = DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    pdf_options: Optional[Dict[str, Any]] = None,
) -> ParsedSubmission:
    """Parse one explicitly authorized PDF accommodation submission."""
    record = record_from_pdf_accommodation(submission_path, student_id=student_id)
    return _parse_pdf_accommodation_record(
        record,
        question_ids=question_ids,
        render_dir=render_dir,
        render_dpi=render_dpi,
        min_text_chars_per_page=min_text_chars_per_page,
        pdf_options=pdf_options,
    )


def parse_submission(
    submission_path: str,
    question_ids: Optional[Sequence[str]] = None,
    *,
    compile_pdf: bool = True,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Dict[str, Any]] = None,
    accommodation_mode: bool = False,
    student_id: Optional[str] = None,
    render_dir: Optional[str] = None,
    render_dpi: int = DEFAULT_RENDER_DPI,
    min_text_chars_per_page: int = DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    pdf_options: Optional[Dict[str, Any]] = None,
) -> ParsedSubmission:
    """Parse one submission.

    Normal calls accept LaTeX only. A PDF is accepted only when
    ``accommodation_mode=True``; this explicit flag prevents an invalid normal
    PDF-only submission from being silently interpreted as an accommodation.
    """
    requested_path = Path(submission_path).expanduser()
    if requested_path.is_symlink():
        raise ValueError(f"Symlinked submission paths are not accepted: {requested_path}")
    path = requested_path.resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))

    if accommodation_mode:
        return parse_pdf_accommodation(
            str(path),
            question_ids,
            student_id=student_id,
            render_dir=render_dir,
            render_dpi=render_dpi,
            min_text_chars_per_page=min_text_chars_per_page,
            pdf_options=pdf_options,
        )

    if path.is_file():
        if path.suffix.lower() == ".pdf":
            raise ValueError(
                "PDF-only submissions require explicit accommodation_mode=True; "
                "normal submissions must provide canonical LaTeX source."
            )
        record = record_from_latex_file(str(path))
    elif path.is_dir():
        record = match_student_directory(str(path))
        if record is None:
            discovered = discover_submissions(str(path))
            if len(discovered) != 1:
                raise ValueError(
                    "parse_submission expected one student submission; "
                    f"found {len(discovered)} under {path}. Use parse_submissions_folder() for batches."
                )
            record = discovered[0]
    else:
        raise ValueError(f"Unsupported submission path: {path}")

    return _parse_record(
        record,
        question_ids=question_ids,
        compile_pdf=compile_pdf,
        compilation_dir=compilation_dir,
        compiler_options=compiler_options,
    )


def parse_submissions_folder(
    submissions_dir: str,
    question_ids: Optional[Sequence[str]] = None,
    *,
    compile_pdf: bool = True,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, ParsedSubmission]:
    """Discover and parse every normal LaTeX submission in a folder.

    PDF-only files remain intentionally excluded. Accommodations must be loaded
    explicitly through ``parse_pdf_accommodation`` or ``parse_pdf_accommodations``.
    """
    parsed: Dict[str, ParsedSubmission] = {}
    for record in discover_submissions(submissions_dir):
        parsed[record.student_id] = _parse_record(
            record,
            question_ids=question_ids,
            compile_pdf=compile_pdf,
            compilation_dir=compilation_dir,
            compiler_options=compiler_options,
        )
    return parsed


def parse_pdf_accommodations(
    accommodations: Mapping[str, str],
    question_ids: Optional[Sequence[str]] = None,
    *,
    render_dir: Optional[str] = None,
    render_dpi: int = DEFAULT_RENDER_DPI,
    min_text_chars_per_page: int = DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    pdf_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, ParsedSubmission]:
    """Parse an explicit ``student_id -> PDF/path`` accommodation mapping.

    The mapping itself is the only stored accommodation signal. No reason or
    medical/disability detail is accepted by this API.
    """
    parsed: Dict[str, ParsedSubmission] = {}
    for raw_student_id, path in accommodations.items():
        student_id = normalize_student_id(raw_student_id)
        if not student_id:
            raise ValueError(f"Invalid accommodation student ID: {raw_student_id!r}")
        if student_id in parsed:
            raise ValueError(f"Duplicate PDF accommodation student ID: {student_id}")

        parsed[student_id] = parse_pdf_accommodation(
            path,
            question_ids,
            student_id=student_id,
            render_dir=render_dir,
            render_dpi=render_dpi,
            min_text_chars_per_page=min_text_chars_per_page,
            pdf_options=pdf_options,
        )
    return parsed


__all__ = [
    "parse_pdf_accommodation",
    "parse_pdf_accommodations",
    "parse_submission",
    "parse_submissions_folder",
]
