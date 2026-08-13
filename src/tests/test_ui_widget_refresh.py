"""UI-surface regression tests for the Commit-5 visual widget refresh."""

import unittest
from unittest.mock import Mock

try:
    import PyQt5
    from PyQt5.QtWidgets import QApplication, QLabel
    PYQT_AVAILABLE = not isinstance(PyQt5, Mock) and not isinstance(QApplication, Mock)
except ImportError:
    PYQT_AVAILABLE = False

if PYQT_AVAILABLE:
    from src.ui.widgets.card import CardWidget
    from src.ui.widgets.criterion import CriterionWidget
    from src.ui.widgets.header import HeaderWidget
    from src.ui.widgets.status_bar import StatusBarWidget


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 is required for UI widget tests")
class TestModernizedWidgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_header_is_responsive_and_supports_subtitle(self):
        header = HeaderWidget()
        self.assertEqual(header.title, "Rubric Grading Tool")
        self.assertGreaterEqual(header.minimumHeight(), 40)
        self.assertLess(header.minimumHeight(), 90)
        header.set_subtitle("PS3 · Question-centric grading")
        self.assertEqual(header.subtitle, "PS3 · Question-centric grading")
        self.assertTrue(header.subtitle_label.isVisibleTo(header) or header.subtitle_label.text())

    def test_card_preserves_existing_content_layout_api(self):
        card = CardWidget("Section", collapsible=True)
        label = QLabel("content")
        card.get_content_layout().addWidget(label)
        self.assertIs(label.parentWidget(), card.content)
        card.set_collapsed(True)
        self.assertTrue(card.is_collapsed())
        self.assertFalse(card.content.isVisible())
        card.set_collapsed(False)
        self.assertFalse(card.is_collapsed())

    def test_status_bar_preserves_legacy_methods_and_adds_submission_state(self):
        status = StatusBarWidget()
        status.set_status("Grading")
        status.set_auto_save_status("Saved")
        status.set_submission_status("Cached", "success")
        status.set_version("v2.2.0")
        self.assertEqual(status.status_label.text(), "Grading")
        self.assertEqual(status.auto_save_status.text(), "Saved")
        self.assertEqual(status.submission_status.text(), "Cached")
        self.assertEqual(status.version_label.text(), "v2.2.0")

    def test_criterion_visual_refresh_keeps_saved_data_contract(self):
        widget = CriterionWidget({
            "id": "Q1_RUNTIME",
            "question_id": "Q1",
            "title": "Q1 Runtime",
            "points": 5,
            "levels": [],
        })
        widget.set_data({
            "points_awarded": 3.5,
            "comments": "Good analysis",
            "grading_status": {
                "graded": True,
                "graded_at": "2026-08-13T00:00:00+00:00",
                "graded_by": "instructor",
            },
        })
        data = widget.get_data()
        self.assertEqual(data["id"], "Q1_RUNTIME")
        self.assertEqual(data["question_id"], "Q1")
        self.assertEqual(data["points_awarded"], 3.5)
        self.assertEqual(data["comments"], "Good analysis")
        self.assertTrue(data["grading_status"]["graded"])


if __name__ == "__main__":
    unittest.main()
