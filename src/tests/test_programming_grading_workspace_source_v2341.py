"""Source guards for the v2.3.4.1 programming dashboard."""

import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE = _ROOT / "ui/workspaces/programming_grading_workspace.py"
_MAIN_WINDOW = _ROOT / "ui/main_window.py"
_WORKER = _ROOT / "ui/workers/autograding_worker.py"


class TestProgrammingGradingWorkspaceSourceV2341(unittest.TestCase):
    def test_dashboard_exposes_required_top_level_actions(self):
        source = _WORKSPACE.read_text(encoding="utf-8")
        for text in (
            "Configure Autograder",
            "Import Submissions",
            "Check Runtime",
            "Grade Selected",
            "Grade All",
            "Run History",
        ):
            self.assertIn('"%s"' % text, source)
        self.assertIn('["Student", "Attempt", "Status", "Score", "Last Run"]', source)
        self.assertIn('QLabel("Latest Result"', source)

    def test_main_window_routes_dashboard_requests_to_existing_orchestration(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        expected = (
            "configure_autograder_requested.connect",
            "import_submissions_requested.connect",
            "check_runtime_requested.connect",
            "grade_selected_requested.connect",
            "grade_all_requested.connect",
            "run_history_requested.connect",
            "view_results_requested.connect",
            "grade_again_requested.connect",
            "student_selected.connect",
        )
        for text in expected:
            self.assertIn(text, source)
        self.assertIn("self._refresh_programming_workspace()", source)
        self.assertIn("service.list_history", source)
        self.assertIn("repository.get_active_submission", source)

    def test_runtime_check_uses_existing_background_worker_boundary(self):
        main = _MAIN_WINDOW.read_text(encoding="utf-8")
        worker = _WORKER.read_text(encoding="utf-8")
        self.assertIn('CHECK_RUNTIME = "check_runtime"', worker)
        self.assertIn("self.service.runtime_availability", worker)
        self.assertIn("AutogradingOperation.CHECK_RUNTIME", main)
        self.assertIn("self.submission_thread_pool.start(worker)", main)

    def test_python39_grammar(self):
        for path in (_WORKSPACE, _MAIN_WINDOW, _WORKER):
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=(3, 9),
            )


if __name__ == "__main__":
    unittest.main()
