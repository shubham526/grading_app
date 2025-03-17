import os
import json
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QScrollArea,
                             QLineEdit, QMessageBox, QGroupBox, QCheckBox,
                             QSpinBox, QDialog, QFormLayout, QComboBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

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

        # Grading mode selection
        self.grading_mode = QComboBox()
        self.grading_mode.addItem("Grade selected questions only", "selected")
        self.grading_mode.addItem("Grade all questions, use best scores", "best_scores")
        layout.addRow("Grading mode:", self.grading_mode)

        # Questions to count in final score
        self.questions_to_count = QSpinBox()
        self.questions_to_count.setMinimum(1)
        self.questions_to_count.setMaximum(self.total_questions)
        self.questions_to_count.setValue(min(5, self.total_questions))  # Default to 5 or max
        layout.addRow("Questions to count in final score:", self.questions_to_count)

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
        self.fixed_total.setValue(self.questions_to_count.value() * self.points_per_question.value())
        layout.addRow("Fixed total points:", self.fixed_total)

        # Update fixed total when other values change
        self.questions_to_count.valueChanged.connect(self.update_fixed_total)
        self.points_per_question.valueChanged.connect(self.update_fixed_total)

        # Information label
        info_text = ("When using 'best scores' mode, you can grade all questions\n"
                     "the student attempted, and the system will automatically\n"
                     "use the highest-scoring questions for the final total.")
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #0066CC; font-style: italic;")
        layout.addRow(info_label)

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
        self.fixed_total.setValue(self.questions_to_count.value() * self.points_per_question.value())

    def get_config(self):
        """Return the configuration as a dictionary."""
        return {
            "grading_mode": self.grading_mode.currentData(),
            "questions_to_count": self.questions_to_count.value(),
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
            "grading_mode": "best_scores",  # "selected" or "best_scores"
            "questions_to_count": 5,  # Number of questions to count in final score
            "points_per_question": 10,  # Default to 10 points per question
            "use_fixed_total": True,  # Use fixed total by default
            "fixed_total": 50  # Default to 50 points total
        }

        self.init_ui()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Advanced Rubric Grading Tool")
        self.setMinimumSize(1000, 700)

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
        self.config_info.setFont(QFont("Arial", 10, QFont.Bold))
        self.update_config_info()
        main_layout.addWidget(self.config_info)

        # Questions selection group
        self.question_selection_group = QGroupBox("Questions Attempted by Student")
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

        # Question summary group
        self.question_summary_group = QGroupBox("Question Scores Summary")
        self.question_summary_layout = QVBoxLayout()
        self.question_summary_group.setLayout(self.question_summary_layout)
        self.question_summary_group.setVisible(False)
        main_layout.addWidget(self.question_summary_group)

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
        if not self.grading_config:
            self.config_info.setText("")
            return

        config = self.grading_config
        total_questions = len(self.question_groups) if self.question_groups else "?"

        # Build info text based on grading mode
        if config["grading_mode"] == "best_scores":
            info = (f"Grading Mode: Using best {config['questions_to_count']} of {total_questions} "
                    f"questions for final score")
        else:
            info = (f"Grading Mode: Counting only {config['questions_to_count']} selected questions")

        # Add points information
        if config["use_fixed_total"]:
            info += f" | Total possible: {config['fixed_total']} points"
        else:
            total = config['questions_to_count'] * config['points_per_question']
            info += f" | {config['points_per_question']} points per question (Total: {total} points)"

        self.config_info.setText(info)
        self.config_info.setStyleSheet(
            "font-weight: bold; color: #0066CC; padding: 5px; background-color: #F0F8FF; border: 1px solid #AACCEE;")

    def show_grading_config(self):
        """Show dialog to configure grading options."""
        if not self.question_groups:
            QMessageBox.warning(self, "Warning", "Please load a rubric first.")
            return

        dialog = GradingConfigDialog(len(self.question_groups), self)

        # Set current values
        index = dialog.grading_mode.findData(self.grading_config["grading_mode"])
        if index >= 0:
            dialog.grading_mode.setCurrentIndex(index)

        dialog.questions_to_count.setValue(self.grading_config["questions_to_count"])
        dialog.points_per_question.setValue(self.grading_config["points_per_question"])
        dialog.use_fixed_total.setChecked(self.grading_config["use_fixed_total"])
        dialog.fixed_total.setValue(self.grading_config["fixed_total"])

        if dialog.exec_() == QDialog.Accepted:
            self.grading_config = dialog.get_config()
            self.update_config_info()

            # Update question selection UI
            self.setup_question_selection()

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
        """Set up checkboxes for selecting which questions the student attempted."""
        # Clear existing checkboxes
        self.clear_layout(self.question_selection_layout)

        grading_mode = self.grading_config["grading_mode"]
        questions_to_count = self.grading_config["questions_to_count"]

        # If we found multiple main questions, create checkboxes for selection
        if len(self.question_groups) > 1:
            self.question_selection_group.setVisible(True)
            self.question_checkboxes = {}

            # Helper text based on grading mode
            if grading_mode == "best_scores":
                helper_text = "Select ALL questions the student attempted:"
            else:
                helper_text = f"Select the {questions_to_count} questions to grade:"

            helper_label = QLabel(helper_text)
            helper_label.setStyleSheet("font-weight: bold;")
            self.question_selection_layout.addWidget(helper_label)

            for q in sorted(self.question_groups.keys()):
                checkbox = QCheckBox(f"Question {q}")
                checkbox.setChecked(True)  # Default to checked
                checkbox.stateChanged.connect(self.update_total_points)
                self.question_selection_layout.addWidget(checkbox)
                self.question_checkboxes[q] = checkbox

            # Add select all/none buttons
            self.question_selection_layout.addStretch()
            select_all_btn = QPushButton("Select All")
            select_all_btn.clicked.connect(self.select_all_questions)
            self.question_selection_layout.addWidget(select_all_btn)

            select_none_btn = QPushButton("Select None")
            select_none_btn.clicked.connect(self.select_no_questions)
            self.question_selection_layout.addWidget(select_none_btn)

        else:
            self.question_selection_group.setVisible(False)

        # Update the question summary display
        self.update_question_summary()

    def select_all_questions(self):
        """Select all question checkboxes."""
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(True)

    def select_no_questions(self):
        """Deselect all question checkboxes."""
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(False)

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

    def update_question_summary(self):
        """Update the question summary display showing scores per question."""
        # Clear existing summary
        self.clear_layout(self.question_summary_layout)

        if not self.question_groups:
            self.question_summary_group.setVisible(False)
            return

        self.question_summary_group.setVisible(True)

        # Calculate scores for each question
        question_scores = {}
        for q, widgets in self.question_groups.items():
            awarded = sum(widget.get_awarded_points() for widget in widgets)
            possible = sum(widget.get_possible_points() for widget in widgets)
            percentage = (awarded / possible * 100) if possible > 0 else 0
            question_scores[q] = (awarded, possible, percentage)

        # Create summary labels
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Question"))
        header_layout.addWidget(QLabel("Score"))
        header_layout.addWidget(QLabel("Percentage"))
        header_layout.addWidget(QLabel("Status"))
        header_layout.addStretch()
        self.question_summary_layout.addLayout(header_layout)

        # Add a line under the header
        line = QLabel()
        line.setFrameShape(QLabel.HLine)
        line.setFrameShadow(QLabel.Sunken)
        self.question_summary_layout.addWidget(line)

        # Create sorted list of questions by percentage (highest first)
        sorted_questions = sorted(
            question_scores.items(),
            key=lambda x: x[1][2],
            reverse=True
        )

        # Determine which questions are counted in the final score
        questions_to_count = self.grading_config["questions_to_count"]
        selected_questions = self.get_selected_questions()

        if self.grading_config["grading_mode"] == "best_scores":
            # Use the best N questions from the selected ones
            best_questions = [q for q, _ in sorted_questions[:questions_to_count]
                              if q in selected_questions]
        else:
            # Use exactly the selected questions
            best_questions = selected_questions

        # Add summary for each question
        for q, (awarded, possible, percentage) in sorted_questions:
            row_layout = QHBoxLayout()

            # Question number
            q_label = QLabel(f"Question {q}")
            row_layout.addWidget(q_label)

            # Score
            score_label = QLabel(f"{awarded} / {possible}")
            row_layout.addWidget(score_label)

            # Percentage
            pct_label = QLabel(f"{percentage:.1f}%")
            row_layout.addWidget(pct_label)

            # Status (counted in final score or not)
            status = ""
            if q in selected_questions:
                if q in best_questions:
                    status = "Counted in final score"
                    status_label = QLabel(status)
                    status_label.setStyleSheet("color: green; font-weight: bold;")
                else:
                    status = "Selected but not counted (better scores exist)"
                    status_label = QLabel(status)
                    status_label.setStyleSheet("color: #CC7700;")
            else:
                status = "Not selected for grading"
                status_label = QLabel(status)
                status_label.setStyleSheet("color: #999999;")

            row_layout.addWidget(status_label)
            row_layout.addStretch()

            # Add the row to the summary
            self.question_summary_layout.addLayout(row_layout)

        # Add note about best scores if applicable
        if self.grading_config["grading_mode"] == "best_scores":
            note = QLabel(f"Note: Final score uses the {questions_to_count} highest-scoring questions.")
            note.setStyleSheet("font-style: italic; color: #0066CC; margin-top: 10px;")
            self.question_summary_layout.addWidget(note)

    def update_total_points(self):
        """Update the total points display based on selected questions and mode."""
        if not self.criterion_widgets:
            self.total_label.setText("Total: 0 / 0 points")
            return

        selected_questions = self.get_selected_questions()

        # Count how many selected questions we have
        num_selected = len(selected_questions)
        questions_to_count = self.grading_config["questions_to_count"]
        grading_mode = self.grading_config["grading_mode"]

        # Handle based on grading mode
        if grading_mode == "selected" and num_selected != questions_to_count:
            # In "selected" mode, we need exactly the right number
            self.total_label.setText(f"Please select exactly {questions_to_count} questions " +
                                     f"(currently {num_selected} selected)")
            self.total_label.setStyleSheet("color: red; font-weight: bold; font-size: 14pt;")
            return
        elif grading_mode == "best_scores" and num_selected < 1:
            # In "best_scores" mode, we need at least one selection
            self.total_label.setText("Please select at least one question to grade")
            self.total_label.setStyleSheet("color: red; font-weight: bold; font-size: 14pt;")
            return

        # Calculate points for each selected question
        question_points = {}

        for q in selected_questions:
            if q in self.question_groups:
                q_widgets = self.question_groups[q]
                question_awarded = sum(widget.get_awarded_points() for widget in q_widgets)
                question_possible = sum(widget.get_possible_points() for widget in q_widgets)
                percentage = (question_awarded / question_possible * 100) if question_possible > 0 else 0
                question_points[q] = (question_awarded, question_possible, percentage)

        # Sort questions by score percentage (descending)
        sorted_questions = sorted(
            question_points.items(),
            key=lambda x: x[1][2],
            reverse=True
        )

        # Calculate total points based on grading mode
        if grading_mode == "best_scores":
            # Take the best N questions (limited by how many were selected)
            count_to_use = min(questions_to_count, len(sorted_questions))
            best_questions = sorted_questions[:count_to_use]
            earned_points = sum(points[0] for _, points in best_questions)

            if self.grading_config["use_fixed_total"]:
                possible_points = self.grading_config["fixed_total"]
            else:
                possible_points = sum(points[1] for _, points in best_questions)
        else:
            # Use exactly the selected questions
            earned_points = sum(points[0] for _, points in sorted_questions)

            if self.grading_config["use_fixed_total"]:
                possible_points = self.grading_config["fixed_total"]
            else:
                possible_points = sum(points[1] for _, points in sorted_questions)

        # Update the total display
        self.total_label.setText(f"Total: {earned_points} / {possible_points} points")

        # Update color based on score
        if possible_points > 0:
            percentage = (earned_points / possible_points) * 100
            if percentage >= 90:
                self.total_label.setStyleSheet("color: green; font-weight: bold; font-size: 14pt;")
            elif percentage >= 70:
                self.total_label.setStyleSheet("color: #CC7700; font-weight: bold; font-size: 14pt;")
            else:
                self.total_label.setStyleSheet("color: red; font-weight: bold; font-size: 14pt;")

        # Update the question summary
        self.update_question_summary()

    def clear_form(self):
        """Clear all entered data."""
        self.student_name_edit.clear()

        for widget in self.criterion_widgets:
            widget.reset()

        # Reset checkboxes if they exist
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(True)

        self.update_total_points()

    def get_assessment_data(self):
        """Gather all the assessment data."""
        if not self.rubric_data or not self.criterion_widgets:
            return None

        selected_questions = self.get_selected_questions()
        questions_to_count = self.grading_config["questions_to_count"]
        grading_mode = self.grading_config["grading_mode"]

        # Validate selections based on grading mode
        if grading_mode == "selected" and len(selected_questions) != questions_to_count:
            QMessageBox.warning(
                self,
                "Warning",
                f"Please select exactly {questions_to_count} questions to grade."
            )
            return None
        elif grading_mode == "best_scores" and len(selected_questions) < 1:
            QMessageBox.warning(
                self,
                "Warning",
                "Please select at least one question to grade."
            )
            return None

        # Calculate points for each selected question
        question_points = {}
        for q in selected_questions:
            if q in self.question_groups:
                q_widgets = self.question_groups[q]
                question_awarded = sum(widget.get_awarded_points() for widget in q_widgets)
                question_possible = sum(widget.get_possible_points() for widget in q_widgets)
                percentage = (question_awarded / question_possible * 100) if question_possible > 0 else 0
                question_points[q] = (question_awarded, question_possible, percentage)

        # Determine which questions count toward the final score
        if grading_mode == "best_scores":
            # Sort questions by percentage and take the best N
            sorted_questions = sorted(
                question_points.items(),
                key=lambda x: x[1][2],
                reverse=True
            )
            count_to_use = min(questions_to_count, len(sorted_questions))
            best_questions = [q for q, _ in sorted_questions[:count_to_use]]
        else:
            # Use all selected questions
            best_questions = selected_questions

        # Get data for all criteria, marking which ones are selected and counted
        criteria_data = []
        for widget in self.criterion_widgets:
            data = widget.get_data()

            # Determine if this criterion is part of a selected question
            title = data["title"]

            main_question = self.extract_question_number(title)
            is_selected = main_question in selected_questions
            is_counted = main_question in best_questions

            data["selected"] = is_selected
            data["counted"] = is_counted
            criteria_data.append(data)

        # Calculate final score
        counted_question_points = [points for q, points in question_points.items() if q in best_questions]
        earned_total = sum(points[0] for points in counted_question_points)

        if self.grading_config["use_fixed_total"]:
            possible_total = self.grading_config["fixed_total"]
        else:
            possible_total = sum(points[1] for points in counted_question_points)

            # Create question summary data for the report
        question_summary = []
        for q in sorted(self.question_groups.keys()):
            if q in question_points:
                points = question_points[q]
                question_summary.append({
                    "question": q,
                    "awarded": points[0],
                    "possible": points[1],
                    "percentage": points[2],
                    "selected": True,
                    "counted": q in best_questions
                })
            else:
                # Question not attempted/selected
                q_widgets = self.question_groups[q]
                possible = sum(widget.get_possible_points() for widget in q_widgets)
                question_summary.append({
                    "question": q,
                    "awarded": 0,
                    "possible": possible,
                    "percentage": 0,
                    "selected": False,
                    "counted": False
                })

        return {
            "student_name": self.student_name_edit.text(),
            "assignment_name": self.assignment_name_edit.text(),
            "criteria": criteria_data,
            "selected_questions": selected_questions,
            "counted_questions": best_questions,
            "question_summary": question_summary,
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

