"""
Question-boundary detection for extracted student submissions.

The splitter is conservative: it only recognizes line-level question headings.
If no headings are found it returns ``FULL_SUBMISSION`` rather than copying the
same text into every rubric question, preventing accidental grading against the
wrong answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


FULL_SUBMISSION = "FULL_SUBMISSION"

# Keep this normalization grammar aligned with src.core.question_utils without
# importing src.core (whose package initializer currently pulls in PyQt-backed
# assessment code).  The submission backend must remain headless and pure.
_QUESTION_LABEL_RE = re.compile(
    r"^\s*(?:QUESTION|PROBLEM|Q|P)\s*(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|\s*([A-Z]))?\s*$",
    re.IGNORECASE,
)

_PLAIN_HEADING_RE = re.compile(
    r"^\s*(?:QUESTION|PROBLEM|Q|P)\s*(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|\s*([A-Z]))?"
    r"\s*(?:[:.\-]\s*)?(.*)$",
    re.IGNORECASE,
)

_LATEX_HEADING_RE = re.compile(
    r"^\s*\\(?:sub)*section\*?\s*\{\s*"
    r"(?:QUESTION|PROBLEM|Q|P)\s*(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|\s*([A-Z]))?"
    r"\s*\}\s*(.*)$",
    re.IGNORECASE,
)

# Bare numeric headings are common in handwritten work and VLM transcriptions
# (for example ``1.`` or ``2(a)``).  They are intentionally handled only as
# a conservative fallback when the caller supplies expected question IDs and
# no explicit Question/Q/Problem/P headings were found.
_BARE_NUMBER_HEADING_RE = re.compile(
    r"^\s*(?:\(\s*)?(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|\s*([A-Z]))?"
    r"\s*(?:\))?\s*([.:)]?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Heading:
    line_index: int
    question_id: str
    trailing_text: str = ""


def normalize_heading_question_id(raw: str) -> Optional[str]:
    """Normalize a supported question heading to Q1/Q1A-style canonical form."""
    if not isinstance(raw, str):
        return None
    match = _QUESTION_LABEL_RE.fullmatch(raw.strip())
    if not match:
        return None
    number = str(int(match.group(1)))
    subpart = (match.group(2) or match.group(3) or "").upper()
    return f"Q{number}{subpart}"


def _explicit_heading_from_line(line: str, line_index: int) -> Optional[_Heading]:
    """Return a prefixed/LaTeX heading, never a bare numeric line."""
    match = _LATEX_HEADING_RE.match(line)
    if match is None:
        match = _PLAIN_HEADING_RE.match(line)
    if match is None:
        return None

    number = str(int(match.group(1)))
    subpart = (match.group(2) or match.group(3) or "").upper()
    trailing = (match.group(4) or "").strip()

    # Avoid treating prose such as "Question 1 is difficult" as a heading.  A
    # plain heading may have trailing answer text only when explicitly separated
    # by punctuation.  LaTeX section headings have no in-brace trailing prose.
    if match.re is _PLAIN_HEADING_RE:
        label_only = re.match(
            r"^\s*(?:QUESTION|PROBLEM|Q|P)\s*\d+"
            r"(?:\s*\(\s*[A-Z]\s*\)|\s*[A-Z])?\s*$",
            line,
            re.IGNORECASE,
        )
        if label_only is None:
            separator_match = re.match(
                r"^\s*(?:QUESTION|PROBLEM|Q|P)\s*\d+"
                r"(?:\s*\(\s*[A-Z]\s*\)|\s*[A-Z])?\s*([:.\-])",
                line,
                re.IGNORECASE,
            )
            if separator_match is None:
                return None

    return _Heading(
        line_index=line_index,
        question_id=f"Q{number}{subpart}",
        trailing_text=trailing,
    )


def _bare_numeric_heading_from_line(
    line: str,
    line_index: int,
    requested: Sequence[str],
) -> Optional[_Heading]:
    """Recognize a bare numeric heading only when it matches an expected ID.

    Requiring the rubric/question context keeps ordinary numbered prose and
    equations from being promoted to question boundaries.  A punctuation mark
    or parenthesized form is also required, so a line containing only ``1`` is
    not enough to create a boundary.
    """
    if not requested:
        return None

    match = _BARE_NUMBER_HEADING_RE.fullmatch(line)
    if match is None:
        return None

    number = str(int(match.group(1)))
    subpart = (match.group(2) or match.group(3) or "").upper()
    punctuation = match.group(4) or ""

    stripped = line.strip()
    parenthesized = (
        stripped.startswith("(")
        or "(" in stripped
        or stripped.endswith(")")
    )
    if not punctuation and not parenthesized:
        return None

    question_id = f"Q{number}{subpart}"
    if question_id not in requested:
        return None

    return _Heading(
        line_index=line_index,
        question_id=question_id,
        trailing_text="",
    )


def _normalize_requested(question_ids: Optional[Sequence[str]]) -> List[str]:
    if not question_ids:
        return []

    normalized: List[str] = []
    for raw in question_ids:
        value = normalize_heading_question_id(str(raw))
        if value is None:
            # Preserve explicit custom IDs rather than inventing a mapping.  They
            # cannot be matched by the built-in heading grammar, so the caller
            # receives a deterministic missing-answer warning.
            value = str(raw).strip().upper()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def split_answers_by_question(
    text: str,
    question_ids: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """Split extracted text into question-specific answers.

    Returns ``(answers_by_question, warnings)``.  When no supported line-level
    headings are detected, the sole answer is ``FULL_SUBMISSION`` and the
    warning ``could_not_split_by_question`` is emitted.
    """
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    lines = text.splitlines()
    requested = _normalize_requested(question_ids)

    # Prefer explicit headings.  Only when an entire submission lacks them do
    # we fall back to bare numeric headings such as ``1.`` / ``2(a)`` and only
    # when those labels match caller-supplied expected question IDs.
    headings: List[_Heading] = []
    for index, line in enumerate(lines):
        heading = _explicit_heading_from_line(line, index)
        if heading is not None:
            headings.append(heading)

    if not headings and requested:
        for index, line in enumerate(lines):
            heading = _bare_numeric_heading_from_line(line, index, requested)
            if heading is not None:
                headings.append(heading)

    warnings: List[str] = []

    if not headings:
        warnings.append("could_not_split_by_question")
        for qid in requested:
            warnings.append(f"missing_answer_for_{qid}")
        return {FULL_SUBMISSION: text.strip()}, warnings

    answers: Dict[str, str] = {}
    duplicate_ids: List[str] = []

    for pos, heading in enumerate(headings):
        next_line = headings[pos + 1].line_index if pos + 1 < len(headings) else len(lines)
        body_lines = lines[heading.line_index + 1:next_line]
        if heading.trailing_text:
            body_lines.insert(0, heading.trailing_text)
        body = "\n".join(body_lines).strip()

        if heading.question_id in answers:
            duplicate_ids.append(heading.question_id)
            # Preserve all student material rather than silently replacing an
            # earlier section with a later duplicate heading.
            if body:
                if answers[heading.question_id]:
                    answers[heading.question_id] += "\n\n" + body
                else:
                    answers[heading.question_id] = body
        else:
            answers[heading.question_id] = body

    for qid in dict.fromkeys(duplicate_ids):
        warnings.append(f"duplicate_heading_for_{qid}")

    for qid in requested:
        if qid not in answers:
            warnings.append(f"missing_answer_for_{qid}")

    return answers, warnings


__all__ = [
    "FULL_SUBMISSION",
    "normalize_heading_question_id",
    "split_answers_by_question",
]
