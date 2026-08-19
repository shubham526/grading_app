"""Source-level contracts for the v2.3.2 canonical submission import dialog."""

from pathlib import Path
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = _REPO_ROOT / "src" / "ui" / "dialogs" / "submission_import_dialog.py"
_SOURCE = _PATH.read_text(encoding="utf-8")


class TestSubmissionImportDialogV232(unittest.TestCase):
    def test_dialog_exposes_file_folder_preview_and_commit_actions(self):
        self.assertIn('class SubmissionImportDialog(QDialog):', _SOURCE)
        self.assertIn('QPushButton("Add Files…"', _SOURCE)
        self.assertIn('QPushButton("Add Folder…"', _SOURCE)
        self.assertIn('QPushButton("Import Selected"', _SOURCE)
        self.assertIn('submissionImportTable', _SOURCE)

    def test_dialog_preview_contains_mapping_attempt_status_and_details(self):
        for label in ("File(s)", "Student", "Attempt", "Status", "Details"):
            self.assertIn(label, _SOURCE)
        self.assertIn('SubmissionImporter(', _SOURCE)
        self.assertIn('student_overrides=overrides', _SOURCE)

    def test_exact_duplicates_are_not_selected_by_default_and_require_confirmation(self):
        self.assertIn('VALIDATION_STATUS_DUPLICATE', _SOURCE)
        self.assertIn('Import Exact Duplicate?', _SOURCE)
        self.assertIn('force_duplicate_ids', _SOURCE)

    def test_slow_work_uses_import_worker(self):
        self.assertIn('SubmissionImportWorker(', _SOURCE)
        self.assertIn('self.thread_pool.start(worker)', _SOURCE)
        self.assertIn('imports_committed = pyqtSignal(object)', _SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
