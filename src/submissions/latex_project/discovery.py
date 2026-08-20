"""Execution-free discovery for safely extracted LaTeX projects.

This module inspects only regular files already represented by a validated
:class:`LatexProjectManifest`.  It identifies LaTeX source files, detects
complete document candidates, records static ``\\input``/``\\include``
references, and emits portable diagnostics.  It does not compile TeX, expand
macros, execute commands, or read files outside the extracted project root.
"""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .config import LatexProjectIngestionConfig
from .models import (
    DIAGNOSTIC_BLOCKING,
    DIAGNOSTIC_INFO,
    DIAGNOSTIC_WARNING,
    FILE_ROLE_TEX_SOURCE,
    LatexProjectDiagnostic,
    LatexProjectManifest,
    normalize_project_relative_path,
)


_DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\s*\[[^\]]*\])?\s*\{", re.IGNORECASE)
_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\s*\{\s*document\s*\}", re.IGNORECASE)
_INCLUDE_RE = re.compile(
    r"\\(?P<command>input|include)\s*\{\s*(?P<target>[^{}]+?)\s*\}",
    re.IGNORECASE,
)
_DYNAMIC_TARGET_RE = re.compile(r"[\\#$&^~{}]")


@dataclass(frozen=True)
class LatexProjectReference:
    """One statically inspectable ``\\input`` or ``\\include`` reference."""

    source_relative_path: str
    command: str
    raw_target: str
    resolved_relative_path: Optional[str]
    exists: bool
    dynamic: bool = False

    def __post_init__(self):
        source = normalize_project_relative_path(
            self.source_relative_path,
            "source_relative_path",
        )
        command = str(self.command or "").strip().lower()
        if command not in ("input", "include"):
            raise ValueError("command must be 'input' or 'include'")
        raw_target = str(self.raw_target or "").strip()
        if not raw_target:
            raise ValueError("raw_target must not be empty")
        resolved = self.resolved_relative_path
        if resolved is not None:
            resolved = normalize_project_relative_path(
                resolved,
                "resolved_relative_path",
            )
        object.__setattr__(self, "source_relative_path", source)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "raw_target", raw_target)
        object.__setattr__(self, "resolved_relative_path", resolved)
        object.__setattr__(self, "exists", bool(self.exists))
        object.__setattr__(self, "dynamic", bool(self.dynamic))


