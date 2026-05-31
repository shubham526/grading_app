"""
test_tools.py
=============

Tests for the three CLI tools in tools/.

Covers:
  - migrate_rubrics_to_abet.py:
      single-file migration (ID generation, schema version, auto-map)
      program_outcomes → abet_outcomes sync (Fix 2)
      abet_outcomes → program_outcomes normalisation
      duplicate title deduplication for generated IDs (Fix 3)
      manual duplicate IDs preserved (not rewritten)
      dry-run does not write
      batch mode: multiple files, output dir, dry-run
      validation report printed after migration

  - validate_abet_rubric.py:
      valid rubric exits 0
      bad rubric exits 0 without --strict, exits 1 with --strict
      --json output is parseable JSON (Fix 4)
      [SKIP] messages go to stderr, not stdout (Fix 4)
      profile-not-found warning goes to stderr, not stdout (Fix 4)

  - create_semester_config.py:
      scan_semester_folder detects assessment directories
      output JSON has required keys and schema_version
      assessment_dir stored as relative path (Fix 1)
      relative paths resolve to real directories (Fix 1)
      config loads into SemesterABETReport.from_config
      closing-the-loop fields present
      nonexistent folder raises
"""

import io
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh)
    return path


def _old_rubric(title="Old PS", n=2):
    return {"title": title, "criteria": [
        {"title": f"Question {i+1} - Runtime Analysis", "points": 5}
        for i in range(n)]}


def _assessment_folder(tmp, name, students):
    adir = os.path.join(tmp, name, "assessments")
    os.makedirs(adir, exist_ok=True)
    for student, (q1, q2) in students.items():
        _write(os.path.join(adir, f"{name}_{student.lower()}.json"), {
            "student_name": student,
            "criteria": [
                {"id": f"{name}_Q1", "title": "Q1",
                 "points_awarded": int(10 * q1 / 100), "points_possible": 10,
                 "program_outcomes": ["SO1"], "course_outcomes": ["LO1"],
                 "selected": True, "counted": True},
            ]})
    return adir


# ---------------------------------------------------------------------------
# migrate_rubrics_to_abet.py
# ---------------------------------------------------------------------------

