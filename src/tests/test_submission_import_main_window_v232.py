"""Structural integration tests for v2.3.2 Commit 7 main-window wiring."""

from pathlib import Path
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
_SOURCE = _PATH.read_text(encoding="utf-8")


class TestSubmissionImportMainWindowV232(unittest.TestCase):
    def test_preferred_canonical_import_action_is_added_without_removing_legacy_loader(self):
        self.assertIn('self.import_submissions_btn = QPushButton("Import Submissions")', _SOURCE)
        self.assertIn('self.import_submissions_btn.clicked.connect(self.show_submission_import_dialog)', _SOURCE)
        self.assertIn('self.load_submissions_btn = QPushButton("Load Submissions")', _SOURCE)
        self.assertIn('self.load_submissions_btn.clicked.connect(self.load_submissions_folder)', _SOURCE)

    def test_history_action_is_available_from_tools(self):
        self.assertIn('"Submission History"', _SOURCE)
        self.assertIn('self.submission_history_action.triggered.connect(self.show_submission_history)', _SOURCE)

    def test_import_completion_registers_final_repository_active_attempt(self):
        self.assertIn('repository.get_active_submission(assessment_id, student_id)', _SOURCE)
        self.assertIn('self.submission_controller.set_active_canonical_submission(', _SOURCE)
        self.assertIn('self.submission_controller.register_canonical_submission(', _SOURCE)
        self.assertIn('parsed_by_student', _SOURCE)

    def test_import_requires_stable_assessment_identity_and_evidence_workspace(self):
        self.assertIn('def _canonical_assessment_id(self):', _SOURCE)
        self.assertIn('Missing Assessment ID', _SOURCE)
        self.assertIn('def _ensure_canonical_submission_repository(self):', _SOURCE)
        self.assertIn('SubmissionRepository(evidence_root, create=True)', _SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
