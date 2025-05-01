"""
Assessment module for handling assessment data and calculations.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QTableWidgetItem, QTableWidget, QHeaderView, QLabel
from PyQt5.QtGui import QFont
from PyQt5.QtGui import QColor

from .utils import extract_question_number


def get_assessment_data(self, validate=True):
    """Gather all the assessment data."""
    if not self.rubric_data or not self.criterion_widgets:
        return None

    selected_questions = self.get_selected_questions()
    questions_to_count = self.grading_config["questions_to_count"]
    grading_mode = self.grading_config["grading_mode"]

    # Validate selections based on grading mode
    if validate:
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

        main_question = extract_question_number(title)
        is_selected = main_question in selected_questions
        is_counted = main_question in best_questions

        data["selected"] = is_selected
        data["counted"] = is_counted
        criteria_data.append(data)

    # Calculate final score
    counted_question_points = [points for q, points in question_points.items() if q in best_questions]
    earned_total = sum(points[0] for points in counted_question_points) if counted_question_points else 0

    if self.grading_config["use_fixed_total"]:
        possible_total = self.grading_config["fixed_total"]
    else:
        possible_total = sum(points[1] for points in counted_question_points) if counted_question_points else 0

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
        "percentage": (earned_total / possible_total * 100) if possible_total > 0 else 0,
        "rubric_path": self.rubric_file_path  # Store the path to the rubric
    }


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
        self.total_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 14pt;")  # Red
        return
    elif grading_mode == "best_scores" and num_selected < 1:
        # In "best_scores" mode, we need at least one selection
        self.total_label.setText("Please select at least one question to grade")
        self.total_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 14pt;")  # Red
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
            self.total_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14pt;")  # Green
        elif percentage >= 70:
            self.total_label.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 14pt;")  # Orange
        else:
            self.total_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 14pt;")  # Red

    # Update the question summary
    update_question_summary(self)

    # Trigger an auto-save when points are updated
    if hasattr(self, 'auto_save_assessment'):
        self.auto_save_assessment()


def update_question_summary(self):
    """Update the question summary display using a proper QTableWidget."""
    # Clear existing summary
    if hasattr(self, 'clear_layout'):
        self.clear_layout(self.question_summary_layout)
    else:
        # Fallback if clear_layout is not found
        while self.question_summary_layout.count():
            item = self.question_summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    if not self.question_groups:
        self.question_summary_card.setVisible(False)
        return

    # Make the card visible
    self.question_summary_card.setVisible(True)

    # Calculate scores for each question
    question_scores = {}
    for q, widgets in self.question_groups.items():
        awarded = sum(widget.get_awarded_points() for widget in widgets)
        possible = sum(widget.get_possible_points() for widget in widgets)
        percentage = (awarded / possible * 100) if possible > 0 else 0
        question_scores[q] = (awarded, possible, percentage)

    # If no scores yet, show a placeholder message
    if not question_scores:
        no_data_label = QLabel("No questions have been scored yet.")
        no_data_label.setStyleSheet("color: #757575; font-style: italic; padding: 20px;")
        no_data_label.setAlignment(Qt.AlignCenter)
        self.question_summary_layout.addWidget(no_data_label)
        return

    # Create a proper table widget for the summary
    table = QTableWidget()
    table.setColumnCount(4)
    table.setRowCount(len(question_scores))
    table.setHorizontalHeaderLabels(["Question", "Score", "Percentage", "Status"])

    # Set table properties
    table.setStyleSheet("""
        QTableWidget {
            border: 1px solid #DDDDDD;
            gridline-color: #DDDDDD;
            background-color: white;
        }
        QTableWidget::item {
            padding: 6px;
        }
        QHeaderView::section {
            background-color: #F5F5F5;
            padding: 6px;
            font-weight: bold;
            border: 1px solid #DDDDDD;
        }
    """)

    # Determine which questions are counted in the final score
    questions_to_count = self.grading_config["questions_to_count"]
    selected_questions = self.get_selected_questions()

    if self.grading_config["grading_mode"] == "best_scores":
        # Sort questions by percentage (highest first)
        sorted_questions = sorted(
            question_scores.items(),
            key=lambda x: x[1][2],
            reverse=True
        )

        # Use the best N questions from the selected ones
        best_questions = [q for q, _ in sorted_questions[:questions_to_count]
                          if q in selected_questions]
    else:
        # Use exactly the selected questions
        best_questions = selected_questions

    # Sort questions by percentage for display (highest first)
    sorted_display_questions = sorted(
        question_scores.items(),
        key=lambda x: x[1][2],
        reverse=True
    )

    # Add table rows for each question
    for row, (q, score_data) in enumerate(sorted_display_questions):
        awarded, possible, percentage = score_data

        # Question number
        q_item = QTableWidgetItem(f"Question {q}")
        q_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, q_item)

        # Score
        score_item = QTableWidgetItem(f"{awarded} / {possible}")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 1, score_item)

        # Percentage
        pct_item = QTableWidgetItem(f"{percentage:.1f}%")
        pct_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, pct_item)

        # Status
        if q in selected_questions:
            if q in best_questions:
                status = "Counted in final score"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor("#4CAF50"))  # Green
                status_item.setFont(QFont("", -1, QFont.Bold))
            else:
                status = "Selected but not counted"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor("#FF9800"))  # Orange
        else:
            status = "Not selected for grading"
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor("#9E9E9E"))  # Gray

        status_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.setItem(row, 3, status_item)

    # Auto-adjust column widths
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
    header.setSectionResizeMode(3, QHeaderView.Stretch)

    # Add the table to the layout
    self.question_summary_layout.addWidget(table)

    # Add note about best scores if applicable
    if self.grading_config["grading_mode"] == "best_scores":
        note = QLabel(f"Note: Final score uses the {questions_to_count} highest-scoring questions.")
        note.setStyleSheet(
            "color: #3F51B5; font-style: italic; background-color: #E8EAF6; padding: 8px; border-radius: 4px;")
        self.question_summary_layout.addWidget(note)