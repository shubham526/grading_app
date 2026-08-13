"""Source-level regressions for the Commit-5 submission viewing UX."""

from pathlib import Path
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_PATH = _REPO_ROOT / "src" / "ui" / "widgets" / "submission_workspace.py"
_SOURCE = _WORKSPACE_PATH.read_text(encoding="utf-8")


class TestSubmissionWorkspaceUx(unittest.TestCase):

    def test_focus_and_popout_actions_are_available(self):
        self.assertIn('self.focus_button = QPushButton("Focus"', _SOURCE)
        self.assertIn('self.popout_button = QPushButton("Pop Out"', _SOURCE)
        self.assertIn("focus_requested = pyqtSignal(bool)", _SOURCE)

    def test_focus_button_can_be_disabled_for_child_popout_workspace(self):
        self.assertIn("allow_focus=True", _SOURCE)
        self.assertIn("allow_popout=True", _SOURCE)
        self.assertIn("self.focus_button.setVisible(self._allow_focus)", _SOURCE)
        self.assertIn("self.popout_button.setVisible(self._allow_popout)", _SOURCE)

    def test_popout_uses_independent_submission_workspace(self):
        self.assertIn("def show_popout(self):", _SOURCE)
        self.assertIn("dialog.resize(1400, 900)", _SOURCE)
        self.assertIn("allow_focus=False", _SOURCE)
        self.assertIn("allow_popout=False", _SOURCE)
        self.assertIn("workspace.set_submission(self._submission)", _SOURCE)
        self.assertIn("workspace.set_question(self._question_id)", _SOURCE)

    def test_popout_tracks_student_and_question_changes(self):
        self.assertIn("self._popout_workspace.set_submission(parsed_submission)", _SOURCE)
        self.assertIn("self._popout_workspace.set_question(self._question_id)", _SOURCE)

    def test_popout_forwards_existing_submission_actions(self):
        self.assertIn("workspace.open_source_requested.connect(self.open_source_requested.emit)", _SOURCE)
        self.assertIn("workspace.refresh_requested.connect(self.refresh_requested.emit)", _SOURCE)
        self.assertIn("self.generate_transcription_requested.emit", _SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
