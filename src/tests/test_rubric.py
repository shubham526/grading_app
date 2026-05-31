"""
test_rubric.py
==============

Tests for rubric loading, criterion ID generation, schema normalisation,
program_outcomes/abet_outcomes field sync, and the rubric_parser shim.

Covers:
  - _ensure_criterion_ids: ID generation, stability, field defaults
  - Bidirectional program_outcomes ↔ abet_outcomes normalisation
  - load_json_rubric / load_rubric_from_file: dirty flag, schema version
  - save_rubric: JSON roundtrip preserves both outcome fields
  - rubric_parser shim delegates to src.core.rubric
  - abet_tool: derive SOs from LOs when abet_outcomes absent
  - Legacy weights passed correctly from ABETMapping
  - Saved assessment fields (criterion data assembly)
  - End-to-end pipeline: load rubric → grade → score → export
"""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# _ensure_criterion_ids
# ---------------------------------------------------------------------------

class TestEnsureCriterionIDs(unittest.TestCase):

    def test_old_rubric_gets_ids(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"title": "Old", "criteria": [
            {"title": "Q1 Runtime", "points": 5},
            {"title": "Q2 Proof",   "points": 5},
        ]}
        dirty = _ensure_criterion_ids(rubric)
        self.assertTrue(dirty)
        for c in rubric["criteria"]:
            self.assertTrue(c.get("id", ""))

    def test_ids_stable_on_second_call(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"title": "Old", "criteria": [
            {"title": "Q1", "points": 5}, {"title": "Q2", "points": 5}]}
        _ensure_criterion_ids(rubric)
        ids1 = [c["id"] for c in rubric["criteria"]]
        _ensure_criterion_ids(rubric)
        ids2 = [c["id"] for c in rubric["criteria"]]
        self.assertEqual(ids1, ids2)

    def test_existing_ids_not_overwritten(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [
            {"id": "MY_ID", "title": "Q1", "points": 5,
             "course_outcomes": [], "abet_outcomes": [], "assessment_tags": []}]}
        dirty = _ensure_criterion_ids(rubric)
        self.assertFalse(dirty)
        self.assertEqual(rubric["criteria"][0]["id"], "MY_ID")

    def test_missing_abet_fields_defaulted(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [{"title": "Q1", "points": 5}]}
        _ensure_criterion_ids(rubric)
        c = rubric["criteria"][0]
        self.assertEqual(c["course_outcomes"], [])
        self.assertEqual(c["abet_outcomes"],   [])
        self.assertEqual(c["assessment_tags"], [])

    def test_existing_abet_fields_not_overwritten(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [{"id": "C1", "title": "Q1", "points": 5,
                                "course_outcomes": ["LO1"],
                                "abet_outcomes": ["SO1"],
                                "assessment_tags": ["runtime"]}]}
        _ensure_criterion_ids(rubric)
        c = rubric["criteria"][0]
        self.assertEqual(c["course_outcomes"], ["LO1"])
        self.assertEqual(c["abet_outcomes"],   ["SO1"])
        self.assertEqual(c["assessment_tags"], ["runtime"])

    def test_manual_duplicate_ids_not_rewritten(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [
            {"id": "SAME", "title": "Q1", "points": 5,
             "course_outcomes": [], "abet_outcomes": [], "assessment_tags": []},
            {"id": "SAME", "title": "Q2", "points": 5,
             "course_outcomes": [], "abet_outcomes": [], "assessment_tags": []},
        ]}
        _ensure_criterion_ids(rubric)
        self.assertEqual([c["id"] for c in rubric["criteria"]], ["SAME", "SAME"])


# ---------------------------------------------------------------------------
# program_outcomes ↔ abet_outcomes normalisation
# ---------------------------------------------------------------------------

