"""Tests for the embedded PyMuPDF submission viewer."""

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
    from src.ui.widgets.pdf_viewer import (
        MAX_ZOOM_PERCENT,
        MIN_ZOOM_PERCENT,
        PdfDocumentViewer,
    )


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 and PyMuPDF are required for PDF viewer tests")
class TestPdfDocumentViewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf_path = Path(self.tmp.name) / "two_pages.pdf"
        doc = pymupdf.open()
        page1 = doc.new_page(width=300, height=400)
        page1.insert_text((40, 60), "Page one")
        page2 = doc.new_page(width=300, height=400)
        page2.insert_text((40, 60), "Page two")
        doc.save(str(self.pdf_path))
        doc.close()
        self.viewer = PdfDocumentViewer()
        self.viewer.resize(800, 600)

    def tearDown(self):
        self.viewer.close()
        self.tmp.cleanup()

    def test_loads_real_pdf_and_navigates_pages(self):
        self.assertTrue(self.viewer.set_document(str(self.pdf_path), title="Submission"))
        self.assertEqual(self.viewer.page_count, 2)
        self.assertEqual(self.viewer.current_page, 1)
        self.assertTrue(self.viewer.next_page())
        self.assertEqual(self.viewer.current_page, 2)
        self.assertTrue(self.viewer.previous_page())
        self.assertEqual(self.viewer.current_page, 1)

    def test_zoom_is_bounded(self):
        self.viewer.set_document(str(self.pdf_path))
        self.viewer.set_zoom_percent(9999)
        self.assertEqual(self.viewer.zoom_percent, MAX_ZOOM_PERCENT)
        self.viewer.set_zoom_percent(1)
        self.assertEqual(self.viewer.zoom_percent, MIN_ZOOM_PERCENT)

    def test_fit_modes_are_explicit(self):
        self.viewer.set_document(str(self.pdf_path))
        self.viewer.fit_page()
        self.assertEqual(self.viewer.fit_mode, "page")
        self.viewer.fit_width()
        self.assertEqual(self.viewer.fit_mode, "width")
        self.viewer.set_zoom_percent(125)
        self.assertIsNone(self.viewer.fit_mode)

    def test_missing_pdf_is_an_in_pane_error(self):
        self.assertFalse(self.viewer.set_document(str(Path(self.tmp.name) / "missing.pdf")))
        self.assertFalse(self.viewer.has_document)
        self.assertIn("PDF not found", self.viewer.last_error)

    def test_authoritative_label_is_explicit(self):
        self.viewer.set_document(str(self.pdf_path), authoritative=True)
        self.assertTrue(self.viewer.authoritative)
        self.assertEqual(self.viewer.authority_label.text(), "Authoritative evidence")


if __name__ == "__main__":
    unittest.main()
