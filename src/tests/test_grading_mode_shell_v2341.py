"""v2.3.4.1 integration tests for Assessment Home and the mode shell."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication
except ModuleNotFoundError as exc:  # pragma: no cover
    QApplication = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None
    from src.core.roster import StudentRecord
    from src.ui.main_window import RubricGrader
    from src.ui.modes.grading_mode import GradingMode
    from src.ui.workspaces import (
        AssessmentHomeWorkspace,
        ProgrammingGradingWorkspace,
        WrittenGradingWorkspace,
    )


@unittest.skipIf(
    QApplication is None,
    "Full PyQt application runtime unavailable: {!r}".format(_IMPORT_ERROR),
)
class TestGradingModeShellV2341(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.window = RubricGrader()
        self.app.processEvents()

    def tearDown(self):
        try:
            self.window.auto_save_timer.stop()
        except Exception:
            pass
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _prime_shared_setup(self):
        root = Path(self.tmp.name)
        rubric_path = root / "rubric.json"
        roster_path = root / "roster.csv"
        rubric_path.write_text("{}", encoding="utf-8")
        roster_path.write_text("student_id,student_name\\nalice,Alice\\n", encoding="utf-8")
        record = StudentRecord("alice", "Alice")
        self.window.rubric_data = {
            "schema_version": "2.0",
            "assessment_id": "HOME_TEST",
            "title": "Home Test",
            "criteria": [],
        }
        self.window.rubric_file_path = str(rubric_path)
        self.window.roster_file_path = str(roster_path)
        self.window.roster_records = [record]
        self.window.student_records = [record]
        self.window.assessments_dir = str(root)
        self.window._refresh_assessment_home()

    def test_startup_opens_shared_assessment_home(self):
        self.assertIsNone(self.window.current_grading_mode)
        self.assertIsInstance(
            self.window.assessment_home_workspace,
            AssessmentHomeWorkspace,
        )
        self.assertIs(
            self.window.active_grading_workspace(),
            self.window.assessment_home_workspace,
        )
        self.assertEqual(self.window.windowTitle(), "Rubric Grading Tool")
        self.assertFalse(
            self.window.assessment_home_workspace.written_card.open_button.isEnabled()
        )
        self.assertFalse(
            self.window.assessment_home_workspace.programming_card.open_button.isEnabled()
        )

    def test_written_mode_reuses_exact_existing_written_root(self):
        self._prime_shared_setup()
        written_root = self.window._written_central_widget
        written_workspace = self.window.written_workspace
        submission_workspace = self.window.submission_workspace
        workflow_combo = self.window.workflow_mode_combo

        self.assertIsInstance(written_workspace, WrittenGradingWorkspace)
        self.assertIs(written_workspace.legacy_root, written_root)

        self.assertTrue(self.window.set_grading_mode(GradingMode.WRITTEN))
        self.assertIs(self.window.active_grading_workspace(), written_workspace)
        self.assertIs(self.window.current_grading_mode, GradingMode.WRITTEN)
        self.assertIs(self.window.submission_workspace, submission_workspace)
        self.assertIs(self.window.workflow_mode_combo, workflow_combo)

        self.assertTrue(self.window.show_assessment_home())
        self.assertTrue(self.window.set_grading_mode(GradingMode.WRITTEN))
        self.assertIs(self.window.active_grading_workspace(), written_workspace)
        self.assertIs(written_workspace.legacy_root, written_root)
        self.assertIs(self.window.submission_workspace, submission_workspace)
        self.assertIs(self.window.workflow_mode_combo, workflow_combo)

    def test_programming_mode_routes_to_independent_dashboard(self):
        self._prime_shared_setup()
        self.assertTrue(self.window.set_grading_mode("programming"))
        self.assertIs(self.window.current_grading_mode, GradingMode.PROGRAMMING)
        self.assertIsInstance(
            self.window.programming_workspace,
            ProgrammingGradingWorkspace,
        )
        self.assertIs(
            self.window.active_grading_workspace(),
            self.window.programming_workspace,
        )
        self.assertIsNot(
            self.window.programming_workspace,
            self.window.written_workspace,
        )
        self.assertEqual(
            self.window.programming_workspace.configure_button.text(),
            "Configure Autograder",
        )

    def test_written_toolbar_contains_only_written_specific_setup(self):
        self.assertTrue(self.window.load_btn.isHidden())
        texts = [action.text() for action in self.window.setup_menu_button.menu().actions()]
        self.assertNotIn("Choose Workspace…", texts)
        self.assertNotIn("Load Roster…", texts)
        self.assertIn("Load Reference Solution…", texts)
        self.assertIn("Add PDF Accommodation…", texts)
        self.assertEqual(self.window.setup_menu_button.text(), "Written Setup")

    def test_written_tools_menu_no_longer_contains_programming_autograding(self):
        texts = [action.text() for action in self.window.tools_menu_button.menu().actions()]
        self.assertNotIn("Programming Autograding", texts)
        self.assertIn("Submission Similarity Review", texts)
        self.assertIn("Submission History", texts)

    def test_file_menu_returns_to_assessment_home(self):
        self._prime_shared_setup()
        self.assertEqual(self.window.assessment_home_action.text(), "Assessment Home…")
        self.assertIs(self.window.switch_grading_mode_action, self.window.assessment_home_action)
        self.assertTrue(self.window.set_grading_mode(GradingMode.WRITTEN))
        self.window.assessment_home_action.trigger()
        self.assertIsNone(self.window.current_grading_mode)
        self.assertIs(
            self.window.active_grading_workspace(),
            self.window.assessment_home_workspace,
        )


if __name__ == "__main__":
    unittest.main()
