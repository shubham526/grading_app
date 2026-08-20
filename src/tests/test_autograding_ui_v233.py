import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestAutogradingUISource(unittest.TestCase):
    def _source(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_programming_autograding_capabilities_remain_wired_after_mode_split(self):
        main = self._source("ui/main_window.py")
        workspace = self._source("ui/workspaces/programming_grading_workspace.py")
        self.assertIn("def show_autograding_setup", main)
        self.assertIn("def grade_current_programming_submission", main)
        self.assertIn("def grade_all_programming_submissions", main)
        self.assertIn("def show_autograding_history", main)
        self.assertIn('"Configure Autograder"', workspace)
        self.assertIn('"Grade Selected"', workspace)
        self.assertIn('"Grade All"', workspace)
        self.assertIn('"Run History"', workspace)

    def test_current_grade_runs_in_worker_not_directly_on_gui_thread(self):
        text = self._source("ui/main_window.py")
        self.assertIn("AutogradingWorker(", text)
        self.assertIn("self.submission_thread_pool.start(worker)", text)
        self.assertNotIn("service.grade_submission(\n            assessment_id", text)

    def test_manual_rubric_scores_are_not_written_by_autograding_flow(self):
        service = self._source("autograding/service.py")
        self.assertIn("never mutates the app's manual rubric/criterion scores", service)
        main = self._source("ui/main_window.py")
        block = main[main.index("def grade_current_programming_submission"):main.index("def _on_submission_history_activated")]
        self.assertNotIn("criterion_widgets", block)
        self.assertNotIn("set_points", block)
        self.assertNotIn("save_assessment(", block)

    def test_batch_dialog_exposes_cooperative_cancel_and_result_view(self):
        text = self._source("ui/dialogs/autograding_batch_dialog.py")
        self.assertIn("Cancel After Current Student", text)
        self.assertIn("View Selected Result", text)
        self.assertIn("worker.cancel()", text)

    def test_results_dialog_is_instructor_side_and_displays_hidden_visibility(self):
        text = self._source("ui/dialogs/autograding_results_dialog.py")
        self.assertIn("build_instructor_run_report", text)
        self.assertIn('"Visibility"', text)
        self.assertIn("item.traceback", text)

    def test_history_dialog_loads_immutable_run_through_service(self):
        text = self._source("ui/dialogs/autograding_history_dialog.py")
        self.assertIn("service.list_history", text)
        self.assertIn("service.load_run", text)
        self.assertIn("Every rerun is immutable evidence", text)

    def test_all_commit9_sources_parse_as_python39(self):
        files = [
            "autograding/service.py",
            "ui/main_window.py",
            "ui/dialogs/autograding_setup_dialog.py",
            "ui/dialogs/autograding_results_dialog.py",
            "ui/dialogs/autograding_history_dialog.py",
            "ui/dialogs/autograding_batch_dialog.py",
            "ui/workers/autograding_worker.py",
        ]
        for relative in files:
            text = self._source(relative)
            ast.parse(text, filename=relative, feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
