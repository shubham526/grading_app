"""
ABET Scoring Engine — Rubric Grading Tool
==========================================

Core principle (Change #4):
    outcome_percentage = sum(awarded_i * weight_i) / sum(possible_i * weight_i) * 100

A criterion mapped to [SO1, SO6] with weight=1.0 contributes 100 % of its
points to SO1 *and* 100 % to SO6 independently (no splitting).

Performance bands and passing thresholds are **profile-driven** — they come
from the loaded OutcomeProfile rather than being hardcoded here.  The
DEFAULT_BANDS constant below is the fall-back only.

Evidence policies
-----------------
  "counted_only"  — criteria where counted=True  (default, best-N-of-M safe)
  "selected_only" — criteria where selected=True
  "all"           — all criteria regardless of flags

Generalisation notes
--------------------
* Internal field name: ``program_outcomes`` (canonical).
* Legacy field name:   ``abet_outcomes``    (still accepted, normalised on read).
* Scoring code uses whichever field the caller passes as ``outcome_key``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Assessment = dict
Criteria   = list


# ---------------------------------------------------------------------------
# Evidence policy
# ---------------------------------------------------------------------------

POLICY_COUNTED  = "counted_only"
POLICY_SELECTED = "selected_only"
POLICY_ALL      = "all"
DEFAULT_POLICY  = POLICY_COUNTED


def _criterion_included(criterion: dict, policy: str) -> bool:
    if policy == POLICY_ALL:
        return True
    if policy == POLICY_SELECTED:
        return criterion.get("selected", True)
    return criterion.get("counted", True)


# ---------------------------------------------------------------------------
# Field normalisation
# ---------------------------------------------------------------------------

def _get_outcome_ids(criterion: dict, outcome_key: str) -> List[str]:
    """
    Return outcome IDs from a criterion, accepting both the canonical name
    ``program_outcomes`` and the legacy name ``abet_outcomes``.

    If ``outcome_key`` is ``"program_outcomes"`` and the field is absent,
    fall back to ``"abet_outcomes"`` (and vice versa).
    """
    ids = criterion.get(outcome_key)
    if ids:
        return list(ids)
    # Try alternate field name
    alt = "abet_outcomes" if outcome_key == "program_outcomes" else "program_outcomes"
    return list(criterion.get(alt, []))


# ---------------------------------------------------------------------------
# Per-student outcome scoring
# ---------------------------------------------------------------------------

def score_student_outcomes(
    criteria: Criteria,
    outcome_key: str,
    policy: str = DEFAULT_POLICY,
    weights: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """
    Compute outcome percentages for one student from their criteria list.

    Args:
        criteria:    List of criterion dicts from a saved assessment.
        outcome_key: "course_outcomes", "program_outcomes", or "abet_outcomes".
        policy:      Evidence inclusion policy.
        weights:     Optional {criterion_id: {outcome_id: weight}}.

    Returns:
        {outcome_id: percentage}  Only outcomes with ≥1 criterion are included.
    """
    earned:   Dict[str, float] = defaultdict(float)
    possible: Dict[str, float] = defaultdict(float)

    for crit in criteria:
        if not _criterion_included(crit, policy):
            continue

        awarded = float(crit.get("points_awarded", 0))
        poss    = float(crit.get("points_possible", 0))
        if poss <= 0:
            continue

        outcome_ids = _get_outcome_ids(crit, outcome_key)
        crit_id    = crit.get("id",    "")
        crit_title = crit.get("title", "")

        for oid in outcome_ids:
            w = 1.0
            if weights:
                # Prefer ID-keyed lookup (new style rubrics)
                if crit_id and crit_id in weights and oid in weights[crit_id]:
                    w = float(weights[crit_id][oid])
                # Fall back to title-keyed (legacy ABETMapping files)
                elif crit_title and crit_title in weights and oid in weights[crit_title]:
                    w = float(weights[crit_title][oid])
            earned[oid]   += awarded * w
            possible[oid] += poss    * w

    return {
        oid: 100.0 * earned[oid] / possible[oid]
        for oid in possible
        if possible[oid] > 0
    }


# ---------------------------------------------------------------------------
# Multi-student aggregation
# ---------------------------------------------------------------------------

def calculate_lo_scores(
    assessments: List[Assessment],
    policy: str = DEFAULT_POLICY,
    weights: Optional[Dict[str, Dict[str, float]]] = None,
    profile=None,
) -> Dict[str, Dict]:
    """Aggregate course LO scores across student assessments."""
    return _aggregate_outcomes(assessments, "course_outcomes", policy, weights, profile)


def calculate_so_scores(
    assessments: List[Assessment],
    policy: str = DEFAULT_POLICY,
    weights: Optional[Dict[str, Dict[str, float]]] = None,
    profile=None,
) -> Dict[str, Dict]:
    """
    Aggregate program/ABET outcome scores across student assessments.
    Accepts ``program_outcomes`` or ``abet_outcomes`` interchangeably.
    """
    return _aggregate_outcomes(assessments, "program_outcomes", policy, weights, profile)


def _aggregate_outcomes(
    assessments: List[Assessment],
    outcome_key: str,
    policy: str,
    weights: Optional[Dict[str, Dict[str, float]]],
    profile,
) -> Dict[str, Dict]:
    per_outcome: Dict[str, List[float]] = defaultdict(list)

    for assessment in assessments:
        criteria = assessment.get("criteria", [])
        student_scores = score_student_outcomes(criteria, outcome_key, policy, weights)
        for oid, pct in student_scores.items():
            per_outcome[oid].append(pct)

    bands = _bands_from_profile(profile)
    result: Dict[str, Dict] = {}
    for oid, percentages in per_outcome.items():
        arr         = np.array(percentages)
        band_counts = calculate_performance_bands(percentages, bands, profile)
        result[oid] = {
            "percentages":         percentages,
            "mean":                float(np.mean(arr)),
            "median":              float(np.median(arr)),
            "std_dev":             float(np.std(arr)),
            "min":                 float(np.min(arr)),
            "max":                 float(np.max(arr)),
            "count":               len(percentages),
            "band_counts":         band_counts,
            "proficient_plus_pct": _passing_pct(band_counts, profile),
        }
    return result


# ---------------------------------------------------------------------------
# Performance bands  (profile-driven)
# ---------------------------------------------------------------------------

# Canonical fall-back: Excellent/Adequate/Needs Improvement/Inadequate
DEFAULT_BANDS: Dict[str, Tuple[float, float]] = {
    "excellent":          (90.0, 100.0),
    "adequate":           (75.0,  89.99),
    "needs_improvement":  (40.0,  74.99),
    "inadequate":         ( 0.0,  39.99),
}

# Backward-compat alias with old name
LEGACY_BANDS: Dict[str, Tuple[float, float]] = {
    "exemplary":      (90.0, 100.0),
    "proficient":     (80.0,  89.99),
    "developing":     (70.0,  79.99),
    "unsatisfactory": ( 0.0,  69.99),
}

_DEFAULT_PASSING = ["excellent", "adequate", "exemplary", "proficient"]


def _bands_from_profile(profile) -> Dict[str, Tuple[float, float]]:
    if profile is not None and hasattr(profile, "performance_bands"):
        return profile.performance_bands
    return DEFAULT_BANDS


def _passing_bands_from_profile(profile) -> List[str]:
    if profile is not None and hasattr(profile, "passing_bands"):
        return profile.passing_bands
    return _DEFAULT_PASSING


def _passing_pct(band_counts: dict, profile) -> float:
    """Return the percentage of students in the passing bands."""
    passing = _passing_bands_from_profile(profile)
    total   = sum(v.get("count", 0) for k, v in band_counts.items()
                  if k not in ("adequate_or_higher", "proficient_or_higher"))
    if total == 0:
        return 0.0
    count = sum(band_counts.get(b, {}).get("count", 0) for b in passing)
    return count / total * 100.0


def calculate_performance_bands(
    percentages: List[float],
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
    profile=None,
) -> Dict[str, Dict]:
    """
    Categorise student percentages into performance bands.

    Band definitions are taken from:
      1. The ``profile`` argument (preferred — course-specific)
      2. The ``bands`` argument (explicit override)
      3. DEFAULT_BANDS (fallback)

    Scores are clamped to [0, 100] so bonus points above 100 still
    classify in the top band.

    Returns a dict with one entry per band name plus:
      ``adequate_or_higher``   — passing roll-up (canonical)
      ``proficient_or_higher`` — alias for backward compat
    """
    effective_bands = _bands_from_profile(profile) if profile else (bands or DEFAULT_BANDS)
    total  = len(percentages)
    result: Dict[str, Dict] = {}

    for band_name, (lo, hi) in effective_bands.items():
        count = sum(
            1 for p in percentages
            if lo <= min(max(p, 0.0), 100.0) <= hi
        )
        result[band_name] = {
            "count":      count,
            "percentage": (count / total * 100.0) if total > 0 else 0.0,
        }

    # Roll-up: sum all passing bands defined by the profile
    passing = _passing_bands_from_profile(profile)
    pass_count = sum(result.get(b, {}).get("count", 0) for b in passing)
    rollup = {
        "count":      pass_count,
        "percentage": (pass_count / total * 100.0) if total > 0 else 0.0,
    }
    result["adequate_or_higher"]   = rollup
    result["proficient_or_higher"] = rollup   # backward-compat alias

    return result


# ---------------------------------------------------------------------------
# Target checking
# ---------------------------------------------------------------------------

def check_targets(
    outcome_scores: Dict[str, Dict],
    target_pct: float = 70.0,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
    profile=None,
) -> Dict[str, Dict]:
    """
    Check whether each outcome meets the target.

    ``target_pct`` is used if supplied; otherwise the profile's
    ``default_target_pct`` is used.  The profile's ``passing_bands``
    determine which bands count as "passing".

    Also back-fills ``band_counts``, ``proficient_plus_pct``, and
    ``meets_target`` into ``outcome_scores[oid]`` so exports can read
    them directly from ``outcome_summary`` without a separate lookup.

    Returns:
        {outcome_id: {"proficient_plus_pct": float, "target": float,
                      "meets_target": bool, "band_counts": dict}}
    """
    effective_target = target_pct
    if profile is not None and hasattr(profile, "default_target_pct"):
        # If caller passed a non-default value, respect it; otherwise use profile default
        if target_pct == 70.0:
            effective_target = profile.default_target_pct

    results: Dict[str, Dict] = {}
    for oid, data in outcome_scores.items():
        band_counts = data.get("band_counts") or \
                      calculate_performance_bands(data.get("percentages", []), bands, profile)
        pass_pct = band_counts["adequate_or_higher"]["percentage"]
        meets    = pass_pct >= effective_target

        # Back-fill so exports always find consistent values in outcome_summary
        data["band_counts"]         = band_counts
        data["proficient_plus_pct"] = pass_pct
        data["meets_target"]        = meets

        results[oid] = {
            "proficient_plus_pct": pass_pct,
            "target":              effective_target,
            "meets_target":        meets,
            "band_counts":         band_counts,
        }
    return results


# ---------------------------------------------------------------------------
# Unmapped criteria detection
# ---------------------------------------------------------------------------

def find_unmapped_criteria(
    assessments: List[Assessment],
    outcome_key: str = "program_outcomes",
) -> List[Dict]:
    """
    Return deduplicated criteria that have no program/ABET outcome mapping.
    Accepts both ``program_outcomes`` and ``abet_outcomes`` as outcome_key.
    """
    seen: Dict[str, Dict] = {}
    for assessment in assessments:
        for crit in assessment.get("criteria", []):
            ids = _get_outcome_ids(crit, outcome_key)
            if not ids:
                cid = crit.get("id") or crit.get("title", "unknown")
                if cid not in seen:
                    seen[cid] = {
                        "id":              crit.get("id", ""),
                        "title":           crit.get("title", ""),
                        "points_possible": crit.get("points_possible", 0),
                        "selected":        crit.get("selected", False),
                        "counted":         crit.get("counted", False),
                    }
    return list(seen.values())
