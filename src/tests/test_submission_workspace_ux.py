"""Source-level regressions for the Gradescope-style submission viewing UX."""

from pathlib import Path
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_PATH = _REPO_ROOT / "src" / "ui" / "widgets" / "submission_workspace.py"
_SOURCE = _WORKSPACE_PATH.read_text(encoding="utf-8")


class TestSubmissionWorkspaceUx(unittest.TestCase):

    def test_permanent_workspace_is_document_only(self):
        self.assertIn("self.pdf_viewer = PdfDocumentViewer(self)", _SOURCE)
        self.assertNotIn("self.text_panel = SubmissionTextPanel", _SOURCE)
        self.assertNotIn("self.splitter = QSplitter(Qt.Horizontal", _SOURCE)

    def test_machine_readable_artifacts_are_on_demand(self):
        self.assertIn('self.view_answer_button = QPushButton("Student Response"', _SOURCE)
        self.assertIn('self.reference_solution_button = QPushButton("Reference Solution"', _SOURCE)
        self.assertIn('self.view_machine_text_button = QPushButton("Source"', _SOURCE)
        self.assertIn("class EvidenceTextDialog", _SOURCE)
        self.assertIn("def show_extracted_answer", _SOURCE)
        self.assertIn("def show_reference_solution", _SOURCE)
        self.assertIn("def show_machine_readable_text", _SOURCE)

    def test_latex_source_is_preserved_for_future_automatic_grading(self):
        self.assertIn('"Canonical LaTeX Source"', _SOURCE)
        self.assertIn("preferred machine-readable", _SOURCE)
        self.assertIn("_read_latex_source", _SOURCE)

    def test_text_bearing_pdf_uses_deterministic_extraction(self):
        self.assertIn('extraction.get("selectable_text")', _SOURCE)
        self.assertIn('"PDF Text"', _SOURCE)
        self.assertIn("PyMuPDF", _SOURCE)

    def test_scan_like_pdf_is_the_only_path_that_offers_vlm_transcription(self):
        self.assertIn('"Scanned PDF · transcription needed"', _SOURCE)
        self.assertIn('"Transcribe Scan"', _SOURCE)
        self.assertIn('"Transcription"', _SOURCE)
        self.assertIn("submitted pdf is authoritative", _SOURCE.lower())

    def test_transcription_failures_explain_the_reason(self):
        self.assertIn('self.transcription_details_button = QPushButton("View Details"', _SOURCE)
        self.assertIn('"model_load_timeout": "model loading timed out"', _SOURCE)
        self.assertIn('"inference_timeout": "transcription inference timed out"', _SOURCE)
        self.assertIn("GPU may be busy", _SOURCE)

    def test_focus_and_whole_workspace_popout_are_optional(self):
        self.assertIn('self.focus_button = QPushButton("Focus"', _SOURCE)
        self.assertIn('self.popout_button = QPushButton("Pop Out Workspace"', _SOURCE)
        self.assertIn("focus_requested = pyqtSignal(bool)", _SOURCE)
        self.assertIn("popout_workspace_requested = pyqtSignal()", _SOURCE)
        self.assertIn("allow_focus=True", _SOURCE)
        self.assertIn("allow_popout=True", _SOURCE)

    def test_submission_widget_no_longer_constructs_duplicate_popout_viewer(self):
        self.assertNotIn("SubmissionWorkspace(dialog, allow_focus=False", _SOURCE)
        self.assertIn("def _emit_popout_workspace", _SOURCE)
        self.assertIn("self.popout_workspace_requested.emit()", _SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
