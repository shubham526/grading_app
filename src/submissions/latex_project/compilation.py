r"""Whole-project LaTeX compilation for safely stored Overleaf ZIPs.

This module does not interpret or concatenate ``\input`` / ``\include`` files.
It verifies the immutable extracted project, resolves the selected root source,
then delegates the complete project tree to the existing restricted LaTeX
compiler.  The real TeX engine therefore owns TeX semantics and produces the
same derived PDF used by the existing Written grading viewer.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

from ..compiler import compile_tex_to_pdf
from ..models import CompilationResult
from .config import LatexProjectIngestionConfig
from .errors import LatexProjectIntegrityError, LatexProjectValidationError
from .models import (
    ROOT_RESOLUTION_RESOLVED,
    LatexProjectResolution,
)
from .storage import StoredLatexProject, verify_stored_latex_project


@dataclass(frozen=True)
class LatexProjectCompilation:
    """One verified project compilation plus portable provenance."""

    project_id: str
    root_relative_path: str
    resolution_method: str
    archive_sha256: str
    manifest_sha256: str
    source_file_count: int
    source_total_bytes: int
    compilation: CompilationResult

    @property
    def success(self):
        return bool(self.compilation.success)

    @property
    def pdf_path(self):
        return self.compilation.pdf_path

    def to_metadata(self, include_logs=False):
        return {
            "project_id": self.project_id,
            "root_relative_path": self.root_relative_path,
            "resolution_method": self.resolution_method,
            "archive_sha256": self.archive_sha256,
            "manifest_sha256": self.manifest_sha256,
            "source_file_count": self.source_file_count,
            "source_total_bytes": self.source_total_bytes,
            "compilation": self.compilation.to_metadata(include_logs=include_logs),
        }


def _resolved_root(stored, resolution):
    if not isinstance(stored, StoredLatexProject):
        raise TypeError("stored must be StoredLatexProject")
    if not isinstance(resolution, LatexProjectResolution):
        raise TypeError("resolution must be LatexProjectResolution")
    if resolution.status != ROOT_RESOLUTION_RESOLVED:
        raise LatexProjectValidationError(
            "LaTeX project root must be resolved before compilation"
        )
    root_relative = str(resolution.root_relative_path or "").strip()
    if not root_relative:
        raise LatexProjectValidationError(
            "Resolved LaTeX project has no root_relative_path"
        )

    resolution_project_id = str(
        (resolution.metadata or {}).get("project_id") or ""
    ).strip()
    if resolution_project_id and resolution_project_id != stored.project_id:
        raise LatexProjectIntegrityError(
            "Root resolution belongs to a different LaTeX project"
        )

    manifest_by_path = {
        item.relative_path: item
        for item in stored.manifest.files
    }
    if root_relative not in manifest_by_path:
        raise LatexProjectIntegrityError(
            "Resolved LaTeX root is not present in the verified project manifest"
        )
    if PurePosixPath(root_relative).suffix.casefold() != ".tex":
        raise LatexProjectIntegrityError(
            "Resolved LaTeX root is not a .tex source"
        )
    return root_relative


def compile_stored_latex_project_to_pdf(
    stored,
    resolution,
    *,
    output_dir=None,
    config=None,
    engine="pdflatex",
    passes=1,
    timeout_seconds=30.0,
    max_pdf_bytes=100 * 1024 * 1024,
    max_log_chars=200_000,
):
    """Compile one verified extracted LaTeX project into a derived PDF.

    The complete extraction is verified immediately before compilation.  Only
    files present in the immutable manifest are handed to the compiler.  The
    existing ``compile_tex_to_pdf`` implementation performs bounded staging,
    disables shell escape, restricts TeX IO, enforces wall-clock limits, and
    validates the resulting PDF.

    Normal LaTeX compiler failures remain structured ``CompilationResult``
    failures.  Invalid project identity/integrity/root-resolution preconditions
    raise before TeX is invoked.
    """
    if config is None:
        config = LatexProjectIngestionConfig()
    elif not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig")

    verify_stored_latex_project(stored)
    root_relative = _resolved_root(stored, resolution)

    extracted_root = Path(stored.extracted_root)
    root_path = extracted_root.joinpath(*PurePosixPath(root_relative).parts)
    if root_path.is_symlink() or not root_path.exists() or not root_path.is_file():
        raise LatexProjectIntegrityError(
            "Resolved LaTeX root is missing or no longer a regular file"
        )

    allowed_paths = tuple(item.relative_path for item in stored.manifest.files)
    compilation = compile_tex_to_pdf(
        str(root_path),
        output_dir=output_dir,
        source_root=str(extracted_root),
        allowed_source_paths=allowed_paths,
        engine=engine,
        passes=passes,
        timeout_seconds=timeout_seconds,
        max_source_files=config.limits.max_file_count,
        max_source_bytes=config.limits.max_total_uncompressed_bytes,
        max_single_file_bytes=config.limits.max_member_bytes,
        max_pdf_bytes=max_pdf_bytes,
        max_log_chars=max_log_chars,
    )

    manifest_sha256 = stored.manifest.manifest_sha256
    if not manifest_sha256:
        raise LatexProjectIntegrityError(
            "Verified LaTeX-project manifest has no SHA-256"
        )

    return LatexProjectCompilation(
        project_id=stored.project_id,
        root_relative_path=root_relative,
        resolution_method=resolution.resolution_method,
        archive_sha256=stored.archive.archive_sha256,
        manifest_sha256=manifest_sha256,
        source_file_count=len(stored.manifest.files),
        source_total_bytes=stored.manifest.total_uncompressed_bytes,
        compilation=compilation,
    )


__all__ = [
    "LatexProjectCompilation",
    "compile_stored_latex_project_to_pdf",
]
