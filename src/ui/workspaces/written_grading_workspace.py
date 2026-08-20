"""Written/text grading workspace boundary for v2.3.4.1.

Commit 2 intentionally isolates presentation without rewriting the mature
manual-grading implementation. ``RubricGrader.init_ui()`` still constructs the
exact written UI and owns its established grading/session state. This widget
adopts that already-constructed root as one intact child so later mode-specific
work can target a real workspace object rather than a raw legacy central widget.

No rubric, roster, submission, save, navigation, similarity, evidence, or
history behavior is duplicated here.
"""

from PyQt5.QtWidgets import QVBoxLayout, QWidget


class WrittenGradingWorkspace(QWidget):
    """Dedicated presentation boundary around the preserved written grader."""

    def __init__(self, legacy_root, parent=None):
        if legacy_root is None:
            raise ValueError("legacy_root is required")
        if not isinstance(legacy_root, QWidget):
            raise TypeError("legacy_root must be a QWidget")

        super().__init__(parent)
        self.setObjectName("writtenGradingWorkspace")
        self._legacy_root = legacy_root
        self._legacy_root.setObjectName("writtenGradingWorkspaceLegacyRoot")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._legacy_root)

    @property
    def legacy_root(self):
        """Return the exact pre-workspace written root widget."""

        return self._legacy_root

    def legacy_layout(self):
        """Return the preserved written root's layout for compatibility hooks."""

        return self._legacy_root.layout()


__all__ = ["WrittenGradingWorkspace"]
