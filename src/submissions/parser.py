"""High-level submission parsing APIs.

Normal submissions are LaTeX-first. PDF-only submissions are accepted only
through an explicit accommodation path; the original PDF remains authoritative
and rendered page images / selectable text / machine transcription are derived
assistive evidence.
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
from .storage import (
    build_transcription_cache_inputs,
    compute_file_sha256,
    evidence_storage_paths,
    load_cached_transcription,
    persist_submission_evidence,
    save_transcription_cache,
)
from .transcription import (
    DEFAULT_HANDWRITING_MODEL,
    OllamaTranscriptionBackend,
    TranscriptionBackend,
    transcribe_page_images,
)


def _split_status(answers: Dict[str, str], warnings: Sequence[str]) -> str:
    if FULL_SUBMISSION in answers:
        return "unsplit"
    if any(warning.startswith("missing_answer_for_") for warning in warnings):
        return "partial"
    return "success"


def _resolve_transcription_backend(
    backend: Optional[TranscriptionBackend],
    options: Optional[Dict[str, Any]],
) -> TranscriptionBackend:
    if backend is not None:
        if options:
            raise ValueError(
                "transcription_options cannot be combined with an explicit "
                "transcription_backend; configure the backend instance directly."
            )
        return backend
    return OllamaTranscriptionBackend(**dict(options or {}))


def _not_requested_transcription_metadata() -> Dict[str, Any]:
    return {
        "enabled": False,
        "status": "not_requested",
        "assistive_only": True,
        "authoritative": False,
        "pages": [],
    }


def _unavailable_transcription_metadata(
    *,
    backend: Optional[TranscriptionBackend],
    options: Optional[Dict[str, Any]],
    warning: str,
) -> Dict[str, Any]:
    model = backend.model_name if backend is not None else str(
        (options or {}).get("model", DEFAULT_HANDWRITING_MODEL)
    )
    backend_name = backend.backend_name if backend is not None else "ollama"
    prompt_version = backend.prompt_version if backend is not None else None
    return {
        "enabled": True,
        "status": "unavailable",
        "backend": backend_name,
        "model": model,
        "prompt_version": prompt_version,
        "warnings": [warning],
        "assistive_only": True,
        "authoritative": False,
        "pages": [],
    }


def _parse_record(
    record: SubmissionRecord,
    *,
    question_ids: Optional[Sequence[str]],
    compile_pdf: bool,
    compilation_dir: Optional[str],
    compiler_options: Optional[Dict[str, Any]],
    evidence_dir: Optional[str],
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

    parsed = ParsedSubmission(
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
    if evidence_dir is not None:
        parsed = persist_submission_evidence(parsed, evidence_dir)
    return parsed


def parse_submission_record(
    record: SubmissionRecord,
    question_ids: Optional[Sequence[str]] = None,
    *,
    compile_pdf: bool = True,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Dict[str, Any]] = None,
    evidence_dir: Optional[str] = None,
) -> ParsedSubmission:
    """Parse one explicit normal-LaTeX ``SubmissionRecord``.

    This public wrapper exists so the v2.3.2 canonical bridge can preserve the
    canonical ``student_id`` even though immutable artifact filenames are
    intentionally opaque.  It delegates to the unchanged v2.2 parser logic.
    """
    if not isinstance(record, SubmissionRecord):
        raise TypeError("record must be SubmissionRecord")
    if record.accommodation_mode or record.submission_mode != SUBMISSION_MODE_LATEX:
        raise ValueError(
            "parse_submission_record accepts normal LaTeX records only; "
            "use parse_pdf_accommodation for explicit PDF accommodations."
        )

    return _parse_record(
        record,
        question_ids=question_ids,
        compile_pdf=compile_pdf,
        compilation_dir=compilation_dir,
        compiler_options=compiler_options,
        evidence_dir=evidence_dir,
    )


def _parse_pdf_accommodation_record(
    record: SubmissionRecord,
    *,
    question_ids: Optional[Sequence[str]],
    render_dir: Optional[str],
    render_dpi: int,
    min_text_chars_per_page: int,
    pdf_options: Optional[Dict[str, Any]],
    transcribe_handwriting: bool,
    transcription_backend: Optional[TranscriptionBackend],
    transcription_options: Optional[Dict[str, Any]],
    evidence_dir: Optional[str],
    reuse_cached_transcription: bool,
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

    # Selectable text can be useful for typed accommodations. Sparse/no text is
    # common for handwritten scans and must not be promoted to answer content:
    # a tiny text layer may contain only a printed header or scanner metadata.
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

    persistent_paths = None
    if evidence_dir is not None:
        if render_dir is not None:
            raise ValueError("render_dir cannot be combined with evidence_dir")
        persistent_paths = evidence_storage_paths(
            evidence_dir,
            record.student_id,
            create=True,
        )

    render_options = {
        key: value
        for key, value in options.items()
        if key in {"max_pdf_bytes", "max_pages", "max_page_pixels"}
    }
    if persistent_paths is not None:
        render_options["output_dir"] = persistent_paths.pages_dir
    elif render_dir is not None:
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

    transcription_requested = bool(transcribe_handwriting or transcription_backend is not None)
    transcription_meta = _not_requested_transcription_metadata()

    if transcription_requested:
        if not rendering.success or not rendering.pages:
            transcription_meta = _unavailable_transcription_metadata(
                backend=transcription_backend,
                options=transcription_options,
                warning="page_images_unavailable",
            )
            transcription_meta["cache"] = {
                "status": "disabled" if persistent_paths is None else "miss",
                "reason": "page_images_unavailable",
            }
            warnings.append("transcription_unavailable")
        else:
            backend = _resolve_transcription_backend(
                transcription_backend,
                transcription_options,
            )
            image_paths = [page.image_path for page in rendering.pages]
            batch = None
            cache_meta: Dict[str, Any] = {"status": "disabled"}
            cache_inputs = None

            if persistent_paths is not None:
                source_sha256 = compute_file_sha256(pdf_path)
                if reuse_cached_transcription:
                    batch, cache_meta = load_cached_transcription(
                        persistent_paths.transcription_cache_path,
                        backend=backend,
                        image_paths=image_paths,
                        render_dpi=render_dpi,
                        source_sha256=source_sha256,
                    )
                else:
                    cache_meta = {
                        "status": "disabled",
                        "reason": "reuse_disabled",
                    }

                # Build inputs separately only when inference is needed; the cache
                # helper already built them while checking for a hit.
                if batch is None:
                    cache_inputs = build_transcription_cache_inputs(
                        backend=backend,
                        image_paths=image_paths,
                        render_dpi=render_dpi,
                        source_sha256=source_sha256,
                    )

            if batch is None:
                batch = transcribe_page_images(backend, image_paths)
                if persistent_paths is not None and cache_inputs is not None:
                    stored_cache = save_transcription_cache(
                        persistent_paths.transcription_cache_path,
                        batch=batch,
                        cache_inputs=cache_inputs,
                    )
                    cache_meta = {
                        **cache_meta,
                        "stored": stored_cache,
                    }

            transcription_meta = batch.to_metadata()
            transcription_meta["enabled"] = True
            transcription_meta["cache"] = cache_meta
            warnings.extend(batch.warnings)

            # Machine transcription may assist question mapping only when the
            # PDF's selectable-text path was insufficient AND every page has a
            # complete usable transcription. A partial/capped/degenerate batch
            # is retained page-by-page but is never silently treated as the full
            # student submission.
            machine_text = batch.combined_text()
            if (
                not extraction_meta.get("selectable_text")
                and machine_text
                and batch.all_pages_usable
            ):
                answers, machine_split_warnings = split_answers_by_question(
                    machine_text,
                    question_ids,
                )
                warnings.extend(machine_split_warnings)
                question_split_status = _split_status(answers, machine_split_warnings)
                answer_text_source = "machine_transcription"
            elif not extraction_meta.get("selectable_text"):
                answers = {}
                question_split_status = "unavailable"
                answer_text_source = None

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
        "transcription": transcription_meta,
        "accommodation_mode": True,
    }

    parsed = ParsedSubmission(
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
    if evidence_dir is not None:
        parsed = persist_submission_evidence(parsed, evidence_dir)
    return parsed


def parse_pdf_accommodation(
    submission_path: str,
    question_ids: Optional[Sequence[str]] = None,
    *,
    student_id: Optional[str] = None,
    render_dir: Optional[str] = None,
    render_dpi: int = DEFAULT_RENDER_DPI,
    min_text_chars_per_page: int = DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    pdf_options: Optional[Dict[str, Any]] = None,
    transcribe_handwriting: bool = False,
    transcription_backend: Optional[TranscriptionBackend] = None,
    transcription_options: Optional[Dict[str, Any]] = None,
    evidence_dir: Optional[str] = None,
    reuse_cached_transcription: bool = True,
) -> ParsedSubmission:
    """Parse one explicitly authorized PDF accommodation submission.

    Handwriting transcription is opt-in at this backend layer so tests and
    grading remain functional without Ollama. When enabled without an explicit
    backend, the production default is Ollama + ``gemma4:31b``. Passing a
    backend instance also enables transcription and is the intended hook for
    tests or future alternative backends.
    """
    record = record_from_pdf_accommodation(submission_path, student_id=student_id)
    return _parse_pdf_accommodation_record(
        record,
        question_ids=question_ids,
        render_dir=render_dir,
        render_dpi=render_dpi,
        min_text_chars_per_page=min_text_chars_per_page,
        pdf_options=pdf_options,
        transcribe_handwriting=transcribe_handwriting,
        transcription_backend=transcription_backend,
        transcription_options=transcription_options,
        evidence_dir=evidence_dir,
        reuse_cached_transcription=reuse_cached_transcription,
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
    transcribe_handwriting: bool = False,
    transcription_backend: Optional[TranscriptionBackend] = None,
    transcription_options: Optional[Dict[str, Any]] = None,
    evidence_dir: Optional[str] = None,
    reuse_cached_transcription: bool = True,
) -> ParsedSubmission:
    """Parse one submission.

    Normal calls accept LaTeX only. A PDF is accepted only when
    ``accommodation_mode=True``; this explicit flag prevents an invalid normal
    PDF-only submission from being silently interpreted as an accommodation.
    Handwriting transcription is available only on that explicit PDF path.
    """
    requested_path = Path(submission_path).expanduser()
    if requested_path.is_symlink():
        raise ValueError(f"Symlinked submission paths are not accepted: {requested_path}")
    path = requested_path.resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))

    transcription_requested = bool(transcribe_handwriting or transcription_backend is not None)

    if accommodation_mode:
        return parse_pdf_accommodation(
            str(path),
            question_ids,
            student_id=student_id,
            render_dir=render_dir,
            render_dpi=render_dpi,
            min_text_chars_per_page=min_text_chars_per_page,
            pdf_options=pdf_options,
            transcribe_handwriting=transcribe_handwriting,
            transcription_backend=transcription_backend,
            transcription_options=transcription_options,
            evidence_dir=evidence_dir,
            reuse_cached_transcription=reuse_cached_transcription,
        )

    if transcription_requested or transcription_options:
        raise ValueError(
            "Handwriting transcription is supported only for explicit PDF accommodations."
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

    return parse_submission_record(
        record,
        question_ids,
        compile_pdf=compile_pdf,
        compilation_dir=compilation_dir,
        compiler_options=compiler_options,
        evidence_dir=evidence_dir,
    )


def parse_submissions_folder(
    submissions_dir: str,
    question_ids: Optional[Sequence[str]] = None,
    *,
    compile_pdf: bool = True,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Dict[str, Any]] = None,
    evidence_dir: Optional[str] = None,
) -> Dict[str, ParsedSubmission]:
    """Discover and parse every normal LaTeX submission in a folder.

    PDF-only files remain intentionally excluded. Accommodations must be loaded
    explicitly through ``parse_pdf_accommodation`` or ``parse_pdf_accommodations``.
    """
    parsed: Dict[str, ParsedSubmission] = {}
    for record in discover_submissions(submissions_dir):
        parsed[record.student_id] = parse_submission_record(
            record,
            question_ids,
            compile_pdf=compile_pdf,
            compilation_dir=compilation_dir,
            compiler_options=compiler_options,
            evidence_dir=evidence_dir,
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
    transcribe_handwriting: bool = False,
    transcription_backend: Optional[TranscriptionBackend] = None,
    transcription_options: Optional[Dict[str, Any]] = None,
    evidence_dir: Optional[str] = None,
    reuse_cached_transcription: bool = True,
) -> Dict[str, ParsedSubmission]:
    """Parse an explicit ``student_id -> PDF/path`` accommodation mapping.

    One backend instance is reused across the batch so Ollama preflight/model
    loading is cached. The mapping itself is the only stored accommodation
    signal; no reason or medical/disability detail is accepted by this API.
    """
    parsed: Dict[str, ParsedSubmission] = {}
    transcription_requested = bool(transcribe_handwriting or transcription_backend is not None)
    shared_backend = transcription_backend
    if transcription_requested:
        shared_backend = _resolve_transcription_backend(
            transcription_backend,
            transcription_options,
        )
        # Options have already been consumed by the shared instance.
        transcription_options = None

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
            transcribe_handwriting=transcription_requested,
            transcription_backend=shared_backend,
            transcription_options=None,
            evidence_dir=evidence_dir,
            reuse_cached_transcription=reuse_cached_transcription,
        )
    return parsed


__all__ = [
    "parse_pdf_accommodation",
    "parse_pdf_accommodations",
    "parse_submission",
    "parse_submission_record",
    "parse_submissions_folder",
]
