"""v2.3.4.1 Commit 1 grading-mode domain tests.

The module is loaded directly from its file so this genuinely Qt-free domain
test can run even though the legacy ``src.ui`` package initializer eagerly
imports the PyQt MainWindow.
"""

import importlib.util
from pathlib import Path
import unittest


_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ui"
    / "modes"
    / "grading_mode.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "v2341_grading_mode_domain",
    _MODULE_PATH,
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
GradingMode = _MODULE.GradingMode


class TestGradingModeV2341(unittest.TestCase):
    def test_module_has_no_qt_dependency(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("PyQt", source)

    def test_modes_have_stable_values_and_display_names(self):
        self.assertEqual(GradingMode.WRITTEN.value, "written")
        self.assertEqual(GradingMode.PROGRAMMING.value, "programming")
        self.assertEqual(GradingMode.WRITTEN.display_name, "Written / Text")
        self.assertEqual(GradingMode.PROGRAMMING.display_name, "Programming")

    def test_coerce_accepts_enum_value_and_enum_name(self):
        self.assertIs(GradingMode.coerce(GradingMode.WRITTEN), GradingMode.WRITTEN)
        self.assertIs(GradingMode.coerce(" written "), GradingMode.WRITTEN)
        self.assertIs(GradingMode.coerce("WRITTEN"), GradingMode.WRITTEN)
        self.assertIs(GradingMode.coerce("programming"), GradingMode.PROGRAMMING)
        self.assertIs(GradingMode.coerce("PROGRAMMING"), GradingMode.PROGRAMMING)

    def test_coerce_rejects_missing_or_unknown_mode(self):
        with self.assertRaises(ValueError):
            GradingMode.coerce(None)
        with self.assertRaises(ValueError):
            GradingMode.coerce("hybrid")


if __name__ == "__main__":
    unittest.main()