@dataclass(frozen=True)
class LatexTexSourceInfo:
    """Discovery metadata for one readable ``.tex`` source file."""

    relative_path: str
    has_documentclass: bool
    has_begin_document: bool
    references: Tuple[LatexProjectReference, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(
            self,
            "relative_path",
            normalize_project_relative_path(self.relative_path),
        )
        object.__setattr__(self, "has_documentclass", bool(self.has_documentclass))
        object.__setattr__(self, "has_begin_document", bool(self.has_begin_document))
        refs = []
        for value in self.references or ():
            if not isinstance(value, LatexProjectReference):
                raise TypeError("references must contain LatexProjectReference objects")
            refs.append(value)
        object.__setattr__(self, "references", tuple(refs))

    @property
    def is_document_candidate(self):
        return self.has_documentclass and self.has_begin_document


@dataclass(frozen=True)
class LatexProjectDiscovery:
    """Execution-free structural discovery result for one extracted project."""

    project_id: str
    tex_sources: Tuple[LatexTexSourceInfo, ...]
    document_candidate_paths: Tuple[str, ...]
    included_tex_paths: Tuple[str, ...]
    orphan_tex_paths: Tuple[str, ...]
    bibliography_paths: Tuple[str, ...]
    figure_paths: Tuple[str, ...]
    other_paths: Tuple[str, ...]
    diagnostics: Tuple[LatexProjectDiagnostic, ...] = field(default_factory=tuple)

    def __post_init__(self):
        project_id = str(self.project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required")
        sources = []
        for value in self.tex_sources or ():
            if not isinstance(value, LatexTexSourceInfo):
                raise TypeError("tex_sources must contain LatexTexSourceInfo objects")
            sources.append(value)
        source_paths = tuple(item.relative_path for item in sources)
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("tex_sources contains duplicate relative paths")

        def normalized_paths(values, name):
            result = []
            seen = set()
            for raw in values or ():
                value = normalize_project_relative_path(raw, "%s entry" % name)
                if value in seen:
                    raise ValueError("%s contains duplicate paths" % name)
                seen.add(value)
                result.append(value)
            return tuple(result)

        candidates = normalized_paths(
            self.document_candidate_paths,
            "document_candidate_paths",
        )
        included = normalized_paths(self.included_tex_paths, "included_tex_paths")
        orphans = normalized_paths(self.orphan_tex_paths, "orphan_tex_paths")
        bibliography = normalized_paths(self.bibliography_paths, "bibliography_paths")
        figures = normalized_paths(self.figure_paths, "figure_paths")
        others = normalized_paths(self.other_paths, "other_paths")

        source_set = set(source_paths)
        if not set(candidates).issubset(source_set):
            raise ValueError("document candidates must be discovered TeX sources")
        if not set(included).issubset(source_set):
            raise ValueError("included_tex_paths must be discovered TeX sources")
        if not set(orphans).issubset(source_set):
            raise ValueError("orphan_tex_paths must be discovered TeX sources")

        diagnostics = []
        for value in self.diagnostics or ():
            if not isinstance(value, LatexProjectDiagnostic):
                raise TypeError("diagnostics must contain LatexProjectDiagnostic objects")
            diagnostics.append(value)

        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "tex_sources", tuple(sources))
        object.__setattr__(self, "document_candidate_paths", candidates)
        object.__setattr__(self, "included_tex_paths", included)
        object.__setattr__(self, "orphan_tex_paths", orphans)
        object.__setattr__(self, "bibliography_paths", bibliography)
        object.__setattr__(self, "figure_paths", figures)
        object.__setattr__(self, "other_paths", others)
        object.__setattr__(self, "diagnostics", tuple(diagnostics))

    @property
    def tex_paths(self):
        return tuple(item.relative_path for item in self.tex_sources)

    def source_by_path(self, relative_path):
        target = normalize_project_relative_path(relative_path)
        for item in self.tex_sources:
            if item.relative_path == target:
                return item
        return None


def _strip_latex_comments(text):
    """Remove unescaped ``%`` comments while preserving line boundaries."""
    output = []
    for line in text.splitlines(True):
        cut = None
        for index, char in enumerate(line):
            if char != "%":
                continue
            slash_count = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slash_count += 1
                cursor -= 1
            if slash_count % 2 == 0:
                cut = index
                break
        if cut is None:
            output.append(line)
        else:
            suffix = "\n" if line.endswith("\n") else ""
            output.append(line[:cut] + suffix)
    return "".join(output)


def _read_utf8_tex(path, relative_path):
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, LatexProjectDiagnostic(
            code="tex_source_read_failed",
            message="Could not read LaTeX source: %s" % exc,
            severity=DIAGNOSTIC_BLOCKING,
            relative_path=relative_path,
        )
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return None, LatexProjectDiagnostic(
            code="tex_source_not_utf8",
            message="LaTeX source is not valid UTF-8 and cannot be inspected safely",
            severity=DIAGNOSTIC_WARNING,
            relative_path=relative_path,
        )


def _static_reference_target(source_relative_path, raw_target, manifest_paths):
    target = str(raw_target or "").strip()
    if not target or _DYNAMIC_TARGET_RE.search(target):
        return None, False, True, None

    target = target.replace("\\", "/")
    if PurePosixPath(target).suffix == "":
        target = target + ".tex"
    base = PurePosixPath(source_relative_path).parent
    raw_parts = base.joinpath(PurePosixPath(target)).parts
    normalized_parts = []
    escaped = False
    for part in raw_parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized_parts:
                escaped = True
                break
            normalized_parts.pop()
        else:
            normalized_parts.append(part)
    if escaped or not normalized_parts:
        return None, False, False, "outside"
    candidate = "/".join(normalized_parts)
    try:
        candidate = normalize_project_relative_path(candidate)
    except Exception:
        return None, False, False, "outside"
    return candidate, candidate in manifest_paths, False, None


def _categorize_non_tex(manifest):
    bib = []
    figures = []
    others = []
    figure_suffixes = {
        ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".eps",
        ".ps", ".tif", ".tiff", ".bmp", ".webp",
    }
    for item in manifest.files:
        suffix = PurePosixPath(item.relative_path).suffix.casefold()
        if suffix == ".tex":
            continue
        if suffix == ".bib":
            bib.append(item.relative_path)
        elif suffix in figure_suffixes:
            figures.append(item.relative_path)
        else:
            others.append(item.relative_path)
    return tuple(sorted(bib)), tuple(sorted(figures)), tuple(sorted(others))


def discover_latex_project(extracted_root, manifest, config=None):
    """Inspect one verified extracted project without executing or compiling it.

    ``manifest`` is the authority for the set of readable regular files.  Files
    present on disk but absent from the manifest are never inspected here.
    """
    if not isinstance(manifest, LatexProjectManifest):
        raise TypeError("manifest must be LatexProjectManifest")
    if config is None:
        config = LatexProjectIngestionConfig()
    elif not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig")

    root = Path(extracted_root)
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise ValueError("extracted_root must be an existing non-symlink directory")

    manifest_paths = {item.relative_path for item in manifest.files}
    tex_manifest_paths = sorted(
        item.relative_path
        for item in manifest.files
        if item.role == FILE_ROLE_TEX_SOURCE
        or PurePosixPath(item.relative_path).suffix.casefold() == ".tex"
    )
    diagnostics = []
    sources = []
    referenced_existing_tex = set()

    if not tex_manifest_paths:
        diagnostics.append(
            LatexProjectDiagnostic(
                code="no_tex_sources",
                message="Extracted project contains no .tex source files",
                severity=DIAGNOSTIC_BLOCKING,
            )
        )

    for relative_path in tex_manifest_paths:
        disk_path = root.joinpath(*PurePosixPath(relative_path).parts)
        if disk_path.is_symlink() or not disk_path.exists() or not disk_path.is_file():
            diagnostics.append(
                LatexProjectDiagnostic(
                    code="tex_source_missing_from_extraction",
                    message="Manifest LaTeX source is missing or no longer regular",
                    severity=DIAGNOSTIC_BLOCKING,
                    relative_path=relative_path,
                )
            )
            continue
        text, read_diagnostic = _read_utf8_tex(disk_path, relative_path)
        if read_diagnostic is not None:
            diagnostics.append(read_diagnostic)
            continue
        stripped = _strip_latex_comments(text)
        references = []
        for match in _INCLUDE_RE.finditer(stripped):
            command = match.group("command").lower()
            raw_target = match.group("target").strip()
            resolved, exists, dynamic, error = _static_reference_target(
                relative_path,
                raw_target,
                manifest_paths,
            )
            references.append(
                LatexProjectReference(
                    source_relative_path=relative_path,
                    command=command,
                    raw_target=raw_target,
                    resolved_relative_path=resolved,
                    exists=exists,
                    dynamic=dynamic,
                )
            )
            if dynamic:
                diagnostics.append(
                    LatexProjectDiagnostic(
                        code="dynamic_include_reference",
                        message=(
                            "Dynamic LaTeX include target cannot be resolved without "
                            "executing TeX semantics"
                        ),
                        severity=DIAGNOSTIC_INFO,
                        relative_path=relative_path,
                        metadata={"command": command, "target": raw_target},
                    )
                )
            elif error == "outside":
                diagnostics.append(
                    LatexProjectDiagnostic(
                        code="include_reference_outside_project",
                        message="LaTeX include target resolves outside the extracted project",
                        severity=DIAGNOSTIC_WARNING,
                        relative_path=relative_path,
                        metadata={"command": command, "target": raw_target},
                    )
                )
            elif resolved is not None and not exists:
                diagnostics.append(
                    LatexProjectDiagnostic(
                        code="missing_include_reference",
                        message="Referenced LaTeX source is not present in the project",
                        severity=DIAGNOSTIC_WARNING,
                        relative_path=relative_path,
                        metadata={
                            "command": command,
                            "target": raw_target,
                            "resolved_path": resolved,
                        },
                    )
                )
            elif resolved is not None and exists and resolved.lower().endswith(".tex"):
                referenced_existing_tex.add(resolved)

        sources.append(
            LatexTexSourceInfo(
                relative_path=relative_path,
                has_documentclass=bool(_DOCUMENTCLASS_RE.search(stripped)),
                has_begin_document=bool(_BEGIN_DOCUMENT_RE.search(stripped)),
                references=tuple(references),
            )
        )

    candidates = tuple(
        sorted(item.relative_path for item in sources if item.is_document_candidate)
    )
    source_paths = {item.relative_path for item in sources}
    included = tuple(sorted(referenced_existing_tex & source_paths))
    orphans = tuple(sorted(source_paths - set(included) - set(candidates)))
    bibliography, figures, others = _categorize_non_tex(manifest)

    return LatexProjectDiscovery(
        project_id=manifest.project_id,
        tex_sources=tuple(sorted(sources, key=lambda item: item.relative_path)),
        document_candidate_paths=candidates,
        included_tex_paths=included,
        orphan_tex_paths=orphans,
        bibliography_paths=bibliography,
        figure_paths=figures,
        other_paths=others,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "LatexProjectDiscovery",
    "LatexProjectReference",
    "LatexTexSourceInfo",
    "discover_latex_project",
]
