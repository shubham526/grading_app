"""Versioned production prompt for handwriting transcription.

The wording is intentionally the same safety-focused prompt used in the
handwriting benchmark that selected Gemma 4 31B.  Prompt changes are therefore
explicitly versioned so later provenance/cache code can invalidate results when
transcription behavior changes.
"""

from __future__ import annotations

import hashlib


HANDWRITING_PROMPT_VERSION = "1.0"

HANDWRITING_TRANSCRIPTION_PROMPT = """Transcribe this handwritten student algorithms assignment page faithfully.

Requirements:
- Preserve all visible text.
- Preserve mathematical notation as LaTeX where possible.
- Preserve asymptotic notation such as O(n), Θ(n log n), and Ω(n).
- Preserve equations and recurrence relations.
- Preserve pseudocode structure and indentation.
- Preserve question and sub-question headings.
- Do not solve the problem.
- Do not correct the student's answer.
- Do not infer missing text.
- If something cannot be read confidently, write [ILLEGIBLE].
- Return only the transcription."""

HANDWRITING_PROMPT_SHA256 = hashlib.sha256(
    HANDWRITING_TRANSCRIPTION_PROMPT.encode("utf-8")
).hexdigest()


__all__ = [
    "HANDWRITING_PROMPT_SHA256",
    "HANDWRITING_PROMPT_VERSION",
    "HANDWRITING_TRANSCRIPTION_PROMPT",
]
