"""Tests for the submission-first document workspace."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

try:
    import PyQt5
    from PyQt5.QtWidgets import QApplication
    import pymupdf
    PYQT_AVAILABLE = not isinstance(PyQt5, Mock) and not isinstance(QApplication, Mock)
except ImportError:
    PYQT_AVAILABLE = False

if PYQT_AVAILABLE:
    from src.submissions.reference_solution import ReferenceSolution
    from src.submissions.models import (
        ParsedSubmission,
        SUBMISSION_MODE_LATEX,
        SUBMISSION_MODE_PDF_ACCOMMODATION,
    )
    from src.ui.widgets.submission_workspace import SubmissionWorkspace


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 and PyMuPDF are required for workspace tests")
class TestSubmissionWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.tex_path = root / "main.tex"
        self.tex_path.write_text("\\section*{Question 1}\nAnswer", encoding="utf-8")
        self.pdf_path = root / "main.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), "Submission")
        doc.save(str(self.pdf_path))
        doc.close()
        self.workspace = SubmissionWorkspace()
        self.workspace.resize(800, 700)

    def tearDown(self):
        self.workspace.close()
        self.tmp.cleanup()

    def test_latex_submission_is_document_first_with_on_demand_text(self):
        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            source_used="latex",
            answers_by_question={"Q1": "Answer"},
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
        )
        self.workspace.set_question("Q1")
        self.workspace.set_submission(parsed)
        self.assertTrue(self.workspace.pdf_viewer.has_document)
        self.assertFalse(self.workspace.pdf_viewer.authoritative)
        self.assertFalse(hasattr(self.workspace, "text_panel"))
        self.assertEqual(self.workspace.view_answer_button.text(), "Student Response")
        self.assertEqual(self.workspace.view_machine_text_button.text(), "Source")
        answer, title, _notice = self.workspace._answer_for_current_context(parsed)
        self.assertEqual(answer, "Answer")
        self.assertIn("Q1", title)
        self.assertTrue(self.workspace.generate_transcription_button.isHidden())

    def test_text_bearing_pdf_uses_deterministic_extraction_without_vlm(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            raw_text="Selectable PDF text",
            answers_by_question={"Q1": "Derived"},
            files={"pdf": str(self.pdf_path)},
            metadata={
                "assistive_text_source": "pdf_selectable_text",
                "extraction": {"selectable_text": True, "text_layer_present": True},
                "transcription": {"status": "not_requested", "pages": []},
            },
        )
        self.workspace.set_question("Q1")
        self.workspace.set_submission(parsed)
        self.assertTrue(self.workspace.pdf_viewer.authoritative)
        self.assertEqual(self.workspace.status_badge.text(), "PDF text extracted")
        self.assertEqual(self.workspace.view_machine_text_button.text(), "PDF Text")
        self.assertTrue(self.workspace.generate_transcription_button.isHidden())

    def test_scan_like_pdf_offers_explicit_transcription(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            files={"pdf": str(self.pdf_path)},
            metadata={
                "extraction": {"selectable_text": False, "text_layer_present": False},
                "transcription": {"enabled": False, "status": "not_requested", "pages": []},
            },
        )
        self.workspace.set_submission(parsed)
        self.assertFalse(self.workspace.generate_transcription_button.isHidden())
        self.assertEqual(self.workspace.generate_transcription_button.text(), "Transcribe Scan")
        self.assertTrue(self.workspace.view_machine_text_button.isHidden())
        self.assertTrue(self.workspace.refresh_button.isHidden())

    def test_successful_scan_transcription_is_viewable_but_not_authoritative(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            answers_by_question={"Q1": "Derived"},
            files={"pdf": str(self.pdf_path)},
            metadata={
                "extraction": {"selectable_text": False, "text_layer_present": False},
                "transcription": {
                    "status": "successful",
                    "model": "gemma4:31b",
                    "pages": [{"page_number": 1, "text": "1. Derived"}],
                    "cache": {"status": "hit"},
                },
            },
        )
        self.workspace.set_submission(parsed)
        self.assertTrue(self.workspace.pdf_viewer.authoritative)
        self.assertIn("cached", self.workspace.status_badge.text())
        self.assertEqual(self.workspace.view_machine_text_button.text(), "Transcription")
        self.assertEqual(self.workspace.refresh_button.text(), "Refresh AI Text")
        self.assertIn("Derived", self.workspace._page_aligned_transcription(parsed))

    def test_question_changes_only_change_on_demand_answer_context(self):
        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
            answers_by_question={"Q1": "One", "Q2": "Two"},
        )
        self.workspace.set_submission(parsed)
        self.workspace.set_question("Q2")
        answer, _title, _notice = self.workspace._answer_for_current_context(parsed)
        self.assertEqual(answer, "Two")
        self.assertTrue(self.workspace.pdf_viewer.has_document)


    def test_actions_reenable_after_empty_state_then_submission_load(self):
        """Regression: ready evidence actions must not stay greyed out."""
        self.workspace.clear_submission()
        self.assertFalse(self.workspace.focus_button.isEnabled())
        self.assertFalse(self.workspace.popout_button.isEnabled())

        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
            answers_by_question={"Q1": "Answer"},
        )
        self.workspace.set_question("Q1")
        self.workspace.set_submission(parsed)

        self.assertTrue(self.workspace.view_answer_button.isEnabled())
        self.assertTrue(self.workspace.view_machine_text_button.isEnabled())
        self.assertTrue(self.workspace.open_source_button.isEnabled())
        self.assertTrue(self.workspace.refresh_button.isEnabled())
        self.assertTrue(self.workspace.focus_button.isEnabled())
        self.assertTrue(self.workspace.popout_button.isEnabled())

    def test_reference_solution_is_separate_from_student_response(self):
        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
            answers_by_question={"Q1": "Student work"},
        )
        solution = ReferenceSolution(
            source_type="latex",
            canonical_source_path=str(self.tex_path),
            display_pdf_path=str(self.pdf_path),
            raw_text="Question 1\nCorrect work",
            answers_by_question={"Q1": "Correct work"},
        )
        self.workspace.set_reference_solution(solution)
        self.workspace.set_question("Q1")
        self.workspace.set_submission(parsed)
        self.assertTrue(self.workspace.reference_solution_button.isEnabled())
        self.assertEqual(self.workspace.reference_solution_button.text(), "Reference Solution")
        student, student_title, _ = self.workspace._answer_for_current_context(parsed)
        self.assertEqual(student, "Student work")
        self.assertIn("Student Response", student_title)
        self.assertEqual(solution.answers_by_question["Q1"], "Correct work")

    def test_failed_model_load_surfaces_details_and_retry(self):
        parsed = ParsedSubmission(
            student_id="carol",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            files={"pdf": str(self.pdf_path)},
            metadata={
                "extraction": {"selectable_text": False},
                "transcription": {
                    "status": "failed",
                    "preflight": {
                        "error_code": "model_load_timeout",
                        "error_message": "Loading gemma4:31b exceeded 600 seconds.",
                    },
                    "pages": [],
                },
            },
        )
        self.workspace.set_submission(parsed)
        self.assertIn("model loading timed out", self.workspace.status_badge.text())
        self.assertEqual(self.workspace.generate_transcription_button.text(), "Retry Transcription")
        self.assertFalse(self.workspace.transcription_details_button.isHidden())

    def test_popout_button_requests_whole_workspace_from_main_window(self):
        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
            answers_by_question={"Q1": "Answer"},
        )
        self.workspace.set_submission(parsed)
        requests = []
        self.workspace.popout_workspace_requested.connect(lambda: requests.append(True))
        self.workspace.popout_button.click()
        self.assertEqual(requests, [True])
        self.assertEqual(self.workspace.popout_button.text(), "Pop Out Workspace")

    def test_action_signals_carry_student_or_source(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            files={"pdf": str(self.pdf_path)},
            metadata={
                "extraction": {"selectable_text": False},
                "transcription": {"status": "not_requested"},
            },
        )
        self.workspace.set_submission(parsed)
        opened = []
        generated = []
        self.workspace.open_source_requested.connect(opened.append)
        self.workspace.generate_transcription_requested.connect(generated.append)
        self.workspace.open_source_button.click()
        self.workspace.generate_transcription_button.click()
        self.assertEqual(opened, [str(self.pdf_path)])
        self.assertEqual(generated, ["bob"])


if __name__ == "__main__":
    unittest.main()
