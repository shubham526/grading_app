"""
Question-centric grading utilities for the Rubric Grading Tool.

v2.1.0 introduces a canonical ``question_id`` field that is intentionally
separate from the legacy question-number parsing used by the existing scoring
workflow.  This module owns the new question-centric data model:

* normalize/infer canonical IDs such as Q1, Q1A, Q2B
* group rubric criteria by canonical question ID
* naturally sort question IDs
* compute grading progress across saved assessment files

The existing best-N/selected scoring logic continues to use
``src.core.utils.extract_question_number`` and is not changed here.
"""

from __future__ import annotations

from dataclasses import dataclass
import glob
import json
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


UNASSIGNED = "UNASSIGNED"


# ---------------------------------------------------------------------------
# Question-ID normalization and inference
# ---------------------------------------------------------------------------

# Direct labels accepted by normalize_question_id().  The subpart may be
# parenthesized (Q2(b)) or directly attached (Q2B), but a word following a
# question number ("Q2 Correctness") must not be mistaken for a subpart.
_DIRECT_QUESTION_RE = re.compile(
    r"^\s*(?:QUESTION|PROBLEM|Q|P)\s*(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|([A-Z]))?\s*$",
    re.IGNORECASE,
)

_LONG_TITLE_RE = re.compile(
    r"\b(?:QUESTION|PROBLEM)\s*(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|([A-Z]))?",
    re.IGNORECASE,
)

_SHORT_TITLE_RE = re.compile(
    r"(?<![A-Z0-9])(?:Q|P)\s*(\d+)"
    r"(?:\s*\(\s*([A-Z])\s*\)|([A-Z]))?",
    re.IGNORECASE,
)

_CANONICAL_QUESTION_RE = re.compile(r"^Q(\d+)([A-Z]+)?$", re.IGNORECASE)


def _canonical_question_id(number: str, subpart: Optional[str] = None) -> str:
    """Build a canonical question ID from a numeric question and subpart."""
    # int() removes harmless leading zeroes while preserving natural semantics.
    normalized_number = str(int(number))
    suffix = (subpart or "").upper()
    return f"Q{normalized_number}{suffix}"


def normalize_question_id(raw: str) -> Optional[str]:
    """
    Normalize a raw question label to canonical form.

    Examples:
        "question 1" -> "Q1"
        "Problem 2"  -> "Q2"
        "q3a"        -> "Q3A"
        "Q4(b)"      -> "Q4B"

    Returns ``None`` when ``raw`` is not a supported question label.
    """
    if not isinstance(raw, str):
        return None

    value = raw.strip()
    if not value:
        return None

    if value.upper() == UNASSIGNED:
        return UNASSIGNED

    match = _DIRECT_QUESTION_RE.fullmatch(value)
    if not match:
        return None

    number = match.group(1)
    subpart = match.group(2) or match.group(3)
    return _canonical_question_id(number, subpart)


def infer_question_id_from_title(title: str) -> Optional[str]:
    """
    Infer a normalized question ID from a rubric criterion title.

    Supported examples:
        "Question 2 - Runtime Analysis" -> "Q2"
        "Q2 Correctness Proof"          -> "Q2"
        "Problem 3: DP Recurrence"      -> "Q3"
        "P4 Reduction"                  -> "Q4"
        "Question 1(a)"                 -> "Q1A"
        "Q2(b) Runtime"                 -> "Q2B"

    Returns ``None`` if no supported question label can be inferred.
    """
    if not isinstance(title, str):
        return None

    value = title.strip()
    if not value:
        return None

    # If the entire title is itself a question label, normalization is the
    # strictest and clearest interpretation.
    normalized = normalize_question_id(value)
    if normalized and normalized != UNASSIGNED:
        return normalized

    # Prefer the explicit words Question/Problem before the shorter Q/P forms.
    match = _LONG_TITLE_RE.search(value)
    if not match:
        match = _SHORT_TITLE_RE.search(value)
    if not match:
        return None

    number = match.group(1)
    subpart = match.group(2) or match.group(3)
    return _canonical_question_id(number, subpart)


# ---------------------------------------------------------------------------
# Sorting and grouping
# ---------------------------------------------------------------------------

def _question_sort_key(question_id: str) -> Tuple:
    """Internal natural-sort key for canonical and fallback question IDs."""
    if question_id == UNASSIGNED:
        return (2,)

    match = _CANONICAL_QUESTION_RE.fullmatch(question_id or "")
    if match:
        number = int(match.group(1))
        suffix = (match.group(2) or "").upper()
        # Empty suffix sorts before A/B/etc., giving Q1, Q1A, Q1B, Q2.
        return (0, number, suffix)

    # Explicit-but-noncanonical IDs are retained rather than dropped.  They
    # sort after canonical questions but before UNASSIGNED.
    return (1, str(question_id).casefold())


