"""Tests for v2.2.1 Commit 1 master ABET evidence row generation."""

import json
import os
import tempfile
import unittest

from types import SimpleNamespace

from src.tools.master_evidence_export import (
    MASTER_EVIDENCE_FIELDS,
    build_master_evidence_rows_for_assessment,
    build_master_evidence_rows_for_assignment,
    collect_master_evidence_for_assignment,
)


def _rubric():
    return {
        "schema_version": "2.0",
        "assessment_id": "PS3",
        "course_code": "CS 2500",
        "semester": "Fall 2026",
        "title": "Problem Set 3",
        "criteria": [
            {
                "id": "PS3_Q1_PROOF",
                "question_id": "Q1",
                "title": "Question 1 - Correctness Proof",
                "description": "Prove the algorithm correct.",
                "points": 10,
                "course_outcomes": ["LO2"],
                "program_outcomes": ["SO1", "SO6"],
                "abet_outcomes": ["SO1", "SO6"],
                "assessment_tags": ["proof", "correctness"],
            },
            {
                "id": "PS3_Q2_RUNTIME",
                "question_id": "Q2",
                "title": "Question 2 - Runtime Analysis",
                "description": "Analyze asymptotic runtime.",
                "points": 4,
                "course_outcomes": ["LO1"],
                "program_outcomes": ["SO1"],
                "abet_outcomes": ["SO1"],
                "assessment_tags": ["runtime", "asymptotic-analysis"],
            },
            {
                "id": "PS3_Q3_EXTRA",
                "question_id": "Q3",
                "title": "Question 3 - Optional Extension",
                "description": "Optional extension.",
                "points": 2,
                "course_outcomes": ["LO3"],
                "program_outcomes": ["SO2"],
                "abet_outcomes": ["SO2"],
                "assessment_tags": ["extension"],
            },
        ],
    }


def _assessment(*, submission=True):
    data = {
        "student_id": "alice",
        "student_name": "Alice Smith",
        "assignment_name": "Problem Set 3",
        "criteria": [
            {
                "id": "PS3_Q1_PROOF",
                "question_id": "Q1",
                "title": "Question 1 - Correctness Proof",
                "description": "Prove the algorithm correct.",
                "points_awarded": 8,
                "points_possible": 10,
                "selected": True,
                "counted": True,
                "course_outcomes": ["LO2"],
                "program_outcomes": ["SO1", "SO6"],
                "abet_outcomes": ["SO1", "SO6"],
                "assessment_tags": ["proof", "correctness"],
            },
            {
                "id": "PS3_Q2_RUNTIME",
                "question_id": "Q2",
                "title": "Question 2 - Runtime Analysis",
                "description": "Analyze asymptotic runtime.",
                "points_awarded": 3,
                "points_possible": 4,
                "selected": True,
                "counted": False,
                "course_outcomes": ["LO1"],
                "program_outcomes": ["SO1"],
                "abet_outcomes": ["SO1"],
                "assessment_tags": ["runtime", "asymptotic-analysis"],
            },
            {
                "id": "PS3_Q3_EXTRA",
                "question_id": "Q3",
                "title": "Question 3 - Optional Extension",
                "points_awarded": 0,
                "points_possible": 2,
                "selected": False,
                "counted": False,
                "course_outcomes": ["LO3"],
                "program_outcomes": ["SO2"],
                "abet_outcomes": ["SO2"],
                "assessment_tags": ["extension"],
            },
        ],
        "abet_meta": {
            "assessment_schema_version": "2.0",
            "assessment_id": "PS3",
            "course_code": "CS 2500",
            "semester": "Fall 2026",
            "rubric_schema_version": "2.0",
            "profile_id": "cs2500_algorithms",
        },
    }
    if submission:
        data["submission_meta"] = {
            "student_id": "alice",
            "source_used": "latex",
            "files": {
                "latex": "/evidence/alice/source/main.tex",
                "compiled_pdf": "/evidence/alice/compiled/main.pdf",
            },
            "file_hashes": {
                "latex_sha256": "latex-hash",
                "compiled_pdf_sha256": "pdf-hash",
            },
        }
    return data


