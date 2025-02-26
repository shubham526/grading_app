"""
Rubric Grading Tool - Main Application Window

This module contains the main application window and core grading functionality.
"""

import os
import json
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QScrollArea,
                             QLineEdit, QMessageBox)
from PyQt5.QtCore import Qt

from widgets.criterion_widget import CriterionWidget
from utils.rubric_parser import parse_rubric_file
from utils.pdf_generator import generate_assessment_pdf


class RubricGrader(QMainWindow):
    """Main application window for the Rubric Grading Tool."""

    def __init__(self):
        """Initialize the application window and UI components."""
        super().__init__()
        self.rubric_data = None
        self.criterion_widgets = []
        self.student_name = ""
        self.assignment_name = ""
        self.init_ui()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Rubric Grading Tool")
        self.setMinimumSize(800, 600)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header controls
        header_layout = QHBoxLayout()

        # Load rubric button
        self.load_btn = QPushButton("Load Rubric")
        self.load_btn.clicked.connect(self.load_rubric)
        header_layout.addWidget(self.load_btn)

        # Student name field
        header_layout.addWidget(QLabel("Student:"))
        self.student_name_edit = QLineEdit()
        header_layout.addWidget(self.student_name_edit)

        # Assignment name field
        header_layout.addWidget(QLabel("Assignment:"))
        self.assignment_name_edit = QLineEdit()
        header_layout.addWidget(self.assignment_name_edit)

        # Export button
        self.export_btn = QPushButton("Export to PDF")
        self.export_btn.clicked.connect(self.export_to_pdf)
        self.export_btn.setEnabled(False)
        header_layout.addWidget(self.export_btn)

        main_layout.addLayout(header_layout)

        # Status label
        self.status_label = QLabel("Please load a rubric to begin.")
        main_layout.addWidget(self.status_label)

        # Scroll area for criteria
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.criteria_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        # Bottom controls
        bottom_layout = QHBoxLayout()

        # Total points display
        self.total_label = QLabel("Total: 0 / 0 points")
        bottom_layout.addWidget(self.total_label)
        bottom_layout.addStretch()

        # Clear button
        clear_btn = QPushButton("Clear Form")
        clear_btn.clicked.connect(self.clear_form)
        bottom_layout.addWidget(clear_btn)

        # Save button
        save_btn = QPushButton("Save Assessment")
        save_btn.clicked.connect(self.save_assessment)
        bottom_layout.addWidget(save_btn)

        # Load assessment button
        load_assessment_btn = QPushButton("Load Assessment")
        load_assessment_btn.clicked.connect(self.load_assessment)
        bottom_layout.addWidget(load_assessment_btn)

        main_layout.addLayout(bottom_layout)

    def load_rubric(self):
        """Load a rubric from a file (JSON or CSV)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Rubric File",
            "",
            "Rubric Files (*.json *.csv);;JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )

        if not file_path:
            return

        try:
            self.rubric_data = parse_rubric_file(file_path)
            self.setup_rubric_ui()
            self.export_btn.setEnabled(True)
            self.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")

    def setup_rubric_ui(self):
        """Set up the UI based on the loaded rubric."""
        # Clear existing criteria
        self.clear_layout(self.criteria_layout)
        self.criterion_widgets = []

        if not self.rubric_data or "criteria" not in self.rubric_data:
            self.status_label.setText("Invalid rubric format.")
            return

        # Set assignment name if available
        if "title" in self.rubric_data and not self.assignment_name_edit.text():
            self.assignment_name_edit.setText(self.rubric_data["title"])

        # Create widgets for each criterion
        for criterion in self.rubric_data["criteria"]:
            criterion_widget = CriterionWidget(criterion)
            # Connect the signal to update total points when a criterion changes
            criterion_widget.points_changed.connect(self.update_total_points)
            self.criteria_layout.addWidget(criterion_widget)
            self.criterion_widgets.append(criterion_widget)

        # Add stretch to push everything up
        self.criteria_layout.addStretch()

        # Update total points
        self.update_total_points()

    def clear_layout(self, layout):
        """Clear all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()

            if widget:
                widget.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def update_total_points(self):
        """Update the total points display."""
        if not self.criterion_widgets:
            self.total_label.setText("Total: 0 / 0 points")
            return

        awarded = sum(widget.get_awarded_points() for widget in self.criterion_widgets)
        possible = sum(widget.get_possible_points() for widget in self.criterion_widgets)

        self.total_label.setText(f"Total: {awarded} / {possible} points")

        # Update color based on score
        if possible > 0:
            percentage = (awarded / possible) * 100
            if percentage >= 90:
                self.total_label.setStyleSheet("color: green; font-weight: bold;")
            elif percentage >= 70:
                self.total_label.setStyleSheet("color: #CC7700; font-weight: bold;")
            else:
                self.total_label.setStyleSheet("color: red; font-weight: bold;")

    def clear_form(self):
        """Clear all entered data."""
        self.student_name_edit.clear()

        for widget in self.criterion_widgets:
            widget.reset()

        self.update_total_points()

    def get_assessment_data(self):
        """Gather all the assessment data."""
        if not self.rubric_data or not self.criterion_widgets:
            return None

        criteria_data = [widget.get_data() for widget in self.criterion_widgets]

        total_awarded = sum(c["points_awarded"] for c in criteria_data)
        total_possible = sum(c["points_possible"] for c in criteria_data)

        return {
            "student_name": self.student_name_edit.text(),
            "assignment_name": self.assignment_name_edit.text(),
            "criteria": criteria_data,
            "total_awarded": total_awarded,
            "total_possible": total_possible,
            "percentage": (total_awarded / total_possible * 100) if total_possible > 0 else 0
        }

    def save_assessment(self):
        """Save the current assessment to a JSON file."""
        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to save.")
            return

        assessment_data = self.get_assessment_data()
        if not assessment_data:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Assessment",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        # Ensure .json extension
        if not file_path.lower().endswith('.json'):
            file_path += '.json'

        try:
            with open(file_path, 'w') as file:
                json.dump(assessment_data, file, indent=2)

            QMessageBox.information(self, "Success", "Assessment saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save assessment: {str(e)}")

    def load_assessment(self):
        """Load a previously saved assessment."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Assessment File",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as file:
                assessment_data = json.load(file)

            # Check if we have a rubric loaded
            if not self.criterion_widgets:
                QMessageBox.warning(self, "Warning", "Please load a rubric first.")
                return

            # Fill in the form
            self.student_name_edit.setText(assessment_data.get("student_name", ""))
            self.assignment_name_edit.setText(assessment_data.get("assignment_name", ""))

            # Fill in criteria data if it matches the current rubric
            criteria_data = assessment_data.get("criteria", [])
            if len(criteria_data) != len(self.criterion_widgets):
                QMessageBox.warning(
                    self,
                    "Warning",
                    "The assessment criteria don't match the current rubric."
                )
            else:
                for i, criterion_data in enumerate(criteria_data):
                    widget = self.criterion_widgets[i]
                    widget.set_data(criterion_data)

            self.update_total_points()
            QMessageBox.information(self, "Success", "Assessment loaded successfully.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load assessment: {str(e)}")

    def export_to_pdf(self):
        """Export the assessment to a PDF file."""
        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to export.")
            return

        assessment_data = self.get_assessment_data()
        if not assessment_data:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to PDF",
            "",
            "PDF Files (*.pdf);;All Files (*)"
        )

        if not file_path:
            return

        # Ensure .pdf extension
        if not file_path.lower().endswith('.pdf'):
            file_path += '.pdf'

        try:
            generate_assessment_pdf(file_path, assessment_data)
            QMessageBox.information(self, "Success", "Assessment exported to PDF successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export to PDF: {str(e)}")