class TestOutcomeFieldNormalisation(unittest.TestCase):

    def test_abet_outcomes_to_program_normalised(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [{"id": "C1", "title": "Q1", "points": 5,
                                "abet_outcomes": ["SO1", "SO6"],
                                "course_outcomes": [], "assessment_tags": []}]}
        _ensure_criterion_ids(rubric)
        c = rubric["criteria"][0]
        self.assertEqual(c["program_outcomes"], ["SO1", "SO6"])
        self.assertEqual(c["abet_outcomes"],    ["SO1", "SO6"])

    def test_program_outcomes_to_abet_alias(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [{"id": "C1", "title": "Q1", "points": 5,
                                "program_outcomes": ["SO2"],
                                "course_outcomes": [], "assessment_tags": []}]}
        _ensure_criterion_ids(rubric)
        c = rubric["criteria"][0]
        self.assertEqual(c["abet_outcomes"], ["SO2"])

    def test_neither_present_both_default_empty(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [{"id": "C1", "title": "Q1", "points": 5}]}
        _ensure_criterion_ids(rubric)
        c = rubric["criteria"][0]
        self.assertEqual(c["program_outcomes"], [])
        self.assertEqual(c["abet_outcomes"],    [])

    def test_both_present_neither_overwritten(self):
        from src.core.rubric import _ensure_criterion_ids
        rubric = {"criteria": [{"id": "C1", "title": "Q1", "points": 5,
                                "program_outcomes": ["SO1"],
                                "abet_outcomes":    ["SO1"],
                                "course_outcomes": [], "assessment_tags": []}]}
        _ensure_criterion_ids(rubric)
        c = rubric["criteria"][0]
        self.assertEqual(c["program_outcomes"], ["SO1"])
        self.assertEqual(c["abet_outcomes"],    ["SO1"])


# ---------------------------------------------------------------------------
# load_json_rubric and load_rubric_from_file
# ---------------------------------------------------------------------------

class TestRubricLoading(unittest.TestCase):

    def _write(self, tmp, data, name="rubric.json"):
        path = os.path.join(tmp, name)
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path

    def test_old_rubric_marked_dirty(self):
        from src.core.rubric import load_json_rubric
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"title": "Old", "criteria": [
                {"title": "Q1", "points": 5}]})
            rubric, is_dirty = load_json_rubric(path)
            self.assertTrue(is_dirty)
            self.assertTrue(rubric["criteria"][0].get("id", ""))

    def test_modern_rubric_not_dirty(self):
        from src.core.rubric import load_json_rubric
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "schema_version": "2.0", "title": "Modern",
                "criteria": [{"id": "C1", "title": "Q1", "points": 5,
                              "course_outcomes": ["LO1"], "abet_outcomes": ["SO1"],
                              "assessment_tags": []}]})
            rubric, is_dirty = load_json_rubric(path)
            self.assertFalse(is_dirty)

    def test_schema_version_added(self):
        from src.core.rubric import load_json_rubric
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"title": "Old", "criteria": [
                {"title": "Q1", "points": 5}]})
            rubric, _ = load_json_rubric(path)
            self.assertEqual(rubric["schema_version"], "2.0")

    def test_embedded_outcomes_preserved(self):
        from src.core.rubric import load_json_rubric
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "schema_version": "2.0", "title": "PS3",
                "criteria": [{"id": "C1", "title": "T", "points": 5,
                              "course_outcomes": ["LO4"],
                              "abet_outcomes": ["SO1", "SO6"],
                              "assessment_tags": ["proof"]}]})
            rubric, is_dirty = load_json_rubric(path)
            self.assertFalse(is_dirty)
            c = rubric["criteria"][0]
            self.assertEqual(c["course_outcomes"], ["LO4"])
            self.assertEqual(c["abet_outcomes"],   ["SO1", "SO6"])
            self.assertEqual(c["assessment_tags"], ["proof"])

    def test_load_rubric_from_file_returns_tuple(self):
        from src.core.rubric import load_rubric_from_file
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "schema_version": "2.0", "title": "T",
                "criteria": [{"id": "C1", "title": "Q1", "points": 5,
                              "course_outcomes": [], "abet_outcomes": [],
                              "assessment_tags": []}]})
            result = load_rubric_from_file(path)
            self.assertIsInstance(result, tuple)
            rubric, is_dirty = result
            self.assertIsInstance(rubric, dict)
            self.assertIsInstance(is_dirty, bool)

    def test_json_roundtrip_preserves_both_fields(self):
        from src.core.rubric import load_json_rubric, save_rubric
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "schema_version": "2.0", "title": "Old",
                "criteria": [{"id": "C1", "title": "Q1", "points": 5,
                              "abet_outcomes": ["SO1", "SO6"],
                              "course_outcomes": ["LO1"],
                              "assessment_tags": []}]})
            rubric, _ = load_json_rubric(path)
            save_rubric(rubric, path)
            rubric2, _ = load_json_rubric(path)
            c = rubric2["criteria"][0]
            self.assertEqual(c["program_outcomes"], ["SO1", "SO6"])
            self.assertEqual(c["abet_outcomes"],    ["SO1", "SO6"])


