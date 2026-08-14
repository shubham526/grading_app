"""Shared-text extraction and side-by-side HTML helpers.

The v2.3.0 implementation intentionally favors explainable shared phrases over
fragile semantic or character-offset inference.
"""

from __future__ import annotations

from collections import Counter
from html import escape
from typing import Iterable

from .shingles import tokenize_for_similarity


def _effective_n(token_count: int, requested_n: int) -> int:
    if requested_n <= 0:
        raise ValueError("n must be a positive integer")
    if token_count <= 0:
        return requested_n
    if token_count < 10:
        return min(3, token_count)
    return requested_n


def _shingle_counter(tokens: list[str], n: int) -> Counter[tuple[str, ...]]:
    if not tokens:
        return Counter()
    effective_n = _effective_n(len(tokens), n)
    if len(tokens) < effective_n:
        return Counter()
    return Counter(
        tuple(tokens[index : index + effective_n])
        for index in range(len(tokens) - effective_n + 1)
    )


def find_shared_spans(
    text_a: str,
    text_b: str,
    n: int = 5,
    *,
    max_spans: int = 50,
) -> list[dict]:
    """Return deterministic shared normalized phrases.

    Each returned record contains:

    ``text``
        Human-readable normalized shared phrase.
    ``count_a`` / ``count_b``
        Number of occurrences in each answer.
    ``token_count``
        Number of tokens in the phrase.

    v2.3.0 uses normalized shared shingles rather than claiming precise
    character-offset alignment in the original source.
    """

    if n <= 0:
        raise ValueError("n must be a positive integer")
    if max_spans < 0:
        raise ValueError("max_spans must be non-negative")
    if max_spans == 0:
        return []

    tokens_a = tokenize_for_similarity(text_a or "")
    tokens_b = tokenize_for_similarity(text_b or "")
    if not tokens_a or not tokens_b:
        return []

    counter_a = _shingle_counter(tokens_a, n)
    counter_b = _shingle_counter(tokens_b, n)
    shared = set(counter_a) & set(counter_b)

    # Most repeated/shared phrases first; lexical tie-break keeps output stable.
    ordered = sorted(
        shared,
        key=lambda shingle: (
            -min(counter_a[shingle], counter_b[shingle]),
            -len(shingle),
            " ".join(shingle),
        ),
    )

    return [
        {
            "text": " ".join(shingle),
            "count_a": counter_a[shingle],
            "count_b": counter_b[shingle],
            "token_count": len(shingle),
        }
        for shingle in ordered[:max_spans]
    ]


def render_side_by_side_html(
    student_a: str,
    student_b: str,
    question_id: str,
    answer_a: str,
    answer_b: str,
    shared_spans: Iterable[dict] | None = None,
) -> str:
    """Render a safe, self-contained side-by-side question comparison fragment.

    Precise source-offset highlighting is intentionally not required in v2.3.0.
    The original answers are displayed side-by-side and normalized shared
    phrases are listed immediately below them.
    """

    spans = list(shared_spans or [])

    if spans:
        phrases = "\n".join(
            (
                "<li><code>"
                + escape(str(span.get("text", "")))
                + "</code>"
                + " <span class=\"shared-count\">"
                + escape(
                    f"(A: {span.get('count_a', 0)}, B: {span.get('count_b', 0)})"
                )
                + "</span></li>"
            )
            for span in spans
        )
    else:
        phrases = "<li><em>No shared phrase spans were identified.</em></li>"

    return f"""
<section class="question-comparison">
  <h4>Question {escape(str(question_id))}</h4>
  <div class="answer-grid">
    <article class="answer-panel">
      <h5>{escape(str(student_a))}</h5>
      <pre>{escape(str(answer_a or ""))}</pre>
    </article>
    <article class="answer-panel">
      <h5>{escape(str(student_b))}</h5>
      <pre>{escape(str(answer_b or ""))}</pre>
    </article>
  </div>
  <div class="shared-phrases">
    <strong>Shared phrases</strong>
    <ul>
      {phrases}
    </ul>
  </div>
</section>
""".strip()


__all__ = [
    "find_shared_spans",
    "render_side_by_side_html",
]
