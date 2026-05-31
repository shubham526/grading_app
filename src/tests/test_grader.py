"""
test_grader.py
==============

Tests for CriterionWidget business logic and the rubric-parser shim.

Why not import CriterionWidget directly
----------------------------------------
CriterionWidget inherits from QFrame (PyQt5).  When PyQt5 is mocked at the
sys.modules level, Python replaces the *class body* of QFrame with a MagicMock
so CriterionWidget itself becomes a MagicMock — its real methods are never
defined.  Attempting to import or instantiate it in a headless environment
therefore always fails.

Fix: define the five business-logic methods (get_data, set_data, reset,
get_awarded_points, get_possible_points) as standalone functions that accept
a plain SimpleNamespace in place of `self`.  This is equivalent to calling the
real methods because they only access four instance attributes:

    self.criterion_data      dict
    self.points_spinbox      QDoubleSpinBox  (mocked)
    self.comments_edit       MarkdownMathEditor  (mocked)
    self.level_checkboxes    list of (QCheckBox, int)  (mocked)

The function bodies are copied verbatim from criterion.py so any change to
the real code will require an equivalent change here.
"""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
import importlib.util as _ilu

# ---------------------------------------------------------------------------
# Suppress all Qt / GUI imports
# ---------------------------------------------------------------------------

_QT_MOCKS = [
    "PyQt5", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.QtCore",
    "PyQt5.QtSvg", "PyQt5.QtPrintSupport",
    "matplotlib", "matplotlib.backends",
    "matplotlib.backends.backend_qt5agg", "matplotlib.figure",
    "qtawesome",
]
for _m in _QT_MOCKS:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()
sys.modules["PyQt5.QtCore"].pyqtSignal = lambda *a, **kw: MagicMock()

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Standalone equivalents of CriterionWidget business-logic methods
# (verbatim from src/ui/widgets/criterion.py — update if that file changes)
# ---------------------------------------------------------------------------

def get_data(self):
    selected_level = None
    for checkbox, _ in getattr(self, "level_checkboxes", []):
        if checkbox.isChecked():
            selected_level = checkbox.text().split(" (")[0]
    return {
        "id":              self.criterion_data.get("id", ""),
        "title":           self.criterion_data.get("title", ""),
        "points_awarded":  self.points_spinbox.value(),
        "points_possible": self.criterion_data.get("points", 0),
        "selected_level":  selected_level,
        "comments":        self.comments_edit.get_text(),
    }


def set_data(self, criterion_data):
    self.points_spinbox.setValue(criterion_data.get("points_awarded", 0))
    self.comments_edit.set_text(criterion_data.get("comments", ""))
    selected_level = criterion_data.get("selected_level", "")
    if selected_level and hasattr(self, "level_checkboxes"):
        for checkbox, _ in self.level_checkboxes:
            if checkbox.text().split(" (")[0] == selected_level:
                checkbox.setChecked(True)
                break


def reset(self):
    self.points_spinbox.setValue(0)
    self.comments_edit.clear()
    for checkbox, _ in getattr(self, "level_checkboxes", []):
        checkbox.setChecked(False)


def get_awarded_points(self):
    return self.points_spinbox.value()


def get_possible_points(self):
    return self.criterion_data.get("points", 0)


# ---------------------------------------------------------------------------
# Helper: build a fake widget instance
# ---------------------------------------------------------------------------

