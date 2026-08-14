"""Deterministic, template-aware normalization for similarity review.

The goal is deliberately modest: reduce formatting/template noise while
preserving meaningful solution content. This is not symbolic algebra, source
code canonicalization, semantic similarity, or plagiarism classification.
"""

from __future__ import annotations

import re
import unicodedata


_DOCUMENT_COMMAND_RE = re.compile(
    r"\\(?:documentclass|usepackage)(?:\[[^\]]*\])?\{[^{}]*\}",
    flags=re.IGNORECASE,
)
_METADATA_COMMAND_RE = re.compile(
    r"\\(?:title|author|date)\*?(?:\[[^\]]*\])?\{[^{}]*\}",
    flags=re.IGNORECASE,
)
_BEGIN_END_DOCUMENT_RE = re.compile(
    r"\\(?:begin|end)\s*\{\s*document\s*\}",
    flags=re.IGNORECASE,
)
_MAKETITLE_RE = re.compile(r"\\maketitle\b", flags=re.IGNORECASE)

_WRAPPED_TEXT_COMMAND_RE = re.compile(
    r"\\(?:text|textrm|texttt|textbf|textit|emph|mathrm|mathbf|mathit|operatorname)"
    r"\s*\{([^{}]*)\}",
    flags=re.IGNORECASE,
)

_TEMPLATE_LINE_PATTERNS = (
    re.compile(r"^\s*write\s+your\s+solution\s+here\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:name|student\s*id|student\s*name|date)\s*:\s*.*$", re.IGNORECASE),
    re.compile(r"^\s*(?:your\s+name|your\s+student\s+id)\s*$", re.IGNORECASE),
)

_MATH_COMMAND_REPLACEMENTS = (
    (re.compile(r"\\Theta\b", re.IGNORECASE), " theta "),
    (re.compile(r"\\Omega\b", re.IGNORECASE), " omega "),
    (re.compile(r"\\Gamma\b", re.IGNORECASE), " gamma "),
    (re.compile(r"\\log\b", re.IGNORECASE), " log "),
    (re.compile(r"\\ln\b", re.IGNORECASE), " ln "),
    (re.compile(r"\\leq?\b", re.IGNORECASE), " <= "),
    (re.compile(r"\\geq?\b", re.IGNORECASE), " >= "),
    (re.compile(r"\\neq\b", re.IGNORECASE), " != "),
    (re.compile(r"\\times\b", re.IGNORECASE), " * "),
    (re.compile(r"\\cdot\b", re.IGNORECASE), " * "),
    (re.compile(r"\\infty\b", re.IGNORECASE), " infinity "),
)

_REMAINING_COMMAND_RE = re.compile(r"\\([A-Za-z]+)\*?")


def _strip_latex_comments(text: str) -> str:
    """Remove unescaped LaTeX comments line-by-line."""
    cleaned: list[str] = []
    for line in text.splitlines():
        cut_at = None
        for index, char in enumerate(line):
            if char != "%":
                continue
            slash_count = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slash_count += 1
                cursor -= 1
            if slash_count % 2 == 0:
                cut_at = index
                break
        cleaned.append(line if cut_at is None else line[:cut_at])
    return "\n".join(cleaned)


def _remove_template_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if any(pattern.match(line) for pattern in _TEMPLATE_LINE_PATTERNS):
            continue
        kept.append(line)
    return "\n".join(kept)


def _unwrap_simple_commands(text: str) -> str:
    previous = None
    current = text
    for _ in range(8):
        if current == previous:
            break
        previous = current
        current = _WRAPPED_TEXT_COMMAND_RE.sub(r" \1 ", current)
    return current


def normalize_for_similarity(text: str) -> str:
    """Normalize extracted submission text for deterministic similarity checks."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = _strip_latex_comments(text)
    text = _DOCUMENT_COMMAND_RE.sub(" ", text)
    text = _METADATA_COMMAND_RE.sub(" ", text)
    text = _BEGIN_END_DOCUMENT_RE.sub(" ", text)
    text = _MAKETITLE_RE.sub(" ", text)
    text = _remove_template_lines(text)
    text = _unwrap_simple_commands(text)

    for pattern, replacement in _MATH_COMMAND_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    # Preserve useful command names such as sum/min/max as ordinary tokens.
    text = _REMAINING_COMMAND_RE.sub(r" \1 ", text)

    # Formatting delimiters and common TeX math punctuation should not create
    # textual differences.
    text = text.replace("\\%", "%")
    text = re.sub(r"[$^_{}()[\],;:]", " ", text)
    # Ignore sentence punctuation while retaining decimal points such as 3.14.
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)

    # Preserve <=, >=, != and basic operators. Everything else that is neither
    # alphanumeric nor one of these operators becomes spacing.
    text = re.sub(r"[^0-9A-Za-z<>=!+\-*/.%]+", " ", text)

    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text
