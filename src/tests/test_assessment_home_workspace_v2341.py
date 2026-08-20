"""Runtime tests for the v2.3.4.1 shared Assessment Home widget."""

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
    from src.ui.modes import GradingMode
    from src.ui.workspaces import AssessmentHomeWorkspace


@unittest.skipIf(
    QApplication is None,
    "PyQt application runtime unavailable: {!r}".format(_IMPORT_ERROR),
)
class TestAssessmentHomeWorkspaceV2341(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.home = AssessmentHomeWorkspace()
        self.home.show()
        self.app.processEvents()

    def tearDown(self):
        self.home.close()
        self.home.deleteLater()
        self.app.processEvents()

    def test_mode_buttons_are_disabled_until_shared_setup_is_complete(self):
        self.home.set_context({})
        self.assertFalse(self.home.written_card.open_button.isEnabled())
        self.assertFalse(self.home.programming_card.open_button.isEnabled())

        self.home.set_context(
            {
                "rubric_ready": True,
                "rubric_path": "/tmp/rubric.json",
                "assessment_id": "PS1",
                "roster_ready": True,
                "roster_path": "/tmp/roster.csv",
                "roster_count": 3,
                "workspace_ready": True,
                "workspace_path": "/tmp/workspace",
            }
        )
        self.assertTrue(self.home.written_card.open_button.isEnabled())
        self.assertTrue(self.home.programming_card.open_button.isEnabled())

    def test_shared_setup_actions_emit_semantic_requests(self):
        received = []
        self.home.load_rubric_requested.connect(lambda: received.append("rubric"))
        self.home.load_roster_requested.connect(lambda: received.append("roster"))
        self.home.choose_workspace_requested.connect(lambda: received.append("workspace"))
        self.home.rubric_card.action_button.click()
        self.home.roster_card.action_button.click()
        self.home.workspace_card.action_button.click()
        self.assertEqual(received, ["rubric", "roster", "workspace"])

    def test_ready_mode_cards_emit_explicit_modes(self):
        self.home.set_context(
            {
                "rubric_ready": True,
                "roster_ready": True,
                "roster_count": 1,
                "workspace_ready": True,
                "workspace_path": "/tmp/workspace",
            }
        )
        received = []
        self.home.mode_selected.connect(received.append)
        self.home.written_card.open_button.click()
        self.home.programming_card.open_button.click()
        self.assertEqual(received, [GradingMode.WRITTEN, GradingMode.PROGRAMMING])


if __name__ == "__main__":
    unittest.main()
