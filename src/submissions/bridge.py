"""Bridge canonical v2.3.2 submissions into the existing v2.2 parsers.

The bridge is intentionally thin.  It resolves immutable canonical artifacts
through :class:`SubmissionRepository`, verifies their hashes by default, and
constructs the legacy parser inputs without allowing filenames to redefine
student identity.

No scoring behavior is changed here.  ``ParsedSubmission`` remains the
existing grading-facing object.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional, Sequence

from .domain import (
    ARTIFACT_TYPE_LATEX_PROJECT_ZIP,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_ZIP,
    Submission,
)
from .models import (
    ParsedSubmission,
    SUBMISSION_MODE_LATEX,
    SubmissionRecord,
)
from .parser import parse_pdf_accommodation, parse_submission_record
from .pdf import DEFAULT_MIN_TEXT_CHARS_PER_PAGE, DEFAULT_RENDER_DPI
from .repository import SubmissionRepository
from .latex_project import (
    LatexProjectIngestionConfig,
    parse_canonical_latex_project,
)
from .storage import persist_canonical_submission_linkage
from .routing import (
    HANDLER_LATEX_PROJECT,
    HANDLER_LEGACY_LATEX,
    HANDLER_PDF_ACCOMMODATION,
    RouteDecision,
    route_submission,
)
from .transcription import TranscriptionBackend


class CanonicalSubmissionBridgeError(ValueError):
    """Base class for canonical-to-parser bridge failures."""


class CanonicalArtifactVerificationError(CanonicalSubmissionBridgeError):
    """Raised when committed canonical bytes fail size/hash verification."""


class SubmissionHandlerUnavailableError(CanonicalSubmissionBridgeError):
    """Raised when the route is known but its handler belongs to a later release."""


class ExplicitAccommodationRequiredError(CanonicalSubmissionBridgeError):
    """Raised when PDF-only work is parsed without explicit accommodation mode."""


def _canonical_metadata(
    submission: Submission,
    decision: RouteDecision,
) -> Dict[str, Any]:
    """Return portable canonical provenance for ``ParsedSubmission.metadata``."""
    return {
        "schema_version": "1.0",
        "submission_id": submission.submission_id,
        "assessment_id": submission.assessment_id,
        "student_id": submission.student_id,
        "attempt": submission.attempt,
        "is_active_attempt": submission.is_active_attempt,
        "source_system": submission.source_system,
        "submitted_at": submission.submitted_at,
        "imported_at": submission.imported_at,
        "status": submission.status,
        "route": decision.route,
        "handler": decision.handler,
        "artifact_ids": list(decision.artifact_ids),
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "role": artifact.role,
                "artifact_type": artifact.artifact_type,
                "original_filename": artifact.original_filename,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
            }
            for artifact in submission.artifacts
        ],
        "external_refs": [
            ref.to_dict() for ref in submission.external_refs
        ],
    }


def _verify_or_raise(
    submission: Submission,
    repository: SubmissionRepository,
) -> Dict[str, Any]:
    verification = repository.verify_submission(submission)
    if verification.get("ok"):
        return verification

    failed = [
        artifact_id
        for artifact_id, result in verification.get("artifacts", {}).items()
        if not result.get("ok")
    ]
    detail = ", ".join(failed) if failed else "unknown artifact"
    raise CanonicalArtifactVerificationError(
        "Canonical submission evidence failed verification: " + detail
    )


def _artifact_of_type(
    submission: Submission,
    artifact_type: str,
):
    values = submission.artifacts_by_type(artifact_type)
    return values[0] if len(values) == 1 else None


def parse_canonical_submission(
    submission: Submission,
    repository: SubmissionRepository,
    question_ids: Optional[Sequence[str]] = None,
    *,
    decision: Optional[RouteDecision] = None,
    verify_artifacts: bool = True,
    compile_pdf: bool = True,
    compilation_dir: Optional[str] = None,
    compiler_options: Optional[Dict[str, Any]] = None,
    latex_project_root: Optional[str] = None,
    latex_project_config: Optional[LatexProjectIngestionConfig] = None,
    accommodation_mode: bool = False,
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
    """Parse one canonical submission through the currently installed handler.

    The canonical repository remains authoritative for original artifact bytes.
    ``evidence_dir`` is retained for compatibility with the existing v2.2
    parsed-evidence store. Canonical identity/linkage remains attached after
    the selected handler returns its grading-facing ``ParsedSubmission``.
    """
    if not isinstance(submission, Submission):
        raise TypeError("submission must be Submission")
    if not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be SubmissionRepository")
    if not isinstance(verify_artifacts, bool):
        raise TypeError("verify_artifacts must be a bool")
    if not isinstance(accommodation_mode, bool):
        raise TypeError("accommodation_mode must be a bool")

    expected_route = route_submission(submission)
    if decision is None:
        route = expected_route
    else:
        if not isinstance(decision, RouteDecision):
            raise TypeError("decision must be RouteDecision or None")
        route = decision
        if (
            route.route != expected_route.route
            or route.handler != expected_route.handler
            or route.supported != expected_route.supported
            or route.artifact_ids != expected_route.artifact_ids
            or route.requires_explicit_accommodation
            != expected_route.requires_explicit_accommodation
        ):
            raise CanonicalSubmissionBridgeError(
                "RouteDecision does not match the current canonical submission"
            )

    if verify_artifacts:
        verification = _verify_or_raise(submission, repository)
    else:
        verification = {
            "submission_id": submission.submission_id,
            "ok": None,
            "performed": False,
        }

    if not route.supported:
        raise SubmissionHandlerUnavailableError(
            "No installed parser handler for canonical route "
            f"{route.route!r}: {route.reason or 'unsupported'}"
        )

    if route.handler == HANDLER_LEGACY_LATEX:
        tex_artifact = _artifact_of_type(submission, ARTIFACT_TYPE_TEX)
        if tex_artifact is None:
            raise CanonicalSubmissionBridgeError(
                "LaTeX route requires exactly one canonical .tex artifact"
            )

        files = {
            "latex": repository.artifact_path(
                submission,
                tex_artifact,
            )
        }

        pdf_artifact = _artifact_of_type(submission, ARTIFACT_TYPE_PDF)
        if pdf_artifact is not None:
            files["pdf"] = repository.artifact_path(
                submission,
                pdf_artifact,
            )

        record = SubmissionRecord(
            student_id=submission.student_id,
            files=files,
            warnings=[],
            submission_root=repository.submission_directory(submission),
            submission_mode=SUBMISSION_MODE_LATEX,
            accommodation_mode=False,
        )

        parsed = parse_submission_record(
            record,
            question_ids,
            compile_pdf=compile_pdf,
            compilation_dir=compilation_dir,
            compiler_options=compiler_options,
            evidence_dir=evidence_dir,
        )

    elif route.handler == HANDLER_LATEX_PROJECT:
        if not compile_pdf:
            raise CanonicalSubmissionBridgeError(
                "LaTeX-project Written parsing requires compile_pdf=True so "
                "the project can produce the visual grading PDF."
            )

        zip_artifacts = [
            artifact
            for artifact in submission.artifacts
            if artifact.artifact_type
            in {ARTIFACT_TYPE_ZIP, ARTIFACT_TYPE_LATEX_PROJECT_ZIP}
        ]
        if len(zip_artifacts) != 1:
            raise CanonicalSubmissionBridgeError(
                "LaTeX-project route requires exactly one canonical ZIP artifact"
            )

        pdf_artifact = _artifact_of_type(submission, ARTIFACT_TYPE_PDF)
        parsed = parse_canonical_latex_project(
            submission,
            repository,
            zip_artifacts[0],
            question_ids,
            reference_pdf_artifact=pdf_artifact,
            root_relative_path=latex_project_root,
            config=latex_project_config,
            compilation_dir=compilation_dir,
            compiler_options=compiler_options,
            pdf_options=pdf_options,
            min_text_chars_per_page=min_text_chars_per_page,
            evidence_dir=evidence_dir,
        )

    elif route.handler == HANDLER_PDF_ACCOMMODATION:
        if route.requires_explicit_accommodation and not accommodation_mode:
            raise ExplicitAccommodationRequiredError(
                "PDF-only canonical submissions require "
                "accommodation_mode=True; normal written submissions "
                "continue to require canonical LaTeX source."
            )

        pdf_artifact = _artifact_of_type(submission, ARTIFACT_TYPE_PDF)
        if pdf_artifact is None:
            raise CanonicalSubmissionBridgeError(
                "PDF route requires exactly one canonical PDF artifact"
            )

        parsed = parse_pdf_accommodation(
            repository.artifact_path(
                submission,
                pdf_artifact,
            ),
            question_ids,
            student_id=submission.student_id,
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

    else:
        raise SubmissionHandlerUnavailableError(
            f"Handler {route.handler!r} is not installed in the canonical bridge"
        )

    parsed.metadata = deepcopy(parsed.metadata)
    parsed.metadata["canonical_submission"] = _canonical_metadata(
        submission,
        route,
    )
    parsed.metadata["canonical_verification"] = deepcopy(verification)

    if evidence_dir is not None:
        # The underlying v2.2 parser persists evidence before this bridge adds
        # canonical identity.  Patch only the persisted metadata linkage so a
        # later load_persisted_submission() can recover submission_id/attempt
        # without re-running parsing or modifying original evidence bytes.
        persist_canonical_submission_linkage(parsed, evidence_dir)

    return parsed


__all__ = [
    "CanonicalArtifactVerificationError",
    "CanonicalSubmissionBridgeError",
    "ExplicitAccommodationRequiredError",
    "SubmissionHandlerUnavailableError",
    "parse_canonical_submission",
]