# ---------------------------------------------------------------------------
# rubric_parser shim
# ---------------------------------------------------------------------------

class TestRubricParserShim(unittest.TestCase):

    def test_shim_delegates_to_core(self):
        """rubric_parser.parse_rubric_file must delegate to core and return a dict."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rubric_parser",
            os.path.join(_REPO_ROOT, "src", "utils", "rubric_parser.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            with open(path, "w") as fh:
                json.dump({"schema_version": "2.0", "title": "T",
                           "criteria": [{"id": "C1", "title": "Q1", "points": 5,
                                         "course_outcomes": [], "abet_outcomes": [],
                                         "assessment_tags": []}]}, fh)
            result = mod.parse_rubric_file(path)
            # Shim returns a plain dict (strips the is_dirty flag)
            self.assertIsInstance(result, dict)
            self.assertIn("criteria", result)
            self.assertEqual(result["schema_version"], "2.0")


# ---------------------------------------------------------------------------
# abet_tool — derive SOs from LOs, legacy weights
# ---------------------------------------------------------------------------

class TestABETTool(unittest.TestCase):

    def test_lo_only_criterion_gets_sos_from_profile(self):
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        from src.core.outcome_profile import load_default_profile
        profile  = load_default_profile()
        analyzer = ABETAssessmentAnalyzer(outcome_profile=profile)
        analyzer.add_assessment({"student_name": "Alice", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 8, "points_possible": 10,
            "course_outcomes": ["LO1"],
            "abet_outcomes":   [],
            "selected": True, "counted": True,
        }]})
        prepared = analyzer._prepare_assessments()
        crit = prepared[0]["criteria"][0]
        self.assertIn("SO1", crit["abet_outcomes"])

    def test_legacy_weights_built_from_mapping(self):
        from src.tools.abet_tool import ABETMapping, ABETAssessmentAnalyzer
        mapping = ABETMapping()
        mapping.add_mapping("Q1 Runtime", ["SO1"], weights={"SO1": 2.0})
        analyzer = ABETAssessmentAnalyzer(mapping)
        weights = analyzer._build_legacy_weights()
        self.assertIsNotNone(weights)
        self.assertEqual(weights["Q1 Runtime"]["SO1"], 2.0)

    def test_no_mapping_weights_none(self):
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        self.assertIsNone(ABETAssessmentAnalyzer()._build_legacy_weights())

    def test_outcome_descriptions_populated(self):
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        from src.core.outcome_profile import load_default_profile
        profile  = load_default_profile()
        analyzer = ABETAssessmentAnalyzer(outcome_profile=profile)
        analyzer.add_assessment({"student_name": "A", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 8, "points_possible": 10,
            "course_outcomes": ["LO1"], "abet_outcomes": ["SO1"],
            "selected": True, "counted": True,
        }]})
        with tempfile.TemporaryDirectory() as tmp:
            report = analyzer.generate_abet_report(
                os.path.join(tmp, "r.json"),
                course_info={"target_percentage": 70.0})
        desc = report.get("outcome_descriptions", {})
        self.assertTrue(len(desc.get("course_outcomes", {}).get("LO1", "")) > 0)

    def test_profile_id_in_report(self):
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        from src.core.outcome_profile import load_default_profile
        profile  = load_default_profile()
        analyzer = ABETAssessmentAnalyzer(outcome_profile=profile)
        analyzer.add_assessment({"student_name": "A", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 5, "points_possible": 10,
            "program_outcomes": ["SO1"], "course_outcomes": [],
            "selected": True, "counted": True,
        }]})
        with tempfile.TemporaryDirectory() as tmp:
            report = analyzer.generate_abet_report(os.path.join(tmp, "r.json"))
        self.assertEqual(report["profile_id"], "cs2500_algorithms")

    def test_report_has_program_and_abet_outcome_aliases(self):
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        from src.core.outcome_profile import create_profile_from_dict
        profile = create_profile_from_dict({
            "schema_version": "2.0", "profile_id": "test",
            "course_outcomes": {"LO1": "x"}, "program_outcomes": {"SO1": "y"},
            "default_course_to_program": {"LO1": ["SO1"]},
            "performance_bands": {"excellent": [90, 100], "adequate": [75, 89.99],
                                  "needs_improvement": [40, 74.99], "inadequate": [0, 39.99]},
            "passing_bands": ["excellent", "adequate"],
            "target_percentage": 75.0, "keyword_to_course_outcome": {},
        })
        analyzer = ABETAssessmentAnalyzer(outcome_profile=profile)
        analyzer.add_assessment({"student_name": "A", "criteria": [{
            "id": "C1", "title": "T",
            "points_awarded": 8, "points_possible": 10,
            "program_outcomes": ["SO1"], "course_outcomes": ["LO1"],
            "selected": True, "counted": True,
        }]})
        with tempfile.TemporaryDirectory() as tmp:
            report = analyzer.generate_abet_report(os.path.join(tmp, "r.json"))
        self.assertIn("program_outcomes", report["outcome_summary"])
        self.assertIn("abet_outcomes",    report["outcome_summary"])


# ---------------------------------------------------------------------------
# Saved assessment field assembly
# ---------------------------------------------------------------------------

class TestSavedAssessmentFields(unittest.TestCase):
    """Simulate get_assessment_data() output without instantiating PyQt5."""

    def _rubric(self):
        return {
            "schema_version": "2.0", "profile_id": "cs2500_algorithms",
            "title": "PS3",
            "criteria": [{"id": "PS3_Q2_RUNTIME", "title": "Q2 Runtime",
                          "description": "Analyze.", "points": 10,
                          "course_outcomes": ["LO1"],
                          "program_outcomes": ["SO1", "SO6"],
                          "abet_outcomes":    ["SO1", "SO6"],
                          "assessment_tags":  ["runtime"], "levels": []}]}

    def _assemble(self, rubric, awarded):
        orig = rubric["criteria"][0]
        pos  = list(orig.get("program_outcomes") or orig.get("abet_outcomes") or [])
        return {
            "id":              orig["id"],
            "points_awarded":  awarded,
            "points_possible": orig["points"],
            "selected": True, "counted": True,
            "program_outcomes": pos,
            "abet_outcomes":    pos,
            "course_outcomes":  list(orig.get("course_outcomes", [])),
            "assessment_tags":  list(orig.get("assessment_tags",  [])),
        }

    def test_criterion_data_has_all_abet_fields(self):
        crit = self._assemble(self._rubric(), 8)
        self.assertEqual(crit["id"],               "PS3_Q2_RUNTIME")
        self.assertEqual(crit["course_outcomes"],   ["LO1"])
        self.assertEqual(crit["program_outcomes"],  ["SO1", "SO6"])
        self.assertEqual(crit["abet_outcomes"],     ["SO1", "SO6"])
        self.assertEqual(crit["assessment_tags"],   ["runtime"])

    def test_scoring_uses_saved_criterion(self):
        from src.tools.abet_scoring import score_student_outcomes
        crit = self._assemble(self._rubric(), 8)
        scores = score_student_outcomes([crit], "program_outcomes")
        self.assertAlmostEqual(scores["SO1"], 80.0, places=5)
        self.assertAlmostEqual(scores["SO6"], 80.0, places=5)

    def test_abet_meta_profile_id(self):
        rubric = self._rubric()
        abet_meta = {"profile_id": rubric.get("profile_id",
                                               rubric.get("outcome_profile", ""))}
        self.assertEqual(abet_meta["profile_id"], "cs2500_algorithms")


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

class TestEndToEndPipeline(unittest.TestCase):

    def _make_rubric(self, tmp):
        rubric = {
            "schema_version": "2.0", "title": "PS3 - Greedy",
            "profile_id": "cs2500_algorithms",
            "criteria": [
                {"id": "PS3_Q1", "title": "Q1 Runtime", "points": 4,
                 "course_outcomes": ["LO1"], "program_outcomes": ["SO1", "SO6"],
                 "abet_outcomes": ["SO1", "SO6"], "assessment_tags": ["runtime"],
                 "levels": []},
                {"id": "PS3_Q2", "title": "Q2 Proof", "points": 6,
                 "course_outcomes": ["LO4"], "program_outcomes": ["SO1", "SO6"],
                 "abet_outcomes": ["SO1", "SO6"], "assessment_tags": ["proof"],
                 "levels": []},
            ]}
        path = os.path.join(tmp, "rubric.json")
        with open(path, "w") as fh:
            json.dump(rubric, fh)
        return path, rubric

    def _grade(self, rubric, student, awards, tmp):
        criteria = []
        for i, orig in enumerate(rubric["criteria"]):
            pos = list(orig["program_outcomes"])
            criteria.append({
                "id": orig["id"], "points_awarded": awards[i],
                "points_possible": orig["points"],
                "course_outcomes": list(orig["course_outcomes"]),
                "program_outcomes": pos, "abet_outcomes": pos,
                "assessment_tags": list(orig["assessment_tags"]),
                "selected": True, "counted": True,
            })
        assessment = {"student_name": student, "criteria": criteria,
                      "abet_meta": {"profile_id": "cs2500_algorithms"}}
        return assessment

    def test_full_pipeline(self):
        import csv as csv_mod
        from src.core.rubric import load_rubric_from_file
        from src.tools.abet_tool import ABETAssessmentAnalyzer
        from src.tools.abet_export import export_assignment_report
        from src.core.outcome_profile import load_default_profile

        with tempfile.TemporaryDirectory() as tmp:
            path, rubric = self._make_rubric(tmp)
            loaded, is_dirty = load_rubric_from_file(path)
            self.assertFalse(is_dirty)

            alice = self._grade(loaded, "Alice", [4, 6], tmp)  # 100%
            bob   = self._grade(loaded, "Bob",   [3, 4], tmp)  # 75% / 67%

            profile  = load_default_profile()
            analyzer = ABETAssessmentAnalyzer(outcome_profile=profile)
            analyzer.add_assessment(alice)
            analyzer.add_assessment(bob)

            report = analyzer.generate_abet_report(
                os.path.join(tmp, "report.json"),
                course_info={"target_percentage": 75.0})

            self.assertEqual(report["profile_id"], "cs2500_algorithms")
            self.assertIn("SO1", report["outcome_summary"]["program_outcomes"])
            self.assertIn("LO1", report["outcome_summary"]["course_outcomes"])

            so1 = report["outcome_summary"]["program_outcomes"]["SO1"]
            self.assertEqual(so1["count"], 2)
            self.assertAlmostEqual(so1["mean"], 85.0, places=1)
            self.assertIn("meets_target", so1)

            export_assignment_report(report, tmp, include_xlsx=False)
            csv_path = os.path.join(tmp, "abet_assignment_so_summary.csv")
            self.assertTrue(os.path.exists(csv_path))
            with open(csv_path) as fh:
                rows = list(csv_mod.reader(fh))
            so1_row = next((r for r in rows[1:] if r[0] == "SO1"), None)
            self.assertIsNotNone(so1_row)
            self.assertEqual(so1_row[-1], "No")  # 50% passing < 75% target

    def test_legacy_rubric_still_works(self):
        from src.core.rubric import load_rubric_from_file
        from src.tools.abet_tool import ABETAssessmentAnalyzer, create_mapping_from_dict

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.json")
            with open(path, "w") as fh:
                json.dump({"title": "Old Exam", "criteria": [
                    {"title": "Q1 Runtime", "points": 10}]}, fh)

            rubric, is_dirty = load_rubric_from_file(path)
            self.assertTrue(is_dirty)

            mapping  = create_mapping_from_dict({"mappings": {
                "Q1 Runtime": {"outcomes": ["SO1"], "weights": {"SO1": 1.0}}}})
            analyzer = ABETAssessmentAnalyzer(mapping)
            analyzer.add_assessment({"student_name": "C", "criteria": [{
                "title": "Q1 Runtime", "points_awarded": 8, "points_possible": 10,
                "selected": True, "counted": True}]})

            report = analyzer.generate_abet_report(os.path.join(tmp, "r.json"))
            so1 = report["outcome_summary"]["program_outcomes"].get("SO1")
            self.assertIsNotNone(so1)
            self.assertAlmostEqual(so1["mean"], 80.0, places=1)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
