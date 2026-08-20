"""Qt behavior tests for the v2.3.4.1 programming dashboard."""

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
    from src.ui.workspaces.programming_grading_workspace import ProgrammingGradingWorkspace


@unittest.skipIf(
    QApplication is None,
    "Full PyQt application runtime unavailable: {!r}".format(_IMPORT_ERROR),
)
class TestProgrammingGradingWorkspaceV2341(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.workspace = ProgrammingGradingWorkspace()
        self.app.processEvents()

    def tearDown(self):
        self.workspace.deleteLater()
        self.app.processEvents()

    def test_roster_rows_preserve_student_identity_and_selection(self):
        rows = [
            {
                "student_id": "s1",
                "student_name": "Alice Example",
                "attempt": 1,
                "status": "Completed",
                "score": "10 / 10",
                "last_run": "Aug 20, 2026 10:42 PM",
            },
            {
                "student_id": "s2",
                "student_name": "Bob Example",
                "attempt": 2,
                "status": "Review",
                "score": "7 / 10",
                "last_run": "Aug 20, 2026 10:43 PM",
            },
        ]
        self.workspace.set_rows(rows, selected_student_id="s2")
        self.assertEqual(self.workspace.student_table.rowCount(), 2)
        self.assertEqual(self.workspace.selected_student_id(), "s2")
        self.assertEqual(self.workspace.selected_student_name(), "Bob Example")
        self.assertEqual(self.workspace.student_table.item(1, 3).text(), "7 / 10")

    def test_latest_result_summary_and_buttons_follow_selected_state(self):
        self.workspace.set_rows(
            [{"student_id": "s1", "student_name": "Alice", "status": "Not graded"}]
        )
        self.workspace.set_latest_result(
            {
                "student_name": "Alice",
                "has_submission": True,
                "has_run": True,
                "status": "Completed",
                "public_tests": "4 / 4",
                "hidden_tests": "3 / 6",
                "score": "7 / 10",
                "attempt": 1,
                "last_run": "Aug 20, 2026 10:42 PM",
                "test_summary": "7 passed • 3 not passed",
            }
        )
        self.assertEqual(self.workspace.public_tests_value.text(), "4 / 4")
        self.assertEqual(self.workspace.hidden_tests_value.text(), "3 / 6")
        self.assertEqual(self.workspace.total_score_value.text(), "7 / 10")
        self.assertTrue(self.workspace.view_results_button.isEnabled())
        self.assertTrue(self.workspace.grade_again_button.isEnabled())

    def test_six_top_actions_emit_semantic_requests(self):
        emitted = []
        pairs = [
            (self.workspace.configure_button, self.workspace.configure_autograder_requested, "configure"),
            (self.workspace.import_button, self.workspace.import_submissions_requested, "import"),
            (self.workspace.runtime_button, self.workspace.check_runtime_requested, "runtime"),
            (self.workspace.grade_selected_button, self.workspace.grade_selected_requested, "selected"),
            (self.workspace.grade_all_button, self.workspace.grade_all_requested, "all"),
            (self.workspace.history_button, self.workspace.run_history_requested, "history"),
        ]
        self.workspace.set_rows([{"student_id": "s1", "student_name": "Alice"}])
        for _button, signal, label in pairs:
            signal.connect(lambda label=label: emitted.append(label))
        for button, _signal, _label in pairs:
            button.click()
        self.assertEqual(emitted, ["configure", "import", "runtime", "selected", "all", "history"])

    def test_busy_state_disables_execution_controls(self):
        self.workspace.set_rows([{"student_id": "s1", "student_name": "Alice"}])
        self.workspace.set_busy(True)
        for button in (
            self.workspace.configure_button,
            self.workspace.import_button,
            self.workspace.runtime_button,
            self.workspace.grade_selected_button,
            self.workspace.grade_all_button,
            self.workspace.history_button,
        ):
            self.assertFalse(button.isEnabled())


if __name__ == "__main__":
    unittest.main()