def _assignment_meta():
    return {
        "assignment_id": "PS3",
        "assignment_title": "Problem Set 3",
        "assignment_type": "problem_set",
        "assignment_date": "2026-09-15",
    }


def _course_meta():
    return {
        "semester": "Fall 2026",
        "course_code": "CS 2500",
        "course_name": "Algorithms",
        "section": "104",
    }


class TestMasterEvidenceRowGeneration(unittest.TestCase):

    def test_all_policy_produces_one_row_per_rubric_criterion(self):
        result = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="all",
        )
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(
            [row["criterion_id"] for row in result.rows],
            ["PS3_Q1_PROOF", "PS3_Q2_RUNTIME", "PS3_Q3_EXTRA"],
        )
        for row in result.rows:
            self.assertEqual(tuple(row.keys()), MASTER_EVIDENCE_FIELDS)

    def test_question_outcomes_tags_points_and_percentage(self):
        result = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="all",
        )
        row = result.rows[1]
        self.assertEqual(row["question_id"], "Q2")
        self.assertEqual(row["course_outcomes"], ["LO1"])
        self.assertEqual(row["program_outcomes"], ["SO1"])
        self.assertEqual(row["abet_outcomes"], ["SO1"])
        self.assertEqual(row["assessment_tags"], ["runtime", "asymptotic-analysis"])
        self.assertEqual(row["points_awarded"], 3.0)
        self.assertEqual(row["points_possible"], 4.0)
        self.assertEqual(row["percentage"], 75.0)

    def test_assignment_and_course_metadata_are_preserved(self):
        row = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows[0]
        self.assertEqual(row["semester"], "Fall 2026")
        self.assertEqual(row["course_code"], "CS 2500")
        self.assertEqual(row["course_name"], "Algorithms")
        self.assertEqual(row["section"], "104")
        self.assertEqual(row["assignment_id"], "PS3")
        self.assertEqual(row["assignment_title"], "Problem Set 3")
        self.assertEqual(row["assignment_type"], "problem_set")
        self.assertEqual(row["assignment_date"], "2026-09-15")

    def test_counted_only_filters_selected_but_not_counted(self):
        rows = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows
        self.assertEqual([r["criterion_id"] for r in rows], ["PS3_Q1_PROOF"])

    def test_selected_only_keeps_selected_not_counted(self):
        rows = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="selected_only",
        ).rows
        self.assertEqual(
            [r["criterion_id"] for r in rows],
            ["PS3_Q1_PROOF", "PS3_Q2_RUNTIME"],
        )

    def test_include_excluded_keeps_rows_and_preserves_flags(self):
        rows = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
            include_excluded=True,
        ).rows
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["counted"])
        self.assertFalse(rows[1]["counted"])
        self.assertFalse(rows[2]["selected"])
        self.assertEqual({r["evidence_policy"] for r in rows}, {"counted_only"})

    def test_invalid_policy_fails_early(self):
        with self.assertRaises(ValueError):
            build_master_evidence_rows_for_assessment(
                _assessment(), _rubric(), _assignment_meta(), _course_meta(),
                evidence_policy="made_up_policy",
            )


