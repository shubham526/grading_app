"""Source-level contracts for the v2.3.2 canonical submission history dialog."""

from pathlib import Path
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = _REPO_ROOT / "src" / "ui" / "dialogs" / "submission_history_dialog.py"
_SOURCE = _PATH.read_text(encoding="utf-8")


class TestSubmissionHistoryDialogV232(unittest.TestCase):
    def test_history_dialog_lists_attempt_provenance(self):
        self.assertIn('class SubmissionHistoryDialog(QDialog):', _SOURCE)
        for label in ("Active", "Attempt", "Source", "Submitted", "Imported", "Artifacts", "SHA-256"):
            self.assertIn(label, _SOURCE)
        self.assertIn('submission_history_for_student(', _SOURCE)

    def test_switching_attempt_uses_controller_atomic_activation(self):
        self.assertIn('Make Selected Active', _SOURCE)
        self.assertIn('self.controller.activate_submission(', _SOURCE)
        self.assertIn('submission_activated.emit(parsed)', _SOURCE)
        self.assertIn('existing active attempt will remain in history', _SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
