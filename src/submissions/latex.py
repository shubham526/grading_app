"""
LaTeX source extraction for grading-friendly text.

The extractor deliberately preserves LaTeX math, proof, and pseudocode markup.
It only removes comments, optionally expands safe local ``\\input``/``\\include``
files, removes the document preamble/trailer, and normalizes excessive blank
lines.  It does not attempt to render or semantically rewrite student work.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\s*\{document\}")
_END_DOCUMENT_RE = re.compile(r"\\end\s*\{document\}")
_INCLUDE_RE = re.compile(r"\\(input|include)\s*\{([^{}]+)\}")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")


def strip_latex_comment(line: str) -> str:
    """Remove an unescaped ``%`` comment from one LaTeX line.

    A percent sign is escaped when immediately preceded by an odd number of
    backslashes.  Thus ``\\%`` is preserved while ``\\\\%`` starts a comment
    after the escaped backslash sequence, matching TeX's lexical behavior.
    """
    for index, char in enumerate(line):
        if char != "%":
            continue

        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1

        if backslashes % 2 == 0:
            return line[:index]

    return line


def _read_utf8(path: Path, warnings: List[str]) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        warnings.append("latex_decode_replacement")
        return path.read_text(encoding="utf-8", errors="replace")


def _strip_comments(text: str) -> str:
    # splitlines(keepends=True) preserves the source's line structure; a line
    # ending is retained even when its trailing comment is removed.
    result: List[str] = []
    for line in text.splitlines(keepends=True):
        newline = ""
        content = line
        if content.endswith("\r\n"):
            content, newline = content[:-2], "\n"
        elif content.endswith("\n") or content.endswith("\r"):
            content, newline = content[:-1], "\n"
        result.append(strip_latex_comment(content) + newline)

    # splitlines returns [] for an empty string and preserves no final marker for
    # a one-line file without a newline, both of which are exactly what we want.
    if not result and text:
        return strip_latex_comment(text)
    return "".join(result)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_include_path(raw_target: str, current_file: Path, root: Path) -> Optional[Path]:
    target = raw_target.strip()
    if not target:
        return None

    candidate = current_file.parent / target
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".tex")

    # Check the path entry before resolve(), because resolve() follows the
    # symlink and the resulting Path would no longer report is_symlink().
    if candidate.is_symlink():
        return None

    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        return None

    if not resolved.is_file():
        return None
    if not _is_within(resolved, root):
        return None
    return resolved


def _expand_file(
    path: Path,
    root: Path,
    warnings: List[str],
    included_files: List[str],
    active: Set[Path],
    depth: int,
    max_depth: int,
) -> str:
    if depth > max_depth:
        warnings.append("latex_include_depth_exceeded")
        return ""

    resolved_path = path.resolve()
    if resolved_path in active:
        warnings.append("latex_include_cycle")
        return ""

    active.add(resolved_path)
    text = _strip_comments(_read_utf8(resolved_path, warnings))

    def replace_include(match: re.Match) -> str:
        include_target = match.group(2)
        include_path = _resolve_include_path(include_target, resolved_path, root)
        if include_path is None:
            warnings.append(f"latex_include_unavailable:{include_target.strip()}")
            # Preserve the original directive so the extracted representation
            # never fabricates content that was not safely available.
            return match.group(0)

        include_str = str(include_path)
        if include_str not in included_files:
            included_files.append(include_str)

        expanded = _expand_file(
            include_path,
            root,
            warnings,
            included_files,
            active,
            depth + 1,
            max_depth,
        )
        return "\n" + expanded + "\n"

    expanded_text = _INCLUDE_RE.sub(replace_include, text)
    active.remove(resolved_path)
    return expanded_text


def _document_body(text: str) -> Tuple[str, bool]:
    begin_match = _BEGIN_DOCUMENT_RE.search(text)
    if begin_match is None:
        return text, False

    body_start = begin_match.end()
    end_match = _END_DOCUMENT_RE.search(text, body_start)
    body_end = end_match.start() if end_match is not None else len(text)
    return text[body_start:body_end], True


def _normalize_blank_lines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _EXCESS_BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def extract_text_from_tex(
    path: str,
    *,
    expand_includes: bool = True,
    max_include_depth: int = 20,
) -> Tuple[str, Dict[str, object]]:
    """Extract grading-friendly source text from a LaTeX file.

    The returned text preserves LaTeX commands and mathematical notation.  Safe
    relative ``\\input``/``\\include`` files are expanded by default when they
    remain within the main source's directory tree.
    """
    requested_path = Path(path).expanduser()
    if requested_path.is_symlink():
        raise ValueError(f"Symlinked LaTeX sources are not accepted: {requested_path}")
    tex_path = requested_path.resolve()
    if not tex_path.exists():
        raise FileNotFoundError(str(tex_path))
    if not tex_path.is_file() or tex_path.suffix.lower() != ".tex":
        raise ValueError(f"Expected a .tex file: {tex_path}")
    if max_include_depth < 0:
        raise ValueError("max_include_depth must be non-negative")

    warnings: List[str] = []
    included_files: List[str] = []
    root = tex_path.parent.resolve()

    if expand_includes:
        text = _expand_file(
            tex_path,
            root,
            warnings,
            included_files,
            set(),
            0,
            max_include_depth,
        )
    else:
        text = _strip_comments(_read_utf8(tex_path, warnings))

    text, found_document_environment = _document_body(text)
    text = _normalize_blank_lines(text)

    # Keep warning order stable while eliminating duplicates generated by
    # repeated unavailable include directives.
    unique_warnings = list(dict.fromkeys(warnings))

    metadata: Dict[str, object] = {
        "source": "latex",
        "source_path": str(tex_path),
        "text_length": len(text),
        "warnings": unique_warnings,
        "document_environment_found": found_document_environment,
        "includes_expanded": bool(expand_includes),
        "included_files": included_files,
    }
    return text, metadata


__all__ = ["extract_text_from_tex", "strip_latex_comment"]
