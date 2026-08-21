"""Release-level, Docker-independent acceptance guards for v2.3.4.1.

The detailed Qt behavior is covered by the permanent ``*_v2341`` workspace and
shell tests.  This module protects the final release contract itself: version,
shared Assessment Home, mode isolation, transition safety, programming action
surface, and release documentation.  It intentionally owns no external fixture
folder so it remains self-contained when ``src/tests`` is copied or run alone.
"""

from pathlib import Path
import unittest

import src


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"
_MAIN = _SRC_ROOT / "ui/main_window.py"
_HOME = _SRC_ROOT / "ui/workspaces/assessment_home_workspace.py"
_PROGRAMMING = _SRC_ROOT / "ui/workspaces/programming_grading_workspace.py"
_WRITTEN = _SRC_ROOT / "ui/workspaces/written_grading_workspace.py"
_DOCS = _REPO_ROOT / "docs"


class TestDualModeReleaseAcceptanceV2341(unittest.TestCase):
    def test_package_version_has_not_regressed_below_v2_3_4_1(self):
        parts = tuple(int(value) for value in src.__version__.split("."))
        self.assertGreaterEqual(parts, (2, 3, 4, 1))

    def test_shared_assessment_home_is_the_shell_entry_point(self):
        main = _MAIN.read_text(encoding="utf-8")
        home = _HOME.read_text(encoding="utf-8")

        self.assertIn("AssessmentHomeWorkspace", main)
        self.assertIn("self.show_assessment_home(force=True)", main)
        self.assertIn("Assessment Home…", main)
        self.assertIn('_REQUIRED_KEYS = ("rubric", "roster", "workspace")', home)
        self.assertIn('"Open Written Grader"', home)
        self.assertIn('"Open Programming Grader"', home)

    def test_written_and_programming_controls_are_mode_isolated(self):
        main = _MAIN.read_text(encoding="utf-8")
        written = _WRITTEN.read_text(encoding="utf-8")
        programming = _PROGRAMMING.read_text(encoding="utf-8")

        self.assertIn("WrittenGradingWorkspace", written)
        self.assertIn("self.load_btn.setVisible(False)", main)
        self.assertIn('self.setup_menu_button.setText("Written Setup")', main)
        self.assertNotIn('QMenu("Programming Autograding", self)', main)

        for label in (
            "Configure Autograder",
            "Import Submissions",
            "Check Runtime",
            "Grade Selected",
            "Grade All",
            "Run History",
        ):
            self.assertIn('"{}"'.format(label), programming)

        for written_only_fragment in (
            "submissionWorkspace",
            "gradingWorkspace",
            "QUESTION_CENTRIC",
        ):
            self.assertNotIn(written_only_fragment, programming)

    def test_mode_transition_safety_contract_is_present(self):
        main = _MAIN.read_text(encoding="utf-8")
        self.assertIn("def _confirm_written_workspace_transition", main)
        self.assertIn("QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel", main)
        self.assertIn("def _can_leave_current_grading_mode", main)
        self.assertIn('"Programming Grading In Progress"', main)
        self.assertIn("self._autograding_workers", main)
        self.assertIn("self._autograding_batch_dialog", main)

    def test_programming_dashboard_reuses_existing_v233_orchestration(self):
        main = _MAIN.read_text(encoding="utf-8")
        self.assertIn("AutogradingWorker(", main)
        self.assertIn("def show_autograding_setup", main)
        self.assertIn("def check_programming_runtime", main)
        self.assertIn("def grade_current_programming_submission", main)
        self.assertIn("def grade_all_programming_submissions", main)
        self.assertIn("def show_autograding_history", main)
        self.assertIn("def view_latest_programming_result", main)
        self.assertIn("service.list_history", main)
        self.assertIn("repository.get_active_submission", main)

    def test_release_documentation_exists_and_describes_current_navigation(self):
        expected = (
            _DOCS / "dual_mode_grading.md",
            _DOCS / "programming_autograding.md",
            _DOCS / "v2.3.4.1_manual_acceptance.md",
            _DOCS / "releases/v2.3.4.1.md",
        )
        for path in expected:
            self.assertTrue(path.is_file(), str(path))

        dual_mode = (_DOCS / "dual_mode_grading.md").read_text(encoding="utf-8")
        programming = (_DOCS / "programming_autograding.md").read_text(encoding="utf-8")
        acceptance = (_DOCS / "v2.3.4.1_manual_acceptance.md").read_text(encoding="utf-8")
        release = (_DOCS / "releases/v2.3.4.1.md").read_text(encoding="utf-8")

        self.assertIn("Assessment Home", dual_mode)
        self.assertIn("Open Programming Grader", dual_mode)
        self.assertIn("File → Assessment Home…", dual_mode)
        self.assertIn("Programming dashboard", programming)
        self.assertNotIn("Tools → Programming Autograding", programming)
        self.assertIn("Save / Discard / Cancel", acceptance)
        self.assertIn("v2.3.4.1", release)


if __name__ == "__main__":
    unittest.main(verbosity=2)