def sort_question_ids(question_ids: Sequence[str]) -> List[str]:
    """
    Return question IDs in natural order.

    Example:
        ["Q10", "Q1B", "Q2", "Q1", "Q1A"]
        -> ["Q1", "Q1A", "Q1B", "Q2", "Q10"]

    ``UNASSIGNED`` is always placed last when present.
    """
    return sorted(list(question_ids), key=_question_sort_key)


def resolve_criterion_question_id(criterion: dict) -> str:
    """Resolve a criterion to an explicit, inferred, or UNASSIGNED question ID."""
    raw_qid = criterion.get("question_id")

    if raw_qid is not None and str(raw_qid).strip():
        raw_text = str(raw_qid).strip()
        normalized = normalize_question_id(raw_text)
        if normalized:
            return normalized
        # Preserve a non-empty explicit value instead of silently discarding it.
        return raw_text.upper()

    inferred = infer_question_id_from_title(criterion.get("title", ""))
    return inferred or UNASSIGNED


def group_criteria_by_question(rubric_data: dict) -> Dict[str, List[dict]]:
    """
    Group rubric criteria by question ID.

    Rules:
      1. Prefer an explicit ``criterion["question_id"]``.
      2. If missing, infer from the criterion title.
      3. Criteria with no resolvable question ID are placed under UNASSIGNED.
      4. No criterion is dropped.
    """
    groups: Dict[str, List[dict]] = {}

    for criterion in rubric_data.get("criteria", []):
        if not isinstance(criterion, dict):
            continue
        qid = resolve_criterion_question_id(criterion)
        groups.setdefault(qid, []).append(criterion)

    return groups


def get_question_ids(
    rubric_data: dict,
    include_unassigned: bool = False,
) -> List[str]:
    """
    Return naturally sorted question IDs found in a rubric.

    ``UNASSIGNED`` is omitted by default and appended at the end when
    ``include_unassigned=True`` and such criteria actually exist.
    """
    groups = group_criteria_by_question(rubric_data)
    ids = [qid for qid in groups.keys() if qid != UNASSIGNED]
    result = sort_question_ids(ids)

    if include_unassigned and UNASSIGNED in groups:
        result.append(UNASSIGNED)

    return result


# ---------------------------------------------------------------------------
# Criterion grading state
# ---------------------------------------------------------------------------

def is_criterion_graded(criterion: dict) -> bool:
    """
    Return whether a saved criterion should be considered graded.

    v2.1 assessments may contain an explicit ``grading_status.graded`` flag.
    When that flag is present it is authoritative, which lets the application
    distinguish an untouched criterion from a legitimately awarded zero.

    Legacy assessments have no grading_status, so they use the design-doc
    fallback: a criterion is graded when ``points_awarded is not None``.
    """
    status = criterion.get("grading_status")
    if isinstance(status, dict) and "graded" in status:
        return bool(status.get("graded"))

    return criterion.get("points_awarded") is not None


# ---------------------------------------------------------------------------
# Question progress across saved assessments
# ---------------------------------------------------------------------------

@dataclass
class QuestionProgress:
    question_id: str
    total_students: int
    graded_students: int
    partially_graded_students: int
    ungraded_students: int


@dataclass
class OverallGradingProgress:
    """Criterion-level progress across a grading session."""

    total_criteria: int
    graded_criteria: int
    ungraded_criteria: int