class TestBackwardCompatibilityAndWarnings(unittest.TestCase):

    def test_missing_optional_fields_produce_blanks_not_crash(self):
        rubric = {
            "criteria": [{"id": "C1", "title": "No question label", "points": 5}]
        }
        assessment = {
            "student_id": "legacy",
            "criteria": [{
                "id": "C1",
                "title": "No question label",
                "points_awarded": 2,
                "points_possible": 5,
                "selected": True,
                "counted": True,
            }],
        }
        result = build_master_evidence_rows_for_assessment(
            assessment, rubric, {}, {}, evidence_policy="all"
        )
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row["student_name"], "")
        self.assertEqual(row["question_id"], "")
        self.assertEqual(row["criterion_description"], "")
        self.assertEqual(row["course_outcomes"], [])
        self.assertEqual(row["program_outcomes"], [])
        self.assertEqual(row["submission_source"], "")
        codes = {w["code"] for w in result.warnings}
        self.assertIn("missing_student_name", codes)
        self.assertIn("missing_question_id", codes)
        self.assertIn("missing_outcome_mapping", codes)
        self.assertIn("missing_submission_meta", codes)

    def test_legacy_missing_selected_counted_flags_follow_existing_policy_default(self):
        rubric = {"criteria": [{
            "id": "C1", "question_id": "Q1", "title": "Q1", "points": 5,
            "course_outcomes": ["LO1"], "program_outcomes": ["SO1"],
        }]}
        assessment = {
            "student_id": "legacy",
            "student_name": "Legacy Student",
            "criteria": [{
                "id": "C1", "title": "Q1",
                "points_awarded": 4, "points_possible": 5,
                "course_outcomes": ["LO1"], "program_outcomes": ["SO1"],
            }],
        }
        result = build_master_evidence_rows_for_assessment(
            assessment, rubric, {}, {}, evidence_policy="counted_only"
        )
        self.assertEqual(len(result.rows), 1)
        self.assertIsNone(result.rows[0]["selected"])
        self.assertIsNone(result.rows[0]["counted"])
        codes = {w["code"] for w in result.warnings}
        self.assertIn("missing_selected_flag", codes)
        self.assertIn("missing_counted_flag", codes)

    def test_zero_points_possible_has_blank_percentage(self):
        rubric = {"criteria": [{"id": "C1", "question_id": "Q1", "title": "Q1", "points": 0}]}
        assessment = {
            "student_id": "alice", "student_name": "Alice",
            "criteria": [{
                "id": "C1", "title": "Q1", "points_awarded": 0,
                "points_possible": 0, "selected": True, "counted": True,
            }],
        }
        row = build_master_evidence_rows_for_assessment(
            assessment, rubric, {}, {}, evidence_policy="all"
        ).rows[0]
        self.assertIsNone(row["percentage"])

    def test_missing_points_warns_and_keeps_none(self):
        rubric = {"criteria": [{"id": "C1", "question_id": "Q1", "title": "Q1"}]}
        assessment = {
            "student_id": "alice", "student_name": "Alice",
            "criteria": [{"id": "C1", "title": "Q1", "selected": True, "counted": True}],
        }
        result = build_master_evidence_rows_for_assessment(
            assessment, rubric, {}, {}, evidence_policy="all"
        )
        self.assertIsNone(result.rows[0]["points_awarded"])
        self.assertIsNone(result.rows[0]["points_possible"])
        self.assertIn("missing_points", {w["code"] for w in result.warnings})

    def test_missing_question_id_is_blank_and_warned(self):
        rubric = {"criteria": [{"id": "C1", "title": "Question 7 - Runtime", "points": 5}]}
        assessment = {
            "student_id": "alice", "student_name": "Alice",
            "criteria": [{
                "id": "C1", "title": "Question 7 - Runtime",
                "points_awarded": 5, "points_possible": 5,
                "selected": True, "counted": True,
            }],
        }
        result = build_master_evidence_rows_for_assessment(
            assessment, rubric, {}, {}, evidence_policy="all"
        )
        self.assertEqual(result.rows[0]["question_id"], "")
        self.assertIn("missing_question_id", {w["code"] for w in result.warnings})

    def test_filename_stem_is_compatibility_student_id(self):
        assessment = _assessment()
        assessment.pop("student_id")
        assessment["submission_meta"].pop("student_id")
        result = build_master_evidence_rows_for_assessment(
            assessment, _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
            assessment_file="/tmp/alice_legacy.json",
        )
        self.assertEqual(result.rows[0]["student_id"], "alice_legacy")
        self.assertIn("missing_student_id", {w["code"] for w in result.warnings})


