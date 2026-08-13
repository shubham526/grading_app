"""Tests for the Commit-5 application visual system."""

import os
import unittest
from unittest.mock import Mock

try:
    import PyQt5
    from PyQt5.QtGui import QFontDatabase, QPalette
    from PyQt5.QtWidgets import QApplication
    _QT_AVAILABLE = (
        not isinstance(PyQt5, Mock)
        and not isinstance(QApplication, Mock)
        and not isinstance(QFontDatabase, Mock)
    )
except (ImportError, ModuleNotFoundError):
    QApplication = None
    QFontDatabase = None
    QPalette = None
    _QT_AVAILABLE = False


@unittest.skipUnless(_QT_AVAILABLE, "PyQt5 is required for application-style tests")
class TestCommit5Styles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_semantic_palette_contains_design_tokens_and_compatibility_aliases(self):
        from src.utils.styles import COLORS, SEMANTIC_COLORS
        self.assertEqual(SEMANTIC_COLORS["primary"], "#3B5CCC")
        self.assertEqual(SEMANTIC_COLORS["background"], "#F6F7F9")
        self.assertEqual(SEMANTIC_COLORS["surface"], "#FFFFFF")
        self.assertEqual(SEMANTIC_COLORS["text_primary"], "#1F2937")
        self.assertEqual(SEMANTIC_COLORS["border"], "#D9DEE7")
        for legacy in ("card", "primary_light", "primary_dark", "accent", "info"):
            self.assertIn(legacy, COLORS)

    def test_apply_style_uses_qt_system_font(self):
        from src.utils.styles import apply_app_style
        expected = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        apply_app_style(self.app)
        self.assertEqual(self.app.font().family(), expected.family())

    def test_apply_style_sets_neutral_window_palette(self):
        from src.utils.styles import apply_app_style
        apply_app_style(self.app)
        self.assertEqual(self.app.palette().color(QPalette.Window).name().upper(), "#F6F7F9")
        self.assertEqual(self.app.palette().color(QPalette.Highlight).name().upper(), "#3B5CCC")

    def test_stylesheet_defines_primary_and_secondary_button_hierarchy(self):
        from src.utils.styles import APP_STYLESHEET
        self.assertIn('QPushButton[buttonRole="primary"]', APP_STYLESHEET)
        self.assertIn("background-color: #FFFFFF", APP_STYLESHEET)
        self.assertIn("background-color: #3B5CCC", APP_STYLESHEET)

    def test_legacy_apply_material_style_remains_callable(self):
        from src.utils.styles import apply_material_style
        apply_material_style(self.app)
        self.assertIn("QPushButton", self.app.styleSheet())


if __name__ == "__main__":
    unittest.main()
