"""
test_semester.py
================

Tests for semester-level ABET aggregation and export.

Covers:
  - SemesterABETReport.from_folder and from_config factory constructors
  - aggregate(): summary structure, SO mean arithmetic, multi-assignment
  - Correct weighted-mean formula (no score inflation from weights > 1)
  - Coverage matrix construction
  - student_outcome_scores present in assignment details
  - unmapped_criteria present in assignment details
  - save() writes valid JSON
  - export_semester_report(): all CSV files written with correct content
  - Error entries for missing directories carry required keys
  - profile_id and outcome descriptions in semester report
"""

import csv
import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_assessment(tmp_dir, student_name, q1_pct, q2_pct, prefix="PS1"):
    awarded1 = int(10 * q1_pct / 100)
    awarded2 = int(10 * q2_pct / 100)
    assessment = {
        "student_name": student_name,
        "criteria": [
            {"id": f"{prefix}_Q1", "title": "Q1 Runtime",
             "points_awarded": awarded1, "points_possible": 10,
             "course_outcomes": ["LO1"], "program_outcomes": ["SO1", "SO6"],
             "abet_outcomes": ["SO1", "SO6"], "assessment_tags": ["runtime"],
             "selected": True, "counted": True},
            {"id": f"{prefix}_Q2", "title": "Q2 Proof",
             "points_awarded": awarded2, "points_possible": 10,
             "course_outcomes": ["LO4"], "program_outcomes": ["SO1", "SO6"],
             "abet_outcomes": ["SO1", "SO6"], "assessment_tags": ["proof"],
             "selected": True, "counted": True},
        ],
        "total_awarded": awarded1 + awarded2,
        "total_possible": 20,
    }
    path = os.path.join(tmp_dir, f"{prefix}_{student_name.lower()}.json")
    with open(path, "w") as fh:
        json.dump(assessment, fh)
    return path


def _semester_folder(tmp_root, assignments):
    """
    assignments = [("PS1", {"Alice": (90, 80), "Bob": (70, 60)}), ...]
    Creates  tmp_root/<name>/assessments/*.json
    """
    for aname, students in assignments:
        adir = os.path.join(tmp_root, aname, "assessments")
        os.makedirs(adir, exist_ok=True)
        for student, (q1, q2) in students.items():
            _make_assessment(adir, student, q1, q2, prefix=aname)
    return tmp_root


# ---------------------------------------------------------------------------
# SemesterABETReport — factory constructors
# ---------------------------------------------------------------------------

