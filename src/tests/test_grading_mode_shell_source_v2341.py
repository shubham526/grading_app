"""Source-level guards for the v2.3.4.1 grading-mode shell."""

import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_MAIN_WINDOW = _ROOT / "ui" / "main_window.py"
_HOME_WORKSPACE = _ROOT / "ui/workspaces/assessment_home_workspace.py"
_PROGRAMMING_WORKSPACE = _ROOT / "ui/workspaces/programming_grading_workspace.py"
_WRITTEN_WORKSPACE = _ROOT / "ui/workspaces/written_grading_workspace.py"


class TestGradingModeShellSourceV2341(unittest.TestCase):
    def test_main_window_uses_home_workspace_stack_and_explicit_mode_methods(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("_install_grading_mode_shell", methods)
        self.assertIn("show_assessment_home", methods)
        self.assertIn("show_grading_mode_selector", methods)
        self.assertIn("set_grading_mode", methods)
        self.assertIn("active_grading_workspace", methods)
        self.assertIn("QStackedWidget", source)
        self.assertIn("Assessment Home…", source)
        self.assertIn("AssessmentHomeWorkspace", source)
        self.assertNotIn("ModeSelectionPage(self)", source)

    def test_programming_workspace_is_presentation_and_intent_only(self):
        source = _PROGRAMMING_WORKSPACE.read_text(encoding="utf-8")
        self.assertIn("class ProgrammingGradingWorkspace", source)
        self.assertIn("student_selected = pyqtSignal(str)", source)
        self.assertNotIn("DockerPytestExecutionBackend", source)
        self.assertNotIn("AutogradingService", source)
        self.assertNotIn("SubmissionRepository", source)
        self.assertNotIn("grade_submission(", source)

    def test_final_v233_written_root_is_preserved_inside_written_workspace(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("written_widget = self.takeCentralWidget()", source)
        self.assertIn("self._written_central_widget = written_widget", source)
        self.assertIn(
            "self.written_workspace = WrittenGradingWorkspace(written_widget, self)",
            source,
        )
        self.assertIn("self._mode_stack.addWidget(self.written_workspace)", source)
        self.assertNotIn(
            "self._mode_stack.addWidget(self._written_central_widget)",
            source,
        )

    def test_shared_setup_is_removed_from_written_toolbar(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("def _isolate_written_specific_setup_controls", source)
        self.assertIn("self.load_btn.setVisible(False)", source)
        self.assertIn("setup_menu.removeAction(action)", source)
        self.assertIn('self.setup_menu_button.setText("Written Setup")', source)

    def test_v233_autograding_backend_wiring_remains_but_written_menu_is_removed(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertNotIn('QMenu("Programming Autograding", self)', source)
        self.assertIn("AutogradingWorker(", source)
        self.assertIn("def show_autograding_setup", source)
        self.assertIn("def grade_current_programming_submission", source)
        self.assertIn("def grade_all_programming_submissions", source)
        self.assertIn("def show_autograding_history", source)
        self.assertIn("def view_latest_programming_result", source)
        self.assertIn("def check_programming_runtime", source)

    def test_python39_grammar(self):
        paths = [
            _MAIN_WINDOW,
            _ROOT / "ui/modes/grading_mode.py",
            _ROOT / "ui/modes/mode_selection_page.py",
            _HOME_WORKSPACE,
            _PROGRAMMING_WORKSPACE,
            _WRITTEN_WORKSPACE,
            _ROOT / "ui/workers/autograding_worker.py",
        ]
        for path in paths:
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=(3, 9),
            )


if __name__ == "__main__":
    unittest.main()
