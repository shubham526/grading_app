"""
Semester ABET Report — Rubric Grading Tool
===========================================

Aggregates assignment-level ABET data across multiple assessments in a
semester into a single course-level report suitable for ABET documentation.

Usage (config-file mode):
    from src.tools.semester_abet_report import SemesterABETReport
    report = SemesterABETReport.from_config("CS2500_Fall2026/semester.json")
    report.aggregate()
    report.save("semester_report.json")
    report.export_all("semester_exports/")

Usage (folder-scan mode):
    report = SemesterABETReport.from_folder("CS2500_Fall2026/", profile_id="cs2500_algorithms")
    report.aggregate()

Semester config JSON format:
    {
        "course_code":  "CS 2500",
        "course_name":  "Algorithms",
        "semester":     "Fall 2026",
        "instructor":   "Shubham Chatterjee",
        "profile_id":   "cs2500_algorithms",
        "target_percentage": 75,
        "assessments": [
            {
                "assessment_id":   "F2026_PS1",
                "assessment_name": "Problem Set 1",
                "assessment_dir":  "PS1/assessments",
                "rubric_path":     "PS1/rubric.json",
                "include_in_abet": true,
                "weight":          1.0
            },
            ...
        ],
        "reflection":            "",
        "planned_improvements":  "",
        "notes_for_next_offering": ""
    }
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# SemesterABETReport
# ---------------------------------------------------------------------------

class SemesterABETReport:
    """
    Aggregates multiple assignment-level assessments into a semester report.

    Attributes
    ----------
    course_info:   dict with course_code, course_name, semester, etc.
    assessments:   list of assessment config dicts
    profile:       OutcomeProfile instance (optional but recommended)
    _assignment_data:  populated by aggregate() — per-assignment outcome scores
    _semester_data:    populated by aggregate() — aggregated semester scores
    """

    def __init__(self, course_info: dict, assessments: List[dict], profile=None):
        self.course_info  = course_info
        self.assessments  = assessments   # list of config dicts
        self.profile      = profile
        self._assignment_data: List[dict] = []   # one entry per assessment
        self._semester_data:   dict       = {}   # aggregated
        self._is_aggregated = False

    # ------------------------------------------------------------------
    # Factory constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config_path: str,
                    profile=None) -> "SemesterABETReport":
        """
        Load from a semester config JSON file.

        Args:
            config_path:  Path to semester config JSON.
            profile:      OutcomeProfile instance (loaded from profile_id if None).
        """
        with open(config_path, "r", encoding="utf-8") as fh:
            config = json.load(fh)

        base_dir = os.path.dirname(os.path.abspath(config_path))

        # Resolve relative paths relative to the config file location
        assessments = []
        for a in config.get("assessments", []):
            entry = dict(a)
            for key in ("assessment_dir", "rubric_path"):
                if key in entry and not os.path.isabs(entry[key]):
                    entry[key] = os.path.join(base_dir, entry[key])
            assessments.append(entry)

        course_info = {k: config.get(k, "") for k in (
            "course_code", "course_name", "semester", "instructor",
            "target_percentage", "reflection",
            "planned_improvements", "notes_for_next_offering",
        )}
        course_info["target_percentage"] = float(
            config.get("target_percentage", 75.0))

        # Load profile
        if profile is None:
            pid = config.get("profile_id", "")
            if pid:
                try:
                    from src.core.outcome_profile import load_profile
                    profile = load_profile(pid)
                except Exception:
                    pass

        return cls(course_info, assessments, profile)

    @classmethod
    def from_folder(cls, folder: str,
                    profile_id: str = "cs2500_algorithms",
                    profile=None,
                    course_info: Optional[dict] = None) -> "SemesterABETReport":
        """
        Auto-detect assessments by scanning a folder for sub-directories
        that contain an 'assessments/' sub-folder with JSON files.

        Expected layout:
            semester_folder/
                PS1/assessments/*.json
                PS2/assessments/*.json
                Midterm/assessments/*.json
                Final/assessments/*.json
        """
        if profile is None and profile_id:
            try:
                from src.core.outcome_profile import load_profile
                profile = load_profile(profile_id)
            except Exception:
                pass

        assessments = []
        for name in sorted(os.listdir(folder)):
            sub = os.path.join(folder, name)
            if not os.path.isdir(sub):
                continue
            adir = os.path.join(sub, "assessments")
            if not os.path.isdir(adir):
                continue
            # Check for at least one assessment JSON
            jsons = [f for f in os.listdir(adir) if f.endswith(".json")]
            if not jsons:
                continue
            # Look for optional rubric
            rubric_path = None
            for rname in ("rubric.json", f"{name.lower()}_rubric.json"):
                candidate = os.path.join(sub, rname)
                if os.path.exists(candidate):
                    rubric_path = candidate
                    break
            assessments.append({
                "assessment_id":   f"AUTO_{name.upper()}",
                "assessment_name": name,
                "assessment_dir":  adir,
                "rubric_path":     rubric_path or "",
                "include_in_abet": True,
                "weight":          1.0,
            })

        _ci = course_info or {}
        _ci.setdefault("target_percentage", 75.0)

        return cls(_ci, assessments, profile)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(self, policy: str = "counted_only") -> dict:
        """
        Load all assessment files and aggregate outcome scores.

        Weighting policy
        ----------------
        ``weight`` in the config applies to assignments, not to individual
        percentages.  Each student's percentage for a given outcome is
        accumulated as ``(percentage, weight)`` pairs.  The semester mean
        is then the weighted mean: ``sum(p * w) / sum(w)``.

        This avoids the bug where weight=2.0 would produce scores > 100%.

        Populates ``self._assignment_data`` and ``self._semester_data``.
        Returns the complete semester report dict.
        """
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        from src.tools.abet_scoring import check_targets, find_unmapped_criteria

        target = float(self.course_info.get("target_percentage", 75.0))
        self._assignment_data = []

        # Per-outcome accumulator: {oid: [(pct, weight), ...]}
        # Using (value, weight) pairs so we can compute a proper weighted mean.
        semester_so_pairs: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        semester_lo_pairs: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

        for config in self.assessments:
            if not config.get("include_in_abet", True):
                continue

            adir = config.get("assessment_dir", "")
            if not adir or not os.path.isdir(adir):
                self._assignment_data.append({
                    "assessment_id":        config.get("assessment_id", ""),
                    "assessment_name":      config.get("assessment_name", ""),
                    "error":                f"Directory not found: {adir}",
                    "so_scores":            {},
                    "lo_scores":            {},
                    "num_students":         0,
                    "student_outcome_scores": [],
                    "unmapped_criteria":    [],
                })
                continue

            analyzer = ABETAssessmentAnalyzer(outcome_profile=self.profile)
            count    = analyzer.load_assessments_from_directory(adir)

            so_scores = analyzer.calculate_outcome_scores(policy)
            lo_scores = analyzer.calculate_lo_scores(policy)
            check_targets(so_scores, target, profile=self.profile)
            check_targets(lo_scores, target, profile=self.profile)

            lo_covered = set(lo_scores.keys())
            so_covered = set(so_scores.keys())

            weight = float(config.get("weight", 1.0))

            # Accumulate as (percentage, weight) pairs — NOT pct * weight
            for oid, data in so_scores.items():
                for pct in data.get("percentages", []):
                    semester_so_pairs[oid].append((pct, weight))
            for oid, data in lo_scores.items():
                for pct in data.get("percentages", []):
                    semester_lo_pairs[oid].append((pct, weight))

            # Fix 2: per-student outcome rows for student-level export
            prepared = analyzer._prepare_assessments()
            legacy_w = analyzer._build_legacy_weights()
            student_rows = analyzer._build_student_rows(prepared, policy, legacy_w)

            # Fix 3: unmapped criteria for this assignment
            unmapped = find_unmapped_criteria(prepared, "program_outcomes")

            self._assignment_data.append({
                "assessment_id":        config.get("assessment_id", ""),
                "assessment_name":      config.get("assessment_name", ""),
                "assessment_dir":       adir,
                "num_students":         count,
                "weight":               weight,
                "so_scores":            so_scores,
                "lo_scores":            lo_scores,
                "lo_covered":           sorted(lo_covered),
                "so_covered":           sorted(so_covered),
                "student_outcome_scores": student_rows,  # Fix 2
                "unmapped_criteria":    unmapped,        # Fix 3
            })

        # Compute semester-level aggregates from weighted pairs
        self._semester_data = self._build_semester_summary(
            semester_so_pairs, semester_lo_pairs, target)

        self._is_aggregated = True
        return self.to_dict()

    def _build_semester_summary(self,
                                  semester_so_pairs: dict,
                                  semester_lo_pairs: dict,
                                  target: float) -> dict:
        """
        Build the semester-level outcome summary from (percentage, weight) pairs.

        Weighted mean = sum(p * w) / sum(w)  — correct for assignment weights.
        All other statistics (median, std dev) are computed on the raw
        percentage values (ignoring weight) since those are per-student evidence
        points, not per-assignment summaries.
        """
        from src.tools.abet_scoring import calculate_performance_bands, check_targets

        def _stats_from_pairs(pairs: List[Tuple[float, float]]) -> dict:
            """pairs = [(percentage, weight), ...]"""
            if not pairs:
                return {"percentages": [], "mean": 0, "median": 0,
                        "std_dev": 0, "min": 0, "max": 0, "count": 0,
                        "band_counts": {}, "proficient_plus_pct": 0.0}

            percentages = [p for p, _ in pairs]
            weights     = [w for _, w in pairs]
            total_w     = sum(weights)
            arr         = np.array(percentages)

            # Weighted mean — correct for assignment-level weights
            weighted_mean = (sum(p * w for p, w in pairs) / total_w
                             if total_w > 0 else 0.0)

            band_counts = calculate_performance_bands(percentages,
                                                      profile=self.profile)
            return {
                "percentages":         percentages,
                "mean":                float(weighted_mean),
                "median":              float(np.median(arr)),
                "std_dev":             float(np.std(arr)),
                "min":                 float(np.min(arr)),
                "max":                 float(np.max(arr)),
                "count":               len(percentages),
                "band_counts":         band_counts,
                "proficient_plus_pct": band_counts["adequate_or_higher"]["percentage"],
            }

        so_agg = {oid: _stats_from_pairs(pairs)
                  for oid, pairs in semester_so_pairs.items()}
        lo_agg = {oid: _stats_from_pairs(pairs)
                  for oid, pairs in semester_lo_pairs.items()}
        check_targets(so_agg, target, profile=self.profile)
        check_targets(lo_agg, target, profile=self.profile)

        # Evidence coverage matrix: {assessment_name: {lo_id: bool}}
        coverage: Dict[str, Dict[str, bool]] = {}
        all_los: set = set()
        all_sos: set = set()
        for asmnt in self._assignment_data:
            cov: Dict[str, bool] = {}
            for lo in asmnt.get("lo_covered", []):
                cov[lo] = True
                all_los.add(lo)
            coverage[asmnt.get("assessment_name",
                               asmnt.get("assessment_id", ""))] = cov
            all_sos.update(asmnt.get("so_covered", []))

        # Outcome-by-assessment table: {outcome_id: {assessment_name: mean%}}
        by_assessment_so: Dict[str, Dict[str, Optional[float]]] = defaultdict(dict)
        by_assessment_lo: Dict[str, Dict[str, Optional[float]]] = defaultdict(dict)
        for asmnt in self._assignment_data:
            name = asmnt.get("assessment_name", asmnt.get("assessment_id", ""))
            for oid, data in asmnt.get("so_scores", {}).items():
                by_assessment_so[oid][name] = data.get("mean")
            for oid, data in asmnt.get("lo_scores", {}).items():
                by_assessment_lo[oid][name] = data.get("mean")

        return {
            "program_outcomes":  so_agg,
            "course_outcomes":   lo_agg,
            "by_assessment_so":  dict(by_assessment_so),
            "by_assessment_lo":  dict(by_assessment_lo),
            "coverage_matrix":   coverage,
            "all_lo_ids":        sorted(all_los),
            "all_so_ids":        sorted(all_sos),
        }

    # ------------------------------------------------------------------
    # Report dict
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return the full semester report as a serialisable dict."""
        if not self._is_aggregated:
            raise RuntimeError("Call aggregate() before to_dict()")

        profile_id = self.profile.profile_id if self.profile else ""

        # Outcome descriptions
        lo_desc, so_desc = {}, {}
        if self.profile:
            lo_desc = {lo: self.profile.lo_description(lo)
                       for lo in self.profile.lo_ids()}
            so_desc = {po: self.profile.po_description(po)
                       for po in self.profile.po_ids()}

        return {
            "report_type":    "semester",
            "schema_version": "2.0",
            "report_date":    datetime.now().isoformat(),
            "course_info":    self.course_info,
            "profile_id":     profile_id,
            "num_assessments": len([a for a in self._assignment_data
                                    if "error" not in a]),
            "outcome_descriptions": {
                "course_outcomes":  lo_desc,
                "program_outcomes": so_desc,
            },
            "semester_summary": self._semester_data,
            "assignment_details": self._assignment_data,
            "closing_the_loop": {
                "reflection":              self.course_info.get("reflection", ""),
                "planned_improvements":    self.course_info.get("planned_improvements", ""),
                "notes_for_next_offering": self.course_info.get("notes_for_next_offering", ""),
            },
        }

    # ------------------------------------------------------------------
    # Save / export
    # ------------------------------------------------------------------

    def save(self, output_path: str) -> str:
        """Save the report as JSON.  Returns output_path."""
        report = self.to_dict()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        return output_path

    def export_all(self, output_dir: str) -> List[str]:
        """Export JSON + CSV + XLSX to output_dir.  Returns list of paths written."""
        from src.tools.abet_export import export_semester_report
        report = self.to_dict()
        return export_semester_report(report, output_dir)
