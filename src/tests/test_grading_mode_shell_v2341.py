"""v2.3.4.1 integration tests for the MainWindow mode shell."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication
except ModuleNotFoundError as exc:  # pragma: no cover
    QApplication = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None
    from src.ui.main_window import RubricGrader
    from src.ui.modes.grading_mode import GradingMode
    from src.ui.workspaces import ProgrammingGradingWorkspace, WrittenGradingWorkspace


@unittest.skipIf(
    QApplication is None,
    "Full PyQt application runtime unavailable: {!r}".format(_IMPORT_ERROR),
)
class TestGradingModeShellV2341(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = RubricGrader()
        self.app.processEvents()

    def tearDown(self):
        try:
            self.window.auto_save_timer.stop()
        except Exception:
            pass
        self.window.deleteLater()
        self.app.processEvents()

    def test_startup_opens_explicit_mode_chooser(self):
        self.assertIsNone(self.window.current_grading_mode)
        self.assertIs(
            self.window.active_grading_workspace(),
            self.window.mode_selection_page,
        )
        self.assertEqual(self.window.windowTitle(), "Rubric Grading Tool")

    def test_written_mode_reuses_exact_existing_written_root(self):
        written_root = self.window._written_central_widget
        written_workspace = self.window.written_workspace
        submission_workspace = self.window.submission_workspace
        workflow_combo = self.window.workflow_mode_combo

        self.assertIsInstance(written_workspace, WrittenGradingWorkspace)
        self.assertIs(written_workspace.legacy_root, written_root)

        self.window.set_grading_mode(GradingMode.WRITTEN)

        self.assertIs(self.window.active_grading_workspace(), written_workspace)
        self.assertIs(self.window.current_grading_mode, GradingMode.WRITTEN)
        self.assertIs(self.window.submission_workspace, submission_workspace)
        self.assertIs(self.window.workflow_mode_combo, workflow_combo)

        self.window.show_grading_mode_selector()
        self.window.set_grading_mode(GradingMode.WRITTEN)

        self.assertIs(self.window.active_grading_workspace(), written_workspace)
        self.assertIs(written_workspace.legacy_root, written_root)
        self.assertIs(self.window.submission_workspace, submission_workspace)
        self.assertIs(self.window.workflow_mode_combo, workflow_combo)

    def test_programming_mode_routes_to_independent_dashboard(self):
        self.window.set_grading_mode("programming")
        self.assertIs(
            self.window.current_grading_mode,
            GradingMode.PROGRAMMING,
        )
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

    def test_written_tools_menu_no_longer_contains_programming_autograding(self):
        texts = [action.text() for action in self.window.tools_menu_button.menu().actions()]
        self.assertNotIn("Programming Autograding", texts)
        self.assertIn("Submission Similarity Review", texts)
        self.assertIn("Submission History", texts)

    def test_file_menu_exposes_switch_grading_mode(self):
        self.assertEqual(
            self.window.switch_grading_mode_action.text(),
            "Switch Grading Mode…",
        )
        self.window.set_grading_mode(GradingMode.WRITTEN)
        self.window.switch_grading_mode_action.trigger()
        self.assertIsNone(self.window.current_grading_mode)
        self.assertIs(
            self.window.active_grading_workspace(),
            self.window.mode_selection_page,
        )


if __name__ == "__main__":
    unittest.main()
