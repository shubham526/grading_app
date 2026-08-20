"""Source-level guards for the v2.3.4.1 shared Assessment Home."""

import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_HOME = _ROOT / "ui/workspaces/assessment_home_workspace.py"
_MAIN = _ROOT / "ui/main_window.py"


class TestAssessmentHomeWorkspaceSourceV2341(unittest.TestCase):
    def test_home_owns_only_shared_setup_and_mode_intent(self):
        source = _HOME.read_text(encoding="utf-8")
        self.assertIn("class AssessmentHomeWorkspace", source)
        self.assertIn("load_rubric_requested = pyqtSignal()", source)
        self.assertIn("load_roster_requested = pyqtSignal()", source)
        self.assertIn("choose_workspace_requested = pyqtSignal()", source)
        self.assertIn("mode_selected = pyqtSignal(object)", source)
        self.assertNotIn("AutogradingService", source)
        self.assertNotIn("SubmissionRepository", source)
        self.assertNotIn("save_assessment(", source)

    def test_home_requires_three_shared_setup_steps_before_mode_entry(self):
        source = _HOME.read_text(encoding="utf-8")
        self.assertIn('_REQUIRED_KEYS = ("rubric", "roster", "workspace")', source)
        self.assertIn('"Load Rubric"', source)
        self.assertIn('"Load Roster"', source)
        self.assertIn('"Choose Workspace"', source)
        self.assertIn('"Open Written Grader"', source)
        self.assertIn('"Open Programming Grader"', source)
        self.assertIn("self.written_card.set_ready(ready, missing)", source)
        self.assertIn("self.programming_card.set_ready(ready, missing)", source)

    def test_main_window_loads_shared_rubric_without_written_config_dialog(self):
        source = _MAIN.read_text(encoding="utf-8")
        self.assertIn("def _load_shared_rubric_from_home", source)
        self.assertIn("self.load_rubric(show_config_on_load=False)", source)
        self.assertIn("def _shared_setup_ready", source)
        self.assertIn("def show_assessment_home", source)

    def test_mode_specific_transition_guards_exist(self):
        source = _MAIN.read_text(encoding="utf-8")
        self.assertIn("def _confirm_written_workspace_transition", source)
        self.assertIn("def _can_leave_current_grading_mode", source)
        self.assertIn("self._autograding_workers", source)
        self.assertIn("self._autograding_batch_dialog", source)
        self.assertIn('"Programming Grading In Progress"', source)

    def test_python39_grammar(self):
        for path in (_HOME, _MAIN):
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=(3, 9),
            )


if __name__ == "__main__":
    unittest.main()
