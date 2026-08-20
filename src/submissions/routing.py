"""Canonical submission artifact routing for v2.3.2 Commit 4.

Routing classifies a committed :class:`Submission` by artifact structure and
selects the downstream handler family.  It deliberately does not parse,
execute, or mutate submission evidence.

The initial v2.3.2 bridge supports only the already-existing v2.2 written
handlers:

* one LaTeX source, optionally accompanied by one rendered/reference PDF;
* one PDF when the caller explicitly authorizes the existing accommodation
  pathway.

Programming submissions are now handled by the v2.3.3 autograding planner.
LaTeX-project ZIP routes remain recognized for v2.3.4 without changing
canonical storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .domain import (
    ARTIFACT_TYPE_LATEX_PROJECT_ZIP,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_ZIP,
    Submission,
)


ROUTE_LATEX_SINGLE_SOURCE = "latex_single_source"
ROUTE_WRITTEN_PDF = "written_pdf"
ROUTE_PROGRAMMING_PYTHON = "programming_python"
ROUTE_LATEX_PROJECT = "latex_project"
ROUTE_MIXED = "mixed"
ROUTE_UNSUPPORTED = "unsupported"

HANDLER_LEGACY_LATEX = "legacy_latex"
HANDLER_PDF_ACCOMMODATION = "pdf_accommodation"
HANDLER_PROGRAMMING = "programming_autograder"
HANDLER_LATEX_PROJECT = "latex_project_ingestion"
HANDLER_NONE = "none"

REASON_NO_ARTIFACTS = "no_artifacts"
REASON_MULTIPLE_LATEX_SOURCES = "multiple_latex_sources"
REASON_MULTIPLE_PDFS = "multiple_pdfs"
REASON_MIXED_ARTIFACTS = "unsupported_mixed_artifacts"
REASON_UNSUPPORTED_ARTIFACTS = "unsupported_artifacts"
REASON_PROGRAMMING_HANDLER_PENDING = "handler_not_available_until_v2.3.3"  # legacy diagnostic constant
REASON_LATEX_PROJECT_HANDLER_PENDING = "handler_not_available_until_v2.3.4"


@dataclass(frozen=True)
class RouteDecision:
    """Result of classifying one canonical submission."""

    route: str
    handler: str
    supported: bool
    artifact_ids: Tuple[str, ...]
    reason: Optional[str] = None
    requires_explicit_accommodation: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_ids",
            tuple(str(value) for value in self.artifact_ids),
        )
        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly diagnostic representation."""
        return {
            "route": self.route,
            "handler": self.handler,
            "supported": self.supported,
            "artifact_ids": list(self.artifact_ids),
            "reason": self.reason,
            "requires_explicit_accommodation": (
                self.requires_explicit_accommodation
            ),
            "metadata": dict(self.metadata),
        }