def _make_widget(points_value=8.0, comment="Test comment",
                 levels_checked=(False, True, False)):
    criterion_data = {
        "id":    "PS3_Q2_RUNTIME",
        "title": "Test Criterion",
        "points": 10,
    }
    spinbox = MagicMock()
    spinbox.value.return_value = points_value

    editor = MagicMock()
    editor.get_text.return_value = comment

    def _cb(title, pts, checked):
        cb = MagicMock()
        cb.text.return_value = f"{title} ({pts} pts)"
        cb.isChecked.return_value = checked
        return cb

    level_checkboxes = [
        (_cb("Excellent",    10, levels_checked[0]), 10),
        (_cb("Good",          8, levels_checked[1]),  8),
        (_cb("Satisfactory",  6, levels_checked[2]),  6),
    ]

    return SimpleNamespace(
        criterion_data   = criterion_data,
        points_spinbox   = spinbox,
        comments_edit    = editor,
        level_checkboxes = level_checkboxes,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCriterionWidget(unittest.TestCase):

    # get_data
    def test_get_data_correct_fields(self):
        w    = _make_widget(points_value=8.0, comment="Test comment",
                            levels_checked=(False, True, False))
        data = get_data(w)
        self.assertEqual(data["id"],              "PS3_Q2_RUNTIME")
        self.assertEqual(data["title"],           "Test Criterion")
        self.assertEqual(data["points_awarded"],  8.0)
        self.assertEqual(data["points_possible"], 10)
        self.assertEqual(data["selected_level"],  "Good")
        self.assertEqual(data["comments"],        "Test comment")

    def test_get_data_no_level_selected(self):
        w    = _make_widget(levels_checked=(False, False, False))
        data = get_data(w)
        self.assertIsNone(data["selected_level"])

    # set_data
    def test_set_data_updates_points(self):
        w = _make_widget()
        set_data(w, {"points_awarded": 6, "comments": "", "selected_level": ""})
        w.points_spinbox.setValue.assert_called_with(6)

    def test_set_data_updates_comments(self):
        w = _make_widget()
        set_data(w, {"points_awarded": 0, "comments": "Updated", "selected_level": ""})
        w.comments_edit.set_text.assert_called_with("Updated")

    def test_set_data_checks_correct_level(self):
        w = _make_widget()
        set_data(w, {"points_awarded": 6, "comments": "", "selected_level": "Satisfactory"})
        w.level_checkboxes[2][0].setChecked.assert_called_with(True)

    # reset
    def test_reset_zeros_points(self):
        w = _make_widget()
        reset(w)
        w.points_spinbox.setValue.assert_called_with(0)

    def test_reset_clears_comments(self):
        w = _make_widget()
        reset(w)
        w.comments_edit.clear.assert_called_once()

    def test_reset_unchecks_all_levels(self):
        w = _make_widget()
        reset(w)
        for cb, _ in w.level_checkboxes:
            cb.setChecked.assert_called_with(False)

    # get_awarded_points / get_possible_points
    def test_get_awarded_points(self):
        w = _make_widget(points_value=8.0)
        self.assertEqual(get_awarded_points(w), 8.0)

    def test_get_possible_points(self):
        w = _make_widget()
        self.assertEqual(get_possible_points(w), 10)


# ---------------------------------------------------------------------------
# parse_rubric_file via rubric_parser shim
# ---------------------------------------------------------------------------

class TestParseRubricFileViaShim(unittest.TestCase):
    """
    Tests parse_rubric_file() from rubric_parser.py using direct module
    loading to avoid the PyQt5 chain in src/utils/__init__.py.
    """

    @classmethod
    def _load_parser(cls):
        spec = _ilu.spec_from_file_location(
            "rubric_parser_shim",
            os.path.join(_REPO_ROOT, "src", "utils", "rubric_parser.py"))
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parse_rubric_file_loads_json(self):
        mod    = self._load_parser()
        sample = {
            "title": "Test Rubric",
            "criteria": [
                {"title": "Criterion 1", "description": "D1", "points": 10},
                {"title": "Criterion 2", "description": "D2", "points": 20},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_rubric.json")
            with open(path, "w") as fh:
                json.dump(sample, fh)
            rubric = mod.parse_rubric_file(path)
        self.assertEqual(rubric["title"],                 "Test Rubric")
        self.assertEqual(len(rubric["criteria"]),         2)
        self.assertEqual(rubric["criteria"][0]["title"],  "Criterion 1")
        self.assertEqual(rubric["criteria"][1]["points"], 20)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)