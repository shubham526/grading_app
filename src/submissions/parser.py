"""
High-level submission parsing APIs.

Commit 1 implements the normal LaTeX path only.  PDF-only accommodations are
added in commit 2.  A student-provided PDF may still be retained as optional
reference material, but the canonical source is .tex and the application's
visual PDF is compiled from that source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .compiler import compile_tex_to_pdf
from .latex import extract_text_from_tex
from .matcher import (
    discover_submissions,
    match_student_directory,
    record_from_latex_file,
)
from .models import ParsedSubmission, SOURCE_LATEX, SUBMISSION_MODE_LATEX, SubmissionRecord
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
            # Caller-supplied output_dir wins only when the parser did not receive
            # its structured per-student compilation_dir argument.
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
        source_used=SOURCE_LATEX,
        raw_text=text,
        answers_by_question=answers,
        files=files,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
    )


def parse_submission(
    submission_path: str,
    question_ids: Optional[Sequence[str]] = None,
    *,
    compile_pdf: bool = True,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Dict[str, Any]] = None,
) -> ParsedSubmission:
    """Parse one normal LaTeX submission from a .tex file or student directory."""
    requested_path = Path(submission_path).expanduser()
    if requested_path.is_symlink():
        raise ValueError(f"Symlinked submission paths are not accepted: {requested_path}")
    path = requested_path.resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))

    if path.is_file():
        record = record_from_latex_file(str(path))
    elif path.is_dir():
        # A directory containing top-level .tex files is interpreted as one
        # student's submission directory.  Otherwise it may be a root with one
        # discoverable student; roots with multiple students must use the batch API.
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
    """Discover and parse every normal LaTeX submission in a folder."""
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


__all__ = ["parse_submission", "parse_submissions_folder"]