class TestSemesterReport(unittest.TestCase):

    def test_from_folder_detects_assessments(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [
                ("PS1", {"Alice": (90, 80), "Bob": (70, 60)}),
                ("PS2", {"Alice": (85, 75), "Bob": (65, 55)}),
            ])
            obj = SemesterABETReport.from_folder(tmp)
            self.assertEqual(len(obj.assessments), 2)

    def test_from_config_file(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            adir = os.path.join(tmp, "PS1", "assessments")
            os.makedirs(adir)
            _make_assessment(adir, "Alice", 90, 90, "PS1")
            _make_assessment(adir, "Bob",   70, 70, "PS1")
            config = {
                "course_code": "CS 2500", "course_name": "Algorithms",
                "semester": "Fall 2026", "profile_id": "cs2500_algorithms",
                "target_percentage": 75.0,
                "assessments": [{"assessment_id": "F2026_PS1",
                                 "assessment_name": "Problem Set 1",
                                 "assessment_dir": adir,
                                 "include_in_abet": True, "weight": 1.0}],
                "reflection": "Students did well.",
            }
            cfg_path = os.path.join(tmp, "semester.json")
            with open(cfg_path, "w") as fh:
                json.dump(config, fh)
            obj    = SemesterABETReport.from_config(cfg_path)
            report = obj.aggregate()
            self.assertEqual(report["course_info"]["course_code"], "CS 2500")
            self.assertIn("SO1", report["semester_summary"]["program_outcomes"])
            self.assertEqual(report["closing_the_loop"]["reflection"],
                             "Students did well.")

    def test_aggregate_summary_structure(self):
        from src.tools.semester_abet_report import SemesterABETReport
        from src.core.outcome_profile import load_default_profile
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (100, 100), "Bob": (80, 80)})])
            obj    = SemesterABETReport.from_folder(
                tmp, profile=load_default_profile(),
                course_info={"target_percentage": 75.0})
            report = obj.aggregate()
            self.assertIn("semester_summary",  report)
            self.assertIn("program_outcomes",  report["semester_summary"])
            self.assertIn("coverage_matrix",   report["semester_summary"])
            self.assertIn("by_assessment_so",  report["semester_summary"])
            self.assertIn("assignment_details", report)

    def test_so1_mean_correct(self):
        """Alice 100% + Bob 80% → SO1 mean = 90%."""
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (100, 100), "Bob": (80, 80)})])
            report = SemesterABETReport.from_folder(tmp).aggregate()
            so1 = report["semester_summary"]["program_outcomes"].get("SO1")
            self.assertIsNotNone(so1)
            self.assertAlmostEqual(so1["mean"], 90.0, places=1)

    def test_multiple_assignments_all_in_details(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [
                ("PS1", {"Alice": (80, 80)}),
                ("PS2", {"Alice": (60, 60)}),
            ])
            report = SemesterABETReport.from_folder(tmp).aggregate()
            ok = [d for d in report["assignment_details"] if "error" not in d]
            self.assertEqual(len(ok), 2)

    def test_coverage_matrix(self):
        """LO1 must be covered in every assignment containing a LO1 criterion."""
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [
                ("PS1", {"Alice": (80, 80)}),
                ("PS2", {"Alice": (70, 70)}),
            ])
            report = SemesterABETReport.from_folder(tmp).aggregate()
            for aname, lo_map in report["semester_summary"]["coverage_matrix"].items():
                self.assertTrue(lo_map.get("LO1", False),
                                f"LO1 missing from {aname}")

    def test_save_writes_valid_json(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            obj = SemesterABETReport.from_folder(tmp)
            obj.aggregate()
            out = os.path.join(tmp, "report.json")
            obj.save(out)
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(data["report_type"], "semester")

    def test_profile_id_in_report(self):
        from src.tools.semester_abet_report import SemesterABETReport
        from src.core.outcome_profile import load_default_profile
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            obj = SemesterABETReport.from_folder(tmp, profile=load_default_profile())
            report = obj.aggregate()
            self.assertEqual(report["profile_id"], "cs2500_algorithms")

    def test_outcome_descriptions_populated(self):
        from src.tools.semester_abet_report import SemesterABETReport
        from src.core.outcome_profile import load_default_profile
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            obj    = SemesterABETReport.from_folder(tmp, profile=load_default_profile())
            report = obj.aggregate()
            descs  = report.get("outcome_descriptions", {})
            self.assertIn("LO1", descs.get("course_outcomes", {}))
            self.assertIn("SO1", descs.get("program_outcomes", {}))
            self.assertTrue(len(descs["course_outcomes"]["LO1"]) > 0)


# ---------------------------------------------------------------------------
# Weighted aggregation — correctness
# ---------------------------------------------------------------------------

class TestWeightedAggregation(unittest.TestCase):

    def test_weight_2_does_not_inflate_scores(self):
        """weight=2.0 on one assignment should not produce scores > 100%."""
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            adir = os.path.join(tmp, "PS1", "assessments")
            obj = SemesterABETReport(
                {"target_percentage": 75.0},
                [{"assessment_id": "PS1", "assessment_name": "PS1",
                  "assessment_dir": adir, "include_in_abet": True, "weight": 2.0}])
            report = obj.aggregate()
            so1 = report["semester_summary"]["program_outcomes"].get("SO1")
            self.assertIsNotNone(so1)
            self.assertLessEqual(so1["mean"], 100.0)
            self.assertAlmostEqual(so1["mean"], 80.0, places=1)

    def test_equal_weights_match_simple_average(self):
        """PS1=100% + PS2=60% with weight=1 each → mean 80%."""
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [
                ("PS1", {"Alice": (100, 100)}),
                ("PS2", {"Alice": (60, 60)}),
            ])
            report = SemesterABETReport.from_folder(tmp).aggregate()
            so1 = report["semester_summary"]["program_outcomes"]["SO1"]
            self.assertAlmostEqual(so1["mean"], 80.0, places=1)

    def test_higher_weight_pulls_mean(self):
        """PS1 weight=3 at 60%, PS2 weight=1 at 100% → weighted mean = 70%."""
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            adir1 = os.path.join(tmp, "PS1", "assessments")
            adir2 = os.path.join(tmp, "PS2", "assessments")
            os.makedirs(adir1); os.makedirs(adir2)
            _make_assessment(adir1, "Alice", 60, 60, "PS1")
            _make_assessment(adir2, "Alice", 100, 100, "PS2")
            obj = SemesterABETReport(
                {"target_percentage": 75.0},
                [{"assessment_id": "PS1", "assessment_name": "PS1",
                  "assessment_dir": adir1, "include_in_abet": True, "weight": 3.0},
                 {"assessment_id": "PS2", "assessment_name": "PS2",
                  "assessment_dir": adir2, "include_in_abet": True, "weight": 1.0}])
            report = obj.aggregate()
            so1 = report["semester_summary"]["program_outcomes"]["SO1"]
            self.assertAlmostEqual(so1["mean"], 70.0, places=1)


