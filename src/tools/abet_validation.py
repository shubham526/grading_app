"""
ABET Validation Engine — Rubric Grading Tool
============================================

Validates rubric files and assessment collections before report generation.

Severity levels:
    ERROR   — report cannot be generated safely
    WARNING — report can be generated but should be reviewed
    INFO    — useful note
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Result dataclass (plain dict for simplicity / JSON serialisability)
# ---------------------------------------------------------------------------

def _issue(level: str, code: str, message: str, criterion_id: str = "") -> dict:
    return {"level": level, "code": code, "message": message,
            "criterion_id": criterion_id}


ERROR   = "ERROR"
WARNING = "WARNING"
INFO    = "INFO"


# ---------------------------------------------------------------------------
# Rubric-level validation
# ---------------------------------------------------------------------------

def validate_rubric(
    rubric: dict,
    known_lo_ids: Optional[List[str]] = None,
    known_so_ids: Optional[List[str]] = None,
) -> List[dict]:
    """
    Validate a loaded rubric dict.

    Args:
        rubric:        The rubric dict (after loading / ID generation).
        known_lo_ids:  List of valid LO IDs from an outcome profile (optional).
        known_so_ids:  List of valid SO IDs from an outcome profile (optional).

    Returns:
        List of issue dicts sorted by severity (ERROR first).
    """
    issues: List[dict] = []
    criteria = rubric.get("criteria", [])

    if not criteria:
        issues.append(_issue(ERROR, "NO_CRITERIA",
                             "Rubric contains no criteria."))
        return issues

    id_counts: Counter = Counter(c.get("id", "") for c in criteria if c.get("id"))

    for idx, crit in enumerate(criteria):
        cid   = crit.get("id", "")
        title = crit.get("title", f"criterion_{idx}")

        # Missing ID
        if not cid:
            issues.append(_issue(ERROR, "MISSING_ID",
                                 f"Criterion '{title}' (index {idx}) has no stable ID.",
                                 cid))

        # Duplicate ID
        elif id_counts[cid] > 1:
            issues.append(_issue(ERROR, "DUPLICATE_ID",
                                 f"Duplicate criterion ID '{cid}'.", cid))

        # No LO mapping
        if not crit.get("course_outcomes"):
            issues.append(_issue(WARNING, "NO_LO_MAPPING",
                                 f"Criterion '{cid or title}' has no course outcome (LO) mapping.",
                                 cid))

        # No program/ABET outcome mapping — accept either field name
        has_po = bool(crit.get("program_outcomes") or crit.get("abet_outcomes"))
        if not has_po:
            issues.append(_issue(WARNING, "NO_SO_MAPPING",
                                 f"Criterion '{cid or title}' has no program/ABET outcome mapping.",
                                 cid))

        # Unknown LO IDs
        if known_lo_ids:
            for lo in crit.get("course_outcomes", []):
                if lo not in known_lo_ids:
                    issues.append(_issue(ERROR, "UNKNOWN_LO",
                                         f"Criterion '{cid or title}' maps to undefined LO '{lo}'.",
                                         cid))

        # Unknown program/ABET outcome IDs — check both field names
        if known_so_ids:
            po_list = list(crit.get("program_outcomes") or crit.get("abet_outcomes") or [])
            for so in po_list:
                if so not in known_so_ids:
                    issues.append(_issue(ERROR, "UNKNOWN_SO",
                                         f"Criterion '{cid or title}' maps to undefined outcome '{so}'.",
                                         cid))

    return _sort_issues(issues)


# ---------------------------------------------------------------------------
# Assessment-collection validation
# ---------------------------------------------------------------------------

def validate_assessments(
    rubric: dict,
    assessments: List[dict],
    known_lo_ids: Optional[List[str]] = None,
    known_so_ids: Optional[List[str]] = None,
    policy: str = "counted_only",
) -> List[dict]:
    """
    Cross-validate a collection of assessment JSONs against the rubric.

    Args:
        rubric:        The loaded rubric dict.
        assessments:   List of loaded assessment dicts.
        known_lo_ids:  Valid LO IDs.
        known_so_ids:  Valid SO IDs.
        policy:        Evidence policy (affects "no evidence" warnings).

    Returns:
        List of issue dicts.
    """
    issues: List[dict] = []
    if not assessments:
        issues.append(_issue(WARNING, "NO_ASSESSMENTS",
                             "No assessment files found in the selected directory."))
        return issues

    rubric_ids: Dict[str, dict] = {
        c.get("id", ""): c for c in rubric.get("criteria", []) if c.get("id")
    }
    rubric_titles: Dict[str, dict] = {
        c.get("title", ""): c for c in rubric.get("criteria", [])
    }

    # Track which rubric criteria appear in at least one assessment
    seen_in_assessments: set = set()

    for aidx, assessment in enumerate(assessments):
        student = assessment.get("student_name", f"assessment_{aidx}")

        for crit in assessment.get("criteria", []):
            cid   = crit.get("id", "")
            title = crit.get("title", "")
            poss_assessment = crit.get("points_possible", 0)

            # Title-based fallback used?
            if not cid:
                issues.append(_issue(INFO, "TITLE_FALLBACK",
                                     f"[{student}] Criterion '{title}' matched by title "
                                     f"(no stable ID in assessment)."))
                rubric_crit = rubric_titles.get(title)
            else:
                rubric_crit = rubric_ids.get(cid)
                if rubric_crit:
                    seen_in_assessments.add(cid)

            # Criterion not in rubric
            if not rubric_crit:
                issues.append(_issue(WARNING, "CRITERION_NOT_IN_RUBRIC",
                                     f"[{student}] Criterion '{cid or title}' not found in rubric."))
                continue

            # Points mismatch
            poss_rubric = rubric_crit.get("points", 0)
            if poss_rubric and poss_assessment and poss_rubric != poss_assessment:
                issues.append(_issue(WARNING, "POINTS_MISMATCH",
                                     f"[{student}] Criterion '{cid or title}': "
                                     f"rubric has {poss_rubric} pts, assessment has {poss_assessment} pts."))

    # Rubric criteria that never appear in any assessment
    for cid, crit in rubric_ids.items():
        if cid and cid not in seen_in_assessments:
            issues.append(_issue(INFO, "CRITERION_NEVER_ASSESSED",
                                 f"Rubric criterion '{cid}' never appears in any assessment file.",
                                 cid))

    # Outcomes with no evidence under the chosen policy
    from src.tools.abet_scoring import find_unmapped_criteria
    unmapped = find_unmapped_criteria(assessments, "program_outcomes")
    if unmapped:
        issues.append(_issue(INFO, "UNMAPPED_CRITERIA",
                             f"{len(unmapped)} criterion/criteria in assessments have no program/ABET outcome mapping."))

    # Check that every known SO/LO has at least one mapped criterion
    all_lo_in_assessments: set = set()
    all_so_in_assessments: set = set()
    for assessment in assessments:
        for crit in assessment.get("criteria", []):
            for lo in crit.get("course_outcomes", []):
                all_lo_in_assessments.add(lo)
            # Accept both field names
            for po in list(crit.get("program_outcomes") or crit.get("abet_outcomes") or []):
                all_so_in_assessments.add(po)

    if known_lo_ids:
        for lo in known_lo_ids:
            if lo not in all_lo_in_assessments:
                issues.append(_issue(WARNING, "NO_LO_EVIDENCE",
                                     f"LO '{lo}' has no evidence in this assessment collection."))
    if known_so_ids:
        for so in known_so_ids:
            if so not in all_so_in_assessments:
                issues.append(_issue(WARNING, "NO_SO_EVIDENCE",
                                     f"Program outcome '{so}' has no evidence in this assessment collection."))

    return _sort_issues(issues)


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

def validate_all(
    rubric: dict,
    assessments: List[dict],
    known_lo_ids: Optional[List[str]] = None,
    known_so_ids: Optional[List[str]] = None,
    policy: str = "counted_only",
) -> List[dict]:
    """Run rubric + assessment validation and return merged, sorted issues."""
    issues  = validate_rubric(rubric, known_lo_ids, known_so_ids)
    issues += validate_assessments(rubric, assessments, known_lo_ids, known_so_ids, policy)
    return _sort_issues(issues)


def has_errors(issues: List[dict]) -> bool:
    """Return True if any issue is at ERROR level."""
    return any(i["level"] == ERROR for i in issues)


def issues_summary(issues: List[dict]) -> str:
    """Return a short human-readable summary string."""
    counts = Counter(i["level"] for i in issues)
    parts = []
    for level in (ERROR, WARNING, INFO):
        if counts[level]:
            parts.append(f"{counts[level]} {level}")
    return ", ".join(parts) if parts else "No issues found"


# ---------------------------------------------------------------------------
# Sorting helper
# ---------------------------------------------------------------------------

_LEVEL_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


def _sort_issues(issues: List[dict]) -> List[dict]:
    return sorted(issues, key=lambda i: _LEVEL_ORDER.get(i.get("level", INFO), 3))