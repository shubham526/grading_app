"""
Criterion Widget for Rubric Grading Tool.

This module defines the UI component that represents a single criterion in the rubric.
"""

from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                           QSpinBox, QCheckBox, QGroupBox, QTextEdit, QSizePolicy, QDoubleSpinBox)
from PyQt5.QtCore import Qt, pyqtSignal
from datetime import datetime, timezone

from src.ui.widgets.math_editor import MarkdownMathEditor


class CriterionWidget(QFrame):
    """Widget representing a single criterion from the rubric."""

    # Signal emitted when points are changed
    points_changed = pyqtSignal()

    def __init__(self, criterion_data, parent=None):
        """
        Initialize the criterion widget.

        Args:
            criterion_data (dict): Dictionary containing the criterion definition
            parent (QWidget, optional): Parent widget
        """
        super().__init__(parent)
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        self.criterion_data = criterion_data

        # v2.1 explicit grading state.  The spin box visually defaults to 0, so
        # a separate flag is required to distinguish "not graded yet" from an
        # intentional score of zero.
        self.is_graded = False
        self.graded_at = None
        self.graded_by = None
        self._loading_data = False

        # Apply material design style
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 4px;
                border: 1px solid #EEEEEE;
                margin: 4px;
                padding: 8px;
            }
            QFrame:hover {
                border: 1px solid #BDBDBD;
                background-color: #FAFAFA;
            }
            QLabel[labelType="criterionTitle"] {
                font-size: 14px;
                font-weight: bold;
                color: #3F51B5;
            }
            QLabel[labelType="criterionDescription"] {
                color: #757575;
                font-style: italic;
                margin-bottom: 8px;
            }
            QGroupBox {
                margin-top: 16px;
            }
            QCheckBox {
                padding: 4px;
                border-radius: 4px;
            }
            QCheckBox:hover {
                background-color: #F5F5F5;
            }
            QTextEdit {
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 4px;
            }
            QTextEdit:focus {
                border: 2px solid #3F51B5;
            }
        """)

        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface for this criterion."""
        layout = QVBoxLayout()

        # Criterion title with styled font
        title_label = QLabel(self.criterion_data.get("title", "Untitled Criterion"))
        title_label.setProperty("labelType", "criterionTitle")
        layout.addWidget(title_label)

        # Description
        description = self.criterion_data.get("description", "")
        if description:
            desc_label = QLabel(description)
            desc_label.setProperty("labelType", "criterionDescription")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # Points controls in a styled container
        points_container = QFrame()
        points_container.setStyleSheet("""
            QFrame {
                background-color: #F5F5F5;
                border-radius: 4px;
                border: none;
                margin: 0px;
                padding: 8px;
            }
        """)
        points_layout = QHBoxLayout(points_container)
        points_layout.setContentsMargins(8, 8, 8, 8)

        points_label = QLabel("Points:")
        points_label.setStyleSheet("font-weight: bold;")
        points_layout.addWidget(points_label)

        self.points_spinbox = QDoubleSpinBox()
        self.points_spinbox.setDecimals(1)  # Allow one decimal place
        self.points_spinbox.setSingleStep(0.5)  # Set step to 0.5 points
        self.max_points = self.criterion_data.get("points", 10)
        self.points_spinbox.setRange(0, self.max_points)
        self.points_spinbox.setToolTip(f"Maximum points: {self.max_points}")
        self.points_spinbox.valueChanged.connect(self._on_points_value_changed)
        self.points_spinbox.editingFinished.connect(self._on_points_editing_finished)
        self.points_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: white;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                padding: 4px;
                min-width: 60px;
            }
            QSpinBox:focus {
                border: 2px solid #3F51B5;
            }
        """)
        points_layout.addWidget(self.points_spinbox)

        points_layout.addWidget(QLabel(f"/ {self.max_points}"))
        points_layout.addStretch()
        layout.addWidget(points_container)

        # Achievement levels if present
        levels = self.criterion_data.get("levels", [])
        if levels:
            levels_group = QGroupBox("Achievement Levels")
            levels_group.setStyleSheet("""
                QGroupBox {
                    font-weight: bold;
                    border: 1px solid #BDBDBD;
                    border-radius: 4px;
                    margin-top: 16px;
                    padding-top: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                }
            """)
            levels_layout = QVBoxLayout()

            self.level_checkboxes = []
            for level in levels:
                level_container = QFrame()
                level_container.setStyleSheet("""
                    QFrame {
                        border: none;
                        border-radius: 0px;
                        margin: 0px;
                        padding: 0px;
                    }
                    QFrame:hover {
                        background-color: #F5F5F5;
                    }
                """)
                level_layout = QVBoxLayout(level_container)
                level_layout.setContentsMargins(0, 4, 0, 4)

                # Checkbox and points in a horizontal layout
                checkbox_layout = QHBoxLayout()

                level_checkbox = QCheckBox(f"{level.get('title')} ({level.get('points')} pts)")
                level_checkbox.setStyleSheet("""
                    QCheckBox {
                        font-weight: bold;
                    }
                """)

                level_description = level.get("description", "")
                if level_description:
                    level_checkbox.setToolTip(level_description)

                level_checkbox.clicked.connect(self.update_points_from_level)
                self.level_checkboxes.append((level_checkbox, level.get("points", 0)))
                checkbox_layout.addWidget(level_checkbox)

                # Show points on the right
                # points_label = QLabel(f"{level.get('points')} pts")
                # points_label.setStyleSheet("color: #757575;")
                # checkbox_layout.addWidget(points_label)

                level_layout.addLayout(checkbox_layout)

                # Show description if available
                if level_description:
                    desc_label = QLabel(level_description)
                    desc_label.setWordWrap(True)
                    desc_label.setStyleSheet("color: #757575; padding-left: 24px; font-size: 12px;")
                    level_layout.addWidget(desc_label)

                levels_layout.addWidget(level_container)

            levels_group.setLayout(levels_layout)
            layout.addWidget(levels_group)

        # Comments area with improved styling
        # layout.addWidget(QLabel("Comments:"))
        # self.comments_edit = QTextEdit()
        # self.comments_edit.setPlaceholderText("Add your feedback here...")
        # self.comments_edit.setMinimumHeight(80)  # Set minimum height instead
        # # Set size policy to allow vertical expansion
        # size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # self.comments_edit.setSizePolicy(size_policy)
        # layout.addWidget(self.comments_edit)
        comment_label = QLabel("Comments (supports Markdown and LaTeX math with $...$ or $$...$$):")
        layout.addWidget(comment_label)
        self.comments_edit = MarkdownMathEditor()
        self.comments_edit.setMinimumHeight(150)  # Make it a bit taller to accommodate the preview
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.comments_edit.setSizePolicy(size_policy)
        layout.addWidget(self.comments_edit)

        self.setLayout(layout)

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

    def _on_points_editing_finished(self):
        """
        Treat an explicitly entered unchanged value (especially 0) as graded.

        QDoubleSpinBox.valueChanged is not emitted when the user confirms the
        value already displayed.  editingFinished lets a deliberate zero be
        distinguished from an untouched default zero.
        """
        if self._loading_data:
            return
        was_graded = self.is_graded
        self._mark_graded()
        if not was_graded:
            self.points_changed.emit()

    def update_points_from_level(self):
        """Update the points value based on the selected achievement level."""
        sender = self.sender()

        # Uncheck other boxes
        for checkbox, points in self.level_checkboxes:
            if checkbox != sender and checkbox.isChecked():
                checkbox.setChecked(False)

        # Update points if a box is checked.  If the selected level has the
        # same numeric value already displayed, valueChanged will not fire, so
        # explicitly mark/emit in that one case.
        for checkbox, points in self.level_checkboxes:
            if checkbox.isChecked():
                previous_value = self.points_spinbox.value()
                self.points_spinbox.setValue(points)
                if previous_value == self.points_spinbox.value():
                    self._mark_graded()
                    self.points_changed.emit()
                return

    def get_data(self):
        """
        Get the current state of this criterion.

        Returns:
            dict: Dictionary containing the criterion data
        """
        selected_level = None
        for checkbox, _ in getattr(self, 'level_checkboxes', []):
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
        """
        Set the widget's data from a criterion data dictionary.

        Args:
            criterion_data (dict): Dictionary containing the criterion data
        """
        self._loading_data = True
        try:
            # Set points.  Legacy/partial data may use None; the visual control
            # still displays zero while explicit grading state remains separate.
            points_awarded = criterion_data.get("points_awarded", 0)
            self.points_spinbox.setValue(0 if points_awarded is None else points_awarded)

            # Set comments
            self.comments_edit.set_text(criterion_data.get("comments", ""))

            # Reset and restore level selection if applicable.
            for checkbox, _ in getattr(self, 'level_checkboxes', []):
                checkbox.setChecked(False)

            selected_level = criterion_data.get("selected_level", "")
            if selected_level and hasattr(self, 'level_checkboxes'):
                for checkbox, _ in self.level_checkboxes:
                    if checkbox.text().split(" (")[0] == selected_level:
                        checkbox.setChecked(True)
                        break

            # v2.1 explicit status is authoritative.  Legacy assessments fall
            # back to the design rule: points_awarded is not None => graded.
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
        """Reset the widget to its initial state."""
        self._loading_data = True
        try:
            self.points_spinbox.setValue(0)
            self.comments_edit.clear()

            # Clear checkboxes
            for checkbox, _ in getattr(self, 'level_checkboxes', []):
                checkbox.setChecked(False)

            self.is_graded = False
            self.graded_at = None
            self.graded_by = None
        finally:
            self._loading_data = False

    def get_awarded_points(self):
        """Get the number of points awarded for this criterion."""
        return self.points_spinbox.value()

    def get_possible_points(self):
        """Get the maximum possible points for this criterion."""
        return self.criterion_data.get("points", 0)
