"""
Additional widgets for the Rubric Grading Tool.

This module contains auxiliary UI components used in the application.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QSplitter, QComboBox)
from PyQt5.QtCore import Qt, pyqtSignal


class StatusBar(QWidget):
    """Custom status bar widget with additional functionality."""

    def __init__(self, parent=None):
        """Initialize the status bar widget."""
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 5, 0)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Version or other info could go here
        version_label = QLabel("v1.0.0")
        layout.addWidget(version_label)

    def set_status(self, message):
        """Set the status message."""
        self.status_label.setText(message)


class RubricInfoWidget(QFrame):
    """Widget displaying information about the loaded rubric."""

    def __init__(self, parent=None):
        """Initialize the widget."""
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        self.title_label = QLabel("No rubric loaded")
        layout.addWidget(self.title_label)

        self.criteria_count_label = QLabel("Criteria: 0")
        layout.addWidget(self.criteria_count_label)

        self.points_label = QLabel("Total points: 0")
        layout.addWidget(self.points_label)

    def update_info(self, rubric_data):
        """Update the widget with information from the rubric data."""
        if not rubric_data:
            self.reset()
            return

        self.title_label.setText(rubric_data.get("title", "Untitled Rubric"))

        criteria_count = len(rubric_data.get("criteria", []))
        self.criteria_count_label.setText(f"Criteria: {criteria_count}")

        total_points = sum(c.get("points", 0) for c in rubric_data.get("criteria", []))
        self.points_label.setText(f"Total points: {total_points}")

    def reset(self):
        """Reset the widget to its initial state."""
        self.title_label.setText("No rubric loaded")
        self.criteria_count_label.setText("Criteria: 0")
        self.points_label.setText("Total points: 0")


class GradeScaleWidget(QWidget):
    """Widget for displaying and selecting grade scales."""

    scale_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        """Initialize the widget."""
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Grade Scale:"))

        self.scale_combo = QComboBox()
        self.scale_combo.addItems([
            "Default (A-F)",
            "Points Only",
            "Percentage Only",
            "Pass/Fail"
        ])
        self.scale_combo.currentTextChanged.connect(self.scale_changed)
        header_layout.addWidget(self.scale_combo)

        layout.addLayout(header_layout)