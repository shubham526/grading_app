"""
Tests for v2.1.0 question-centric grading core/data behavior.

This file intentionally focuses on pure data behavior.  The question-centric UI
is added in a later commit; these tests establish the stable question identity,
partial-save, explicit grading-state, and progress foundations first.
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock


# Keep the core package importable in headless CI environments.  The existing
# project tests use the same strategy because src.core.__init__ imports the
# PyQt-backed assessment module.
_QT_MOCKS = [
    "PyQt5", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.QtCore",
    "PyQt5.QtSvg", "PyQt5.QtPrintSupport",
]
for _module in _QT_MOCKS:
    if _module not in sys.modules:
        sys.modules[_module] = MagicMock()
sys.modules["PyQt5.QtCore"].pyqtSignal = lambda *a, **kw: MagicMock()


_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


class TestQuestionIdNormalization(unittest.TestCase):

    def test_required_inference_examples(self):
        from src.core.question_utils import infer_question_id_from_title

        cases = {
            "Question 1 - Runtime": "Q1",
            "Q2 Correctness": "Q2",
            "Problem 3: DP": "Q3",
            "P4 Reduction": "Q4",
            "Question 1(a)": "Q1A",
            "Q2(b) Runtime": "Q2B",
            "No question label here": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(infer_question_id_from_title(title), expected)

    def test_normalize_question_id(self):
        from src.core.question_utils import normalize_question_id

        cases = {
            "question 1": "Q1",
            "Problem 2": "Q2",
            "q3a": "Q3A",
            "Q4(b)": "Q4B",
            "P5(a)": "Q5A",
            "Q10": "Q10",
            "not a question": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_question_id(raw), expected)

    def test_does_not_treat_next_word_as_subpart(self):
        from src.core.question_utils import infer_question_id_from_title
        self.assertEqual(infer_question_id_from_title("Q2 Correctness Proof"), "Q2")
        self.assertEqual(infer_question_id_from_title("Question 3 Runtime"), "Q3")

    def test_natural_sort_with_subparts_and_unassigned(self):
        from src.core.question_utils import UNASSIGNED, sort_question_ids

        raw = ["Q10", "Q2", "Q1B", UNASSIGNED, "Q1", "Q1A"]
        self.assertEqual(
            sort_question_ids(raw),
            ["Q1", "Q1A", "Q1B", "Q2", "Q10", UNASSIGNED],
        )


class TestQuestionGrouping(unittest.TestCase):

    def test_grouping_prefers_explicit_and_keeps_unassigned(self):
        from src.core.question_utils import UNASSIGNED, group_criteria_by_question

        rubric = {
            "criteria": [
                {"id": "C1", "question_id": "Q2", "title": "Question 99 - explicit wins", "points": 1},
                {"id": "C2", "title": "Q2 Proof", "points": 1},
                {"id": "C3", "title": "Q2 Clarity", "points": 1},
                {"id": "C4", "title": "General presentation", "points": 1},
            ]
        }
        groups = group_criteria_by_question(rubric)

        self.assertEqual([c["id"] for c in groups["Q2"]], ["C1", "C2", "C3"])
        self.assertEqual([c["id"] for c in groups[UNASSIGNED]], ["C4"])

    def test_get_question_ids_natural_order(self):
        from src.core.question_utils import get_question_ids

        rubric = {"criteria": [
            {"title": "Q10 A", "points": 1},
            {"title": "Q2 A", "points": 1},
            {"title": "Q1(b)", "points": 1},
            {"title": "Q1(a)", "points": 1},
            {"title": "Q1", "points": 1},
            {"title": "General", "points": 1},
        ]}
        self.assertEqual(get_question_ids(rubric), ["Q1", "Q1A", "Q1B", "Q2", "Q10"])
        self.assertEqual(
            get_question_ids(rubric, include_unassigned=True),
            ["Q1", "Q1A", "Q1B", "Q2", "Q10", "UNASSIGNED"],
        )


class TestRubricQuestionMigration(unittest.TestCase):

    def _write_json(self, directory, data, name="rubric.json"):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_old_rubric_infers_question_ids_and_marks_dirty(self):
        from src.core.rubric import load_json_rubric

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {
                "schema_version": "2.0",
                "title": "Old",
                "criteria": [
                    {"id": "C1", "title": "Question 1 - Runtime", "points": 4},
                    {"id": "C2", "title": "Q2 Proof", "points": 6},
                ],
            })
            rubric, dirty = load_json_rubric(path)

        self.assertTrue(dirty)
        self.assertEqual(rubric["criteria"][0]["question_id"], "Q1")
        self.assertEqual(rubric["criteria"][1]["question_id"], "Q2")

    def test_explicit_question_id_is_preserved(self):
        from src.core.rubric import load_json_rubric

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {
                "schema_version": "2.0",
                "title": "Modern",
                "criteria": [{
                    "id": "C1",
                    "question_id": "CUSTOM_Q",
                    "title": "Question 1 - Runtime",
                    "points": 4,
                }],
            })
            rubric, dirty = load_json_rubric(path)

        self.assertFalse(dirty)
        self.assertEqual(rubric["criteria"][0]["question_id"], "CUSTOM_Q")

    def test_uninferable_question_does_not_crash_or_force_dirty(self):
        from src.core.rubric import load_json_rubric

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {
                "schema_version": "2.0",
                "title": "Rubric",
                "criteria": [{"id": "C1", "title": "Written Clarity", "points": 2}],
            })
            rubric, dirty = load_json_rubric(path)

        self.assertFalse(dirty)
        self.assertNotIn("question_id", rubric["criteria"][0])

    def test_save_rubric_persists_inferred_question_id(self):
        from src.core.rubric import load_json_rubric, save_rubric

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {
                "schema_version": "2.0",
                "title": "Old",
                "criteria": [{"id": "C1", "title": "Problem 3: DP", "points": 5}],
            })
            rubric, dirty = load_json_rubric(path)
            self.assertTrue(dirty)
            save_rubric(rubric, path)
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)

        self.assertEqual(saved["criteria"][0]["question_id"], "Q3")

    def test_csv_loading_infers_question_id(self):
        from src.core.rubric import load_csv_rubric

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rubric.csv")
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Title", "Description", "Points"])
                writer.writerow(["Question 2 - Runtime Analysis", "Analyze runtime", "4"])

            rubric = load_csv_rubric(path)

        self.assertEqual(rubric["criteria"][0]["question_id"], "Q2")

    def test_schema_field_addition_marks_dirty(self):
        from src.core.rubric import load_json_rubric

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, {
                "title": "Old",
                "criteria": [{
                    "id": "C1", "question_id": "Q1", "title": "Q1", "points": 1,
                }],
            })
            _rubric, dirty = load_json_rubric(path)

        self.assertTrue(dirty)


class TestQuestionValidation(unittest.TestCase):

    def test_missing_question_id_is_warning_not_error(self):
        from src.tools.abet_validation import ERROR, WARNING, validate_rubric

        rubric = {"criteria": [{
            "id": "C1",
            "title": "General Clarity",
            "points": 2,
            "course_outcomes": ["LO1"],
            "program_outcomes": ["SO1"],
        }]}
        issues = validate_rubric(rubric)
        codes_by_level = {
            level: [issue["code"] for issue in issues if issue["level"] == level]
            for level in (WARNING, ERROR)
        }

        self.assertIn("NO_QUESTION_ID", codes_by_level[WARNING])
        self.assertNotIn("NO_QUESTION_ID", codes_by_level[ERROR])

    def test_multiple_criteria_same_question_id_are_valid(self):
        from src.tools.abet_validation import validate_rubric

        rubric = {"criteria": [
            {"id": "C1", "question_id": "Q2", "title": "Q2 Runtime", "points": 2,
             "course_outcomes": ["LO1"], "program_outcomes": ["SO1"]},
            {"id": "C2", "question_id": "Q2", "title": "Q2 Proof", "points": 3,
             "course_outcomes": ["LO1"], "program_outcomes": ["SO1"]},
        ]}
        issues = validate_rubric(rubric)
        self.assertFalse(any(issue["code"] == "DUPLICATE_QUESTION_ID" for issue in issues))


class TestPartialCriteriaMerge(unittest.TestCase):

    def _assessment(self):
        return {
            "student_name": "Alice",
            "assignment_name": "PS3",
            "criteria": [
                {"id": "Q1_A", "title": "Q1 A", "points_awarded": 5,
                 "comments": "old q1", "program_outcomes": ["SO1"]},
                {"id": "Q2_A", "title": "Q2 A", "points_awarded": 7,
                 "comments": "keep q2", "program_outcomes": ["SO2"]},
            ],
            "abet_meta": {"profile_id": "cs2500_algorithms"},
            "grading_progress": {"mode": "question_centric", "last_question": "Q2"},
        }

    def test_updating_q1_does_not_erase_q2(self):
        from src.core.assessment import merge_partial_criteria_update

        existing = self._assessment()
        merged = merge_partial_criteria_update(existing, [
            {"id": "Q1_A", "title": "Q1 A", "points_awarded": 4,
             "comments": "new q1"},
        ])

        self.assertEqual(merged["criteria"][0]["points_awarded"], 4)
        self.assertEqual(merged["criteria"][1]["points_awarded"], 7)
        self.assertEqual(merged["criteria"][1]["comments"], "keep q2")
        self.assertEqual(merged["criteria"][1]["program_outcomes"], ["SO2"])

    def test_merge_does_not_mutate_original(self):
        from src.core.assessment import merge_partial_criteria_update

        existing = self._assessment()
        merged = merge_partial_criteria_update(existing, [
            {"id": "Q1_A", "points_awarded": 1},
        ])
        self.assertEqual(existing["criteria"][0]["points_awarded"], 5)
        self.assertEqual(merged["criteria"][0]["points_awarded"], 1)

    def test_assessment_level_metadata_is_preserved(self):
        from src.core.assessment import merge_partial_criteria_update

        merged = merge_partial_criteria_update(self._assessment(), [
            {"id": "Q1_A", "points_awarded": 3},
        ])
        self.assertEqual(merged["student_name"], "Alice")
        self.assertEqual(merged["abet_meta"]["profile_id"], "cs2500_algorithms")
        self.assertEqual(merged["grading_progress"]["last_question"], "Q2")

    def test_title_fallback_when_updated_id_missing(self):
        from src.core.assessment import merge_partial_criteria_update

        merged = merge_partial_criteria_update(self._assessment(), [
            {"title": "Q2 A", "points_awarded": 6},
        ])
        self.assertEqual(len(merged["criteria"]), 2)
        self.assertEqual(merged["criteria"][1]["points_awarded"], 6)
        self.assertEqual(merged["criteria"][1]["id"], "Q2_A")

    def test_title_is_not_used_when_updated_id_is_present(self):
        from src.core.assessment import merge_partial_criteria_update

        merged = merge_partial_criteria_update(self._assessment(), [
            {"id": "NEW_ID", "title": "Q2 A", "points_awarded": 2},
        ])
        self.assertEqual(len(merged["criteria"]), 3)
        self.assertEqual(merged["criteria"][-1]["id"], "NEW_ID")

    def test_new_criterion_is_appended(self):
        from src.core.assessment import merge_partial_criteria_update

        merged = merge_partial_criteria_update(self._assessment(), [
            {"id": "Q3_A", "title": "Q3 A", "points_awarded": 9},
        ])
        self.assertEqual([c["id"] for c in merged["criteria"]], ["Q1_A", "Q2_A", "Q3_A"])


class TestBlankAssessmentCreation(unittest.TestCase):

    def test_blank_assessment_contains_full_rubric_and_ungraded_status(self):
        from src.core.assessment import create_blank_assessment_from_rubric

        rubric = {
            "schema_version": "2.0",
            "title": "PS3",
            "profile_id": "cs2500_algorithms",
            "criteria": [
                {"id": "C1", "question_id": "Q1", "title": "Q1 Runtime", "points": 4,
                 "course_outcomes": ["LO1"], "program_outcomes": ["SO1"],
                 "assessment_tags": ["runtime"]},
                {"id": "C2", "question_id": "Q2", "title": "Q2 Proof", "points": 6,
                 "course_outcomes": ["LO4"], "program_outcomes": ["SO6"],
                 "assessment_tags": ["proof"]},
            ],
        }
        assessment = create_blank_assessment_from_rubric(
            rubric,
            student_id="alice",
            student_name="Alice Smith",
            rubric_path="/tmp/rubric.json",
        )

        self.assertEqual(assessment["student_id"], "alice")
        self.assertEqual(len(assessment["criteria"]), 2)
        self.assertEqual(assessment["criteria"][0]["question_id"], "Q1")
        self.assertFalse(assessment["criteria"][0]["grading_status"]["graded"])
        self.assertFalse(assessment["criteria"][0]["selected"])
        self.assertFalse(assessment["criteria"][0]["counted"])
        self.assertEqual(assessment["abet_meta"]["profile_id"], "cs2500_algorithms")


class TestQuestionProgress(unittest.TestCase):

    def _rubric(self):
        return {
            "criteria": [
                {"id": "Q1_A", "question_id": "Q1", "title": "Q1 Runtime", "points": 4},
                {"id": "Q1_B", "question_id": "Q1", "title": "Q1 Proof", "points": 6},
                {"id": "Q2_A", "question_id": "Q2", "title": "Q2 Design", "points": 10},
                {"id": "GEN", "title": "General Clarity", "points": 2},
            ]
        }

    def _criterion(self, cid, title, graded, points=0):
        return {
            "id": cid,
            "title": title,
            "points_awarded": points,
            "grading_status": {
                "graded": graded,
                "graded_at": "2026-08-12T12:00:00+00:00" if graded else None,
                "graded_by": "instructor" if graded else None,
            },
        }

    def _write_assessment(self, directory, student_id, criteria):
        path = os.path.join(directory, f"{student_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "student_id": student_id,
                "student_name": student_id.title(),
                "criteria": criteria,
            }, fh)

    def test_progress_counts_full_partial_and_missing_as_ungraded(self):
        from src.core.question_utils import compute_question_progress

        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(tmp, "alice", [
                self._criterion("Q1_A", "Q1 Runtime", True, 4),
                self._criterion("Q1_B", "Q1 Proof", True, 5),
            ])
            self._write_assessment(tmp, "bob", [
                self._criterion("Q1_A", "Q1 Runtime", True, 3),
                self._criterion("Q1_B", "Q1 Proof", False, 0),
            ])

            progress = compute_question_progress(
                tmp,
                self._rubric(),
                "Q1",
                student_ids=["alice", "bob", "chen"],
            )

        self.assertEqual(progress.total_students, 3)
        self.assertEqual(progress.graded_students, 1)
        self.assertEqual(progress.partially_graded_students, 1)
        self.assertEqual(progress.ungraded_students, 1)

    def test_explicit_ungraded_zero_is_not_counted_as_graded(self):
        from src.core.question_utils import compute_question_progress

        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(tmp, "alice", [
                self._criterion("Q1_A", "Q1 Runtime", False, 0),
                self._criterion("Q1_B", "Q1 Proof", False, 0),
            ])
            progress = compute_question_progress(tmp, self._rubric(), "Q1")

        self.assertEqual(progress.ungraded_students, 1)
        self.assertEqual(progress.graded_students, 0)

    def test_legacy_zero_without_status_is_treated_as_graded(self):
        from src.core.question_utils import compute_question_progress

        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(tmp, "alice", [
                {"id": "Q1_A", "title": "Q1 Runtime", "points_awarded": 0},
                {"id": "Q1_B", "title": "Q1 Proof", "points_awarded": 0},
            ])
            progress = compute_question_progress(tmp, self._rubric(), "Q1")

        self.assertEqual(progress.graded_students, 1)

    def test_unassigned_criteria_progress_does_not_break(self):
        from src.core.question_utils import UNASSIGNED, compute_question_progress

        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(tmp, "alice", [
                self._criterion("GEN", "General Clarity", True, 2),
            ])
            progress = compute_question_progress(tmp, self._rubric(), UNASSIGNED)

        self.assertEqual(progress.total_students, 1)
        self.assertEqual(progress.graded_students, 1)

    def test_compute_all_question_progress_includes_unassigned(self):
        from src.core.question_utils import compute_all_question_progress

        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(tmp, "alice", [
                self._criterion("Q1_A", "Q1 Runtime", True, 4),
                self._criterion("Q1_B", "Q1 Proof", True, 6),
                self._criterion("Q2_A", "Q2 Design", False, 0),
                self._criterion("GEN", "General Clarity", True, 2),
            ])
            all_progress = compute_all_question_progress(tmp, self._rubric())

        self.assertEqual(list(all_progress.keys()), ["Q1", "Q2", "UNASSIGNED"])
        self.assertEqual(all_progress["Q1"].graded_students, 1)
        self.assertEqual(all_progress["Q2"].ungraded_students, 1)
        self.assertEqual(all_progress["UNASSIGNED"].graded_students, 1)


class TestRosterAndStudentDiscovery(unittest.TestCase):

    def test_load_roster_csv_and_preserve_order(self):
        from src.core.roster import load_roster_csv

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster.csv")
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["student_id", "student_name"])
                writer.writerow(["alice", "Alice Smith"])
                writer.writerow(["bob", "Bob Chen"])

            records = load_roster_csv(path)

        self.assertEqual([r.student_id for r in records], ["alice", "bob"])
        self.assertEqual([r.student_name for r in records], ["Alice Smith", "Bob Chen"])

    def test_duplicate_roster_ids_are_rejected(self):
        from src.core.roster import load_roster_csv

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster.csv")
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["student_id", "student_name"])
                writer.writerow(["alice", "Alice Smith"])
                writer.writerow(["ALICE", "Alice Duplicate"])

            with self.assertRaises(ValueError):
                load_roster_csv(path)

    def test_assessment_directory_discovers_valid_student_files_only(self):
        from src.core.roster import load_students_from_assessment_dir

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "alice.json"), "w", encoding="utf-8") as fh:
                json.dump({"student_name": "Alice Smith", "criteria": []}, fh)
            with open(os.path.join(tmp, "rubric.json"), "w", encoding="utf-8") as fh:
                json.dump({"title": "Rubric", "criteria": []}, fh)
            with open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8") as fh:
                fh.write("not-json")

            records = load_students_from_assessment_dir(tmp)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].student_id, "alice")
        self.assertEqual(records[0].student_name, "Alice Smith")

    def test_roster_merge_attaches_legacy_assessment_by_student_name(self):
        from src.core.roster import StudentRecord, merge_student_records

        roster = [StudentRecord("123", "Alice Smith"), StudentRecord("456", "Bob Chen")]
        assessments = [StudentRecord("old_filename", "Alice Smith", "/tmp/alice.json")]
        merged = merge_student_records(roster, assessments, "/tmp")

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].student_id, "123")
        self.assertEqual(merged[0].assessment_path, "/tmp/alice.json")
        self.assertTrue(merged[1].assessment_path.endswith("456.json"))


class TestGradingProgressMetadata(unittest.TestCase):

    def test_mark_complete_preserves_other_assessment_metadata(self):
        from src.core.assessment import update_grading_progress_metadata

        original = {
            "student_name": "Alice",
            "abet_meta": {"profile_id": "test"},
            "grading_progress": {"completed_questions": ["Q1"]},
        }
        updated = update_grading_progress_metadata(
            original,
            mode="question_centric",
            question_id="Q2",
            student_id="alice",
            question_complete=True,
        )

        self.assertEqual(updated["student_name"], "Alice")
        self.assertEqual(updated["abet_meta"], {"profile_id": "test"})
        self.assertEqual(updated["grading_progress"]["completed_questions"], ["Q1", "Q2"])
        self.assertEqual(updated["grading_progress"]["last_question"], "Q2")
        self.assertEqual(updated["grading_progress"]["last_student_id"], "alice")
        self.assertIn("last_updated", updated["grading_progress"])
        self.assertEqual(original["grading_progress"]["completed_questions"], ["Q1"])

    def test_incomplete_question_removes_completion_marker(self):
        from src.core.assessment import update_grading_progress_metadata

        updated = update_grading_progress_metadata(
            {"grading_progress": {"completed_questions": ["Q1", "Q2"]}},
            mode="question_centric",
            question_id="Q2",
            question_complete=False,
        )
        self.assertEqual(updated["grading_progress"]["completed_questions"], ["Q1"])


class TestOverallCriteriaProgress(unittest.TestCase):

    def _rubric(self):
        return {
            "criteria": [
                {"id": "Q1_A", "question_id": "Q1", "title": "Q1 A", "points": 5},
                {"id": "Q1_B", "question_id": "Q1", "title": "Q1 B", "points": 5},
                {"id": "Q2_A", "question_id": "Q2", "title": "Q2 A", "points": 5},
            ]
        }

    def _criterion(self, cid, graded):
        return {
            "id": cid,
            "points_awarded": 0,
            "grading_status": {"graded": graded},
        }

    def test_overall_progress_counts_criteria_and_missing_students(self):
        from src.core.question_utils import compute_overall_criteria_progress

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "alice.json"), "w", encoding="utf-8") as fh:
                json.dump({
                    "student_name": "Alice",
                    "criteria": [
                        self._criterion("Q1_A", True),
                        self._criterion("Q1_B", True),
                        self._criterion("Q2_A", False),
                    ],
                }, fh)

            progress = compute_overall_criteria_progress(
                tmp,
                self._rubric(),
                student_ids=["Alice", "Bob"],
            )

        self.assertEqual(progress.total_criteria, 6)
        self.assertEqual(progress.graded_criteria, 2)
        self.assertEqual(progress.ungraded_criteria, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
