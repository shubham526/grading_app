"""Safe import-preview support for LaTeX/Overleaf project ZIPs.

Commit 6 uses the same bounded ZIP extraction, project discovery, and root
resolution code as the canonical Written bridge, but runs it in a temporary
workspace before canonical commit.  Preview never compiles or executes TeX.

The preview metadata is attached to :class:`ImportCandidate` objects so the Qt
import dialog can surface invalid archives and request an instructor root only
when deterministic resolution is impossible.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..domain import (
    ARTIFACT_TYPE_ZIP,
    VALIDATION_STATUS_INVALID,
    ImportCandidate,
)
from .config import LatexProjectIngestionConfig
from .discovery import discover_latex_project
from .errors import LatexProjectError
from .models import (
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_INVALID_PROJECT,
    ROOT_RESOLUTION_NO_ROOT_FOUND,
    ROOT_RESOLUTION_RESOLVED,
)
from .resolution import resolve_latex_project_root
from .storage import LatexProjectArchiveStore


LATEX_PROJECT_PREVIEW_METADATA_KEY = "latex_project_preview"
LATEX_PROJECT_ROOT_METADATA_KEY = "latex_project_root"
LATEX_PROJECT_ROOT_METHOD_METADATA_KEY = "latex_project_root_selection_method"

ROOT_SELECTION_DETERMINISTIC = "deterministic"
ROOT_SELECTION_INSTRUCTOR = "instructor_selected"


@dataclass(frozen=True)
class LatexProjectImportPreview:
    """Portable result of execution-free inspection of one project archive."""

    status: str
    archive_name: str
    root_relative_path: Optional[str] = None
    candidate_paths: Tuple[str, ...] = ()
    tex_source_count: int = 0
    diagnostics: Tuple[Dict[str, Any], ...] = ()
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def requires_root_selection(self) -> bool:
        return self.status == ROOT_RESOLUTION_AMBIGUOUS

    @property
    def is_valid(self) -> bool:
        return self.status in {
            ROOT_RESOLUTION_RESOLVED,
            ROOT_RESOLUTION_AMBIGUOUS,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "archive_name": self.archive_name,
            "root_relative_path": self.root_relative_path,
            "candidate_paths": list(self.candidate_paths),
            "tex_source_count": self.tex_source_count,
            "diagnostics": [deepcopy(item) for item in self.diagnostics],
            "error_message": self.error_message,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LatexProjectImportPreview":
        if not isinstance(data, Mapping):
            raise TypeError("LaTeX-project preview data must be a mapping")
        return cls(
            status=str(data.get("status") or "").strip(),
            archive_name=str(data.get("archive_name") or "").strip(),
            root_relative_path=(
                str(data.get("root_relative_path")).strip()
                if data.get("root_relative_path")
                else None
            ),
            candidate_paths=tuple(
                str(value).strip()
                for value in (data.get("candidate_paths") or ())
                if str(value).strip()
            ),
            tex_source_count=int(data.get("tex_source_count") or 0),
            diagnostics=tuple(
                deepcopy(dict(item))
                for item in (data.get("diagnostics") or ())
                if isinstance(item, Mapping)
            ),
            error_message=(
                str(data.get("error_message")).strip()
                if data.get("error_message")
                else None
            ),
            metadata=deepcopy(dict(data.get("metadata") or {})),
        )


def _diagnostic_dicts(values: Sequence[Any]) -> Tuple[Dict[str, Any], ...]:
    result = []
    for value in values:
        if hasattr(value, "to_dict"):
            payload = value.to_dict()
        elif isinstance(value, Mapping):
            payload = dict(value)
        else:
            payload = {"message": str(value)}
        result.append(deepcopy(dict(payload)))
    return tuple(result)


def inspect_latex_project_zip(
    archive_path: str,
    *,
    config: Optional[LatexProjectIngestionConfig] = None,
) -> LatexProjectImportPreview:
    """Safely inspect one local ZIP without compiling or executing TeX."""
    if config is None:
        config = LatexProjectIngestionConfig()
    elif not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig or None")

    archive = Path(str(archive_path or "")).expanduser()
    archive_name = archive.name or "submission.zip"

    try:
        with tempfile.TemporaryDirectory(prefix="grading-latex-preview-") as tmp:
            store = LatexProjectArchiveStore(tmp)
            stored = store.ingest_zip(
                str(archive),
                source_artifact_id="import-preview",
                config=config,
            )
            discovery = discover_latex_project(
                stored.extracted_root,
                stored.manifest,
                config=config,
            )
            resolution = resolve_latex_project_root(discovery, config=config)
            return LatexProjectImportPreview(
                status=resolution.status,
                archive_name=archive_name,
                root_relative_path=resolution.root_relative_path,
                candidate_paths=tuple(resolution.candidate_paths),
                tex_source_count=len(discovery.tex_sources),
                diagnostics=_diagnostic_dicts(resolution.diagnostics),
                metadata={
                    "document_candidate_count": len(
                        discovery.document_candidate_paths
                    ),
                    "preferred_name_hints": list(
                        resolution.metadata.get("preferred_name_hints", [])
                    ),
                },
            )
    except (LatexProjectError, FileNotFoundError, OSError, ValueError) as exc:
        diagnostics = getattr(exc, "diagnostics", ()) or ()
        return LatexProjectImportPreview(
            status=ROOT_RESOLUTION_INVALID_PROJECT,
            archive_name=archive_name,
            diagnostics=_diagnostic_dicts(diagnostics),
            error_message=str(exc) or type(exc).__name__,
        )


def _zip_candidate_files(candidate: ImportCandidate):
    return [
        item for item in candidate.files if item.artifact_type == ARTIFACT_TYPE_ZIP
    ]


def preflight_latex_project_candidate(
    candidate: ImportCandidate,
    *,
    config: Optional[LatexProjectIngestionConfig] = None,
) -> ImportCandidate:
    """Attach safe LaTeX-project preview metadata to a candidate in-place.

    Candidates without ZIP artifacts are returned unchanged.  A candidate with
    more than one ZIP is recorded as invalid project metadata; the canonical
    router independently preserves its own multi-archive safety check.
    """
    if not isinstance(candidate, ImportCandidate):
        raise TypeError("candidate must be ImportCandidate")

    zip_files = _zip_candidate_files(candidate)
    if not zip_files:
        return candidate

    if len(zip_files) != 1:
        preview = LatexProjectImportPreview(
            status=ROOT_RESOLUTION_INVALID_PROJECT,
            archive_name=", ".join(item.original_filename for item in zip_files),
            error_message="LaTeX project import requires exactly one ZIP archive",
        )
    else:
        preview = inspect_latex_project_zip(
            zip_files[0].source_path,
            config=config,
        )

    candidate.metadata[LATEX_PROJECT_PREVIEW_METADATA_KEY] = preview.to_dict()
    if preview.status == ROOT_RESOLUTION_RESOLVED and preview.root_relative_path:
        candidate.metadata[LATEX_PROJECT_ROOT_METADATA_KEY] = (
            preview.root_relative_path
        )
        candidate.metadata[LATEX_PROJECT_ROOT_METHOD_METADATA_KEY] = (
            ROOT_SELECTION_DETERMINISTIC
        )
    else:
        candidate.metadata.pop(LATEX_PROJECT_ROOT_METADATA_KEY, None)
        candidate.metadata.pop(LATEX_PROJECT_ROOT_METHOD_METADATA_KEY, None)
    return candidate


def preflight_latex_project_candidates(
    candidates: Sequence[ImportCandidate],
    *,
    config: Optional[LatexProjectIngestionConfig] = None,
):
    """Preflight a candidate batch while preserving candidate identity/order."""
    return [
        preflight_latex_project_candidate(candidate, config=config)
        for candidate in candidates
    ]


def candidate_latex_project_preview(
    candidate: ImportCandidate,
) -> Optional[LatexProjectImportPreview]:
    if not isinstance(candidate, ImportCandidate):
        raise TypeError("candidate must be ImportCandidate")
    data = candidate.metadata.get(LATEX_PROJECT_PREVIEW_METADATA_KEY)
    if not isinstance(data, Mapping):
        return None
    return LatexProjectImportPreview.from_dict(data)


def apply_latex_project_preview_validation(
    candidate: ImportCandidate,
) -> ImportCandidate:
    """Apply preview-only blocking state after generic importer preparation."""
    preview = candidate_latex_project_preview(candidate)
    if preview is None:
        return candidate

    if preview.status in {
        ROOT_RESOLUTION_INVALID_PROJECT,
        ROOT_RESOLUTION_NO_ROOT_FOUND,
    }:
        detail = preview.error_message or "No compilable LaTeX root document was found"
        candidate.errors.append("latex_project:%s" % detail)
        candidate.errors = list(dict.fromkeys(candidate.errors))
        candidate.validation_status = VALIDATION_STATUS_INVALID
    elif preview.requires_root_selection:
        warning = "latex_project_root_selection_required"
        candidate.warnings.append(warning)
        candidate.warnings = list(dict.fromkeys(candidate.warnings))
    return candidate


def latex_project_root_selection_required(candidate: ImportCandidate) -> bool:
    preview = candidate_latex_project_preview(candidate)
    if preview is None or not preview.requires_root_selection:
        return False
    selected = str(
        candidate.metadata.get(LATEX_PROJECT_ROOT_METADATA_KEY) or ""
    ).strip()
    return not selected


def set_candidate_latex_project_root(
    candidate: ImportCandidate,
    root_relative_path: str,
) -> ImportCandidate:
    """Record a validated instructor root selection on a previewed candidate."""
    preview = candidate_latex_project_preview(candidate)
    if preview is None or not preview.requires_root_selection:
        raise ValueError("candidate does not require LaTeX-project root selection")
    selected = str(root_relative_path or "").strip()
    if selected not in preview.candidate_paths:
        raise ValueError("selected root must be one of the previewed document candidates")
    candidate.metadata[LATEX_PROJECT_ROOT_METADATA_KEY] = selected
    candidate.metadata[LATEX_PROJECT_ROOT_METHOD_METADATA_KEY] = (
        ROOT_SELECTION_INSTRUCTOR
    )
    return candidate


__all__ = [
    "LATEX_PROJECT_PREVIEW_METADATA_KEY",
    "LATEX_PROJECT_ROOT_METADATA_KEY",
    "LATEX_PROJECT_ROOT_METHOD_METADATA_KEY",
    "ROOT_SELECTION_DETERMINISTIC",
    "ROOT_SELECTION_INSTRUCTOR",
    "LatexProjectImportPreview",
    "apply_latex_project_preview_validation",
    "candidate_latex_project_preview",
    "inspect_latex_project_zip",
    "latex_project_root_selection_required",
    "preflight_latex_project_candidate",
    "preflight_latex_project_candidates",
    "set_candidate_latex_project_root",
]