class TestMigrationTool(unittest.TestCase):

    def test_adds_schema_version_and_ids(self):
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), _old_rubric())
            out = os.path.join(tmp, "out.json")
            rubric, changes = migrate_rubric(inp, out)
            self.assertEqual(rubric["schema_version"], "2.0")
            for c in rubric["criteria"]:
                self.assertTrue(c.get("id", ""))

    def test_existing_ids_preserved(self):
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), {
                "title": "Modern", "criteria": [
                    {"id": "MY_ID", "title": "Q1", "points": 5}]})
            out = os.path.join(tmp, "out.json")
            rubric, _ = migrate_rubric(inp, out)
            self.assertEqual(rubric["criteria"][0]["id"], "MY_ID")

    def test_auto_map_infers_lo_and_so(self):
        from tools.migrate_rubrics_to_abet import migrate_rubric
        from src.core.outcome_profile import load_default_profile
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), {
                "title": "PS3", "criteria": [
                    {"title": "Question 1 - Runtime Analysis", "points": 5}]})
            out = os.path.join(tmp, "out.json")
            profile = load_default_profile()
            rubric, changes = migrate_rubric(inp, out, profile=profile, auto_map=True)
            c = rubric["criteria"][0]
            self.assertIn("LO1", c["course_outcomes"])
            self.assertTrue(len(c["program_outcomes"]) > 0)

    def test_abet_outcomes_to_program_normalised(self):
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), {
                "title": "Legacy", "criteria": [
                    {"title": "Q1", "points": 5, "abet_outcomes": ["SO6"]}]})
            out = os.path.join(tmp, "out.json")
            rubric, _ = migrate_rubric(inp, out)
            c = rubric["criteria"][0]
            self.assertEqual(c["program_outcomes"], ["SO6"])
            self.assertEqual(c["abet_outcomes"],    ["SO6"])

    def test_program_outcomes_synced_to_abet(self):
        """Fix 2: program_outcomes present → abet_outcomes alias populated."""
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), {
                "title": "New Style", "criteria": [
                    {"title": "Q1", "points": 5, "program_outcomes": ["SO1", "SO6"]}]})
            out = os.path.join(tmp, "out.json")
            rubric, _ = migrate_rubric(inp, out)
            self.assertEqual(rubric["criteria"][0]["abet_outcomes"], ["SO1", "SO6"])

    def test_duplicate_titles_produce_unique_ids(self):
        """Fix 3: two criteria with same title → unique generated IDs."""
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), {
                "title": "Dups", "criteria": [
                    {"title": "Q1 Runtime", "points": 5},
                    {"title": "Q1 Runtime", "points": 5},
                    {"title": "Q1 Runtime", "points": 5},
                ]})
            out = os.path.join(tmp, "out.json")
            rubric, _ = migrate_rubric(inp, out)
            ids = [c["id"] for c in rubric["criteria"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_manual_duplicate_ids_preserved(self):
        """Manual duplicate IDs must not be rewritten — only flagged by validation."""
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), {
                "title": "Manual Dups", "criteria": [
                    {"id": "SAME", "title": "Q1", "points": 5},
                    {"id": "SAME", "title": "Q2", "points": 5},
                ]})
            out = os.path.join(tmp, "out.json")
            rubric, _ = migrate_rubric(inp, out)
            self.assertEqual([c["id"] for c in rubric["criteria"]], ["SAME", "SAME"])

    def test_dry_run_does_not_write(self):
        from tools.migrate_rubrics_to_abet import migrate_rubric
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), _old_rubric())
            out = os.path.join(tmp, "out.json")
            migrate_rubric(inp, out, dry_run=True)
            self.assertFalse(os.path.exists(out))

    def test_batch_mode(self):
        from tools.migrate_rubrics_to_abet import migrate_batch
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(1, 4):
                _write(os.path.join(tmp, f"ps{i}.json"), _old_rubric(f"PS{i}"))
            out_dir    = os.path.join(tmp, "migrated")
            summaries  = migrate_batch(tmp, output_dir=out_dir)
            ok_count   = sum(1 for s in summaries if s["status"] == "ok")
            self.assertEqual(ok_count, 3)
            for i in range(1, 4):
                self.assertTrue(os.path.exists(os.path.join(out_dir, f"ps{i}.json")))

    def test_batch_dry_run_no_output_dir(self):
        from tools.migrate_rubrics_to_abet import migrate_batch
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "ps1.json"), _old_rubric())
            out_dir = os.path.join(tmp, "migrated")
            migrate_batch(tmp, output_dir=out_dir, dry_run=True)
            self.assertFalse(os.path.exists(out_dir))

    def test_migration_runs_validation(self):
        from tools.migrate_rubrics_to_abet import migrate_rubric
        from src.core.outcome_profile import load_default_profile
        with tempfile.TemporaryDirectory() as tmp:
            inp = _write(os.path.join(tmp, "in.json"), _old_rubric())
            out = os.path.join(tmp, "out.json")
            rubric, changes = migrate_rubric(inp, out,
                                             profile=load_default_profile(),
                                             auto_map=True)
            self.assertIsInstance(changes, list)


# ---------------------------------------------------------------------------
# validate_abet_rubric.py
# ---------------------------------------------------------------------------

