"""Criterion widget for manual rubric grading.

Commit 5 changes only presentation and layout density here.  Scoring, explicit
zero handling, achievement-level behavior, dirty-state signals, comments, and
saved-data semantics remain the same as v2.1.
"""

from datetime import datetime, timezone

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from src.ui.widgets.math_editor import MarkdownMathEditor


class CriterionWidget(QFrame):
    """Widget representing one rubric criterion."""

    points_changed = pyqtSignal()
    content_changed = pyqtSignal()

    def __init__(self, criterion_data, parent=None):
        super().__init__(parent)
        self.criterion_data = criterion_data

        # Explicit grading state distinguishes an untouched visual zero from an
        # intentionally awarded zero.
        self.is_graded = False
        self.graded_at = None
        self.graded_by = None
        self._loading_data = False

        self.setObjectName("criterionCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setup_ui()
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(
            """
            QFrame#criterionCard {
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 8px;
            }
            QLabel#criterionTitle {
                color: #1F2937;
                font-size: 14px;
                font-weight: 600;
                background: transparent;
            }
            QLabel#criterionDescription {
                color: #667085;
                background: transparent;
            }
            QLabel#criterionMeta {
                color: #667085;
                background: transparent;
            }
            QFrame#pointsPanel {
                background-color: #F9FAFB;
                border: 1px solid #E6E9EF;
                border-radius: 6px;
            }
            QDoubleSpinBox#criterionPoints {
                min-width: 72px;
                padding: 5px 7px;
                color: #1F2937;
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 5px;
            }
            QDoubleSpinBox#criterionPoints:focus {
                border: 1px solid #3B5CCC;
            }
            QGroupBox#achievementLevels {
                color: #1F2937;
                font-weight: 600;
                border: 1px solid #E6E9EF;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
                background-color: #FFFFFF;
            }
            QGroupBox#achievementLevels::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QFrame[levelRow="true"] {
                background: transparent;
                border: none;
                border-radius: 5px;
            }
            QFrame[levelRow="true"]:hover {
                background-color: #F9FAFB;
            }
            QCheckBox {
                color: #1F2937;
                spacing: 7px;
                padding: 2px;
                background: transparent;
            }
            QCheckBox:hover {
                color: #304DAF;
            }
            """
        )

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel(self.criterion_data.get("title", "Untitled Criterion"), self)
        title_label.setObjectName("criterionTitle")
        title_label.setProperty("labelType", "criterionTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        description = self.criterion_data.get("description", "")
        if description:
            desc_label = QLabel(str(description), self)
            desc_label.setObjectName("criterionDescription")
            desc_label.setProperty("labelType", "criterionDescription")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        points_container = QFrame(self)
        points_container.setObjectName("pointsPanel")
        points_layout = QHBoxLayout(points_container)
        points_layout.setContentsMargins(10, 7, 10, 7)
        points_layout.setSpacing(8)

        points_label = QLabel("Points", points_container)
        points_label.setStyleSheet("font-weight: 600; color: #1F2937; background: transparent;")
        points_layout.addWidget(points_label)

        self.points_spinbox = QDoubleSpinBox(points_container)
        self.points_spinbox.setObjectName("criterionPoints")
        self.points_spinbox.setDecimals(1)
        self.points_spinbox.setSingleStep(0.5)
        self.max_points = self.criterion_data.get("points", 10)
        self.points_spinbox.setRange(0, self.max_points)
        self.points_spinbox.setToolTip(f"Maximum points: {self.max_points}")
        self.points_spinbox.valueChanged.connect(self._on_points_value_changed)
        self.points_spinbox.editingFinished.connect(self._on_points_editing_finished)
        points_layout.addWidget(self.points_spinbox)

        possible_label = QLabel(f"/ {self.max_points}", points_container)
        possible_label.setObjectName("criterionMeta")
        points_layout.addWidget(possible_label)
        points_layout.addStretch(1)
        layout.addWidget(points_container)

        levels = self.criterion_data.get("levels", [])
        if levels:
            levels_group = QGroupBox("Achievement Levels", self)
            levels_group.setObjectName("achievementLevels")
            levels_layout = QVBoxLayout(levels_group)
            levels_layout.setContentsMargins(10, 10, 10, 8)
            levels_layout.setSpacing(4)

            self.level_checkboxes = []
            for level in levels:
                level_container = QFrame(levels_group)
                level_container.setProperty("levelRow", True)
                level_layout = QVBoxLayout(level_container)
                level_layout.setContentsMargins(6, 5, 6, 5)
                level_layout.setSpacing(4)

                level_checkbox = QCheckBox(
                    f"{level.get('title')} ({level.get('points')} pts)",
                    level_container,
                )
                level_checkbox.setStyleSheet("font-weight: 600; background: transparent;")

                level_description = level.get("description", "")
                if level_description:
                    level_checkbox.setToolTip(str(level_description))

                level_checkbox.clicked.connect(self.update_points_from_level)
                self.level_checkboxes.append((level_checkbox, level.get("points", 0)))
                level_layout.addWidget(level_checkbox)

                if level_description:
                    desc_label = QLabel(str(level_description), level_container)
                    desc_label.setObjectName("criterionMeta")
                    desc_label.setWordWrap(True)
                    desc_label.setStyleSheet(
                        "color: #667085; padding-left: 24px; font-size: 12px; background: transparent;"
                    )
                    level_layout.addWidget(desc_label)

                levels_layout.addWidget(level_container)

            layout.addWidget(levels_group)

        comment_label = QLabel(
            "Comments  ·  Markdown and LaTeX math supported with $...$ or $$...$$",
            self,
        )
        comment_label.setObjectName("criterionMeta")
        layout.addWidget(comment_label)

        self.comments_edit = MarkdownMathEditor(self)
        self.comments_edit.setMinimumHeight(120)
        self.comments_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if hasattr(self.comments_edit, "editor"):
            self.comments_edit.editor.setPlaceholderText("Add grading feedback…")
            self.comments_edit.editor.setStyleSheet(
                """
                QTextEdit {
                    color: #1F2937;
                    background-color: #FFFFFF;
                    border: 1px solid #D9DEE7;
                    border-radius: 6px;
                    padding: 7px;
                }
                QTextEdit:focus {
                    border: 1px solid #3B5CCC;
                }
                """
            )
            self.comments_edit.editor.textChanged.connect(self._on_comment_changed)
        layout.addWidget(self.comments_edit)

    def _mark_graded(self):
        """Mark the criterion graded and refresh its grading timestamp."""
        if self._loading_data:
            return
        self.is_graded = True
        self.graded_at = datetime.now(timezone.utc).isoformat()
        if not self.graded_by:
            self.graded_by = "instructor"

    def _on_points_value_changed(self, _value):
        """Handle a real score change from the spin box."""
        if self._loading_data:
            return
        self._mark_graded()
        self.points_changed.emit()
        self.content_changed.emit()

    def _on_comment_changed(self):
        """Mark comment-only edits dirty without changing graded status."""
        if self._loading_data:
            return
        self.content_changed.emit()

    def _on_points_editing_finished(self):
        """Treat an explicitly confirmed unchanged value (especially zero) as graded."""
        if self._loading_data:
            return
        was_graded = self.is_graded
        self._mark_graded()
        if not was_graded:
            self.points_changed.emit()
            self.content_changed.emit()

    def update_points_from_level(self):
        """Update the points value based on the selected achievement level."""
        sender = self.sender()

        for checkbox, _points in self.level_checkboxes:
            if checkbox != sender and checkbox.isChecked():
                checkbox.setChecked(False)

        for checkbox, points in self.level_checkboxes:
            if checkbox.isChecked():
                previous_value = self.points_spinbox.value()
                self.points_spinbox.setValue(points)
                if previous_value == self.points_spinbox.value():
                    self._mark_graded()
                    self.points_changed.emit()
                    self.content_changed.emit()
                return

        self._mark_graded()
        self.points_changed.emit()
        self.content_changed.emit()

    def get_data(self):
        """Return the current criterion grading state."""
        selected_level = None
        for checkbox, _ in getattr(self, "level_checkboxes", []):
            if checkbox.isChecked():
                selected_level = checkbox.text().split(" (")[0]

        data = {
            "id": self.criterion_data.get("id", ""),
            "title": self.criterion_data.get("title", ""),
            "points_awarded": self.points_spinbox.value(),
            "points_possible": self.criterion_data.get("points", 0),
            "selected_level": selected_level,
            "comments": self.comments_edit.get_text(),
            "grading_status": {
                "graded": bool(self.is_graded),
                "graded_at": self.graded_at,
                "graded_by": self.graded_by,
            },
        }

        question_id = self.criterion_data.get("question_id")
        if question_id:
            data["question_id"] = question_id
        return data

    def set_data(self, criterion_data):
        """Restore widget state from saved criterion data."""
        self._loading_data = True
        try:
            points_awarded = criterion_data.get("points_awarded", 0)
            self.points_spinbox.setValue(0 if points_awarded is None else points_awarded)
            self.comments_edit.set_text(criterion_data.get("comments", ""))

            for checkbox, _ in getattr(self, "level_checkboxes", []):
                checkbox.setChecked(False)

            selected_level = criterion_data.get("selected_level", "")
            if selected_level and hasattr(self, "level_checkboxes"):
                for checkbox, _ in self.level_checkboxes:
                    if checkbox.text().split(" (")[0] == selected_level:
                        checkbox.setChecked(True)
                        break

            status = criterion_data.get("grading_status")
            if isinstance(status, dict) and "graded" in status:
                self.is_graded = bool(status.get("graded"))
                self.graded_at = status.get("graded_at")
                self.graded_by = status.get("graded_by")
            else:
                self.is_graded = criterion_data.get("points_awarded") is not None
                self.graded_at = None
                self.graded_by = None
        finally:
            self._loading_data = False

    def reset(self):
        """Reset the widget to its initial ungraded state."""
        self._loading_data = True
        try:
            self.points_spinbox.setValue(0)
            self.comments_edit.clear()
            for checkbox, _ in getattr(self, "level_checkboxes", []):
                checkbox.setChecked(False)
            self.is_graded = False
            self.graded_at = None
            self.graded_by = None
        finally:
            self._loading_data = False

    def get_awarded_points(self):
        return self.points_spinbox.value()

    def get_possible_points(self):
        return self.criterion_data.get("points", 0)
