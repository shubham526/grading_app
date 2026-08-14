"""Deterministic clustering for submission-similarity review.

v2.3.1 intentionally starts with a simple, explainable graph model:

* students are graph nodes;
* qualifying pairwise similarity results are graph edges;
* clusters are connected components containing at least two students.

This module does not infer collaboration, plagiarism, cheating, or misconduct.
Clusters are review aids only.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from .models import FLAG_RANK, PairSimilarity


DEFAULT_CLUSTER_MIN_FLAG_LEVEL = "high"


def _validate_min_flag_level(min_flag_level: str) -> str:
    level = str(min_flag_level or "").strip().lower()
    if level not in FLAG_RANK:
        allowed = ", ".join(FLAG_RANK)
        raise ValueError(
            f"Unsupported cluster minimum flag level {min_flag_level!r}; "
            f"expected one of: {allowed}"
        )
    return level


def _qualifies(pair: PairSimilarity, min_flag_level: str) -> bool:
    return FLAG_RANK[pair.flag_level] >= FLAG_RANK[min_flag_level]


def _canonical_pair_key(pair: PairSimilarity) -> tuple[str, str]:
    return tuple(sorted((pair.student_a, pair.student_b)))


def _ordered_pairs(pairs: Iterable[PairSimilarity]) -> list[PairSimilarity]:
    result = list(pairs)
    for pair in result:
        if not isinstance(pair, PairSimilarity):
            raise TypeError("pairs must contain PairSimilarity instances")
    return sorted(result, key=_canonical_pair_key)


def build_similarity_graph(
    pairs: Iterable[PairSimilarity],
    min_flag_level: str = DEFAULT_CLUSTER_MIN_FLAG_LEVEL,
) -> dict[str, set[str]]:
    """Build an undirected student graph from qualifying similarity pairs.

    All students observed in ``pairs`` are included as nodes, including
    students with no qualifying edges. Only pairs whose ``flag_level`` is at
    least ``min_flag_level`` create edges.
    """

    level = _validate_min_flag_level(min_flag_level)
    ordered = _ordered_pairs(pairs)

    graph: dict[str, set[str]] = {}
    for pair in ordered:
        graph.setdefault(pair.student_a, set())
        graph.setdefault(pair.student_b, set())

        if not _qualifies(pair, level):
            continue

        graph[pair.student_a].add(pair.student_b)
        graph[pair.student_b].add(pair.student_a)

    return {student: set(graph[student]) for student in sorted(graph)}


def _connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    components: list[list[str]] = []

    for start in sorted(graph):
        if start in visited:
            continue

        queue: deque[str] = deque([start])
        visited.add(start)
        component: list[str] = []

        while queue:
            student = queue.popleft()
            component.append(student)

            for neighbor in sorted(graph.get(student, ())):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)

        components.append(sorted(component))

    return components


def _questions_for_pair(
    pair: PairSimilarity,
    min_flag_level: str,
) -> set[str]:
    """Return question IDs that explain a qualifying edge when available."""

    questions: set[str] = set()
    threshold_rank = FLAG_RANK[min_flag_level]

    for qid, question in pair.question_similarities.items():
        if FLAG_RANK[question.flag_level] >= threshold_rank:
            questions.add(str(qid))

    normalized = pair.signals.get("normalized_text_hash")
    if isinstance(normalized, dict):
        details = normalized.get("details")
        if isinstance(details, dict):
            matching = details.get("matching_questions")
            if isinstance(matching, (list, tuple, set)):
                questions.update(
                    str(qid)
                    for qid in matching
                    if str(qid).strip()
                )

    # Exact file identity may not point to a particular question. If the pair
    # has a strongest question from another available signal, retaining it is
    # still useful for cluster review.
    if not questions and pair.most_similar_question:
        questions.add(str(pair.most_similar_question))

    return questions


def _signals_for_pair(
    pair: PairSimilarity,
    min_flag_level: str,
) -> set[str]:
    """Return readable signal names supporting a qualifying edge.

    Deterministic v2.3.0 signals are included only when they materially support
    the pair at the requested cluster threshold. Advanced methods added later
    may explicitly register themselves in ``pair.signals`` and will be carried
    through without coupling clustering to a specific model/provider.
    """

    signals: set[str] = set()
    threshold_rank = FLAG_RANK[min_flag_level]

    if pair.exact_file_match:
        signals.add("exact_file_hash")

    if pair.normalized_text_match and threshold_rank <= FLAG_RANK["high"]:
        signals.add("normalized_text_hash")

    if any(
        FLAG_RANK[question.flag_level] >= threshold_rank
        for question in pair.question_similarities.values()
    ):
        signals.add("ngram_jaccard")

    # v2.3.1 advanced-report integration will add these keys only when the
    # corresponding signal participates in the pair result.
    for method in ("embedding_cosine", "pseudocode_structure"):
        if method in pair.signals:
            signals.add(method)

    return signals


def _component_edges(
    students: set[str],
    pairs: list[PairSimilarity],
    min_flag_level: str,
) -> list[PairSimilarity]:
    return [
        pair
        for pair in pairs
        if pair.student_a in students
        and pair.student_b in students
        and _qualifies(pair, min_flag_level)
    ]


def _cluster_payload(
    students: list[str],
    edges: list[PairSimilarity],
    min_flag_level: str,
) -> dict[str, Any]:
    max_similarity = max((float(pair.overall_score) for pair in edges), default=0.0)

    questions: set[str] = set()
    signals: set[str] = set()

    for pair in edges:
        questions.update(_questions_for_pair(pair, min_flag_level))
        signals.update(_signals_for_pair(pair, min_flag_level))

    return {
        "students": sorted(students),
        "size": len(students),
        "max_similarity": max_similarity,
        "questions": sorted(questions),
        "signals": sorted(signals),
    }


def find_similarity_clusters(
    pairs: Iterable[PairSimilarity],
    min_flag_level: str = DEFAULT_CLUSTER_MIN_FLAG_LEVEL,
) -> list[dict[str, Any]]:
    """Find deterministic connected-component clusters.

    Singleton components are intentionally omitted because they do not
    represent a similarity group.

    Cluster IDs are deterministic for a fixed report. Components are sorted by:
      1. larger size first;
      2. larger maximum similarity first;
      3. lexical student list.

    IDs are then assigned ``C1``, ``C2``, ...
    """

    level = _validate_min_flag_level(min_flag_level)
    ordered = _ordered_pairs(pairs)
    graph = build_similarity_graph(ordered, min_flag_level=level)

    payloads: list[dict[str, Any]] = []
    for component in _connected_components(graph):
        if len(component) < 2:
            continue

        student_set = set(component)
        edges = _component_edges(student_set, ordered, level)
        if not edges:
            continue

        payloads.append(_cluster_payload(component, edges, level))

    payloads.sort(
        key=lambda cluster: (
            -int(cluster["size"]),
            -float(cluster["max_similarity"]),
            tuple(cluster["students"]),
        )
    )

    result: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads, start=1):
        result.append(
            {
                "cluster_id": f"C{index}",
                **payload,
            }
        )

    return result


__all__ = [
    "DEFAULT_CLUSTER_MIN_FLAG_LEVEL",
    "build_similarity_graph",
    "find_similarity_clusters",
]