# ---------------------------------------------------------------------------
# student_outcome_scores in assignment details
# ---------------------------------------------------------------------------

class TestStudentOutcomeScores(unittest.TestCase):

    def test_key_present_in_details(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80), "Bob": (60, 60)})])
            report = SemesterABETReport.from_folder(tmp).aggregate()
            details = [d for d in report["assignment_details"] if "error" not in d]
            self.assertIn("student_outcome_scores", details[0])

    def test_count_matches_students(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {
                "Alice": (90, 90), "Bob": (70, 70), "Carol": (80, 80)})])
            report  = SemesterABETReport.from_folder(tmp).aggregate()
            details = [d for d in report["assignment_details"] if "error" not in d]
            self.assertEqual(len(details[0]["student_outcome_scores"]), 3)

    def test_rows_contain_so_scores(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            report  = SemesterABETReport.from_folder(tmp).aggregate()
            details = [d for d in report["assignment_details"] if "error" not in d]
            row = details[0]["student_outcome_scores"][0]
            self.assertIn("student_name", row)
            self.assertIn("so_scores",    row)
            self.assertIn("SO1", row["so_scores"])

    def test_student_csv_populated(self):
        from src.tools.semester_abet_report import SemesterABETReport
        from src.tools.abet_export import export_semester_report
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80), "Bob": (60, 60)})])
            report = SemesterABETReport.from_folder(tmp).aggregate()
            out    = os.path.join(tmp, "exports")
            export_semester_report(report, out, include_xlsx=False)
            path = os.path.join(out, "abet_student_outcomes_all.csv")
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                rows = list(csv.reader(fh))
            self.assertGreaterEqual(len(rows), 3)  # header + 2 students


# ---------------------------------------------------------------------------
# unmapped_criteria in assignment details
# ---------------------------------------------------------------------------

