"""Deterministic pseudocode / algorithm-structure similarity.

This module is intentionally lightweight. It does not attempt to parse a full
programming language or infer algorithmic equivalence. Instead it extracts
explicit pseudocode regions, normalizes superficial differences such as
variable names/comments/whitespace, and compares normalized token 3-grams.

The resulting score is a structural review signal only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
import unicodedata
from typing import Any

from .shingles import jaccard_similarity, make_word_shingles


DEFAULT_PSEUDOCODE_THRESHOLDS = {
    "pseudocode_medium": 0.65,
    "pseudocode_high": 0.80,
    "pseudocode_exact": 0.95,
}

PSEUDOCODE_REVIEW_WARNING = "pseudocode_similarity_requires_manual_review"

_ENVIRONMENT_PRIORITY = {
    "algorithmic": 0,
    "verbatim": 1,
    "algorithm": 2,
}

_ENVIRONMENT_PATTERNS = {
    name: re.compile(
        rf"\\begin\s*\{{\s*{name}\s*\}}(.*?)"
        rf"\\end\s*\{{\s*{name}\s*\}}",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for name in _ENVIRONMENT_PRIORITY
}

_HEADING_RE = re.compile(
    r"^\s*(algorithm|pseudocode)\s*:\s*(.*)$",
    flags=re.IGNORECASE,
)

_LATEX_COMMENT_COMMAND_RE = re.compile(
    r"\\(?:comment|tcp|tcc)\*?\s*\{[^{}]*\}",
    flags=re.IGNORECASE,
)

_COMMON_COMMAND_REPLACEMENTS = (
    (re.compile(r"\\forall\b", re.IGNORECASE), " for "),
    (re.compile(r"\\ForAll\b", re.IGNORECASE), " for "),
    (re.compile(r"\\For\b", re.IGNORECASE), " for "),
    (re.compile(r"\\EndFor\b", re.IGNORECASE), " end for "),
    (re.compile(r"\\While\b", re.IGNORECASE), " while "),
    (re.compile(r"\\EndWhile\b", re.IGNORECASE), " end while "),
    (re.compile(r"\\If\b", re.IGNORECASE), " if "),
    (re.compile(r"\\ElsIf\b", re.IGNORECASE), " else if "),
    (re.compile(r"\\Else\b", re.IGNORECASE), " else "),
    (re.compile(r"\\EndIf\b", re.IGNORECASE), " end if "),
    (re.compile(r"\\Repeat\b", re.IGNORECASE), " repeat "),
    (re.compile(r"\\Until\b", re.IGNORECASE), " until "),
    (re.compile(r"\\Loop\b", re.IGNORECASE), " loop "),
    (re.compile(r"\\EndLoop\b", re.IGNORECASE), " end loop "),
    (re.compile(r"\\Return\b", re.IGNORECASE), " return "),
    (re.compile(r"\\Break\b", re.IGNORECASE), " break "),
    (re.compile(r"\\Continue\b", re.IGNORECASE), " continue "),
    (re.compile(r"\\Procedure\b", re.IGNORECASE), " procedure "),
    (re.compile(r"\\EndProcedure\b", re.IGNORECASE), " end procedure "),
    (re.compile(r"\\Function\b", re.IGNORECASE), " function "),
    (re.compile(r"\\EndFunction\b", re.IGNORECASE), " end function "),
    (re.compile(r"\\Require\b", re.IGNORECASE), " require "),
    (re.compile(r"\\Ensure\b", re.IGNORECASE), " ensure "),
    # \State is formatting rather than algorithmic structure.
    (re.compile(r"\\Statex?\b", re.IGNORECASE), " "),
)

_BEGIN_END_ANY_RE = re.compile(
    r"\\(?:begin|end)\s*\{[^{}]+\}",
    flags=re.IGNORECASE,
)
_REMAINING_LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+\*?")

_STRING_RE = re.compile(r"""(["'])(?:\\.|(?!\1).)*\1""")

_TOKEN_RE = re.compile(
    r"<=|>=|!=|==|:=|<-|->|"
    r"[A-Za-z_][A-Za-z0-9_]*|"
    r"\d+(?:\.\d+)?|"
    r"[+\-*/%=<>\[\](),:]"
)

# Preserve control-flow / structural vocabulary while replacing ordinary
# identifiers with VAR. This list is deliberately conservative.
_STRUCTURAL_KEYWORDS = {
    "for",
    "foreach",
    "while",
    "if",
    "else",
    "then",
    "do",
    "end",
    "return",
    "break",
    "continue",
    "repeat",
    "until",
    "loop",
    "to",
    "downto",
    "in",
    "and",
    "or",
    "not",
    "procedure",
    "function",
    "require",
    "ensure",
    "true",
    "false",
}


def _strip_line_comment(line: str) -> str:
    """Remove common pseudocode comments while respecting escaped TeX percent."""
    percent_cut = None
    for index, char in enumerate(line):
        if char != "%":
            continue
        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            slash_count += 1
            cursor -= 1
        if slash_count % 2 == 0:
            percent_cut = index
            break

    cut_points = [point for point in [percent_cut] if point is not None]

    slash = line.find("//")
    if slash >= 0:
        cut_points.append(slash)

    hash_pos = line.find("#")
    if hash_pos >= 0:
        cut_points.append(hash_pos)

    if cut_points:
        return line[: min(cut_points)]
    return line


def _strip_comments(text: str) -> str:
    text = _LATEX_COMMENT_COMMAND_RE.sub(" ", text)
    return "\n".join(_strip_line_comment(line) for line in text.splitlines())


def _deduplicate_blocks(blocks: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        cleaned = str(block or "").strip()
        key = re.sub(r"\s+", " ", cleaned).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def extract_pseudocode_blocks(text: str) -> list[str]:
    """Extract explicit pseudocode/algorithm regions from one answer.

    Supported LaTeX environments:
      * algorithm
      * algorithmic
      * verbatim

    Supported plain-text headings:
      * Algorithm:
      * Pseudocode:

    When an ``algorithmic`` block is nested inside ``algorithm``, the inner
    algorithmic block is preferred to avoid reporting the same pseudocode twice.
    """

    if text is None:
        return []
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return []

    candidates: list[tuple[int, int, int, str, str]] = []
    for environment, priority in _ENVIRONMENT_PRIORITY.items():
        pattern = _ENVIRONMENT_PATTERNS[environment]
        for match in pattern.finditer(text):
            candidates.append(
                (
                    priority,
                    match.start(),
                    match.end(),
                    environment,
                    match.group(1).strip(),
                )
            )

    if candidates:
        selected: list[tuple[int, int, int, str, str]] = []
        # Prefer algorithmic, then verbatim, then outer algorithm blocks.
        for candidate in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
            _, start, end, _, _ = candidate
            overlaps_selected = any(
                not (end <= existing[1] or start >= existing[2])
                for existing in selected
            )
            if overlaps_selected:
                continue
            selected.append(candidate)

        selected.sort(key=lambda item: item[1])
        return _deduplicate_blocks([item[4] for item in selected])

    # Plain-text fallback. A heading owns the following contiguous non-empty
    # lines. This keeps prose after a blank paragraph out of the pseudocode block.
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = _HEADING_RE.match(lines[index])
        if not match:
            index += 1
            continue

        collected: list[str] = []
        same_line = match.group(2).strip()
        if same_line:
            collected.append(same_line)

        index += 1
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                break
            if _HEADING_RE.match(line):
                break
            collected.append(line)
            index += 1

        block = "\n".join(collected).strip()
        if block:
            blocks.append(block)

        # Move past the blank separator, if present.
        while index < len(lines) and not lines[index].strip():
            index += 1

    return _deduplicate_blocks(blocks)


def normalize_pseudocode(code: str) -> list[str]:
    """Normalize pseudocode into deterministic structural tokens.

    The normalization:
      * lowercases structural keywords;
      * removes comments and LaTeX formatting commands;
      * normalizes assignment arrows;
      * replaces identifiers with ``VAR``;
      * replaces numeric constants with ``NUM``;
      * replaces string literals with ``STR``;
      * preserves control-flow keywords, operators, and indexing punctuation.
    """

    if code is None:
        return []
    if not isinstance(code, str):
        code = str(code)
    if not code.strip():
        return []

    text = unicodedata.normalize("NFKC", code)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_comments(text)

    # Remove plain-text extraction headings when normalize_pseudocode is called
    # directly on a heading-based block.
    text = re.sub(
        r"(?im)^\s*(?:algorithm|pseudocode)\s*:\s*",
        "",
        text,
    )

    text = _STRING_RE.sub(" STR ", text)

    # Normalize common assignment arrows before punctuation/token processing.
    text = text.replace("←", " = ")
    text = text.replace("⟵", " = ")
    text = text.replace(":=", " = ")
    text = text.replace("<-", " = ")

    for pattern, replacement in _COMMON_COMMAND_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    text = _BEGIN_END_ANY_RE.sub(" ", text)
    text = _REMAINING_LATEX_COMMAND_RE.sub(" ", text)

    # TeX grouping and math delimiters are formatting noise here.
    text = text.replace("$", " ")
    text = text.replace("{", " ").replace("}", " ")

    raw_tokens = _TOKEN_RE.findall(text)
    normalized: list[str] = []

    for token in raw_tokens:
        lower = token.lower()

        if lower == "str":
            normalized.append("STR")
            continue

        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            normalized.append("NUM")
            continue

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            if lower in _STRUCTURAL_KEYWORDS:
                normalized.append(lower)
            else:
                normalized.append("VAR")
            continue

        if token in {"<-", ":="}:
            normalized.append("=")
            continue

        normalized.append(token)

    return normalized


def pseudocode_similarity(code_a: str, code_b: str) -> float:
    """Compare two pseudocode blocks using normalized token 3-gram Jaccard."""

    tokens_a = normalize_pseudocode(code_a)
    tokens_b = normalize_pseudocode(code_b)
    if not tokens_a or not tokens_b:
        return 0.0

    shingles_a = make_word_shingles(tokens_a, n=3)
    shingles_b = make_word_shingles(tokens_b, n=3)
    return float(jaccard_similarity(shingles_a, shingles_b))


def compute_question_pseudocode_similarity(
    answers_a: Mapping[str, str],
    answers_b: Mapping[str, str],
    question_ids: Sequence[str],
) -> dict[str, float]:
    """Compute same-question pseudocode similarity for one student pair.

    A question is omitted when either answer contains no explicit pseudocode
    block. If multiple blocks exist in one answer, the maximum block-pair score
    is used as the review signal for that question.
    """

    result: dict[str, float] = {}

    for raw_qid in question_ids:
        qid = str(raw_qid or "").strip()
        if not qid:
            continue

        answer_a = answers_a.get(qid, "")
        answer_b = answers_b.get(qid, "")
        blocks_a = extract_pseudocode_blocks(answer_a)
        blocks_b = extract_pseudocode_blocks(answer_b)

        if not blocks_a or not blocks_b:
            continue

        best = max(
            pseudocode_similarity(block_a, block_b)
            for block_a in blocks_a
            for block_b in blocks_b
        )
        result[qid] = float(best)

    return result


def resolve_pseudocode_thresholds(
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Resolve and validate configurable pseudocode similarity thresholds."""

    merged = dict(DEFAULT_PSEUDOCODE_THRESHOLDS)
    if thresholds is not None:
        unknown = set(thresholds) - set(DEFAULT_PSEUDOCODE_THRESHOLDS)
        if unknown:
            raise ValueError(
                "Unsupported pseudocode threshold key(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        for key, value in thresholds.items():
            merged[key] = float(value)

    values = [
        merged["pseudocode_medium"],
        merged["pseudocode_high"],
        merged["pseudocode_exact"],
    ]

    if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in values):
        raise ValueError("Pseudocode thresholds must be finite values between 0.0 and 1.0.")

    if values != sorted(values):
        raise ValueError(
            "Pseudocode thresholds must satisfy medium <= high <= exact."
        )

    return merged


def pseudocode_flag_for_score(
    score: float,
    thresholds: Mapping[str, Any] | None = None,
) -> str:
    """Map one structural similarity score to a review flag."""

    value = float(score)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError("Pseudocode similarity score must be between 0.0 and 1.0.")

    resolved = resolve_pseudocode_thresholds(thresholds)
    if value >= resolved["pseudocode_exact"]:
        return "exact"
    if value >= resolved["pseudocode_high"]:
        return "high"
    if value >= resolved["pseudocode_medium"]:
        return "medium"
    return "none"
