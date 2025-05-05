"""
Criterion Widget for Rubric Grading Tool.

This module defines the UI component that represents a single criterion in the rubric.
"""

from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                           QSpinBox, QCheckBox, QGroupBox, QTextEdit, QSizePolicy)
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

        self.points_spinbox = QSpinBox()
        self.max_points = self.criterion_data.get("points", 10)
        self.points_spinbox.setRange(0, self.max_points)
        self.points_spinbox.setToolTip(f"Maximum points: {self.max_points}")
        self.points_spinbox.valueChanged.connect(self.points_changed)
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
        layout.addWidget(QLabel("Comments:"))
        self.comments_edit = QTextEdit()
        self.comments_edit.setPlaceholderText("Add your feedback here...")
        self.comments_edit.setMinimumHeight(80)  # Set minimum height instead
        # Set size policy to allow vertical expansion
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.comments_edit.setSizePolicy(size_policy)
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