class TestRubricAssessmentMerge(unittest.TestCase):

    def test_saved_assessment_snapshot_is_primary_for_abet_fields(self):
        rubric = _rubric()
        assessment = _assessment()
        assessment["criteria"][0]["points_possible"] = 12
        assessment["criteria"][0]["course_outcomes"] = ["LO_SAVED"]
        assessment["criteria"][0]["program_outcomes"] = ["SO_SAVED"]
        assessment["criteria"][0]["abet_outcomes"] = ["SO_SAVED"]
        row = build_master_evidence_rows_for_assessment(
            assessment, rubric, _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows[0]
        self.assertEqual(row["points_possible"], 12.0)
        self.assertEqual(row["course_outcomes"], ["LO_SAVED"])
        self.assertEqual(row["program_outcomes"], ["SO_SAVED"])
        self.assertAlmostEqual(row["percentage"], 8 / 12 * 100)

    def test_rubric_fills_metadata_missing_from_legacy_assessment(self):
        assessment = _assessment()
        criterion = assessment["criteria"][0]
        criterion.pop("question_id")
        criterion.pop("description")
        criterion.pop("course_outcomes")
        criterion.pop("program_outcomes")
        criterion.pop("abet_outcomes")
        criterion.pop("assessment_tags")
        row = build_master_evidence_rows_for_assessment(
            assessment, _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows[0]
        self.assertEqual(row["question_id"], "Q1")
        self.assertEqual(row["criterion_description"], "Prove the algorithm correct.")
        self.assertEqual(row["course_outcomes"], ["LO2"])
        self.assertEqual(row["program_outcomes"], ["SO1", "SO6"])
        self.assertEqual(row["assessment_tags"], ["proof", "correctness"])

    def test_legacy_title_match_used_only_when_id_missing(self):
        rubric = {"criteria": [{
            "id": "C1", "question_id": "Q1", "title": "Question 1 - Proof",
            "points": 5, "course_outcomes": ["LO1"], "program_outcomes": ["SO1"],
        }]}
        assessment = {
            "student_id": "alice", "student_name": "Alice",
            "criteria": [{
                "title": "Question 1 - Proof", "points_awarded": 4,
                "points_possible": 5, "selected": True, "counted": True,
            }],
        }
        rows = build_master_evidence_rows_for_assessment(
            assessment, rubric, {}, {}, evidence_policy="all"
        ).rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["criterion_id"], "C1")
        self.assertEqual(rows[0]["points_awarded"], 4.0)

    def test_assessment_only_criterion_is_preserved_and_warned(self):
        assessment = _assessment()
        assessment["criteria"].append({
            "id": "OLD_CRITERION",
            "question_id": "Q9",
            "title": "Old Criterion",
            "points_awarded": 1,
            "points_possible": 1,
            "selected": True,
            "counted": True,
            "program_outcomes": ["SO1"],
        })
        result = build_master_evidence_rows_for_assessment(
            assessment, _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="all",
        )
        self.assertIn("OLD_CRITERION", [r["criterion_id"] for r in result.rows])
        self.assertIn("rubric_criterion_not_found", {w["code"] for w in result.warnings})

    def test_rubric_only_criterion_appears_for_all_but_not_counted_only(self):
        assessment = _assessment()
        assessment["criteria"] = assessment["criteria"][:2]
        all_rows = build_master_evidence_rows_for_assessment(
            assessment, _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="all",
        ).rows
        counted_rows = build_master_evidence_rows_for_assessment(
            assessment, _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows
        q3 = next(r for r in all_rows if r["criterion_id"] == "PS3_Q3_EXTRA")
        self.assertIsNone(q3["points_awarded"])
        self.assertEqual(q3["points_possible"], 2.0)
        self.assertIsNone(q3["selected"])
        self.assertNotIn("PS3_Q3_EXTRA", [r["criterion_id"] for r in counted_rows])


class TestSubmissionMetadata(unittest.TestCase):

    def test_submission_source_paths_and_hashes_are_included(self):
        row = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows[0]
        self.assertEqual(row["submission_source"], "latex")
        self.assertEqual(row["submission_file_latex"], "/evidence/alice/source/main.tex")
        self.assertEqual(row["submission_file_pdf"], "/evidence/alice/compiled/main.pdf")
        self.assertEqual(row["submission_hash_latex"], "latex-hash")
        self.assertEqual(row["submission_hash_pdf"], "pdf-hash")

    def test_original_pdf_is_preferred_over_compiled_pdf(self):
        assessment = _assessment()
        assessment["submission_meta"]["files"]["pdf"] = "/student/original.pdf"
        assessment["submission_meta"]["file_hashes"]["pdf_sha256"] = "original-pdf-hash"
        row = build_master_evidence_rows_for_assessment(
            assessment, _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="counted_only",
        ).rows[0]
        self.assertEqual(row["submission_file_pdf"], "/student/original.pdf")
        self.assertEqual(row["submission_hash_pdf"], "original-pdf-hash")

    def test_missing_submission_metadata_is_blank_and_warned_once_per_assessment(self):
        result = build_master_evidence_rows_for_assessment(
            _assessment(submission=False), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="all",
        )
        self.assertTrue(all(r["submission_source"] == "" for r in result.rows))
        warnings = [w for w in result.warnings if w["code"] == "missing_submission_meta"]
        self.assertEqual(len(warnings), 1)


class TestPerformanceBand(unittest.TestCase):

    def test_row_band_uses_profile_but_meets_target_stays_blank(self):
        profile = SimpleNamespace(performance_bands={
            "excellent": [90, 100],
            "adequate": [75, 89.99],
            "needs_improvement": [40, 74.99],
            "inadequate": [0, 39.99],
        })
        rows = build_master_evidence_rows_for_assessment(
            _assessment(), _rubric(), _assignment_meta(), _course_meta(),
            evidence_policy="selected_only",
            outcome_profile=profile,
        ).rows
        self.assertEqual(rows[0]["performance_band"], "adequate")  # 80%
        self.assertEqual(rows[1]["performance_band"], "adequate")  # 75%
        self.assertIsNone(rows[0]["meets_target"])


class TestAssignmentFolderGeneration(unittest.TestCase):

    def _write_json(self, path, value):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle)

    def test_assignment_builder_reads_multiple_assessments(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_json(os.path.join(tmp, "alice.json"), _assessment())
            bob = _assessment()
            bob["student_id"] = "bob"
            bob["student_name"] = "Bob Jones"
            bob["submission_meta"]["student_id"] = "bob"
            self._write_json(os.path.join(tmp, "bob.json"), bob)

            rows = build_master_evidence_rows_for_assignment(
                _rubric(), tmp, _assignment_meta(), _course_meta(),
                evidence_policy="counted_only",
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["student_id"] for r in rows}, {"alice", "bob"})

    def test_unreadable_assessment_warns_and_does_not_abort_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_json(os.path.join(tmp, "alice.json"), _assessment())
            with open(os.path.join(tmp, "broken.json"), "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            result = collect_master_evidence_for_assignment(
                _rubric(), tmp, _assignment_meta(), _course_meta(),
                evidence_policy="counted_only",
            )
            self.assertEqual(len(result.rows), 1)
            self.assertIn("assessment_file_unreadable", {w["code"] for w in result.warnings})

    def test_existing_abet_json_files_are_not_treated_as_students(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_json(os.path.join(tmp, "alice.json"), _assessment())
            self._write_json(os.path.join(tmp, "abet_report.json"), {
                "criteria": [{"id": "NOT_STUDENT"}]
            })
            rows = build_master_evidence_rows_for_assignment(
                _rubric(), tmp, _assignment_meta(), _course_meta(),
                evidence_policy="counted_only",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["student_id"], "alice")

    def test_missing_assessment_directory_is_fatal(self):
        with self.assertRaises(FileNotFoundError):
            build_master_evidence_rows_for_assignment(
                _rubric(), "/definitely/not/here", _assignment_meta(), _course_meta()
            )


if __name__ == "__main__":
    unittest.main()