class TestUnmappedCriteria(unittest.TestCase):

    def test_key_present(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            report  = SemesterABETReport.from_folder(tmp).aggregate()
            details = [d for d in report["assignment_details"] if "error" not in d]
            self.assertIn("unmapped_criteria", details[0])

    def test_empty_for_fully_mapped_rubric(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [("PS1", {"Alice": (80, 80)})])
            report  = SemesterABETReport.from_folder(tmp).aggregate()
            details = [d for d in report["assignment_details"] if "error" not in d]
            self.assertEqual(details[0]["unmapped_criteria"], [])

    def test_detected_for_unmapped_criterion(self):
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            adir = os.path.join(tmp, "PS1", "assessments")
            os.makedirs(adir)
            with open(os.path.join(adir, "alice.json"), "w") as fh:
                json.dump({"student_name": "Alice", "criteria": [{
                    "id": "C1", "title": "Q1",
                    "points_awarded": 8, "points_possible": 10,
                    "program_outcomes": [],   # intentionally empty
                    "course_outcomes": [],
                    "selected": True, "counted": True}]}, fh)
            obj = SemesterABETReport(
                {"target_percentage": 75.0},
                [{"assessment_id": "PS1", "assessment_name": "PS1",
                  "assessment_dir": adir, "include_in_abet": True, "weight": 1.0}])
            report  = obj.aggregate()
            details = [d for d in report["assignment_details"] if "error" not in d]
            self.assertEqual(len(details[0]["unmapped_criteria"]), 1)

    def test_error_entry_has_required_keys(self):
        from src.tools.semester_abet_report import SemesterABETReport
        obj = SemesterABETReport(
            {"target_percentage": 75.0},
            [{"assessment_id": "MISSING", "assessment_name": "Missing",
              "assessment_dir": "/nonexistent/path",
              "include_in_abet": True, "weight": 1.0}])
        report = obj.aggregate()
        detail = report["assignment_details"][0]
        self.assertIn("error",                  detail)
        self.assertIn("student_outcome_scores", detail)
        self.assertIn("unmapped_criteria",      detail)
        self.assertEqual(detail["student_outcome_scores"], [])
        self.assertEqual(detail["unmapped_criteria"],      [])


# ---------------------------------------------------------------------------
# Semester CSV export
# ---------------------------------------------------------------------------

class TestSemesterExport(unittest.TestCase):

    def _make_report(self, tmp):
        from src.tools.semester_abet_report import SemesterABETReport
        from src.core.outcome_profile import load_default_profile
        _semester_folder(tmp, [
            ("PS1", {"Alice": (100, 80), "Bob": (80, 60)}),
            ("PS2", {"Alice": (90, 90),  "Bob": (70, 70)}),
        ])
        return SemesterABETReport.from_folder(
            tmp, profile=load_default_profile(),
            course_info={"target_percentage": 75.0}).aggregate()

    def test_all_csvs_written(self):
        from src.tools.abet_export import export_semester_report
        with tempfile.TemporaryDirectory() as tmp:
            report = self._make_report(tmp)
            out    = os.path.join(tmp, "exports")
            files  = export_semester_report(report, out, include_xlsx=False)
            names  = [os.path.basename(f) for f in files]
            self.assertIn("abet_report.json",               names)
            self.assertIn("abet_semester_summary.csv",      names)
            self.assertIn("abet_outcome_by_assessment.csv", names)
            self.assertIn("abet_evidence_coverage.csv",     names)

    def test_semester_summary_csv_content(self):
        from src.tools.abet_export import export_semester_report
        with tempfile.TemporaryDirectory() as tmp:
            report = self._make_report(tmp)
            out    = os.path.join(tmp, "exports")
            export_semester_report(report, out, include_xlsx=False)
            with open(os.path.join(out, "abet_semester_summary.csv")) as fh:
                rows = list(csv.reader(fh))
            self.assertGreater(len(rows), 1)
            header = rows[0]
            for col in ("Outcome", "Mean %", "Adequate+ %", "Meets Target"):
                self.assertIn(col, header)
            so1_row = next((r for r in rows[1:] if r[0] == "SO1"), None)
            self.assertIsNotNone(so1_row)

    def test_by_assessment_csv_columns(self):
        from src.tools.abet_export import export_semester_report
        with tempfile.TemporaryDirectory() as tmp:
            report = self._make_report(tmp)
            out    = os.path.join(tmp, "exports")
            export_semester_report(report, out, include_xlsx=False)
            with open(os.path.join(out, "abet_outcome_by_assessment.csv")) as fh:
                rows = list(csv.reader(fh))
            self.assertIn("PS1",          rows[0])
            self.assertIn("PS2",          rows[0])
            self.assertIn("Overall Mean", rows[0])

    def test_coverage_matrix_csv(self):
        from src.tools.abet_export import export_semester_report
        with tempfile.TemporaryDirectory() as tmp:
            report = self._make_report(tmp)
            out    = os.path.join(tmp, "exports")
            export_semester_report(report, out, include_xlsx=False)
            with open(os.path.join(out, "abet_evidence_coverage.csv")) as fh:
                rows = list(csv.reader(fh))
            self.assertIn("LO1", rows[0])
            ps1_row = next((r for r in rows[1:] if "PS1" in r[0]), None)
            self.assertIsNotNone(ps1_row)
            lo1_idx = rows[0].index("LO1")
            self.assertEqual(ps1_row[lo1_idx], "Yes")

    def test_full_pipeline(self):
        from src.tools.semester_abet_report import SemesterABETReport
        from src.tools.abet_export import export_semester_report
        from src.core.outcome_profile import load_default_profile

        with tempfile.TemporaryDirectory() as tmp:
            _semester_folder(tmp, [
                ("PS1", {"Alice": (100, 100), "Bob": (80, 80)}),
                ("PS2", {"Alice": (90, 90),   "Bob": (70, 70)}),
                ("Midterm", {"Alice": (95, 85), "Bob": (75, 65)}),
            ])
            obj    = SemesterABETReport.from_folder(
                tmp, profile=load_default_profile(),
                course_info={"target_percentage": 75.0, "course_code": "CS 2500"})
            report = obj.aggregate()

            self.assertEqual(report["report_type"], "semester")
            self.assertEqual(len([d for d in report["assignment_details"]
                                  if "error" not in d]), 3)

            json_path = os.path.join(tmp, "report.json")
            obj.save(json_path)
            self.assertTrue(os.path.exists(json_path))

            export_dir = os.path.join(tmp, "exports")
            files = export_semester_report(report, export_dir, include_xlsx=False)
            names = [os.path.basename(f) for f in files]
            self.assertIn("abet_semester_summary.csv", names)

            so1 = report["semester_summary"]["program_outcomes"]["SO1"]
            self.assertGreater(so1["mean"],    70.0)
            self.assertLessEqual(so1["mean"], 100.0)

            with open(os.path.join(export_dir, "abet_semester_summary.csv")) as fh:
                rows = list(csv.reader(fh))
            so1_row = next((r for r in rows[1:] if r[0] == "SO1"), None)
            self.assertIsNotNone(so1_row)
            self.assertIn(so1_row[-1], ["Yes", "No"])

    def test_missing_dir_flagged_not_crashed(self):
        from src.tools.semester_abet_report import SemesterABETReport
        obj = SemesterABETReport(
            {"target_percentage": 75.0},
            [{"assessment_id": "MISSING", "assessment_name": "Missing",
              "assessment_dir": "/nonexistent/path/assessments",
              "include_in_abet": True, "weight": 1.0}])
        report = obj.aggregate()
        self.assertIn("error", report["assignment_details"][0])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
