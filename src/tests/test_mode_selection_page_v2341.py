"""v2.3.4.1 Commit 1 startup chooser tests."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication
except ModuleNotFoundError as exc:  # pragma: no cover
    QApplication = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None
    from src.ui.modes.grading_mode import GradingMode
    from src.ui.modes.mode_selection_page import ModeSelectionPage


@unittest.skipIf(
    QApplication is None,
    "PyQt5 UI runtime unavailable: {!r}".format(_IMPORT_ERROR),
)
class TestModeSelectionPageV2341(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = ModeSelectionPage()

    def tearDown(self):
        self.page.deleteLater()
        self.app.processEvents()

    def test_page_exposes_two_explicit_modes(self):
        self.assertIs(self.page.written_card.mode, GradingMode.WRITTEN)
        self.assertIs(
            self.page.programming_card.mode,
            GradingMode.PROGRAMMING,
        )
        self.assertTrue(self.page.written_card.open_button.isEnabled())
        self.assertTrue(self.page.programming_card.open_button.isEnabled())

    def test_written_button_emits_written_mode(self):
        selected = []
        self.page.mode_selected.connect(selected.append)
        self.page.written_card.open_button.click()
        self.assertEqual(selected, [GradingMode.WRITTEN])

    def test_programming_button_emits_programming_mode(self):
        selected = []
        self.page.mode_selected.connect(selected.append)
        self.page.programming_card.open_button.click()
        self.assertEqual(selected, [GradingMode.PROGRAMMING])


if __name__ == "__main__":
    unittest.main()
