"""
test_templates.py
=================

Tests for outcome profile files, rubric template files, and the
rubric_template.py generator.

Covers:
  - All template JSON files: schema 2.0, criteria, stable IDs,
    program_outcomes, abet_outcomes consistency
  - CS 2500 template set completeness (8 files)
  - New profiles: cs5480, cs5001, cs1575 — load, lo_ids, keyword inference
  - list_available_profiles() includes all profiles
  - rubric_template.py: create_from_template_file, create_blank_rubric,
    list_template_files, legacy backward-compat, error handling
  - Template-generated rubric scores correctly through abet_scoring
"""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

_TEMPLATE_ROOT = os.path.join(_REPO_ROOT, "templates")


# ---------------------------------------------------------------------------
# Template file integrity (subtests over all templates)
# ---------------------------------------------------------------------------

class TestTemplateFileIntegrity(unittest.TestCase):

    def _iter_templates(self):
        for dirpath, _, files in os.walk(_TEMPLATE_ROOT):
            for f in sorted(files):
                if f.endswith(".json"):
                    yield os.path.join(dirpath, f)

    def test_all_templates_load_as_json(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                self.assertIsInstance(data, dict)

    def test_all_templates_have_schema_version_2(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                self.assertEqual(data.get("schema_version"), "2.0")

    def test_all_templates_have_criteria(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                self.assertGreater(len(data.get("criteria", [])), 0)

    def test_all_criteria_have_stable_ids(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                for c in data.get("criteria", []):
                    self.assertTrue(bool(c.get("id", "").strip()),
                                    f"Missing id in {os.path.basename(path)}")

    def test_all_criteria_have_program_outcomes(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                for c in data.get("criteria", []):
                    self.assertIn("program_outcomes", c,
                                  f"{os.path.basename(path)}: criterion '{c.get('id','')}'"
                                  f" missing program_outcomes")

    def test_all_criteria_have_abet_outcomes(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                for c in data.get("criteria", []):
                    self.assertIn("abet_outcomes", c)

    def test_program_and_abet_outcomes_consistent(self):
        for path in self._iter_templates():
            with self.subTest(path=os.path.relpath(path, _TEMPLATE_ROOT)):
                with open(path) as fh:
                    data = json.load(fh)
                for c in data.get("criteria", []):
                    self.assertEqual(c.get("program_outcomes", []),
                                     c.get("abet_outcomes",    []),
                                     f"{os.path.basename(path)}: "
                                     f"program/abet outcomes mismatch")

    def test_cs2500_all_eight_templates_present(self):
        cs2500 = os.path.join(_TEMPLATE_ROOT, "cs2500")
        expected = {
            "ps_asymptotic_analysis.json", "ps_divide_conquer.json",
            "ps_dynamic_programming.json", "ps_greedy.json",
            "ps_graphs.json", "ps_np_completeness.json",
            "ps_sorting.json", "exam_template.json",
        }
        found = set(os.listdir(cs2500))
        for name in expected:
            self.assertIn(name, found, f"Missing CS 2500 template: {name}")


# ---------------------------------------------------------------------------
# New outcome profiles
# ---------------------------------------------------------------------------

class TestNewOutcomeProfiles(unittest.TestCase):

    def _load(self, pid):
        from src.core.outcome_profile import load_profile
        return load_profile(pid)

    def test_cs5480_loads(self):
        p = self._load("cs5480_deep_learning")
        self.assertEqual(p.profile_id, "cs5480_deep_learning")
        self.assertIn("LO1", p.lo_ids())
        self.assertIn("SO1", p.po_ids())

    def test_cs5001_loads(self):
        p = self._load("cs5001_information_retrieval")
        self.assertEqual(p.profile_id, "cs5001_information_retrieval")
        self.assertIn("LO6", p.lo_ids())

    def test_cs1575_loads(self):
        p = self._load("cs1575_data_structures")
        self.assertEqual(p.profile_id, "cs1575_data_structures")
        self.assertIn("LO2", p.lo_ids())

    def test_cs5480_keyword_training(self):
        p = self._load("cs5480_deep_learning")
        self.assertIn("LO3", p.infer_los_from_title(
            "Train the model with dropout regularization"))

    def test_cs5480_keyword_architecture(self):
        p = self._load("cs5480_deep_learning")
        self.assertIn("LO2", p.infer_los_from_title(
            "Design a convolutional neural network architecture"))

    def test_cs5001_keyword_indexing(self):
        p = self._load("cs5001_information_retrieval")
        self.assertIn("LO1", p.infer_los_from_title(
            "Implement an inverted index with tokenization"))

    def test_cs5001_keyword_evaluation(self):
        p = self._load("cs5001_information_retrieval")
        self.assertIn("LO3", p.infer_los_from_title(
            "Evaluate using MAP and NDCG metrics"))

    def test_cs1575_keyword_implement(self):
        p = self._load("cs1575_data_structures")
        self.assertIn("LO2", p.infer_los_from_title(
            "Implement a linked list with a stack interface"))

    def test_new_profiles_have_performance_bands(self):
        for pid in ("cs5480_deep_learning", "cs5001_information_retrieval",
                    "cs1575_data_structures"):
            with self.subTest(pid=pid):
                p = self._load(pid)
                self.assertIn("excellent", p.performance_bands)
                self.assertIn("adequate",  p.performance_bands)

    def test_all_profiles_listed(self):
        from src.core.outcome_profile import list_available_profiles
        profiles = list_available_profiles()
        for pid in ("cs2500_algorithms", "cs5480_deep_learning",
                    "cs5001_information_retrieval", "cs1575_data_structures",
                    "generic_course"):
            self.assertIn(pid, profiles)


# ---------------------------------------------------------------------------
# rubric_template.py
# ---------------------------------------------------------------------------

class TestRubricTemplate(unittest.TestCase):

    def _greedy_template(self):
        return os.path.join(_TEMPLATE_ROOT, "cs2500", "ps_greedy.json")

    def test_create_from_template_file(self):
        from src.tools.rubric_template import create_from_template_file
        with tempfile.TemporaryDirectory() as tmp:
            out    = os.path.join(tmp, "ps3.json")
            rubric = create_from_template_file(
                self._greedy_template(), out,
                title="PS3 - Greedy", assessment_id="F2026_PS3")
            self.assertEqual(rubric["title"], "PS3 - Greedy")
            self.assertEqual(rubric["assessment_id"], "F2026_PS3")
            self.assertEqual(rubric["schema_version"], "2.0")
            self.assertTrue(os.path.exists(out))
            for c in rubric["criteria"]:
                self.assertIn("program_outcomes", c)

    def test_create_blank_rubric(self):
        from src.tools.rubric_template import create_blank_rubric
        with tempfile.TemporaryDirectory() as tmp:
            out    = os.path.join(tmp, "blank.json")
            rubric = create_blank_rubric(out, title="Midterm 2",
                                         profile_id="cs2500_algorithms",
                                         num_questions=4, points_each=25)
            self.assertEqual(rubric["title"],      "Midterm 2")
            self.assertEqual(rubric["profile_id"], "cs2500_algorithms")
            self.assertEqual(len(rubric["criteria"]), 4)
            self.assertEqual(rubric["criteria"][0]["points"], 25)
            for c in rubric["criteria"]:
                self.assertIn("program_outcomes", c)
                self.assertIn("course_outcomes",  c)

    def test_list_template_files(self):
        from src.tools.rubric_template import list_template_files
        templates = list_template_files()
        self.assertGreater(len(templates), 0)
        self.assertTrue(any("cs2500" in t for t in templates))

    def test_legacy_essay_template_backward_compat(self):
        from src.tools.rubric_template import create_rubric_template
        with tempfile.TemporaryDirectory() as tmp:
            out    = os.path.join(tmp, "essay.json")
            result = create_rubric_template("essay", out, title="My Essay")
            self.assertTrue(result)
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(data["title"], "My Essay")
            self.assertEqual(data["schema_version"], "2.0")
            for c in data["criteria"]:
                self.assertIn("program_outcomes", c)

    def test_template_not_found_raises(self):
        from src.tools.rubric_template import create_from_template_file
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                create_from_template_file(
                    "nonexistent_template.json",
                    os.path.join(tmp, "out.json"))

    def test_created_rubric_scores_correctly(self):
        """Full-marks assessment on a template-generated rubric → 100% per outcome."""
        from src.tools.rubric_template import create_from_template_file
        from src.tools.abet_scoring import score_student_outcomes
        with tempfile.TemporaryDirectory() as tmp:
            rubric = create_from_template_file(
                os.path.join(_TEMPLATE_ROOT, "cs2500", "ps_asymptotic_analysis.json"),
                os.path.join(tmp, "r.json"))
            criteria = [{
                "id":               c["id"],
                "points_awarded":   c["points"],
                "points_possible":  c["points"],
                "program_outcomes": c["program_outcomes"],
                "course_outcomes":  c["course_outcomes"],
                "selected": True, "counted": True,
            } for c in rubric["criteria"]]
            scores = score_student_outcomes(criteria, "program_outcomes")
            for oid, pct in scores.items():
                self.assertAlmostEqual(pct, 100.0, places=1,
                                       msg=f"{oid} should be 100% for full marks")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
