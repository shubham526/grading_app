"""Deterministic root-document resolution for discovered LaTeX projects."""

from pathlib import PurePosixPath

from .config import LatexProjectIngestionConfig
from .discovery import LatexProjectDiscovery
from .models import (
    DIAGNOSTIC_BLOCKING,
    DIAGNOSTIC_INFO,
    ROOT_METHOD_INSTRUCTOR_SELECTED,
    ROOT_METHOD_NONE,
    ROOT_METHOD_UNIQUE_DOCUMENT,
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_INVALID_PROJECT,
    ROOT_RESOLUTION_NO_ROOT_FOUND,
    ROOT_RESOLUTION_RESOLVED,
    LatexProjectDiagnostic,
    LatexProjectResolution,
    normalize_project_relative_path,
)


def _preferred_hints(candidates, preferred_names):
    """Return preferred-name matches as UI hints, never as auto-selection."""
    matches = []
    seen = set()
    for preferred in preferred_names:
        for path in candidates:
            if PurePosixPath(path).name.casefold() == preferred.casefold():
                if path not in seen:
                    seen.add(path)
                    matches.append(path)
    return tuple(matches)


def resolve_latex_project_root(discovery, config=None):
    """Return a deterministic root resolution without guessing.

    Resolution policy:
    1. no readable TeX sources -> invalid project;
    2. exactly one complete document -> resolve it;
    3. multiple complete documents -> ambiguous/instructor selection;
    4. TeX sources but no complete document -> no root found.

    Preferred root names are retained only as presentation hints.  A filename
    such as ``main.tex`` never overrides genuine structural ambiguity.
    """
    if not isinstance(discovery, LatexProjectDiscovery):
        raise TypeError("discovery must be LatexProjectDiscovery")
    if config is None:
        config = LatexProjectIngestionConfig()
    elif not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig")

    candidates = tuple(discovery.document_candidate_paths)
    common_metadata = {
        "project_id": discovery.project_id,
        "tex_source_count": len(discovery.tex_sources),
        "document_candidate_count": len(candidates),
    }

    if not discovery.tex_sources:
        diagnostic = LatexProjectDiagnostic(
            code="invalid_project_no_readable_tex",
            message="Project has no readable LaTeX source files",
            severity=DIAGNOSTIC_BLOCKING,
        )
        return LatexProjectResolution(
            status=ROOT_RESOLUTION_INVALID_PROJECT,
            candidate_paths=(),
            resolution_method=ROOT_METHOD_NONE,
            diagnostics=tuple(discovery.diagnostics) + (diagnostic,),
            metadata=common_metadata,
        )

    if len(candidates) == 1:
        return LatexProjectResolution(
            status=ROOT_RESOLUTION_RESOLVED,
            root_relative_path=candidates[0],
            candidate_paths=candidates,
            resolution_method=ROOT_METHOD_UNIQUE_DOCUMENT,
            diagnostics=tuple(discovery.diagnostics),
            metadata=common_metadata,
        )

    if len(candidates) > 1:
        preferred_hints = _preferred_hints(candidates, config.preferred_root_names)
        diagnostic = LatexProjectDiagnostic(
            code="ambiguous_root_documents",
            message=(
                "Multiple complete LaTeX root documents were found; instructor "
                "selection is required"
            ),
            severity=DIAGNOSTIC_BLOCKING,
            metadata={
                "candidate_paths": list(candidates),
                "preferred_name_hints": list(preferred_hints),
            },
        )
        metadata = dict(common_metadata)
        metadata["preferred_name_hints"] = list(preferred_hints)
        return LatexProjectResolution(
            status=ROOT_RESOLUTION_AMBIGUOUS,
            candidate_paths=candidates,
            resolution_method=ROOT_METHOD_NONE,
            diagnostics=tuple(discovery.diagnostics) + (diagnostic,),
            metadata=metadata,
        )

    diagnostic = LatexProjectDiagnostic(
        code="no_complete_root_document",
        message=(
            "LaTeX sources were found, but none contains both a document class "
            "and a document body marker"
        ),
        severity=DIAGNOSTIC_BLOCKING,
    )
    return LatexProjectResolution(
        status=ROOT_RESOLUTION_NO_ROOT_FOUND,
        candidate_paths=(),
        resolution_method=ROOT_METHOD_NONE,
        diagnostics=tuple(discovery.diagnostics) + (diagnostic,),
        metadata=common_metadata,
    )


def select_latex_project_root(discovery, relative_path):
    """Resolve an ambiguous discovery by explicit instructor selection.

    Selection is intentionally restricted to deterministic document candidates.
    A no-root project remains blocking in v2.3.4.2 rather than allowing an
    arbitrary source file to be promoted silently.
    """
    if not isinstance(discovery, LatexProjectDiscovery):
        raise TypeError("discovery must be LatexProjectDiscovery")
    selected = normalize_project_relative_path(relative_path, "relative_path")
    candidates = tuple(discovery.document_candidate_paths)
    if selected not in candidates:
        raise ValueError("selected root must be one of the discovered document candidates")
    if len(candidates) < 2:
        raise ValueError("instructor root selection is only valid for ambiguous projects")

    diagnostic = LatexProjectDiagnostic(
        code="root_selected_by_instructor",
        message="Instructor selected the LaTeX project root document",
        severity=DIAGNOSTIC_INFO,
        relative_path=selected,
    )
    return LatexProjectResolution(
        status=ROOT_RESOLUTION_RESOLVED,
        root_relative_path=selected,
        candidate_paths=candidates,
        resolution_method=ROOT_METHOD_INSTRUCTOR_SELECTED,
        diagnostics=tuple(discovery.diagnostics) + (diagnostic,),
        metadata={
            "project_id": discovery.project_id,
            "tex_source_count": len(discovery.tex_sources),
            "document_candidate_count": len(candidates),
        },
    )


__all__ = [
    "resolve_latex_project_root",
    "select_latex_project_root",
]
