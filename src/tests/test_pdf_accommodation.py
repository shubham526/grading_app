"""Tests for v2.2.0 commit-2 PDF accommodation ingestion/rendering."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.pdf import (
    cleanup_pdf_render_artifacts,
    extract_text_from_pdf,
    record_from_pdf_accommodation,
    render_pdf_pages,
)

try:
    import pymupdf
except ImportError:  # pragma: no cover - compatibility with older PyMuPDF installs.
    try:
        import fitz as pymupdf
    except ImportError:  # pragma: no cover
        pymupdf = None


@unittest.skipIf(pymupdf is None, "PyMuPDF not installed")
class TestPdfAccommodationBackend(unittest.TestCase):

    def _make_pdf(self, path, page_texts):
        doc = pymupdf.open()
        for text in page_texts:
            page = doc.new_page(width=612, height=792)  # US Letter in points.
            if text is not None:
                page.insert_textbox(
                    pymupdf.Rect(72, 72, 540, 720),
                    text,
                    fontsize=11,
                )
        doc.save(str(path))
        doc.close()
        return path

    def test_explicit_file_record_marks_generic_accommodation_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "Alice Smith.pdf", ["Answer"])
            record = record_from_pdf_accommodation(str(pdf))

        self.assertEqual(record.student_id, "alice_smith")
        self.assertEqual(record.submission_mode, "pdf_accommodation")
        self.assertTrue(record.accommodation_mode)
        self.assertTrue(record.files["pdf"].endswith("Alice Smith.pdf"))

    def test_directory_prefers_main_pdf_and_warns_on_multiple(self):
        with tempfile.TemporaryDirectory() as tmp:
            student = Path(tmp) / "Student 7"
            student.mkdir()
            self._make_pdf(student / "other.pdf", ["x" * 500])
            self._make_pdf(student / "main.pdf", ["main"])
            record = record_from_pdf_accommodation(str(student))

        self.assertEqual(record.student_id, "student_7")
        self.assertTrue(record.files["pdf"].endswith("main.pdf"))
        self.assertIn("multiple_pdf_files", record.warnings)

    def test_extracts_selectable_text_without_ocr(self):
        text = "Question 1\n" + ("A correct typed response. " * 12)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "typed.pdf", [text])
            extracted, metadata = extract_text_from_pdf(str(pdf))

        self.assertIn("Question 1", extracted)
        self.assertTrue(metadata["text_layer_present"])
        self.assertTrue(metadata["selectable_text"])
        self.assertEqual(metadata["page_count"], 1)
        self.assertFalse(metadata["ocr_performed"])
        self.assertNotIn("pdf_may_be_image_only", metadata["warnings"])

    def test_sparse_text_is_preserved_but_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "scanlike.pdf", ["Question 1"])
            extracted, metadata = extract_text_from_pdf(str(pdf))

        self.assertEqual(extracted.strip(), "Question 1")
        self.assertTrue(metadata["text_layer_present"])
        self.assertFalse(metadata["selectable_text"])
        self.assertIn("pdf_may_be_image_only", metadata["warnings"])

    def test_renders_pages_at_200_dpi_with_deterministic_names(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            pdf = self._make_pdf(Path(tmp) / "two_pages.pdf", ["Page one", "Page two"])
            result = render_pdf_pages(str(pdf), output_dir=out, dpi=200)

            self.assertTrue(result.success, result.error_message)
            self.assertEqual(result.page_count, 2)
            self.assertEqual([Path(p.image_path).name for p in result.pages], [
                "page_001.png",
                "page_002.png",
            ])
            self.assertEqual(result.pages[0].width_px, 1700)
            self.assertEqual(result.pages[0].height_px, 2200)
            self.assertFalse(result.temporary_output)
            self.assertTrue(all(Path(p.image_path).is_file() for p in result.pages))

    def test_persistent_render_removes_stale_managed_page_files_only(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            output = Path(out)
            (output / "page_003.png").write_bytes(b"stale")
            (output / "keep.txt").write_text("keep", encoding="utf-8")
            pdf = self._make_pdf(Path(tmp) / "one.pdf", ["Only page"])
            result = render_pdf_pages(str(pdf), output_dir=out)

            self.assertTrue(result.success)
            self.assertFalse((output / "page_003.png").exists())
            self.assertTrue((output / "keep.txt").exists())

    def test_temporary_render_can_be_cleaned_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "one.pdf", ["Only page"])
            result = render_pdf_pages(str(pdf))
            output_dir = result.output_dir
            self.assertTrue(result.success)
            self.assertTrue(result.temporary_output)
            self.assertTrue(Path(output_dir).is_dir())
            cleanup_pdf_render_artifacts(result)
            self.assertFalse(Path(output_dir).exists())

    def test_symlinked_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = self._make_pdf(Path(tmp) / "real.pdf", ["text"])
            link = Path(tmp) / "linked.pdf"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this platform")
            with self.assertRaises(ValueError):
                extract_text_from_pdf(str(link))


class TestPdfDependencyFailure(unittest.TestCase):

    def test_missing_pymupdf_returns_structured_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "fake.pdf"
            pdf.write_bytes(b"%PDF-1.4\nnot parsed because dependency is mocked missing")
            with patch("src.submissions.pdf._import_pymupdf", return_value=None):
                text, metadata = extract_text_from_pdf(str(pdf))
                rendered = render_pdf_pages(str(pdf))

        self.assertEqual(text, "")
        self.assertEqual(metadata["error_code"], "pdf_extraction_unavailable")
        self.assertIn("pdf_extraction_unavailable", metadata["warnings"])
        self.assertFalse(rendered.success)
        self.assertEqual(rendered.error_code, "pdf_rendering_unavailable")

    def test_render_dpi_is_bounded_before_backend_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "fake.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            with self.assertRaises(ValueError):
                render_pdf_pages(str(pdf), dpi=50)
            with self.assertRaises(ValueError):
                render_pdf_pages(str(pdf), dpi=1200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
