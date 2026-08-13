"""
Submission discovery and student-file matching.

Normal v2.2 submissions are LaTeX-first: a .tex source is required for the
normal path and a student-provided PDF is optional reference material.  The
application compiles the canonical LaTeX source itself.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .models import SubmissionRecord


_LATEX_SUFFIX = ".tex"
_PDF_SUFFIX = ".pdf"
_STUDENT_ID_UNSAFE_RE = re.compile(r"[^a-z0-9_-]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def normalize_student_id(raw: str) -> str:
    """Normalize a folder/file label into a stable internal student ID.

    Rules follow the v2.2 design: strip whitespace and an extension, lowercase,
    replace whitespace with underscores, and retain only alphanumeric, dash,
    and underscore characters.
    """
    if raw is None:
        return ""

    value = str(raw).strip()
    if not value:
        return ""

    # Path.stem safely removes one conventional filename extension while also
    # leaving ordinary IDs such as "abc.123" deterministic.
    value = Path(value).name
    suffix = Path(value).suffix.lower()
    if suffix in {_LATEX_SUFFIX, _PDF_SUFFIX}:
        value = Path(value).stem

    value = re.sub(r"\s+", "_", value.casefold())
    value = _STUDENT_ID_UNSAFE_RE.sub("_", value)
    value = _MULTI_UNDERSCORE_RE.sub("_", value)
    return value.strip("_")


def _regular_files(directory: Path, suffix: str) -> List[Path]:
    """Return top-level regular, non-symlink files matching ``suffix``."""
    try:
        children = list(directory.iterdir())
    except OSError:
        return []

    return sorted(
        [
            path
            for path in children
            if path.suffix.lower() == suffix
            and path.is_file()
            and not path.is_symlink()
        ],
        key=lambda path: path.name.casefold(),
    )


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1


def _choose_latex(paths: Sequence[Path]) -> Optional[Path]:
    if not paths:
        return None

    for path in paths:
        if path.name.casefold() == "main.tex":
            return path

    return max(paths, key=lambda path: (_safe_size(path), path.name.casefold()))


def _choose_pdf(paths: Sequence[Path], latex_path: Optional[Path]) -> Optional[Path]:
    if not paths:
        return None

    if latex_path is not None:
        wanted_stem = latex_path.stem.casefold()
        for path in paths:
            if path.stem.casefold() == wanted_stem:
                return path

    for path in paths:
        if path.name.casefold() == "main.pdf":
            return path

    return max(paths, key=lambda path: (_safe_size(path), path.name.casefold()))


def match_student_directory(
    student_dir: str,
    student_id: Optional[str] = None,
) -> Optional[SubmissionRecord]:
    """Match the normal LaTeX submission contained in one student directory.

    A directory without a .tex source is not a normal commit-1 submission and
    therefore returns ``None``.  PDF-only accommodation support is introduced
    in commit 2.
    """
    directory = Path(student_dir).expanduser().resolve()
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))

    tex_files = _regular_files(directory, _LATEX_SUFFIX)
    if not tex_files:
        return None

    pdf_files = _regular_files(directory, _PDF_SUFFIX)
    selected_tex = _choose_latex(tex_files)
    selected_pdf = _choose_pdf(pdf_files, selected_tex)

    warnings: List[str] = []
    if len(tex_files) > 1:
        warnings.append("multiple_tex_files")
    if len(pdf_files) > 1:
        warnings.append("multiple_pdf_files")

    resolved_id = normalize_student_id(student_id or directory.name)
    if not resolved_id:
        raise ValueError(f"Could not infer student ID from directory: {directory}")

    files = {"latex": str(selected_tex)}
    if selected_pdf is not None:
        files["pdf"] = str(selected_pdf)

    return SubmissionRecord(
        student_id=resolved_id,
        files=files,
        warnings=warnings,
        submission_root=str(directory),
    )


def _discover_subdirectory_records(root: Path) -> Dict[str, SubmissionRecord]:
    records: Dict[str, SubmissionRecord] = {}

    for directory in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not directory.is_dir() or directory.is_symlink() or directory.name.startswith("."):
            continue

        record = match_student_directory(str(directory))
        if record is None:
            continue

        if record.student_id in records:
            record.warnings.append("duplicate_student_submission")
            continue
        records[record.student_id] = record

    return records


def _discover_flat_records(root: Path) -> Dict[str, SubmissionRecord]:
    """Discover normal submissions represented by flat ``student_id.tex`` files."""
    grouped: Dict[str, Dict[str, List[Path]]] = {}

    for path in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.is_symlink():
            continue
        suffix = path.suffix.lower()
        if suffix not in {_LATEX_SUFFIX, _PDF_SUFFIX}:
            continue

        student_id = normalize_student_id(path.name)
        if not student_id:
            continue

        kind = "latex" if suffix == _LATEX_SUFFIX else "pdf"
        grouped.setdefault(student_id, {"latex": [], "pdf": []})[kind].append(path)

    records: Dict[str, SubmissionRecord] = {}
    for student_id, paths_by_kind in grouped.items():
        tex_files = paths_by_kind["latex"]
        if not tex_files:
            # PDF-only records are accommodation-path inputs and are intentionally
            # deferred to commit 2.
            continue

        selected_tex = _choose_latex(tex_files)
        selected_pdf = _choose_pdf(paths_by_kind["pdf"], selected_tex)
        warnings: List[str] = []
        if len(tex_files) > 1:
            warnings.append("multiple_tex_files")
        if len(paths_by_kind["pdf"]) > 1:
            warnings.append("multiple_pdf_files")

        files = {"latex": str(selected_tex)}
        if selected_pdf is not None:
            files["pdf"] = str(selected_pdf)

        records[student_id] = SubmissionRecord(
            student_id=student_id,
            files=files,
            warnings=warnings,
            submission_root=str(root),
        )

    return records


def discover_submissions(submissions_dir: str) -> List[SubmissionRecord]:
    """Discover normal LaTeX submissions under ``submissions_dir``.

    Supported layouts:

    1. one subdirectory per student, containing a .tex source;
    2. flat ``student_id.tex`` files with an optional same-stem PDF;
    3. a mixed layout.  When the same normalized student ID appears in both,
       the subdirectory record wins and receives ``duplicate_student_submission``.

    PDF-only accommodation records are intentionally not returned until commit 2.
    """
    root = Path(submissions_dir).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    directory_records = _discover_subdirectory_records(root)
    flat_records = _discover_flat_records(root)

    for student_id, flat_record in flat_records.items():
        if student_id in directory_records:
            if "duplicate_student_submission" not in directory_records[student_id].warnings:
                directory_records[student_id].warnings.append("duplicate_student_submission")
            continue
        directory_records[student_id] = flat_record

    return [directory_records[key] for key in sorted(directory_records)]


def record_from_latex_file(path: str) -> SubmissionRecord:
    """Create a record for one explicit .tex file.

    A same-stem PDF in the same directory is included as optional reference
    material when present.
    """
    requested_path = Path(path).expanduser()
    if requested_path.is_symlink():
        raise ValueError(f"Symlinked LaTeX sources are not accepted: {requested_path}")
    tex_path = requested_path.resolve()
    if not tex_path.exists():
        raise FileNotFoundError(str(tex_path))
    if not tex_path.is_file() or tex_path.suffix.lower() != _LATEX_SUFFIX:
        raise ValueError(f"Expected a .tex file: {tex_path}")

    student_id = normalize_student_id(tex_path.name)
    files = {"latex": str(tex_path)}
    sibling_pdf = tex_path.with_suffix(".pdf")
    if sibling_pdf.is_file() and not sibling_pdf.is_symlink():
        files["pdf"] = str(sibling_pdf.resolve())

    return SubmissionRecord(
        student_id=student_id,
        files=files,
        warnings=[],
        submission_root=str(tex_path.parent),
    )


__all__ = [
    "discover_submissions",
    "match_student_directory",
    "normalize_student_id",
    "record_from_latex_file",
]
