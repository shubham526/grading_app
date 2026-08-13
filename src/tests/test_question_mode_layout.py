"""Headless tests for v2.1 criterion visibility helpers."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock


# Preserve headless-CI compatibility without poisoning the process when real
# PyQt5 is installed.  unittest discovery imports every test module into the
# same interpreter, so unconditional sys.modules mocks leak into later tests.
def _install_qt_stubs_only_if_unavailable():
    try:
        import PyQt5  # noqa: F401
        from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
        return False
    except (ImportError, ModuleNotFoundError):
        qt_modules = (
            "PyQt5", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.QtCore",
            "PyQt5.QtSvg", "PyQt5.QtPrintSupport",
        )
        for module_name in qt_modules:
            if module_name not in sys.modules:
                sys.modules[module_name] = MagicMock()
        sys.modules["PyQt5.QtCore"].pyqtSignal = lambda *a, **kw: MagicMock()
        return True


_QT_STUBS_ACTIVE = _install_qt_stubs_only_if_unavailable()

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


class _FakeWidget:
    def __init__(self, name):
        self.name = name
        self.visible = None

    def setVisible(self, value):
        self.visible = bool(value)


class TestQuestionModeVisibility(unittest.TestCase):

    def test_filter_shows_only_selected_question(self):
        from src.utils.layout import apply_workflow_question_filter

        q1a = _FakeWidget("q1a")
        q1b = _FakeWidget("q1b")
        q2 = _FakeWidget("q2")
        window = SimpleNamespace(
            criterion_widgets=[q1a, q1b, q2],
            workflow_question_groups={"Q1": [q1a, q1b], "Q2": [q2]},
        )

        apply_workflow_question_filter(window, "Q2")

        self.assertFalse(q1a.visible)
        self.assertFalse(q1b.visible)
        self.assertTrue(q2.visible)

    def test_student_centric_restore_shows_every_criterion(self):
        from src.utils.layout import show_all_criteria

        widgets = [_FakeWidget("a"), _FakeWidget("b"), _FakeWidget("c")]
        window = SimpleNamespace(criterion_widgets=widgets)

        show_all_criteria(window)

        self.assertTrue(all(widget.visible for widget in widgets))


if __name__ == "__main__":
    unittest.main(verbosity=2)
