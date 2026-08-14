"""Tests for v2.2.1 Commit 4 Master ABET Evidence CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "tools" / "export_master_abet_evidence.py"


def _rubric() -> dict:
    return {
        "schema_version": "2.0",
        "assessment_id": "PS1",
        "title": "Asymptotic Analysis",
        "criteria": [
            {
                "id": "PS1_Q1_RUNTIME",
                "question_id": "Q1",
                "title": "Question 1 - Runtime",
                "description": "Analyze the runtime.",
                "points": 10,
                "course_outcomes": ["LO1"],
                "program_outcomes": ["SO1"],
                "abet_outcomes": ["SO1"],
                "assessment_tags": ["runtime"],
            }
        ],
    }


def _assessment(*, counted: bool = True, selected: bool = True, submission_meta=True) -> dict:
    data = {
        "student_id": "alice",
        "student_name": "Alice Smith",
        "criteria": [
            {
                "id": "PS1_Q1_RUNTIME",
                "question_id": "Q1",
                "title": "Question 1 - Runtime",
                "description": "Analyze the runtime.",
                "points_awarded": 8,
                "points_possible": 10,
                "selected": selected,
                "counted": counted,
                "course_outcomes": ["LO1"],
                "program_outcomes": ["SO1"],
                "abet_outcomes": ["SO1"],
                "assessment_tags": ["runtime"],
            }
        ],
    }
    if submission_meta:
        data["submission_meta"] = {
            "source_used": "latex",
            "files": {"latex": "submissions/alice/main.tex"},
            "file_hashes": {"latex_sha256": "abc123"},
        }
    return data


class CLIFixture:
    def __init__(self, root: Path, *, counted=True, selected=True, submission_meta=True):
        self.root = root
        self.rubric_path = root / "rubric.json"
        self.assessments_dir = root / "assessments"
        self.assessments_dir.mkdir(parents=True)
        self.rubric_path.write_text(json.dumps(_rubric()), encoding="utf-8")
        (self.assessments_dir / "alice.json").write_text(
            json.dumps(
                _assessment(
                    counted=counted,
                    selected=selected,
                    submission_meta=submission_meta,
                )
            ),
            encoding="utf-8",
        )
        self.semester_path = root / "semester.json"
        self.semester_path.write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "semester": "Fall 2026",
                    "course_code": "CS 2500",
                    "course_name": "Algorithms",
                    "section": "104",
                    "assessments": [
                        {
                            "assessment_id": "PS1",
                            "assessment_name": "Asymptotic Analysis",
                            "rubric_path": "rubric.json",
                            "assessment_dir": "assessments",
                            "include_in_abet": True,
                            "weight": 1.0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


class TestMasterEvidenceCLI(unittest.TestCase):

    def test_semester_config_mode_exports_csv_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root)
            output = root / "out"
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(output),
                "--formats", "csv,json",
                "--evidence-policy", "counted_only",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "master_abet_evidence.csv").is_file())
            self.assertTrue((output / "master_abet_evidence.json").is_file())
            payload = json.loads((output / "master_abet_evidence.json").read_text())
            self.assertEqual(payload["summary"]["num_rows"], 1)
            self.assertEqual(payload["course"]["course_code"], "CS 2500")
            self.assertIn("Master ABET evidence export complete.", result.stdout)

    def test_assignment_mode_exports_with_cli_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root)
            output = root / "out"
            result = _run(
                "--rubric", str(fixture.rubric_path),
                "--assessments-dir", str(fixture.assessments_dir),
                "--assignment-id", "PS1",
                "--assignment-title", "Asymptotic Analysis",
                "--course-code", "CS 2500",
                "--course-name", "Algorithms",
                "--semester", "Fall 2026",
                "--section", "104",
                "--output-dir", str(output),
                "--formats", "json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((output / "master_abet_evidence.json").read_text())
            row = payload["rows"][0]
            self.assertEqual(row["assignment_id"], "PS1")
            self.assertEqual(row["assignment_title"], "Asymptotic Analysis")
            self.assertEqual(row["course_code"], "CS 2500")
            self.assertEqual(row["semester"], "Fall 2026")

    def test_assignment_mode_requires_assessments_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CLIFixture(Path(tmp))
            result = _run(
                "--rubric", str(fixture.rubric_path),
                "--output-dir", str(Path(tmp) / "out"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--assessments-dir is required", result.stderr)

    def test_modes_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CLIFixture(Path(tmp))
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--rubric", str(fixture.rubric_path),
                "--output-dir", str(Path(tmp) / "out"),
            )
            self.assertEqual(result.returncode, 2)

    def test_one_mode_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run("--output-dir", str(Path(tmp) / "out"))
            self.assertEqual(result.returncode, 2)

    def test_invalid_evidence_policy_fails_in_argparse(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CLIFixture(Path(tmp))
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(Path(tmp) / "out"),
                "--evidence-policy", "bogus",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid choice", result.stderr)

    def test_invalid_format_fails_in_argparse(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CLIFixture(Path(tmp))
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(Path(tmp) / "out"),
                "--formats", "csv,pdf",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsupported format", result.stderr)

    def test_formats_are_case_insensitive_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root)
            output = root / "out"
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(output),
                "--formats", "CSV,json,csv",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "master_abet_evidence.csv").is_file())
            self.assertTrue((output / "master_abet_evidence.json").is_file())
            self.assertFalse((output / "master_abet_evidence.xlsx").exists())

    def test_include_excluded_keeps_noncounted_row_with_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root, counted=False, selected=False)

            without_output = root / "without"
            without = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(without_output),
                "--formats", "json",
                "--evidence-policy", "counted_only",
            )
            self.assertEqual(without.returncode, 0, without.stderr)
            payload = json.loads(
                (without_output / "master_abet_evidence.json").read_text()
            )
            self.assertEqual(payload["rows"], [])

            with_output = root / "with"
            included = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(with_output),
                "--formats", "json",
                "--evidence-policy", "counted_only",
                "--include-excluded",
            )
            self.assertEqual(included.returncode, 0, included.stderr)
            payload = json.loads((with_output / "master_abet_evidence.json").read_text())
            self.assertEqual(len(payload["rows"]), 1)
            self.assertFalse(payload["rows"][0]["counted"])
            self.assertFalse(payload["rows"][0]["selected"])

    def test_strict_mode_fails_on_critical_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root)
            # A malformed student assessment is skipped by the backend and is a
            # critical warning for CLI strict mode.
            (fixture.assessments_dir / "broken.json").write_text("{bad", encoding="utf-8")
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(root / "out"),
                "--formats", "json",
                "--strict",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("STRICT:", result.stderr)
            self.assertIn("assessment_file_unreadable", result.stdout)

    def test_non_strict_mode_exports_despite_critical_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root)
            (fixture.assessments_dir / "broken.json").write_text("{bad", encoding="utf-8")
            output = root / "out"
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(output),
                "--formats", "json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((output / "master_abet_evidence.json").read_text())
            codes = {warning["code"] for warning in payload["warnings"]}
            self.assertIn("assessment_file_unreadable", codes)

    def test_strict_mode_does_not_fail_on_optional_submission_metadata_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = CLIFixture(root, submission_meta=False)
            output = root / "out"
            result = _run(
                "--semester-config", str(fixture.semester_path),
                "--output-dir", str(output),
                "--formats", "json",
                "--strict",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((output / "master_abet_evidence.json").read_text())
            codes = {warning["code"] for warning in payload["warnings"]}
            self.assertIn("missing_submission_meta", codes)

    def test_missing_semester_config_is_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                "--semester-config", str(Path(tmp) / "missing.json"),
                "--output-dir", str(Path(tmp) / "out"),
                "--formats", "json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("semester config not found", result.stderr)

    def test_assignment_missing_rubric_is_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assessments = root / "assessments"
            assessments.mkdir()
            result = _run(
                "--rubric", str(root / "missing.json"),
                "--assessments-dir", str(assessments),
                "--output-dir", str(root / "out"),
                "--formats", "json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("rubric not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