def _decision(
    *,
    route: str,
    handler: str,
    supported: bool,
    artifact_ids: Tuple[str, ...],
    reason: Optional[str] = None,
    requires_explicit_accommodation: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> RouteDecision:
    return RouteDecision(
        route=route,
        handler=handler,
        supported=supported,
        artifact_ids=artifact_ids,
        reason=reason,
        requires_explicit_accommodation=requires_explicit_accommodation,
        metadata=dict(metadata or {}),
    )


def route_submission(submission: Submission) -> RouteDecision:
    """Classify a canonical submission for downstream handling.

    ``supported`` answers whether the handler exists in the current codebase.
    A PDF-only route is therefore supported but carries
    ``requires_explicit_accommodation=True`` because the existing v2.2 parser
    intentionally accepts PDF-only work only through that explicit pathway.
    """
    if not isinstance(submission, Submission):
        raise TypeError("submission must be Submission")

    artifacts = list(submission.artifacts)
    if not artifacts:
        return _decision(
            route=ROUTE_UNSUPPORTED,
            handler=HANDLER_NONE,
            supported=False,
            artifact_ids=(),
            reason=REASON_NO_ARTIFACTS,
        )

    tex = [a for a in artifacts if a.artifact_type == ARTIFACT_TYPE_TEX]
    pdf = [a for a in artifacts if a.artifact_type == ARTIFACT_TYPE_PDF]
    python = [a for a in artifacts if a.artifact_type == ARTIFACT_TYPE_PYTHON]
    project_zip = [
        a
        for a in artifacts
        if a.artifact_type
        in {ARTIFACT_TYPE_ZIP, ARTIFACT_TYPE_LATEX_PROJECT_ZIP}
    ]

    recognized_ids = {
        a.artifact_id for a in tex + pdf + python + project_zip
    }
    other = [a for a in artifacts if a.artifact_id not in recognized_ids]

    # A ZIP paired with a rendered PDF is the v2.3.4 Overleaf/LaTeX-project
    # shape.  A ZIP alone is also routed there so the future project validator
    # can provide the correct missing-PDF/main.tex diagnostics.
    if project_zip and not tex and not python and not other:
        if len(pdf) <= 1:
            selected = tuple(
                a.artifact_id for a in project_zip + pdf
            )
            return _decision(
                route=ROUTE_LATEX_PROJECT,
                handler=HANDLER_LATEX_PROJECT,
                supported=False,
                artifact_ids=selected,
                reason=REASON_LATEX_PROJECT_HANDLER_PENDING,
                metadata={
                    "zip_count": len(project_zip),
                    "pdf_count": len(pdf),
                },
            )
        return _decision(
            route=ROUTE_MIXED,
            handler=HANDLER_NONE,
            supported=False,
            artifact_ids=tuple(a.artifact_id for a in artifacts),
            reason=REASON_MULTIPLE_PDFS,
        )

    # Pure Python/multi-file Python is handled by the v2.3.3 autograding
    # planner.  The router only classifies the immutable canonical artifact
    # structure; planning validates the assignment's entrypoint/required-file
    # contract and execution still belongs to later v2.3.3 commits.
    # Supporting non-Python files remain MIXED until a future programming
    # submission contract explicitly admits them.
    if python and not tex and not pdf and not project_zip and not other:
        return _decision(
            route=ROUTE_PROGRAMMING_PYTHON,
            handler=HANDLER_PROGRAMMING,
            supported=True,
            artifact_ids=tuple(a.artifact_id for a in python),
            metadata={
                "python_file_count": len(python),
                "handler_available_since": "2.3.3",
            },
        )

    # Existing v2.2 normal submissions have exactly one canonical LaTeX source
    # and may include at most one optional PDF reference.
    if tex:
        if len(tex) != 1:
            return _decision(
                route=ROUTE_MIXED,
                handler=HANDLER_NONE,
                supported=False,
                artifact_ids=tuple(a.artifact_id for a in artifacts),
                reason=REASON_MULTIPLE_LATEX_SOURCES,
            )
        if len(pdf) > 1:
            return _decision(
                route=ROUTE_MIXED,
                handler=HANDLER_NONE,
                supported=False,
                artifact_ids=tuple(a.artifact_id for a in artifacts),
                reason=REASON_MULTIPLE_PDFS,
            )
        if python or project_zip or other:
            return _decision(
                route=ROUTE_MIXED,
                handler=HANDLER_NONE,
                supported=False,
                artifact_ids=tuple(a.artifact_id for a in artifacts),
                reason=REASON_MIXED_ARTIFACTS,
            )

        selected = tuple(a.artifact_id for a in tex + pdf)
        return _decision(
            route=ROUTE_LATEX_SINGLE_SOURCE,
            handler=HANDLER_LEGACY_LATEX,
            supported=True,
            artifact_ids=selected,
            metadata={
                "tex_artifact_id": tex[0].artifact_id,
                "pdf_artifact_id": pdf[0].artifact_id if pdf else None,
            },
        )

    # PDF-only work is intentionally gated by the existing explicit
    # accommodation flag in the bridge/parser.
    if pdf and not python and not project_zip and not other:
        if len(pdf) != 1:
            return _decision(
                route=ROUTE_MIXED,
                handler=HANDLER_NONE,
                supported=False,
                artifact_ids=tuple(a.artifact_id for a in artifacts),
                reason=REASON_MULTIPLE_PDFS,
            )
        return _decision(
            route=ROUTE_WRITTEN_PDF,
            handler=HANDLER_PDF_ACCOMMODATION,
            supported=True,
            artifact_ids=(pdf[0].artifact_id,),
            requires_explicit_accommodation=True,
            metadata={"pdf_artifact_id": pdf[0].artifact_id},
        )

    if len({a.artifact_type for a in artifacts}) > 1:
        return _decision(
            route=ROUTE_MIXED,
            handler=HANDLER_NONE,
            supported=False,
            artifact_ids=tuple(a.artifact_id for a in artifacts),
            reason=REASON_MIXED_ARTIFACTS,
        )

    return _decision(
        route=ROUTE_UNSUPPORTED,
        handler=HANDLER_NONE,
        supported=False,
        artifact_ids=tuple(a.artifact_id for a in artifacts),
        reason=REASON_UNSUPPORTED_ARTIFACTS,
        metadata={
            "artifact_types": sorted(
                {a.artifact_type for a in artifacts}
            )
        },
    )


__all__ = [
    "HANDLER_LATEX_PROJECT",
    "HANDLER_LEGACY_LATEX",
    "HANDLER_NONE",
    "HANDLER_PDF_ACCOMMODATION",
    "HANDLER_PROGRAMMING",
    "REASON_LATEX_PROJECT_HANDLER_PENDING",
    "REASON_MIXED_ARTIFACTS",
    "REASON_MULTIPLE_LATEX_SOURCES",
    "REASON_MULTIPLE_PDFS",
    "REASON_NO_ARTIFACTS",
    "REASON_PROGRAMMING_HANDLER_PENDING",
    "REASON_UNSUPPORTED_ARTIFACTS",
    "ROUTE_LATEX_PROJECT",
    "ROUTE_LATEX_SINGLE_SOURCE",
    "ROUTE_MIXED",
    "ROUTE_PROGRAMMING_PYTHON",
    "ROUTE_UNSUPPORTED",
    "ROUTE_WRITTEN_PDF",
    "RouteDecision",
    "route_submission",
]
