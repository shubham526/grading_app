"""Commit-5 submission workspace integration contracts."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
_SOURCE = _PATH.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _class():
    return next(
        node for node in _TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "RubricGrader"
    )


def _method(name):
    return next(
        node for node in _class().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _segment(name):
    return ast.get_source_segment(_SOURCE, _method(name)) or ""


class TestSubmissionUiIntegration(unittest.TestCase):

    def test_workspace_is_constructed_and_signals_are_connected(self):
        source = _segment("init_ui")
        self.assertIn("self.submission_workspace = SubmissionWorkspace(self)", source)
        self.assertIn("open_source_requested.connect(self.open_submission_source)", source)
        self.assertIn("refresh_requested.connect(self.refresh_submission_evidence)", source)
        self.assertIn("generate_transcription_requested.connect", source)
        self.assertIn("self.generate_submission_transcription", source)

    def test_load_submissions_requires_persistent_assessment_workspace(self):
        source = _segment("load_submissions_folder")
        self.assertIn("_ensure_assessments_dir(allow_prompt=True)", source)
        self.assertIn("persist_evidence", source)
        self.assertIn("SubmissionOperation.LOAD_NORMAL_SUBMISSIONS", source)

    def test_pdf_accommodation_is_explicit_and_does_not_auto_transcribe(self):
        source = _segment("add_pdf_accommodation")
        self.assertIn("SubmissionOperation.LOAD_PDF_ACCOMMODATION", source)
        self.assertNotIn("GENERATE_TRANSCRIPTION", source)
        self.assertNotIn("REFRESH_TRANSCRIPTION", source)

    def test_generate_transcription_is_cache_first_worker_operation(self):
        source = _segment("generate_submission_transcription")
        self.assertIn("SubmissionOperation.GENERATE_TRANSCRIPTION", source)
        self.assertIn("submission_inference_settings", source)
        self.assertIn('"base_url"', source)
        self.assertIn('"model"', source)

    def test_refresh_existing_transcription_uses_forced_refresh_operation(self):
        source = _segment("refresh_submission_evidence")
        self.assertIn('== "successful"', source)
        self.assertIn("SubmissionOperation.REFRESH_TRANSCRIPTION", source)
        self.assertIn("SubmissionOperation.LOAD_PDF_ACCOMMODATION", source)

    def test_assistance_failure_preserves_existing_evidence(self):
        source = _segment("_on_submission_worker_failed")
        self.assertNotIn("current_submission = None", source)
        self.assertNotIn("clear_submission", source)
        self.assertIn("Evidence retained", source)

    def test_open_source_uses_os_desktop_service_not_shell_command(self):
        source = _segment("open_submission_source")
        self.assertIn("QDesktopServices.openUrl", source)
        self.assertIn("QUrl.fromLocalFile", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)

    def test_loaded_submission_mapping_is_non_modal(self):
        source = _segment("_summarize_loaded_submission_mapping")
        self.assertNotIn("QMessageBox", source)
        self.assertIn("without a matched submission", source)
        self.assertIn("not in the current roster", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