def _load_assessment_records(assessments_dir: str) -> List[Tuple[str, dict]]:
    """Load assessment-like JSON files from a directory, ignoring unrelated JSON."""
    if not assessments_dir or not os.path.isdir(assessments_dir):
        return []

    records: List[Tuple[str, dict]] = []
    for path in sorted(glob.glob(os.path.join(assessments_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue

        if not isinstance(data, dict):
            continue
        if not isinstance(data.get("criteria"), list):
            continue
        # A rubric/report JSON can also contain criteria.  Student identity is
        # required before a file is treated as an assessment record.
        if not (data.get("student_id") or data.get("student_name")):
            continue

        records.append((path, data))

    return records


def _student_lookup_key(value: object) -> str:
    """Normalize student identifiers for matching roster IDs/names to files."""
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _assessment_aliases(path: str, assessment: dict) -> Iterable[str]:
    """Yield normalized aliases that may identify a saved assessment."""
    values = [
        assessment.get("student_id"),
        assessment.get("student_name"),
        os.path.splitext(os.path.basename(path))[0],
    ]
    for value in values:
        key = _student_lookup_key(value)
        if key:
            yield key


def _select_student_assessments(
    records: List[Tuple[str, dict]],
    student_ids: Optional[Sequence[str]],
) -> List[Optional[dict]]:
    """
    Resolve assessment records for the requested students.

    Missing requested students are represented by ``None`` so they count as
    ungraded, as required by the v2.1 design.
    """
    if student_ids is None:
        return [assessment for _, assessment in records]

    alias_map: Dict[str, dict] = {}
    for path, assessment in records:
        for alias in _assessment_aliases(path, assessment):
            alias_map.setdefault(alias, assessment)

    selected: List[Optional[dict]] = []
    for student_id in student_ids:
        selected.append(alias_map.get(_student_lookup_key(student_id)))
    return selected


def _find_saved_criterion(assessment: dict, rubric_criterion: dict) -> Optional[dict]:
    """Match a saved criterion to a rubric criterion, preferring stable ID."""
    saved_criteria = assessment.get("criteria", []) if assessment else []
    rubric_id = rubric_criterion.get("id")
    rubric_title = rubric_criterion.get("title", "")

    if rubric_id:
        for saved in saved_criteria:
            if saved.get("id") == rubric_id:
                return saved

        # Legacy assessment fallback: only title-match a saved criterion that
        # itself lacks a stable ID.
        for saved in saved_criteria:
            if not saved.get("id") and saved.get("title", "") == rubric_title:
                return saved
        return None

    # Legacy rubric criterion without an ID: title matching is the only option.
    for saved in saved_criteria:
        if saved.get("title", "") == rubric_title:
            return saved
    return None


def _classify_question_for_student(
    assessment: Optional[dict],
    question_criteria: Sequence[dict],
) -> str:
    """Return 'graded', 'partial', or 'ungraded' for one student/question."""
    if not assessment or not question_criteria:
        return "ungraded"

    graded_flags: List[bool] = []
    for rubric_criterion in question_criteria:
        saved = _find_saved_criterion(assessment, rubric_criterion)
        graded_flags.append(bool(saved) and is_criterion_graded(saved))

    if graded_flags and all(graded_flags):
        return "graded"
    if any(graded_flags):
        return "partial"
    return "ungraded"


def compute_question_progress(
    assessments_dir: str,
    rubric_data: dict,
    question_id: str,
    student_ids: Optional[Sequence[str]] = None,
) -> QuestionProgress:
    """
    Compute grading progress for one question across all students.

    A student is fully graded when every criterion for the question is graded,
    partially graded when at least one but not all are graded, and ungraded
    when none are graded.  When ``student_ids`` is supplied, missing assessment
    files count as ungraded students.
    """
    if question_id == UNASSIGNED:
        resolved_qid = UNASSIGNED
    else:
        resolved_qid = normalize_question_id(question_id) or str(question_id).strip().upper()

    groups = group_criteria_by_question(rubric_data)
    question_criteria = groups.get(resolved_qid, [])

    records = _load_assessment_records(assessments_dir)
    assessments = _select_student_assessments(records, student_ids)

    graded = 0
    partial = 0
    ungraded = 0

    for assessment in assessments:
        state = _classify_question_for_student(assessment, question_criteria)
        if state == "graded":
            graded += 1
        elif state == "partial":
            partial += 1
        else:
            ungraded += 1

    return QuestionProgress(
        question_id=resolved_qid,
        total_students=len(assessments),
        graded_students=graded,
        partially_graded_students=partial,
        ungraded_students=ungraded,
    )


def compute_all_question_progress(
    assessments_dir: str,
    rubric_data: dict,
    student_ids: Optional[Sequence[str]] = None,
) -> Dict[str, QuestionProgress]:
    """Compute grading progress for every question represented in the rubric."""
    progress: Dict[str, QuestionProgress] = {}
    for qid in get_question_ids(rubric_data, include_unassigned=True):
        progress[qid] = compute_question_progress(
            assessments_dir,
            rubric_data,
            qid,
            student_ids=student_ids,
        )
    return progress

def compute_overall_criteria_progress(
    assessments_dir: str,
    rubric_data: dict,
    student_ids: Optional[Sequence[str]] = None,
) -> OverallGradingProgress:
    """
    Compute criterion-level grading progress across all requested students.

    The denominator is ``number of rubric criteria × number of students``.
    Missing assessment files and missing saved criteria count as ungraded.
    Explicit ``grading_status`` remains authoritative, so an intentionally
    awarded zero is counted as graded while an untouched zero is not.
    """
    rubric_criteria = [
        criterion for criterion in rubric_data.get("criteria", [])
        if isinstance(criterion, dict)
    ]

    records = _load_assessment_records(assessments_dir)
    assessments = _select_student_assessments(records, student_ids)

    total = len(rubric_criteria) * len(assessments)
    graded = 0

    for assessment in assessments:
        if assessment is None:
            continue
        for rubric_criterion in rubric_criteria:
            saved = _find_saved_criterion(assessment, rubric_criterion)
            if saved is not None and is_criterion_graded(saved):
                graded += 1

    return OverallGradingProgress(
        total_criteria=total,
        graded_criteria=graded,
        ungraded_criteria=max(0, total - graded),
    )

