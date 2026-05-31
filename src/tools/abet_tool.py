"""
ABET Tool — Rubric Grading Tool
================================

Orchestration layer on top of:
  abet_scoring.py    — all scoring math (profile-driven)
  abet_validation.py — validation
  abet_export.py     — file output

ABETMapping          — backward-compat, title-keyed legacy mapping
ABETAssessmentAnalyzer — main analyser; now accepts an OutcomeProfile
                         and passes it through to all scoring calls.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from src.tools.abet_scoring import (
    calculate_lo_scores,
    calculate_so_scores,
    calculate_performance_bands,
    check_targets,
    find_unmapped_criteria,
    DEFAULT_POLICY,
)


# ---------------------------------------------------------------------------
# ABETMapping  (backward-compatible, title-keyed)
# ---------------------------------------------------------------------------

class ABETMapping:
    """Legacy title-keyed ABET mapping.  Still used by the old UI dialog."""

    def __init__(self, rubric_path: Optional[str] = None):
        self.rubric_path    = rubric_path
        self.mappings:        Dict[str, List[str]]          = {}
        self.outcome_weights: Dict[str, Dict[str, float]]   = {}

    def add_mapping(self, criterion_title: str,
                    outcome_ids: List[str],
                    weights: Optional[Dict[str, float]] = None) -> None:
        self.mappings[criterion_title] = outcome_ids
        if weights:
            self.outcome_weights[criterion_title] = weights
        else:
            # Full weight to each outcome — no splitting
            self.outcome_weights[criterion_title] = {oid: 1.0 for oid in outcome_ids}

    def save_mapping(self, file_path: str) -> None:
        data = {
            "rubric_path":     self.rubric_path,
            "mappings":        self.mappings,
            "outcome_weights": self.outcome_weights,
            "created_date":    datetime.now().isoformat(),
        }
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    @classmethod
    def load_mapping(cls, file_path: str) -> "ABETMapping":
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        obj = cls(data.get("rubric_path"))
        obj.mappings       = data.get("mappings", {})
        obj.outcome_weights = data.get("outcome_weights", {})
        return obj


# ---------------------------------------------------------------------------
# ABETAssessmentAnalyzer
# ---------------------------------------------------------------------------

class ABETAssessmentAnalyzer:
    """
    Analyse a collection of student assessments for ABET/program reporting.

    Parameters
    ----------
    abet_mapping:    Optional legacy ABETMapping for title-based fallback.
    outcome_profile: Optional OutcomeProfile instance — drives band
                     definitions, passing threshold, and LO→PO derivation.
                     When provided, every scoring call uses the profile's
                     bands instead of the hard-coded defaults.
    """

    def __init__(self, abet_mapping: Optional[ABETMapping] = None,
                 outcome_profile=None):
        self.mapping         = abet_mapping
        self.outcome_profile = outcome_profile
        self.assessments: List[dict] = []

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def add_assessment(self, assessment_data: dict) -> None:
        self.assessments.append(assessment_data)

    def load_assessments_from_directory(self, directory: str) -> int:
        count = 0
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            if fname.startswith("abet"):
                continue
            path = os.path.join(directory, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if "criteria" in data:
                    self.add_assessment(data)
                    count += 1
            except Exception as exc:
                print(f"Error loading {fname}: {exc}")
        return count

    # ------------------------------------------------------------------
    # Prepare: inject outcomes where missing (legacy + LO-only derivation)
    # ------------------------------------------------------------------

    def _prepare_assessments(self) -> List[dict]:
        """
        Return deep-copied assessments with program_outcomes fully populated.

        Priority per criterion:
          1. Embedded program_outcomes / abet_outcomes present → keep as-is.
          2. Has course_outcomes but no program_outcomes → derive via profile.
          3. Neither → inject from legacy ABETMapping (title-keyed).
        """
        import copy
        prepared: List[dict] = []
        for assessment in self.assessments:
            a = copy.deepcopy(assessment)
            for crit in a.get("criteria", []):
                has_po = bool(
                    crit.get("program_outcomes") or crit.get("abet_outcomes")
                )
                has_lo = bool(crit.get("course_outcomes"))

                if has_po:
                    # Case 1: already has program/ABET outcomes
                    continue

                if has_lo and self.outcome_profile:
                    # Case 2: derive program outcomes from LOs via profile crosswalk
                    pos = self.outcome_profile.derive_program_from_los(
                        crit["course_outcomes"]
                    )
                    crit["program_outcomes"] = pos
                    crit["abet_outcomes"]    = pos   # keep alias in sync
                    continue

                # Case 3: legacy fallback
                title = crit.get("title", "")
                if self.mapping and title in self.mapping.mappings:
                    pos = list(self.mapping.mappings[title])
                    crit["program_outcomes"] = pos
                    crit["abet_outcomes"]    = pos   # alias

            prepared.append(a)
        return prepared

    def _build_legacy_weights(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Convert legacy title-keyed weights to criterion-id-keyed format."""
        if not self.mapping or not self.mapping.outcome_weights:
            return None
        return dict(self.mapping.outcome_weights)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def calculate_outcome_scores(self, policy: str = DEFAULT_POLICY) -> Dict[str, Dict]:
        """Aggregate program/ABET outcome scores (corrected formula)."""
        assessments    = self._prepare_assessments()
        legacy_weights = self._build_legacy_weights()
        return calculate_so_scores(assessments, policy,
                                   weights=legacy_weights,
                                   profile=self.outcome_profile)

    def calculate_lo_scores(self, policy: str = DEFAULT_POLICY) -> Dict[str, Dict]:
        """Aggregate course LO scores."""
        assessments    = self._prepare_assessments()
        legacy_weights = self._build_legacy_weights()
        return calculate_lo_scores(assessments, policy,
                                   weights=legacy_weights,
                                   profile=self.outcome_profile)

    def calculate_performance_levels(self, outcome_scores: Dict[str, Dict]) -> Dict[str, Dict]:
        """Categorise scores into performance bands using the loaded profile."""
        result: Dict[str, Dict] = {}
        for oid, data in outcome_scores.items():
            result[oid] = calculate_performance_bands(
                data.get("percentages", []),
                profile=self.outcome_profile,
            )
        return result

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_abet_report(
        self,
        output_path: str,
        course_info: Optional[dict] = None,
        policy: str = DEFAULT_POLICY,
    ) -> dict:
        """
        Generate a comprehensive ABET/program-outcome assessment report.

        ``course_info`` can override ``target_percentage``; otherwise the
        profile's ``default_target_pct`` is used.

        Returns the report dict and saves JSON to ``output_path``.
        """
        assessments    = self._prepare_assessments()
        legacy_weights = self._build_legacy_weights()
        profile        = self.outcome_profile

        # Use profile target if caller didn't specify one
        _ci            = course_info or {}
        target_pct     = float(_ci.get("target_percentage",
                                        profile.default_target_pct
                                        if profile else 70.0))

        so_scores = calculate_so_scores(assessments, policy,
                                        weights=legacy_weights, profile=profile)
        lo_scores = calculate_lo_scores(assessments, policy,
                                        weights=legacy_weights, profile=profile)

        # check_targets back-fills band_counts + meets_target into so/lo_scores
        so_targets = check_targets(so_scores, target_pct, profile=profile)
        lo_targets = check_targets(lo_scores, target_pct, profile=profile)
        unmapped   = find_unmapped_criteria(assessments, "program_outcomes")

        # Outcome descriptions from profile, or empty strings
        if profile:
            lo_desc = {lo: profile.lo_description(lo)  for lo in profile.lo_ids()}
            po_desc = {po: profile.po_description(po)  for po in profile.po_ids()}
        else:
            lo_desc = {lo: "" for lo in lo_scores}
            po_desc = {so: "" for so in so_scores}

        student_rows        = self._build_student_rows(assessments, policy, legacy_weights)
        criterion_breakdown = self._build_criterion_breakdown(assessments)

        report = {
            "report_type":    "assignment",
            "schema_version": "2.0",
            "report_date":    datetime.now().isoformat(),
            "course_info":    _ci,
            # Store which profile was used for traceability
            "profile_id":     profile.profile_id if profile else "",
            "num_students":   len(self.assessments),
            "outcome_summary": {
                "program_outcomes": so_scores,
                "abet_outcomes":    so_scores,   # alias for backward compat
                "course_outcomes":  lo_scores,
            },
            "meets_targets": {
                "program_outcomes": so_targets,
                "abet_outcomes":    so_targets,  # alias
                "course_outcomes":  lo_targets,
            },
            "outcome_descriptions": {
                "course_outcomes":  lo_desc,
                "program_outcomes": po_desc,
                "abet_outcomes":    po_desc,     # alias
            },
            "student_outcome_scores":       student_rows,
            "criterion_outcome_breakdown":  criterion_breakdown,
            "unmapped_criteria":            unmapped,
            "mapping_warnings":             [],
            "summary": self._generate_summary(so_scores, so_targets, _ci, target_pct),
        }

        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_student_rows(self, assessments, policy, weights):
        from src.tools.abet_scoring import score_student_outcomes
        profile = self.outcome_profile
        rows = []
        for assessment in assessments:
            criteria = assessment.get("criteria", [])
            rows.append({
                "student_name": assessment.get("student_name", ""),
                "lo_scores": score_student_outcomes(
                    criteria, "course_outcomes", policy, weights),
                "so_scores": score_student_outcomes(
                    criteria, "program_outcomes", policy, weights),
            })
        return rows

    def _build_criterion_breakdown(self, assessments):
        import numpy as np
        from collections import defaultdict as _dd
        crit_stats:  Dict[str, dict]        = {}
        crit_scores: Dict[str, List[float]] = _dd(list)

        for assessment in assessments:
            for crit in assessment.get("criteria", []):
                cid   = crit.get("id") or crit.get("title", "unknown")
                poss  = float(crit.get("points_possible", 0))
                award = float(crit.get("points_awarded",  0))
                po_ids = list(
                    crit.get("program_outcomes") or crit.get("abet_outcomes") or []
                )

                if cid not in crit_stats:
                    crit_stats[cid] = {
                        "id":              crit.get("id", ""),
                        "title":           crit.get("title", ""),
                        "points":          poss,
                        "course_outcomes": list(crit.get("course_outcomes", [])),
                        "program_outcomes": po_ids,
                        "abet_outcomes":   po_ids,   # alias
                        "students_counted": 0,
                    }
                if crit.get("counted", True):
                    crit_stats[cid]["students_counted"] += 1
                    if poss > 0:
                        crit_scores[cid].append(award / poss * 100.0)

        result = []
        for cid, stats in crit_stats.items():
            scores = crit_scores[cid]
            stats["mean_pct"] = float(np.mean(scores)) if scores else None
            result.append(stats)
        return result

    def _generate_summary(self, so_scores, so_targets, course_info, target_pct):
        lines = [
            "Program Outcome Assessment Summary",
            "=" * 60, "",
            f"Total Students Assessed: {len(self.assessments)}",
            f"Target (passing or above): {target_pct:.0f}%",
            "",
        ]
        for oid in sorted(so_scores.keys()):
            s = so_scores[oid]
            t = so_targets.get(oid, {})
            lines += [
                f"{oid}:",
                f"  Mean:              {s.get('mean', 0):.1f}%",
                f"  Median:            {s.get('median', 0):.1f}%",
                f"  Std Dev:           {s.get('std_dev', 0):.1f}%",
                f"  Students Assessed: {s.get('count', 0)}",
                f"  Passing+:          {t.get('proficient_plus_pct', 0):.1f}%",
                f"  Meets Target:      {'Yes' if t.get('meets_target') else 'No'}",
                "",
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy helper
# ---------------------------------------------------------------------------

def create_mapping_from_dict(mapping_dict: dict) -> ABETMapping:
    mapping = ABETMapping()
    for title, data in mapping_dict.get("mappings", {}).items():
        outcomes = data.get("outcomes", [])
        weights  = data.get("weights",  {})
        mapping.add_mapping(title, outcomes, weights)
    return mapping
