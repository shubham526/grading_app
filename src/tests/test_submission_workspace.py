"""Tests for the resizable two-pane submission workspace."""

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
        self.workspace.resize(1200, 700)

    def tearDown(self):
        self.workspace.close()
        self.tmp.cleanup()

    def test_latex_submission_uses_compiled_pdf_and_source_panel(self):
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
        self.assertEqual(self.workspace.text_panel.answer_text(), "Answer")
        self.assertEqual(self.workspace.text_panel.secondary_kind, "latex_source")
        self.assertTrue(self.workspace.generate_transcription_button.isHidden())

    def test_pdf_accommodation_marks_original_authoritative(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            answers_by_question={"Q1": "Derived"},
            files={"pdf": str(self.pdf_path)},
            metadata={
                "assistive_text_source": "machine_transcription",
                "transcription": {
                    "status": "successful",
                    "model": "gemma4:31b",
                    "pages": [{"page_number": 1, "text": "1. Derived"}],
                    "cache": {"status": "hit"},
                },
            },
        )
        self.workspace.set_question("Q1")
        self.workspace.set_submission(parsed)
        self.assertTrue(self.workspace.pdf_viewer.authoritative)
        self.assertIn("cached", self.workspace.status_badge.text())
        self.assertEqual(self.workspace.text_panel.answer_text(), "Derived")

    def test_uncached_accommodation_offers_explicit_generation(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            files={"pdf": str(self.pdf_path)},
            metadata={
                "transcription": {"enabled": False, "status": "not_requested", "pages": []}
            },
        )
        self.workspace.set_submission(parsed)
        self.assertFalse(self.workspace.generate_transcription_button.isHidden())
        self.assertEqual(self.workspace.generate_transcription_button.text(), "Generate Transcription")

    def test_question_changes_update_answer_without_reloading_submission(self):
        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
            answers_by_question={"Q1": "One", "Q2": "Two"},
        )
        self.workspace.set_submission(parsed)
        self.workspace.set_question("Q2")
        self.assertEqual(self.workspace.text_panel.answer_text(), "Two")

    def test_panels_can_collapse_and_restore(self):
        parsed = ParsedSubmission(
            student_id="alice",
            files={"latex": str(self.tex_path), "compiled_pdf": str(self.pdf_path)},
        )
        self.workspace.set_submission(parsed)
        self.workspace.set_splitter_sizes([600, 500])
        self.workspace.collapse_document_panel()
        self.assertLessEqual(self.workspace.splitter.sizes()[0], 1)
        self.workspace.restore_document_panel()
        self.assertGreater(self.workspace.splitter.sizes()[0], 1)
        self.workspace.collapse_text_panel()
        self.assertLessEqual(self.workspace.splitter.sizes()[1], 1)
        self.workspace.restore_text_panel()
        self.assertGreater(self.workspace.splitter.sizes()[1], 1)

    def test_action_signals_carry_student_or_source(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            files={"pdf": str(self.pdf_path)},
            metadata={"transcription": {"status": "not_requested"}},
        )
        self.workspace.set_submission(parsed)
        opened = []
        generated = []
        refreshed = []
        self.workspace.open_source_requested.connect(opened.append)
        self.workspace.generate_transcription_requested.connect(generated.append)
        self.workspace.refresh_requested.connect(refreshed.append)
        self.workspace.open_source_button.click()
        self.workspace.generate_transcription_button.click()
        self.workspace.refresh_button.click()
        self.assertEqual(opened, [str(self.pdf_path)])
        self.assertEqual(generated, ["bob"])
        self.assertEqual(refreshed, ["bob"])


if __name__ == "__main__":
    unittest.main()
