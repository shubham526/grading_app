import os
import json
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QScrollArea,
                             QLineEdit, QMessageBox, QGroupBox, QCheckBox,
                             QSpinBox, QDialog, QFormLayout)
from PyQt5.QtCore import Qt

from widgets.criterion_widget import CriterionWidget
from utils.rubric_parser import parse_rubric_file
from utils.pdf_generator import generate_assessment_pdf


class GradingConfigDialog(QDialog):
    """Dialog for configuring grading options."""

    def __init__(self, total_questions, parent=None):
        """Initialize the dialog with the number of available questions."""
        super().__init__(parent)
        self.total_questions = total_questions
        self.init_ui()

    def init_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Grading Configuration")
        layout = QFormLayout()

        # Questions to grade
        self.questions_to_grade = QSpinBox()
        self.questions_to_grade.setMinimum(1)
        self.questions_to_grade.setMaximum(self.total_questions)
        self.questions_to_grade.setValue(self.total_questions)  # Default to all questions
        layout.addRow("Number of questions to grade:", self.questions_to_grade)

        # Points per question
        self.points_per_question = QSpinBox()
        self.points_per_question.setMinimum(1)
        self.points_per_question.setMaximum(100)
        self.points_per_question.setValue(10)  # Default to 10 points
        layout.addRow("Points per main question:", self.points_per_question)

        # Calculate total or use fixed total
        self.use_fixed_total = QCheckBox("Use fixed total points")
        self.use_fixed_total.setChecked(False)
        layout.addRow(self.use_fixed_total)

        # Fixed total points
        self.fixed_total = QSpinBox()
        self.fixed_total.setMinimum(1)
        self.fixed_total.setMaximum(1000)
        self.fixed_total.setValue(self.questions_to_grade.value() * self.points_per_question.value())
        layout.addRow("Fixed total points:", self.fixed_total)

        # Update fixed total when other values change
        self.questions_to_grade.valueChanged.connect(self.update_fixed_total)
        self.points_per_question.valueChanged.connect(self.update_fixed_total)

        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addRow(button_layout)

        self.setLayout(layout)

    def update_fixed_total(self):
        """Update the fixed total based on questions and points per question."""
        self.fixed_total.setValue(self.questions_to_grade.value() * self.points_per_question.value())

    def get_config(self):
        """Return the configuration as a dictionary."""
        return {
            "questions_to_grade": self.questions_to_grade.value(),
            "points_per_question": self.points_per_question.value(),
            "use_fixed_total": self.use_fixed_total.isChecked(),
            "fixed_total": self.fixed_total.value()
        }


