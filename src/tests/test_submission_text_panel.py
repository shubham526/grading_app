"""Tests for question-aware answer/source/transcription presentation."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

try:
    import PyQt5
    from PyQt5.QtWidgets import QApplication
    PYQT_AVAILABLE = not isinstance(PyQt5, Mock) and not isinstance(QApplication, Mock)
except ImportError:
    PYQT_AVAILABLE = False

if PYQT_AVAILABLE:
    from src.submissions.models import (
        ParsedSubmission,
        SUBMISSION_MODE_LATEX,
        SUBMISSION_MODE_PDF_ACCOMMODATION,
    )
    from src.ui.widgets.submission_text_panel import SubmissionTextPanel


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 is required for submission text-panel tests")
class TestSubmissionTextPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.panel = SubmissionTextPanel()

    def tearDown(self):
        self.panel.close()
        self.tmp.cleanup()

    def test_latex_mode_shows_current_answer_and_canonical_source(self):
        tex = Path(self.tmp.name) / "main.tex"
        tex.write_text("\\section*{Question 1}\nStudent source", encoding="utf-8")
        parsed = ParsedSubmission(
            student_id="alice",
            submission_mode=SUBMISSION_MODE_LATEX,
            source_used="latex",
            raw_text="Question 1\nStudent answer",
            answers_by_question={"Q1": "Student answer"},
            files={"latex": str(tex)},
        )
        self.panel.set_question("Q1")
        self.panel.set_submission(parsed)
        self.assertEqual(self.panel.answer_text(), "Student answer")
        self.assertIn("Student source", self.panel.secondary_text())
        self.assertEqual(self.panel.secondary_kind, "latex_source")
        self.assertEqual(self.panel.tabs.tabText(self.panel.secondary_tab_index), "LaTeX Source")

    def test_machine_transcription_is_labeled_assistive(self):
        parsed = ParsedSubmission(
            student_id="bob",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            answers_by_question={"Q1": "Derived Q1"},
            metadata={
                "assistive_text_source": "machine_transcription",
                "transcription": {
                    "status": "successful",
                    "model": "gemma4:31b",
                    "assistive_only": True,
                    "authoritative": False,
                    "cache": {"status": "hit"},
                    "pages": [
                        {"page_number": 1, "text": "1.\nHandwritten answer", "status": "successful"}
                    ],
                },
            },
        )
        self.panel.set_question("Q1")
        self.panel.set_submission(parsed)
        self.assertEqual(self.panel.answer_text(), "Derived Q1")
        self.assertEqual(self.panel.secondary_kind, "transcription")
        self.assertIn("Assistive only", self.panel.secondary_notice.text())
        self.assertIn("gemma4:31b", self.panel.secondary_notice.text())
        self.assertIn("Page 1", self.panel.secondary_text())

    def test_selectable_pdf_text_is_not_called_transcription(self):
        parsed = ParsedSubmission(
            student_id="charlie",
            submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
            accommodation_mode=True,
            source_used="pdf",
            raw_text="Typed PDF answer",
            answers_by_question={"Q1": "Typed PDF answer"},
            metadata={
                "assistive_text_source": "pdf_selectable_text",
                "transcription": {"enabled": False, "status": "not_requested"},
            },
        )
        self.panel.set_submission(parsed)
        self.assertEqual(self.panel.secondary_kind, "pdf_selectable_text")
        self.assertEqual(self.panel.tabs.tabText(self.panel.secondary_tab_index), "Extracted Text")
        self.assertNotIn("transcription", self.panel.secondary_notice.text().lower())

    def test_missing_question_does_not_invent_answer(self):
        parsed = ParsedSubmission(
            student_id="alice",
            answers_by_question={"Q1": "Only Q1"},
        )
        self.panel.set_question("Q2")
        self.panel.set_submission(parsed)
        self.assertEqual(self.panel.answer_text(), "")
        self.assertIn("No extracted answer", self.panel.answer_notice.text())


if __name__ == "__main__":
    unittest.main()
