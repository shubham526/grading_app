"""Bridge canonical LaTeX-project ZIPs into the existing Written grader.

The canonical ZIP remains the authoritative submitted source.  This module
materializes a verified project beneath the canonical submission's ``derived``
directory, resolves the root document, compiles the complete project with the
existing LaTeX compiler, and exposes the compiled PDF through the same
``ParsedSubmission.files['compiled_pdf']`` contract used by single-file LaTeX
submissions.

It does not implement TeX composition, grading logic, or UI behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional, Sequence

from ..domain import ArtifactFile, Submission
from ..models import CompilationResult, ParsedSubmission, SOURCE_LATEX, SUBMISSION_MODE_LATEX
from ..pdf import (
    DEFAULT_MAX_PDF_BYTES,
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    extract_text_from_pdf,
)
from ..repository import DERIVED_DIRNAME, SubmissionRepository
from ..splitter import FULL_SUBMISSION, split_answers_by_question
from ..storage import persist_submission_evidence
from .compilation import LatexProjectCompilation, compile_stored_latex_project_to_pdf
from .config import LatexProjectIngestionConfig
from .discovery import LatexProjectDiscovery, discover_latex_project
from .errors import LatexProjectIntegrityError, LatexProjectValidationError
from .models import (
    DIAGNOSTIC_INFO,
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_RESOLVED,
    LatexProjectResolution,
)
from .resolution import resolve_latex_project_root, select_latex_project_root
from .provenance import (
    LatexProjectProvenanceState,
    append_compilation_attempt,
    load_latex_project_provenance,
    provenance_diagnostic_payload,
    provenance_path,
    reusable_compiled_pdf,
    save_latex_project_provenance,
    state_with_resolution,
)
from .storage import LatexProjectArchiveStore, StoredLatexProject


LATEX_PROJECT_DERIVED_DIRNAME = "latex_project"
LATEX_PROJECT_COMPILED_DIRNAME = "compiled"


class LatexProjectWrittenBridgeError(ValueError):
    """Base class for canonical LaTeX-project Written-bridge failures."""


class LatexProjectRootResolutionRequiredError(LatexProjectWrittenBridgeError):
    """Raised when a project cannot be compiled without an instructor choice."""

    def __init__(self, message: str, resolution: LatexProjectResolution) -> None:
        super().__init__(message)
        self.resolution = resolution


class LatexProjectCompilationFailedError(LatexProjectWrittenBridgeError):
    """Raised when the real LaTeX compiler does not produce a usable PDF."""

    def __init__(self, message: str, result: LatexProjectCompilation) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class LatexProjectPreparedContext:
    """Verified project state used to produce a Written ``ParsedSubmission``."""

    stored: StoredLatexProject
    discovery: LatexProjectDiscovery
    resolution: LatexProjectResolution
    compilation: LatexProjectCompilation
    provenance: LatexProjectProvenanceState


def _stable_project_id(submission: Submission, zip_artifact: ArtifactFile) -> str:
    payload = "%s\0%s\0%s" % (
        submission.submission_id,
        zip_artifact.artifact_id,
        zip_artifact.sha256,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return "lproj_%s" % digest


def _project_store_root(
    submission: Submission,
    repository: SubmissionRepository,
) -> Path:
    submission_dir = Path(repository.submission_directory(submission))
    root = submission_dir / DERIVED_DIRNAME / LATEX_PROJECT_DERIVED_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_or_ingest_project(
    submission: Submission,
    repository: SubmissionRepository,
    zip_artifact: ArtifactFile,
    config: LatexProjectIngestionConfig,
) -> StoredLatexProject:
    canonical_zip = repository.artifact_path(submission, zip_artifact)
    store = LatexProjectArchiveStore(str(_project_store_root(submission, repository)))
    project_id = _stable_project_id(submission, zip_artifact)
    project_dir = store.project_dir(project_id)

    if project_dir.exists() or project_dir.is_symlink():
        stored = store.load(project_id, verify=True)
    else:
        stored = store.ingest_zip(
            canonical_zip,
            source_artifact_id=zip_artifact.artifact_id,
            config=config,
            project_id=project_id,
            imported_at=submission.imported_at,
        )

    if stored.archive.source_artifact_id != zip_artifact.artifact_id:
        raise LatexProjectIntegrityError(
            "Stored LaTeX project belongs to a different canonical source artifact"
        )
    if stored.archive.archive_sha256 != zip_artifact.sha256:
        raise LatexProjectIntegrityError(
            "Stored LaTeX project ZIP digest does not match canonical artifact"
        )
    return stored


def _resolve_root(
    discovery: LatexProjectDiscovery,
    config: LatexProjectIngestionConfig,
    root_relative_path: Optional[str],
) -> LatexProjectResolution:
    resolution = resolve_latex_project_root(discovery, config=config)

    if root_relative_path is not None:
        requested = str(root_relative_path).strip()
        if not requested:
            raise ValueError("root_relative_path must not be empty")
        if resolution.status == ROOT_RESOLUTION_AMBIGUOUS:
            return select_latex_project_root(discovery, requested)
        if resolution.status == ROOT_RESOLUTION_RESOLVED:
            if requested != resolution.root_relative_path:
                raise ValueError(
                    "Explicit root does not match the project's deterministic root"
                )
            return resolution

    if resolution.status != ROOT_RESOLUTION_RESOLVED:
        detail = resolution.status
        if resolution.candidate_paths:
            detail += ": " + ", ".join(resolution.candidate_paths)
        raise LatexProjectRootResolutionRequiredError(
            "LaTeX project root is not resolved (%s)" % detail,
            resolution,
        )
    return resolution


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compiler_kwargs(options: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    values = dict(options or {})
    allowed = {
        "engine",
        "passes",
        "timeout_seconds",
        "max_pdf_bytes",
        "max_log_chars",
    }
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(
            "Unsupported LaTeX-project compiler option(s): %s"
            % ", ".join(unknown)
        )
    return values


def _effective_compiler_options(options: Mapping[str, Any]) -> Dict[str, Any]:
    effective: Dict[str, Any] = {
        "engine": "pdflatex",
        "passes": 1,
        "timeout_seconds": 30.0,
        "max_pdf_bytes": 100 * 1024 * 1024,
        "max_log_chars": 200_000,
    }
    effective.update(dict(options))
    return effective


def _restored_compilation(
    stored: StoredLatexProject,
    resolution: LatexProjectResolution,
    state: LatexProjectProvenanceState,
    pdf_path: str,
) -> LatexProjectCompilation:
    latest = state.latest_attempt
    if latest is None or not latest.success:
        raise LatexProjectIntegrityError("Persisted compiled state has no successful attempt")
    root_path = Path(stored.extracted_root).joinpath(
        *PurePosixPath(str(resolution.root_relative_path)).parts
    )
    result = CompilationResult(
        success=True,
        source_path=str(root_path.resolve()),
        engine=latest.engine,
        pdf_path=str(Path(pdf_path).resolve()),
        passes_completed=latest.passes_completed,
        duration_seconds=latest.duration_seconds,
        warnings=list(latest.warnings),
    )
    return LatexProjectCompilation(
        project_id=stored.project_id,
        root_relative_path=str(resolution.root_relative_path),
        resolution_method=str(resolution.resolution_method),
        archive_sha256=stored.archive.archive_sha256,
        manifest_sha256=str(stored.manifest.manifest_sha256),
        source_file_count=len(stored.manifest.files),
        source_total_bytes=stored.manifest.total_uncompressed_bytes,
        compilation=result,
    )


def prepare_canonical_latex_project(
    submission: Submission,
    repository: SubmissionRepository,
    zip_artifact: ArtifactFile,
    *,
    root_relative_path: Optional[str] = None,
    config: Optional[LatexProjectIngestionConfig] = None,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Mapping[str, Any]] = None,
    force_recompile: bool = False,
    reuse_persisted_compilation: bool = True,
) -> LatexProjectPreparedContext:
    """Verify, resolve, and compile one canonical LaTeX-project ZIP."""
    if not isinstance(submission, Submission):
        raise TypeError("submission must be Submission")
    if not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be SubmissionRepository")
    if not isinstance(zip_artifact, ArtifactFile):
        raise TypeError("zip_artifact must be ArtifactFile")
    if zip_artifact.submission_id != submission.submission_id:
        raise ValueError("zip_artifact does not belong to submission")
    if config is None:
        config = LatexProjectIngestionConfig()
    elif not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig")

    if not isinstance(force_recompile, bool):
        raise TypeError("force_recompile must be bool")
    if not isinstance(reuse_persisted_compilation, bool):
        raise TypeError("reuse_persisted_compilation must be bool")

    stored = _load_or_ingest_project(
        submission,
        repository,
        zip_artifact,
        config,
    )
    discovery = discover_latex_project(
        stored.extracted_root,
        stored.manifest,
        config=config,
    )
    previous_state = load_latex_project_provenance(stored)
    if (
        previous_state is not None
        and previous_state.submission_id != submission.submission_id
    ):
        raise LatexProjectIntegrityError(
            "Persisted provenance belongs to another canonical submission"
        )
    effective_root = root_relative_path
    if effective_root is None and previous_state is not None:
        effective_root = previous_state.root_relative_path
    if effective_root is None:
        effective_root = str(submission.metadata.get("latex_project_root") or "").strip() or None

    resolution = _resolve_root(discovery, config, effective_root)
    state = state_with_resolution(
        stored,
        submission_id=submission.submission_id,
        resolution=resolution,
        previous=previous_state,
    )
    save_latex_project_provenance(stored, state)

    kwargs = _compiler_kwargs(compiler_options)
    effective_options = _effective_compiler_options(kwargs)
    if reuse_persisted_compilation and not force_recompile:
        reusable_pdf = reusable_compiled_pdf(
            stored,
            state,
            root_relative_path=str(resolution.root_relative_path),
            compiler_options=effective_options,
        )
        if reusable_pdf is not None:
            return LatexProjectPreparedContext(
                stored=stored,
                discovery=discovery,
                resolution=resolution,
                compilation=_restored_compilation(
                    stored,
                    resolution,
                    state,
                    reusable_pdf,
                ),
                provenance=state,
            )

    if compilation_dir is None:
        output_dir = str(
            Path(stored.project_dir) / LATEX_PROJECT_COMPILED_DIRNAME
        )
    else:
        output_dir = str(
            Path(compilation_dir).expanduser().resolve()
            / submission.student_id
            / LATEX_PROJECT_DERIVED_DIRNAME
        )

    started_at = _utc_now_iso()
    compilation = compile_stored_latex_project_to_pdf(
        stored,
        resolution,
        output_dir=output_dir,
        config=config,
        **kwargs,
    )
    state = append_compilation_attempt(
        stored,
        state,
        compilation.compilation,
        compiler_options=effective_options,
        started_at=started_at,
        completed_at=_utc_now_iso(),
    )
    save_latex_project_provenance(stored, state)

    if not compilation.success or not compilation.pdf_path:
        result = compilation.compilation
        reason = result.error_code or "latex_compilation_failed"
        message = result.error_message or reason
        raise LatexProjectCompilationFailedError(
            "LaTeX project compilation failed (%s): %s" % (reason, message),
            compilation,
        )

    return LatexProjectPreparedContext(
        stored=stored,
        discovery=discovery,
        resolution=resolution,
        compilation=compilation,
        provenance=state,
    )


def _split_status(answers: Dict[str, str], warnings: Sequence[str]) -> str:
    if FULL_SUBMISSION in answers:
        return "unsplit"
    if any(value.startswith("missing_answer_for_") for value in warnings):
        return "partial"
    return "success"


def _diagnostic_codes(discovery: LatexProjectDiscovery) -> list[str]:
    values = []
    for diagnostic in discovery.diagnostics:
        if diagnostic.severity == DIAGNOSTIC_INFO:
            continue
        if diagnostic.code not in values:
            values.append(diagnostic.code)
    return values


def parse_canonical_latex_project(
    submission: Submission,
    repository: SubmissionRepository,
    zip_artifact: ArtifactFile,
    question_ids: Optional[Sequence[str]] = None,
    *,
    reference_pdf_artifact: Optional[ArtifactFile] = None,
    root_relative_path: Optional[str] = None,
    config: Optional[LatexProjectIngestionConfig] = None,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Mapping[str, Any]] = None,
    pdf_options: Optional[Mapping[str, Any]] = None,
    min_text_chars_per_page: int = DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    evidence_dir: Optional[str] = None,
    force_recompile: bool = False,
) -> ParsedSubmission:
    """Compile and adapt one canonical LaTeX project for Written grading.

    Text/question extraction uses selectable text from the app-compiled PDF.
    This avoids reimplementing multi-file TeX semantics while preserving the
    existing Written ``ParsedSubmission`` contract and visual PDF viewer path.
    """
    context = prepare_canonical_latex_project(
        submission,
        repository,
        zip_artifact,
        root_relative_path=root_relative_path,
        config=config,
        compilation_dir=compilation_dir,
        compiler_options=compiler_options,
        force_recompile=force_recompile,
    )

    compiled_pdf = str(context.compilation.pdf_path)
    options = dict(pdf_options or {})
    allowed_pdf_options = {"max_pdf_bytes", "max_pages"}
    unknown_pdf = sorted(set(options) - allowed_pdf_options)
    if unknown_pdf:
        raise ValueError(
            "Unsupported LaTeX-project PDF extraction option(s): %s"
            % ", ".join(unknown_pdf)
        )
    options.setdefault("max_pdf_bytes", DEFAULT_MAX_PDF_BYTES)
    options.setdefault("max_pages", DEFAULT_MAX_PDF_PAGES)
    text, extraction = extract_text_from_pdf(
        compiled_pdf,
        min_chars_per_page=min_text_chars_per_page,
        **options,
    )
    answers, split_warnings = split_answers_by_question(text, question_ids)

    root_relative = str(context.resolution.root_relative_path)
    root_path = Path(context.stored.extracted_root).joinpath(
        *PurePosixPath(root_relative).parts
    )
    files: Dict[str, str] = {
        "latex": str(root_path.resolve()),
        "latex_project_zip": repository.artifact_path(submission, zip_artifact),
        "compiled_pdf": compiled_pdf,
    }
    if reference_pdf_artifact is not None:
        if reference_pdf_artifact.submission_id != submission.submission_id:
            raise ValueError("reference_pdf_artifact does not belong to submission")
        files["pdf"] = repository.artifact_path(
            submission,
            reference_pdf_artifact,
        )

    warnings = []
    warnings.extend(_diagnostic_codes(context.discovery))
    warnings.extend(str(value) for value in extraction.get("warnings", []) or [])
    warnings.extend(str(value) for value in split_warnings)

    metadata: Dict[str, Any] = {
        "source_priority": ["latex_project", "compiled_pdf"],
        "canonical_source": "latex_project",
        "authoritative_source": "latex_project_zip",
        "assistive_text_source": "compiled_pdf_selectable_text",
        "text_length": len(text),
        "question_ids_detected": [
            qid for qid in answers if qid != FULL_SUBMISSION
        ],
        "question_split_status": _split_status(answers, split_warnings),
        "extraction": extraction,
        "compilation": context.compilation.compilation.to_metadata(
            include_logs=False
        ),
        "latex_project": {
            "project_id": context.stored.project_id,
            "archive_sha256": context.stored.archive.archive_sha256,
            "manifest_sha256": context.stored.manifest.manifest_sha256,
            "root_relative_path": root_relative,
            "root_resolution_method": context.resolution.resolution_method,
            "candidate_paths": list(context.resolution.candidate_paths),
            "tex_source_count": len(context.discovery.tex_sources),
            "source_file_count": context.compilation.source_file_count,
            "source_total_bytes": context.compilation.source_total_bytes,
            "diagnostics": [
                item.to_dict()
                for item in context.resolution.diagnostics
            ],
            "provenance_state_path": str(provenance_path(context.stored).resolve()),
            "compilation_attempt_count": len(context.provenance.compilation_attempts),
            "compiled_pdf_sha256": (
                context.provenance.latest_attempt.compiled_pdf_sha256
                if context.provenance.latest_attempt is not None
                else None
            ),
        },
    }

    parsed = ParsedSubmission(
        student_id=submission.student_id,
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


def canonical_latex_project_diagnostic(
    submission: Submission,
    repository: SubmissionRepository,
    zip_artifact: ArtifactFile,
    *,
    error: Optional[BaseException] = None,
    candidate_paths: Sequence[str] = (),
    root_relative_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a structured instructor-facing status for one canonical project."""
    project_id = _stable_project_id(submission, zip_artifact)
    store = LatexProjectArchiveStore(str(_project_store_root(submission, repository)))
    project_dir = store.project_dir(project_id)
    stored = None
    state = None
    if project_dir.exists() and not project_dir.is_symlink():
        try:
            stored = store.load(project_id, verify=False)
            state = load_latex_project_provenance(stored)
        except Exception:
            stored = None
            state = None
    payload = provenance_diagnostic_payload(
        stored,
        state,
        error=error,
        project_dir=str(project_dir),
        candidate_paths=candidate_paths,
        root_relative_path=root_relative_path,
    )
    if isinstance(error, LatexProjectRootResolutionRequiredError):
        payload["status"] = error.resolution.status
        payload["candidate_paths"] = list(error.resolution.candidate_paths)
        payload["recoverable"] = True
    return payload


__all__ = [
    "LATEX_PROJECT_COMPILED_DIRNAME",
    "LATEX_PROJECT_DERIVED_DIRNAME",
    "LatexProjectCompilationFailedError",
    "LatexProjectPreparedContext",
    "LatexProjectRootResolutionRequiredError",
    "LatexProjectWrittenBridgeError",
    "canonical_latex_project_diagnostic",
    "parse_canonical_latex_project",
    "prepare_canonical_latex_project",
]
