"""Tests for the v2.3.4.1 WrittenGradingWorkspace boundary."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
except ModuleNotFoundError as exc:  # pragma: no cover
    QApplication = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None
    from src.ui.workspaces.written_grading_workspace import WrittenGradingWorkspace


@unittest.skipIf(
    QApplication is None,
    "Full PyQt application runtime unavailable: {!r}".format(_IMPORT_ERROR),
)
class TestWrittenGradingWorkspaceV2341(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_adopts_exact_legacy_root_without_rebuilding_children(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        child = QLabel("preserved")
        root_layout.addWidget(child)

        workspace = WrittenGradingWorkspace(root)

        self.assertIs(workspace.legacy_root, root)
        self.assertIs(workspace.legacy_layout(), root_layout)
        self.assertIs(child.parentWidget(), root)
        self.assertIs(root.parentWidget(), workspace)
        self.assertEqual(workspace.layout().contentsMargins().left(), 0)
        self.assertEqual(workspace.layout().spacing(), 0)
        workspace.deleteLater()

    def test_rejects_missing_or_non_widget_root(self):
        with self.assertRaises(ValueError):
            WrittenGradingWorkspace(None)
        with self.assertRaises(TypeError):
            WrittenGradingWorkspace(object())


if __name__ == "__main__":
    unittest.main()
