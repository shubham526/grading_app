"""Tests for v2.2.1 Commit 2 semester-level master evidence composition."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.tools.master_evidence_export import (
    build_master_evidence_rows_for_semester,
    build_master_evidence_rows_for_semester_config,
    collect_master_evidence_for_semester,
    collect_master_evidence_for_semester_config,
)


def _rubric(assignment_id: str, title: str, *, question_id: str = "Q1") -> dict:
    return {
        "schema_version": "2.0",
        "assessment_id": assignment_id,
        "course_code": "CS 2500",
        "semester": "Fall 2026",
        "title": title,
        "criteria": [{
            "id": f"{assignment_id}_{question_id}_C1",
            "question_id": question_id,
            "title": f"{question_id} Evidence",
            "description": f"Evidence for {title}",
            "points": 10,
            "course_outcomes": ["LO1"],
            "program_outcomes": ["SO1"],
            "abet_outcomes": ["SO1"],
            "assessment_tags": ["proof"],
        }],
    }


def _assessment(
    assignment_id: str,
    student_id: str,
    student_name: str,
    *,
    awarded: float = 8,
    selected: bool = True,
    counted: bool = True,
    submission: bool = True,
) -> dict:
    data = {
        "student_id": student_id,
        "student_name": student_name,
        "criteria": [{
            "id": f"{assignment_id}_Q1_C1",
            "question_id": "Q1",
            "title": "Q1 Evidence",
            "description": "Saved evidence",
            "points_awarded": awarded,
            "points_possible": 10,
            "selected": selected,
            "counted": counted,
            "course_outcomes": ["LO1"],
            "program_outcomes": ["SO1"],
            "abet_outcomes": ["SO1"],
            "assessment_tags": ["proof"],
        }],
        "abet_meta": {
            "assessment_id": assignment_id,
            "course_code": "CS 2500",
            "semester": "Fall 2026",
        },
    }
    if submission:
        data["submission_meta"] = {
            "student_id": student_id,
            "source_used": "latex",
            "files": {"latex": f"/evidence/{student_id}/main.tex"},
            "file_hashes": {"latex_sha256": f"hash-{student_id}"},
        }
    return data


class SemesterFixtureMixin:
    def _write_json(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def _make_assignment(
        self,
        root,
        assignment_id,
        title,
        students,
        *,
        rubric_filename="rubric.json",
    ):
        folder = Path(root) / assignment_id
        assessments = folder / "assessments"
        assessments.mkdir(parents=True, exist_ok=True)
        self._write_json(folder / rubric_filename, _rubric(assignment_id, title))
        for student_id, student in students.items():
            self._write_json(
                assessments / f"{student_id}.json",
                _assessment(
                    assignment_id,
                    student_id,
                    student.get("name", student_id.title()),
                    awarded=student.get("awarded", 8),
                    selected=student.get("selected", True),
                    counted=student.get("counted", True),
                    submission=student.get("submission", True),
                ),
            )
        return folder, assessments

    def _course_config(self, entries):
        return {
            "schema_version": "2.0",
            "semester": "Fall 2026",
            "course_code": "CS 2500",
            "course_name": "Algorithms",
            "section": "104",
            "assessments": entries,
        }


class TestSemesterComposition(SemesterFixtureMixin, unittest.TestCase):

    def test_multiple_assignments_are_composed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {
                "alice": {"name": "Alice", "awarded": 8},
                "bob": {"name": "Bob", "awarded": 7},
            })
            self._make_assignment(tmp, "PS2", "Problem Set 2", {
                "alice": {"name": "Alice", "awarded": 9},
            })
            config = self._course_config([
                {
                    "assessment_id": "PS1",
                    "assessment_name": "Problem Set 1",
                    "assessment_dir": "PS1/assessments",
                    "rubric_path": "PS1/rubric.json",
                    "include_in_abet": True,
                    "weight": 1.0,
                },
                {
                    "assessment_id": "PS2",
                    "assessment_name": "Problem Set 2",
                    "assessment_dir": "PS2/assessments",
                    "rubric_path": "PS2/rubric.json",
                    "include_in_abet": True,
                    "weight": 1.0,
                },
            ])

            rows = build_master_evidence_rows_for_semester(
                config, evidence_policy="counted_only", base_dir=tmp
            )
            self.assertEqual(len(rows), 3)
            self.assertEqual({r["assignment_id"] for r in rows}, {"PS1", "PS2"})
            self.assertEqual({r["student_id"] for r in rows}, {"alice", "bob"})

    def test_assignment_and_course_metadata_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Rubric Title", {"alice": {}})
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_name": "Configured Problem Set 1",
                "assessment_type": "problem_set",
                "assignment_date": "2026-09-05",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            row = build_master_evidence_rows_for_semester(
                config, base_dir=tmp
            )[0]
            self.assertEqual(row["semester"], "Fall 2026")
            self.assertEqual(row["course_code"], "CS 2500")
            self.assertEqual(row["course_name"], "Algorithms")
            self.assertEqual(row["section"], "104")
            self.assertEqual(row["assignment_id"], "PS1")
            self.assertEqual(row["assignment_title"], "Configured Problem Set 1")
            self.assertEqual(row["assignment_type"], "problem_set")
            self.assertEqual(row["assignment_date"], "2026-09-05")

    def test_design_doc_assignments_key_and_alias_fields_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {"alice": {}})
            config = {
                "semester": "Fall 2026",
                "course_code": "CS 2500",
                "course_name": "Algorithms",
                "section": "104",
                "assignments": [{
                    "assignment_id": "PS1",
                    "assignment_title": "Asymptotic Analysis",
                    "assignment_type": "problem_set",
                    "assignment_date": "2026-09-05",
                    "assessments_dir": "PS1/assessments",
                    "rubric_path": "PS1/rubric.json",
                }],
            }
            row = build_master_evidence_rows_for_semester(config, base_dir=tmp)[0]
            self.assertEqual(row["assignment_id"], "PS1")
            self.assertEqual(row["assignment_title"], "Asymptotic Analysis")
            self.assertEqual(row["assignment_type"], "problem_set")

    def test_include_in_abet_false_matches_existing_semester_report_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {"alice": {}})
            self._make_assignment(tmp, "PS2", "Problem Set 2", {"alice": {}})
            config = self._course_config([
                {
                    "assessment_id": "PS1",
                    "assessment_dir": "PS1/assessments",
                    "rubric_path": "PS1/rubric.json",
                    "include_in_abet": True,
                },
                {
                    "assessment_id": "PS2",
                    "assessment_dir": "PS2/assessments",
                    "rubric_path": "PS2/rubric.json",
                    "include_in_abet": False,
                },
            ])
            rows = build_master_evidence_rows_for_semester(config, base_dir=tmp)
            self.assertEqual({r["assignment_id"] for r in rows}, {"PS1"})

    def test_evidence_policy_is_forwarded_to_every_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {
                "alice": {"selected": True, "counted": False},
            })
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            counted = build_master_evidence_rows_for_semester(
                config, evidence_policy="counted_only", base_dir=tmp
            )
            selected = build_master_evidence_rows_for_semester(
                config, evidence_policy="selected_only", base_dir=tmp
            )
            self.assertEqual(counted, [])
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["evidence_policy"], "selected_only")

    def test_include_excluded_is_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {
                "alice": {"selected": False, "counted": False},
            })
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            rows = build_master_evidence_rows_for_semester(
                config,
                evidence_policy="counted_only",
                include_excluded=True,
                base_dir=tmp,
            )
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["selected"])
            self.assertFalse(rows[0]["counted"])


class TestSemesterConfigPathResolution(SemesterFixtureMixin, unittest.TestCase):

    def test_config_file_helper_resolves_relative_paths_from_config_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "semester_root"
            root.mkdir()
            self._make_assignment(root, "PS1", "Problem Set 1", {"alice": {}})
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_name": "Problem Set 1",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            config_path = root / "semester.json"
            self._write_json(config_path, config)

            rows = build_master_evidence_rows_for_semester_config(str(config_path))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["student_id"], "alice")

    def test_absolute_paths_continue_to_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, assessments = self._make_assignment(
                tmp, "PS1", "Problem Set 1", {"alice": {}}
            )
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": str(assessments),
                "rubric_path": str(folder / "rubric.json"),
            }])
            rows = build_master_evidence_rows_for_semester(config)
            self.assertEqual(len(rows), 1)

    def test_missing_course_fields_fall_back_to_rubric_where_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {"alice": {}})
            config = {
                "assessments": [{
                    "assessment_id": "PS1",
                    "assessment_dir": "PS1/assessments",
                    "rubric_path": "PS1/rubric.json",
                }]
            }
            row = build_master_evidence_rows_for_semester(config, base_dir=tmp)[0]
            self.assertEqual(row["semester"], "Fall 2026")
            self.assertEqual(row["course_code"], "CS 2500")
            self.assertEqual(row["assignment_title"], "Problem Set 1")


class TestSemesterWarnings(SemesterFixtureMixin, unittest.TestCase):

    def test_assignment_warnings_are_collected_and_tagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {
                "alice": {"submission": False},
            })
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            result = collect_master_evidence_for_semester(config, base_dir=tmp)
            warning = next(
                w for w in result.warnings if w["code"] == "missing_submission_meta"
            )
            self.assertEqual(warning["assignment_id"], "PS1")

    def test_bad_assignment_does_not_abort_good_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {"alice": {}})
            config = self._course_config([
                {
                    "assessment_id": "PS1",
                    "assessment_dir": "PS1/assessments",
                    "rubric_path": "PS1/rubric.json",
                },
                {
                    "assessment_id": "PS2",
                    "assessment_dir": "PS2/assessments",
                    "rubric_path": "PS2/missing-rubric.json",
                },
            ])
            result = collect_master_evidence_for_semester(config, base_dir=tmp)
            self.assertEqual(len(result.rows), 1)
            warning = next(w for w in result.warnings if w["code"] == "rubric_file_missing")
            self.assertEqual(warning["assignment_id"], "PS2")

    def test_missing_assessments_directory_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "PS1"
            folder.mkdir()
            self._write_json(folder / "rubric.json", _rubric("PS1", "Problem Set 1"))
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": "PS1/no-such-assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            result = collect_master_evidence_for_semester(config, base_dir=tmp)
            self.assertEqual(result.rows, [])
            self.assertIn("assessments_dir_missing", {w["code"] for w in result.warnings})

    def test_missing_rubric_path_is_warning(self):
        config = self._course_config([{
            "assessment_id": "PS1",
            "assessment_dir": "PS1/assessments",
        }])
        result = collect_master_evidence_for_semester(config)
        self.assertEqual(result.rows, [])
        self.assertIn("missing_rubric_path", {w["code"] for w in result.warnings})

    def test_unreadable_rubric_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "PS1"
            assessments = folder / "assessments"
            assessments.mkdir(parents=True)
            (folder / "rubric.json").write_text("{bad-json", encoding="utf-8")
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            result = collect_master_evidence_for_semester(config, base_dir=tmp)
            self.assertEqual(result.rows, [])
            self.assertIn("rubric_file_unreadable", {w["code"] for w in result.warnings})

    def test_empty_config_returns_warning_not_crash(self):
        result = collect_master_evidence_for_semester({"semester": "Fall 2026"})
        self.assertEqual(result.rows, [])
        self.assertIn("no_assignments_configured", {w["code"] for w in result.warnings})

    def test_bad_profile_is_nonfatal_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_assignment(tmp, "PS1", "Problem Set 1", {"alice": {}})
            config = self._course_config([{
                "assessment_id": "PS1",
                "assessment_dir": "PS1/assessments",
                "rubric_path": "PS1/rubric.json",
            }])
            config["profile_id"] = "definitely_missing_profile"
            result = collect_master_evidence_for_semester(config, base_dir=tmp)
            self.assertEqual(len(result.rows), 1)
            self.assertIn("outcome_profile_unavailable", {w["code"] for w in result.warnings})


class TestSemesterInputValidation(SemesterFixtureMixin, unittest.TestCase):

    def test_invalid_policy_fails_before_io(self):
        with self.assertRaises(ValueError):
            build_master_evidence_rows_for_semester(
                {"assessments": []}, evidence_policy="not-a-policy"
            )

    def test_non_list_assessments_fails(self):
        with self.assertRaises(ValueError):
            collect_master_evidence_for_semester({"assessments": {}})

    def test_missing_config_file_is_fatal(self):
        with self.assertRaises(FileNotFoundError):
            collect_master_evidence_for_semester_config("/definitely/not/here/semester.json")

    def test_malformed_config_file_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semester.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ValueError):
                collect_master_evidence_for_semester_config(str(path))


if __name__ == "__main__":
    unittest.main()