class RubricGrader(QMainWindow):
    """Main application window for the Rubric Grading Tool."""

    def __init__(self):
        """Initialize the application window and UI components."""
        super().__init__()
        self.rubric_data = None
        self.criterion_widgets = []
        self.question_groups = {}  # Dictionary to group widgets by main question
        self.student_name = ""
        self.assignment_name = ""

        # Default grading configuration
        self.grading_config = {
            "questions_to_grade": 5,  # Default to 5 questions
            "points_per_question": 10,  # Default to 10 points per question
            "use_fixed_total": True,   # Use fixed total by default
            "fixed_total": 50          # Default to 50 points total
        }

        self.init_ui()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Flexible Rubric Grading Tool")
        self.setMinimumSize(900, 700)

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

        # Grading configuration button
        self.config_btn = QPushButton("Grading Config")
        self.config_btn.clicked.connect(self.show_grading_config)
        self.config_btn.setEnabled(False)
        header_layout.addWidget(self.config_btn)

        # Export button
        self.export_btn = QPushButton("Export to PDF")
        self.export_btn.clicked.connect(self.export_to_pdf)
        self.export_btn.setEnabled(False)
        header_layout.addWidget(self.export_btn)

        main_layout.addLayout(header_layout)

        # Status label
        self.status_label = QLabel("Please load a rubric to begin.")
        main_layout.addWidget(self.status_label)

        # Grading configuration info
        self.config_info = QLabel()
        self.update_config_info()
        main_layout.addWidget(self.config_info)

        # Questions selection group
        self.question_selection_group = QGroupBox("Questions to Grade")
        self.question_selection_layout = QHBoxLayout()
        self.question_selection_group.setLayout(self.question_selection_layout)
        self.question_selection_group.setVisible(False)
        main_layout.addWidget(self.question_selection_group)

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
        self.total_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
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

    def update_config_info(self):
        """Update the displayed grading configuration info."""
        config = self.grading_config
        if config["use_fixed_total"]:
            info = (f"Grading {config['questions_to_grade']} of {len(self.question_groups) if self.question_groups else '?'} "
                   f"questions for a total of {config['fixed_total']} points")
        else:
            total = config['questions_to_grade'] * config['points_per_question']
            info = (f"Grading {config['questions_to_grade']} of {len(self.question_groups) if self.question_groups else '?'} "
                   f"questions at {config['points_per_question']} points each (Total: {total} points)")

        self.config_info.setText(info)
        self.config_info.setStyleSheet("font-weight: bold; color: #0066CC;")

    def show_grading_config(self):
        """Show dialog to configure grading options."""
        if not self.question_groups:
            QMessageBox.warning(self, "Warning", "Please load a rubric first.")
            return

        dialog = GradingConfigDialog(len(self.question_groups), self)

        # Set current values
        dialog.questions_to_grade.setValue(self.grading_config["questions_to_grade"])
        dialog.points_per_question.setValue(self.grading_config["points_per_question"])
        dialog.use_fixed_total.setChecked(self.grading_config["use_fixed_total"])
        dialog.fixed_total.setValue(self.grading_config["fixed_total"])

        if dialog.exec_() == QDialog.Accepted:
            self.grading_config = dialog.get_config()
            self.update_config_info()

            # Update max selectable questions
            max_select = self.grading_config["questions_to_grade"]
            self.update_question_selection(max_select)

            # Update total points display
            self.update_total_points()

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
            self.config_btn.setEnabled(True)
            self.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")

            # Show grading config dialog for initial setup
            self.show_grading_config()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")

    def setup_rubric_ui(self):
        """Set up the UI based on the loaded rubric."""
        # Clear existing criteria
        self.clear_layout(self.criteria_layout)
        self.criterion_widgets = []
        self.question_groups = {}

        if not self.rubric_data or "criteria" not in self.rubric_data:
            self.status_label.setText("Invalid rubric format.")
            return

        # Set assignment name if available
        if "title" in self.rubric_data and not self.assignment_name_edit.text():
            self.assignment_name_edit.setText(self.rubric_data["title"])

        # Extract main questions from criteria titles
        main_questions = self.extract_main_questions()

        # Create widgets for each criterion
        for criterion in self.rubric_data["criteria"]:
            criterion_widget = CriterionWidget(criterion)
            # Connect the signal to update total points when a criterion changes
            criterion_widget.points_changed.connect(self.update_total_points)
            self.criteria_layout.addWidget(criterion_widget)
            self.criterion_widgets.append(criterion_widget)

            # Group by main question
            title = criterion["title"]
            main_question = self.extract_question_number(title)

            if main_question:
                if main_question not in self.question_groups:
                    self.question_groups[main_question] = []

                self.question_groups[main_question].append(criterion_widget)

        # Set up question selection UI
        self.setup_question_selection()

        # Add stretch to push everything up
        self.criteria_layout.addStretch()

        # Update total points
        self.update_total_points()

        # Update config info with question count
        self.update_config_info()

    def extract_main_questions(self):
        """Extract and return list of main question identifiers from criteria titles."""
        main_questions = []

        for criterion in self.rubric_data["criteria"]:
            title = criterion["title"]
            main_question = self.extract_question_number(title)

            if main_question and main_question not in main_questions:
                main_questions.append(main_question)

        return sorted(main_questions)

    def extract_question_number(self, title):
        """Extract the main question number from a criterion title."""
        # Handle various formats like "Question 1a", "Question 1: Title", etc.
        if not title.startswith("Question "):
            return None

        # Remove "Question " prefix
        question_id = title.split(":")[0].replace("Question ", "").strip()

        # Extract main number (1 from "1a", "1b", etc.)
        if len(question_id) > 1 and question_id[1].isalpha():
            return question_id[0]

        # Handle other formats
        for i, char in enumerate(question_id):
            if not char.isdigit():
                if i > 0:
                    return question_id[:i]
                break

        return question_id

    def setup_question_selection(self):
        """Set up checkboxes for selecting which questions to grade."""
        # Clear existing checkboxes
        self.clear_layout(self.question_selection_layout)

        # If we found multiple main questions, create checkboxes for selection
        if len(self.question_groups) > 1:
            self.question_selection_group.setVisible(True)
            self.question_checkboxes = {}

            # Helper text based on grading config
            helper_text = f"Select {self.grading_config['questions_to_grade']} questions the student attempted:"
            helper_label = QLabel(helper_text)
            helper_label.setStyleSheet("font-weight: bold;")
            self.question_selection_layout.addWidget(helper_label)

            for q in sorted(self.question_groups.keys()):
                checkbox = QCheckBox(f"Q{q}")
                checkbox.setChecked(True)  # Default to checked
                checkbox.stateChanged.connect(self.update_total_points)
                self.question_selection_layout.addWidget(checkbox)
                self.question_checkboxes[q] = checkbox

            self.update_question_selection(self.grading_config["questions_to_grade"])
        else:
            self.question_selection_group.setVisible(False)

    def update_question_selection(self, max_selectable):
        """Update question selection based on maximum selectable questions."""
        if not hasattr(self, 'question_checkboxes') or not self.question_checkboxes:
            return

        # Count checked boxes
        checked = sum(1 for cb in self.question_checkboxes.values() if cb.isChecked())

        # If more checked than allowed, uncheck some
        if checked > max_selectable:
            for i, (q, cb) in enumerate(sorted(self.question_checkboxes.items())):
                if cb.isChecked() and i >= max_selectable:
                    cb.setChecked(False)

        # Update selection text
        helper_text = f"Select {max_selectable} questions the student attempted:"
        self.question_selection_layout.itemAt(0).widget().setText(helper_text)

    def clear_layout(self, layout):
        """Clear all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()

            if widget:
                widget.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def get_selected_questions(self):
        """Get the list of selected question numbers."""
        # If no checkboxes were created, select all questions
        if not hasattr(self, 'question_checkboxes') or not self.question_checkboxes:
            return list(self.question_groups.keys())

        # Return the list of checked question numbers
        return [q for q, cb in self.question_checkboxes.items() if cb.isChecked()]

    def update_total_points(self):
        """Update the total points display based on selected questions."""
        if not self.criterion_widgets:
            self.total_label.setText("Total: 0 / 0 points")
            return

        selected_questions = self.get_selected_questions()

        # Count how many selected questions we have
        num_selected = len(selected_questions)
        questions_to_grade = self.grading_config["questions_to_grade"]

        if num_selected < questions_to_grade:
            # If fewer than required questions selected, show warning
            self.total_label.setText(f"Please select {questions_to_grade} questions " +
                                   f"(currently {num_selected} selected)")
            self.total_label.setStyleSheet("color: red; font-weight: bold; font-size: 14pt;")
            return
        elif num_selected > questions_to_grade:
            # If more than required questions selected, show warning
            self.total_label.setText(f"Please select only {questions_to_grade} questions " +
                                   f"(currently {num_selected} selected)")
            self.total_label.setStyleSheet("color: red; font-weight: bold; font-size: 14pt;")
            return

        # Calculate points for each selected question
        question_points = {}

        for q in selected_questions:
            if q in self.question_groups:
                q_widgets = self.question_groups[q]
                question_awarded = sum(widget.get_awarded_points() for widget in q_widgets)
                question_possible = sum(widget.get_possible_points() for widget in q_widgets)
                question_points[q] = (question_awarded, question_possible)

        # Calculate total points from the selected questions
        earned_total = sum(points[0] for points in question_points.values())

        # Determine max possible points based on configuration
        if self.grading_config["use_fixed_total"]:
            # Use the fixed total
            possible_total = self.grading_config["fixed_total"]
        else:
            # Calculate from selected questions
            possible_total = sum(points[1] for points in question_points.values())

        self.total_label.setText(f"Total: {earned_total} / {possible_total} points")

        # Update color based on score
        if possible_total > 0:
            percentage = (earned_total / possible_total) * 100
            if percentage >= 90:
                self.total_label.setStyleSheet("color: green; font-weight: bold; font-size: 14pt;")
            elif percentage >= 70:
                self.total_label.setStyleSheet("color: #CC7700; font-weight: bold; font-size: 14pt;")
            else:
                self.total_label.setStyleSheet("color: red; font-weight: bold; font-size: 14pt;")

    def clear_form(self):
        """Clear all entered data."""
        self.student_name_edit.clear()

        for widget in self.criterion_widgets:
            widget.reset()

        # Reset checkboxes if they exist
        if hasattr(self, 'question_checkboxes'):
            # Check first N checkboxes where N is questions_to_grade
            questions_to_grade = self.grading_config["questions_to_grade"]
            for i, (q, cb) in enumerate(sorted(self.question_checkboxes.items())):
                cb.setChecked(i < questions_to_grade)

        self.update_total_points()

    def get_assessment_data(self):
        """Gather all the assessment data."""
        if not self.rubric_data or not self.criterion_widgets:
            return None

        selected_questions = self.get_selected_questions()
        questions_to_grade = self.grading_config["questions_to_grade"]

        # Verify we have exactly the required number of selected questions
        if len(selected_questions) != questions_to_grade:
            QMessageBox.warning(
                self,
                "Warning",
                f"Please select exactly {questions_to_grade} questions to grade."
            )
            return None

        # Get data for all criteria, but mark which ones are in selected questions
        criteria_data = []
        for widget in self.criterion_widgets:
            data = widget.get_data()

            # Determine if this criterion is part of a selected question
            title = data["title"]
            is_selected = False

            main_question = self.extract_question_number(title)
            if main_question:
                is_selected = main_question in selected_questions

            data["selected"] = is_selected
            criteria_data.append(data)

        # Calculate totals based on configuration
        selected_criteria = [c for c in criteria_data if c["selected"]]
        earned_total = sum(c["points_awarded"] for c in selected_criteria)

        if self.grading_config["use_fixed_total"]:
            possible_total = self.grading_config["fixed_total"]
        else:
            possible_total = sum(c["points_possible"] for c in selected_criteria)

        return {
            "student_name": self.student_name_edit.text(),
            "assignment_name": self.assignment_name_edit.text(),
            "criteria": criteria_data,
            "selected_questions": selected_questions,
            "grading_config": self.grading_config,
            "total_awarded": earned_total,
            "total_possible": possible_total,
            "percentage": (earned_total / possible_total * 100) if possible_total > 0 else 0
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

            # Load grading configuration if present
            if "grading_config" in assessment_data:
                self.grading_config = assessment_data["grading_config"]
                self.update_config_info()

            # Update question selection if it exists
            selected_questions = assessment_data.get("selected_questions", [])
            if hasattr(self, 'question_checkboxes') and selected_questions:
                for q, checkbox in self.question_checkboxes.items():
                    checkbox.setChecked(q in selected_questions)

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