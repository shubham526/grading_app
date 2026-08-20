"""Source-level guards for the v2.3.4.1 grading-mode shell."""

import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_MAIN_WINDOW = _ROOT / "ui" / "main_window.py"
_PROGRAMMING_PLACEHOLDER = (
    _ROOT / "ui/workspaces/programming_grading_workspace.py"
)
_WRITTEN_WORKSPACE = _ROOT / "ui/workspaces/written_grading_workspace.py"


class TestGradingModeShellSourceV2341(unittest.TestCase):
    def test_main_window_uses_workspace_stack_and_explicit_mode_methods(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("_install_grading_mode_shell", methods)
        self.assertIn("show_grading_mode_selector", methods)
        self.assertIn("set_grading_mode", methods)
        self.assertIn("active_grading_workspace", methods)
        self.assertIn("QStackedWidget", source)
        self.assertIn("Switch Grading Mode…", source)

    def test_commit1_programming_page_is_still_presentation_only(self):
        source = _PROGRAMMING_PLACEHOLDER.read_text(encoding="utf-8")
        self.assertNotIn("DockerPytestExecutionBackend", source)
        self.assertNotIn("AutogradingService", source)
        self.assertNotIn("grade_submission", source)
        self.assertIn("Commit 3", source)

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

    def test_final_v233_programming_wiring_is_still_present(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn('QMenu("Programming Autograding", self)', source)
        self.assertIn('"Configure Autograder…"', source)
        self.assertIn('"Grade Current Submission"', source)
        self.assertIn('"Grade All Active Submissions…"', source)
        self.assertIn('"Autograding History…"', source)
        self.assertIn("AutogradingWorker(", source)

    def test_python39_grammar(self):
        paths = [
            _MAIN_WINDOW,
            _ROOT / "ui/modes/grading_mode.py",
            _ROOT / "ui/modes/mode_selection_page.py",
            _PROGRAMMING_PLACEHOLDER,
            _WRITTEN_WORKSPACE,
        ]
        for path in paths:
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=(3, 9),
            )


if __name__ == "__main__":
    unittest.main()
