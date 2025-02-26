"""
Criterion Widget for Rubric Grading Tool.

This module defines the UI component that represents a single criterion in the rubric.
"""

from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                             QSpinBox, QCheckBox, QGroupBox, QTextEdit)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, pyqtSignal


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
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface for this criterion."""
        layout = QVBoxLayout()

        # Criterion title with bold font
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)

        title_label = QLabel(self.criterion_data.get("title", "Untitled Criterion"))
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Description
        description = self.criterion_data.get("description", "")
        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # Points controls
        points_layout = QHBoxLayout()
        points_layout.addWidget(QLabel("Points:"))

        self.points_spinbox = QSpinBox()
        self.max_points = self.criterion_data.get("points", 10)
        self.points_spinbox.setRange(0, self.max_points)
        self.points_spinbox.setToolTip(f"Maximum points: {self.max_points}")
        self.points_spinbox.valueChanged.connect(self.points_changed)
        points_layout.addWidget(self.points_spinbox)

        points_layout.addWidget(QLabel(f"/ {self.max_points}"))
        points_layout.addStretch()
        layout.addLayout(points_layout)

        # Achievement levels if present
        levels = self.criterion_data.get("levels", [])
        if levels:
            levels_group = QGroupBox("Achievement Levels")
            levels_layout = QVBoxLayout()

            self.level_checkboxes = []
            for level in levels:
                level_checkbox = QCheckBox(f"{level.get('title')} ({level.get('points')} pts)")
                level_checkbox.setToolTip(level.get("description", ""))
                level_checkbox.clicked.connect(self.update_points_from_level)
                self.level_checkboxes.append((level_checkbox, level.get("points", 0)))
                levels_layout.addWidget(level_checkbox)

            levels_group.setLayout(levels_layout)
            layout.addWidget(levels_group)

        # Comments area
        layout.addWidget(QLabel("Comments:"))
        self.comments_edit = QTextEdit()
        layout.addWidget(self.comments_edit)

        self.setLayout(layout)

    def update_points_from_level(self):
        """Update the points value based on the selected achievement level."""
        sender = self.sender()

        # Uncheck other boxes
        for checkbox, points in self.level_checkboxes:
            if checkbox != sender and checkbox.isChecked():
                checkbox.setChecked(False)

        # Update points if a box is checked
        for checkbox, points in self.level_checkboxes:
            if checkbox.isChecked():
                self.points_spinbox.setValue(points)
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

        return {
            "title": self.criterion_data.get("title", ""),
            "points_awarded": self.points_spinbox.value(),
            "points_possible": self.criterion_data.get("points", 0),
            "selected_level": selected_level,
            "comments": self.comments_edit.toPlainText()
        }

    def set_data(self, criterion_data):
        """
        Set the widget's data from a criterion data dictionary.

        Args:
            criterion_data (dict): Dictionary containing the criterion data
        """
        # Set points
        self.points_spinbox.setValue(criterion_data.get("points_awarded", 0))

        # Set comments
        self.comments_edit.setPlainText(criterion_data.get("comments", ""))

        # Set level if applicable
        selected_level = criterion_data.get("selected_level", "")
        if selected_level and hasattr(self, 'level_checkboxes'):
            for checkbox, _ in self.level_checkboxes:
                if checkbox.text().split(" (")[0] == selected_level:
                    checkbox.setChecked(True)
                    break

    def reset(self):
        """Reset the widget to its initial state."""
        self.points_spinbox.setValue(0)
        self.comments_edit.clear()

        # Clear checkboxes
        for checkbox, _ in getattr(self, 'level_checkboxes', []):
            checkbox.setChecked(False)

    def get_awarded_points(self):
        """Get the number of points awarded for this criterion."""
        return self.points_spinbox.value()

    def get_possible_points(self):
        """Get the maximum possible points for this criterion."""
        return self.criterion_data.get("points", 0)