def _load_validate_mod():
    spec = importlib.util.spec_from_file_location(
        "validate_abet_rubric",
        os.path.join(_REPO_ROOT, "tools", "validate_abet_rubric.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestValidationCLI(unittest.TestCase):

    def _run(self, args):
        mod      = _load_validate_mod()
        old_argv = sys.argv
        sys.argv = ["validate_abet_rubric.py"] + args
        try:
            code = mod.main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old_argv
        return code

    def _run_json(self, args):
        mod        = _load_validate_mod()
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_argv   = sys.argv
        sys.argv   = ["v"] + args
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                try:
                    mod.main()
                except SystemExit:
                    pass
        finally:
            sys.argv = old_argv
        return stdout_buf.getvalue(), stderr_buf.getvalue()

    def _valid_rubric(self, tmp):
        return _write(os.path.join(tmp, "rubric.json"), {
            "schema_version": "2.0", "title": "T",
            "criteria": [{"id": "C1", "title": "Q1", "points": 5,
                          "course_outcomes": ["LO1"],
                          "program_outcomes": ["SO1"], "abet_outcomes": ["SO1"],
                          "assessment_tags": []}]})

    def _bad_rubric(self, tmp):
        return _write(os.path.join(tmp, "bad.json"), {
            "schema_version": "2.0", "title": "T",
            "criteria": [
                {"id": "DUP", "title": "Q1", "points": 5,
                 "course_outcomes": ["LO1"],
                 "program_outcomes": ["SO99"], "abet_outcomes": ["SO99"],
                 "assessment_tags": []},
                {"id": "DUP", "title": "Q2", "points": 5,
                 "course_outcomes": [],
                 "program_outcomes": [], "abet_outcomes": [],
                 "assessment_tags": []},
            ]})

    def test_valid_rubric_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._valid_rubric(tmp)
            code = self._run(["--rubric", path, "--profile", "cs2500_algorithms"])
            self.assertEqual(code, 0)

    def test_bad_rubric_exits_0_without_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._bad_rubric(tmp)
            code = self._run(["--rubric", path, "--profile", "cs2500_algorithms"])
            self.assertEqual(code, 0)

    def test_bad_rubric_exits_1_with_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._bad_rubric(tmp)
            code = self._run(["--rubric", path, "--profile", "cs2500_algorithms",
                               "--strict"])
            self.assertEqual(code, 1)

    def test_json_stdout_is_valid_json(self):
        """Fix 4: --json output must be parseable JSON with no extra text."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._valid_rubric(tmp)
            stdout, _ = self._run_json(["--rubric", path, "--json"])
            data = json.loads(stdout)
            self.assertIn("summary", data)
            self.assertIn("issues",  data)

    def test_skip_messages_on_stderr_not_stdout(self):
        """Fix 4: malformed assessment file → [SKIP] on stderr, not stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            rubric_path = self._valid_rubric(tmp)
            adir = os.path.join(tmp, "assessments")
            os.makedirs(adir)
            with open(os.path.join(adir, "bad.json"), "w") as fh:
                fh.write("NOT_VALID_JSON{{{")
            stdout, stderr = self._run_json(
                ["--rubric", rubric_path, "--assessments", adir, "--json"])
            data = json.loads(stdout)  # must still be valid JSON
            self.assertIn("summary", data)
            self.assertNotIn("SKIP", stdout)  # not in stdout

    def test_profile_warning_on_stderr_not_stdout(self):
        """Fix 4: profile-not-found warning must not corrupt JSON stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._valid_rubric(tmp)
            stdout, stderr = self._run_json(
                ["--rubric", path, "--json", "--profile", "nonexistent_xyz"])
            data = json.loads(stdout)
            self.assertIn("summary", data)
            self.assertNotIn("not found", stdout)


# ---------------------------------------------------------------------------
# create_semester_config.py
# ---------------------------------------------------------------------------

class TestCreateSemesterConfig(unittest.TestCase):

    def _semester_folder(self, tmp, assignments):
        for aname, students in assignments:
            _assessment_folder(tmp, aname, students)
        return tmp

    def test_scan_semester_folder(self):
        from tools.create_semester_config import scan_semester_folder
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [
                ("PS1", {"Alice": (80, 0), "Bob": (70, 0)}),
                ("PS2", {"Alice": (90, 0)}),
                ("Midterm", {"Alice": (85, 0)}),
            ])
            entries = scan_semester_folder(tmp)
            names = [e["assessment_name"] for e in entries]
            self.assertIn("PS1",    names)
            self.assertIn("PS2",    names)
            self.assertIn("Midterm", names)
            self.assertEqual(len(entries), 3)

    def test_create_config_writes_json(self):
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [("PS1", {"Alice": (80, 0)})])
            out    = os.path.join(tmp, "semester.json")
            config = create_semester_config(tmp, out, course_code="CS 2500",
                                             target_pct=75.0)
            self.assertTrue(os.path.exists(out))
            self.assertEqual(config["course_code"], "CS 2500")
            self.assertEqual(len(config["assessments"]), 1)

    def test_schema_version_in_config(self):
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [("PS1", {"Alice": (80, 0)})])
            out    = os.path.join(tmp, "semester.json")
            config = create_semester_config(tmp, out)
            self.assertEqual(config["schema_version"], "2.0")

    def test_closing_the_loop_fields_present(self):
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [("PS1", {"Alice": (80, 0)})])
            out    = os.path.join(tmp, "semester.json")
            config = create_semester_config(tmp, out)
            for field in ("reflection", "planned_improvements",
                          "notes_for_next_offering"):
                self.assertIn(field, config)

    def test_required_assessment_keys(self):
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [("PS1", {"Alice": (80, 0)})])
            out    = os.path.join(tmp, "semester.json")
            config = create_semester_config(tmp, out)
            for a in config["assessments"]:
                for key in ("assessment_id", "assessment_name",
                            "assessment_dir", "include_in_abet", "weight"):
                    self.assertIn(key, a)

    def test_paths_are_relative_not_absolute(self):
        """Fix 1: assessment_dir must be stored as a relative path."""
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [("PS1", {"Alice": (80, 0)})])
            out    = os.path.join(tmp, "semester.json")
            config = create_semester_config(tmp, out)
            for a in config["assessments"]:
                self.assertFalse(os.path.isabs(a["assessment_dir"]),
                                 f"Expected relative path, got: {a['assessment_dir']}")

    def test_relative_paths_resolve_correctly(self):
        """Fix 1: stored relative path resolves to an existing directory."""
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            self._semester_folder(tmp, [("PS1", {"Alice": (80, 0)})])
            out    = os.path.join(tmp, "semester.json")
            config = create_semester_config(tmp, out)
            base   = os.path.dirname(os.path.abspath(out))
            for a in config["assessments"]:
                resolved = os.path.normpath(
                    os.path.join(base, a["assessment_dir"]))
                self.assertTrue(os.path.isdir(resolved),
                                f"Resolved path not found: {resolved}")

    def test_config_in_subdirectory_resolves(self):
        """Fix 1: config in reports/ subdir can still find assessments above it."""
        from tools.create_semester_config import create_semester_config
        from src.tools.semester_abet_report import SemesterABETReport
        with tempfile.TemporaryDirectory() as tmp:
            adir = os.path.join(tmp, "PS1", "assessments")
            os.makedirs(adir)
            _write(os.path.join(adir, "alice.json"), {
                "student_name": "Alice",
                "criteria": [{"id": "C1", "title": "Q1",
                              "points_awarded": 8, "points_possible": 10,
                              "program_outcomes": ["SO1"], "abet_outcomes": ["SO1"],
                              "course_outcomes": ["LO1"],
                              "selected": True, "counted": True}]})
            reports_dir = os.path.join(tmp, "reports")
            os.makedirs(reports_dir)
            out    = os.path.join(reports_dir, "semester.json")
            create_semester_config(tmp, out, target_pct=75.0)
            # Must aggregate without error
            obj    = SemesterABETReport.from_config(out)
            report = obj.aggregate()
            ok     = [d for d in report["assignment_details"] if "error" not in d]
            self.assertEqual(len(ok), 1)

    def test_nonexistent_folder_raises(self):
        from tools.create_semester_config import create_semester_config
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                create_semester_config("/nonexistent/path",
                                       os.path.join(tmp, "out.json"))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
