"""Tests for v2.2.0 commit-2 PDF accommodation parser orchestration."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.models import PdfRenderResult
from src.submissions.parser import (
    parse_pdf_accommodation,
    parse_pdf_accommodations,
    parse_submission,
)

try:
    import pymupdf
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf
    except ImportError:  # pragma: no cover
        pymupdf = None


@unittest.skipIf(pymupdf is None, "PyMuPDF not installed")
class TestPdfAccommodationParser(unittest.TestCase):

    def _make_pdf(self, path, page_texts):
        doc = pymupdf.open()
        for text in page_texts:
            page = doc.new_page(width=612, height=792)
            if text:
                page.insert_textbox(
                    pymupdf.Rect(72, 72, 540, 720),
                    text,
                    fontsize=11,
                )
        doc.save(str(path))
        doc.close()
        return path

    def test_pdf_is_rejected_without_explicit_accommodation_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "student.pdf", ["Answer"])
            with self.assertRaisesRegex(ValueError, "accommodation_mode=True"):
                parse_submission(str(pdf), ["Q1"])

    def test_typed_accommodation_renders_and_splits_assistive_text(self):
        q1 = "Question 1\n" + ("Typed answer one. " * 15)
        q2 = "Question 2\n" + ("Typed answer two. " * 15)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as rendered:
            pdf = self._make_pdf(Path(tmp) / "Student 42.pdf", [q1 + "\n\n" + q2])
            parsed = parse_submission(
                str(pdf),
                ["Q1", "Q2"],
                accommodation_mode=True,
                render_dir=rendered,
            )

            self.assertEqual(parsed.student_id, "student_42")
            self.assertEqual(parsed.submission_mode, "pdf_accommodation")
            self.assertTrue(parsed.accommodation_mode)
            self.assertEqual(parsed.source_used, "pdf")
            self.assertEqual(parsed.metadata["authoritative_source"], "original_pdf")
            self.assertTrue(parsed.metadata["original_pdf_authoritative"])
            self.assertEqual(parsed.metadata["assistive_text_source"], "pdf_selectable_text")
            self.assertEqual(parsed.metadata["question_split_status"], "success")
            self.assertIn("Typed answer one", parsed.answers_by_question["Q1"])
            self.assertIn("Typed answer two", parsed.answers_by_question["Q2"])
            self.assertEqual(len(parsed.page_image_paths), 1)
            self.assertTrue(Path(parsed.page_image_paths[0]).is_file())
            self.assertTrue(parsed.files["rendered_pages_dir"].endswith("student_42"))
            self.assertEqual(parsed.metadata["rendering"]["dpi"], 200)

    def test_scanlike_accommodation_keeps_original_and_pages_without_fake_answers(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as rendered:
            # A blank page models image-only/handwritten content with no selectable text.
            pdf = self._make_pdf(Path(tmp) / "handwritten.pdf", [None])
            parsed = parse_pdf_accommodation(
                str(pdf),
                ["Q1", "Q2"],
                student_id="student-a",
                render_dir=rendered,
            )

            self.assertEqual(parsed.answers_by_question, {})
            self.assertEqual(parsed.metadata["question_split_status"], "unavailable")
            self.assertIsNone(parsed.metadata["assistive_text_source"])
            self.assertIn("pdf_may_be_image_only", parsed.warnings)
            self.assertTrue(parsed.metadata["rendering"]["success"])
            self.assertEqual(len(parsed.page_image_paths), 1)
            self.assertEqual(parsed.files["pdf"], str(pdf.resolve()))
            self.assertTrue(parsed.metadata["original_pdf_authoritative"])

    @patch("src.submissions.parser.render_pdf_pages")
    def test_render_failure_does_not_make_original_pdf_unavailable(self, render_mock):
        render_mock.return_value = PdfRenderResult(
            success=False,
            source_path="student.pdf",
            dpi=200,
            warnings=["pdf_rendering_unavailable"],
            error_code="pdf_rendering_unavailable",
            error_message="missing backend",
        )
        text = "Question 1\n" + ("Typed answer. " * 20)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "student.pdf", [text])
            parsed = parse_pdf_accommodation(str(pdf), ["Q1"])

        self.assertEqual(parsed.files["pdf"], str(pdf.resolve()))
        self.assertNotIn("rendered_pages_dir", parsed.files)
        self.assertIn("pdf_rendering_unavailable", parsed.warnings)
        self.assertIn("Typed answer", parsed.answers_by_question["Q1"])

    def test_explicit_batch_mapping_stores_no_accommodation_reason(self):
        text = "Question 1\n" + ("Answer. " * 30)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as rendered:
            a = self._make_pdf(Path(tmp) / "a.pdf", [text])
            b = self._make_pdf(Path(tmp) / "b.pdf", [text])
            parsed = parse_pdf_accommodations(
                {"Alice Student": str(a), "Bob Student": str(b)},
                ["Q1"],
                render_dir=rendered,
            )

        self.assertEqual(sorted(parsed), ["alice_student", "bob_student"])
        for submission in parsed.values():
            self.assertTrue(submission.accommodation_mode)
            metadata_text = repr(submission.metadata).casefold()
            self.assertNotIn("medical", metadata_text)
            self.assertNotIn("disability", metadata_text)
            self.assertNotIn("accommodation_reason", metadata_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
