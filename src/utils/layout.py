"""
Layout utilities for the Rubric Grading Tool.

This module provides functions for managing UI layouts, including setting up
UI components based on loaded data and handling layout-specific operations.
"""

from PyQt5.QtWidgets import QLabel, QHBoxLayout, QPushButton, QCheckBox
from src.core.assessment import update_question_summary


def setup_rubric_ui(window):
    """
    Set up the UI based on the loaded rubric.

    Args:
        window: The parent window object
    """
    # Clear existing criteria
    clear_layout(window.criteria_layout)
    window.criterion_widgets = []
    window.question_groups = {}
    window.question_summary_card.setVisible(True)

    if not window.rubric_data or "criteria" not in window.rubric_data:
        window.status_bar.set_status("Invalid rubric format.")
        window.status_label.setText("Invalid rubric format.")
        return

    # Set assignment name if available
    if "title" in window.rubric_data and not window.assignment_name_edit.text():
        window.assignment_name_edit.setText(window.rubric_data["title"])

    # Extract main questions from criteria titles
    from src.core.grader import extract_main_questions
    main_questions = extract_main_questions(window)

    # Create widgets for each criterion
    from src.ui.widgets import CriterionWidget
    from src.core.utils import extract_question_number

    for criterion in window.rubric_data["criteria"]:
        criterion_widget = CriterionWidget(criterion)
        # Connect the signal to update total points when a criterion changes
        criterion_widget.points_changed.connect(window.on_criterion_points_changed)
        window.criteria_layout.addWidget(criterion_widget)
        window.criterion_widgets.append(criterion_widget)

        # Group by main question
        title = criterion["title"]
        main_question = extract_question_number(title)

        if main_question:
            if main_question not in window.question_groups:
                window.question_groups[main_question] = []

            window.question_groups[main_question].append(criterion_widget)

    # Set up question selection UI
    setup_question_selection(window)

    # Add stretch to push everything up
    window.criteria_layout.addStretch()

    # Update total points
    from src.core.assessment import update_total_points
    update_total_points(window)

    # Update config info with question count
    window.update_config_info()

    # Update the question summary
    from src.core.assessment import update_question_summary
    update_question_summary(window)


def setup_question_selection(window):
    """
    Set up checkboxes for selecting which questions the student attempted.

    Args:
        window: The parent window object
    """
    # Clear existing checkboxes
    clear_layout(window.question_selection_layout)

    grading_mode = window.grading_config["grading_mode"]
    questions_to_count = window.grading_config["questions_to_count"]

    # If we found multiple main questions, create checkboxes for selection
    if len(window.question_groups) > 1:
        window.question_selection_group.setVisible(True)
        window.question_checkboxes = {}

        # Helper text based on grading mode
        if grading_mode == "best_scores":
            helper_text = "Select ALL questions the student attempted:"
        else:
            helper_text = f"Select the {questions_to_count} questions to grade:"

        helper_label = QLabel(helper_text)
        helper_label.setStyleSheet("font-weight: bold; margin-bottom: 8px;")
        window.question_selection_layout.addWidget(helper_label)

        # Create a grid layout for checkboxes
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(16)

        for q in sorted(window.question_groups.keys()):
            checkbox = QCheckBox(f"Question {q}")
            checkbox.setChecked(True)  # Default to checked
            checkbox.setStyleSheet("""
                QCheckBox {
                    font-size: 12px;
                    padding: 4px;
                }
                QCheckBox:hover {
                    background-color: #F5F5F5;
                    border-radius: 4px;
                }
            """)
            checkbox.stateChanged.connect(window.on_question_selection_changed)
            checkbox_layout.addWidget(checkbox)
            window.question_checkboxes[q] = checkbox

        checkbox_layout.addStretch()
        window.question_selection_layout.addLayout(checkbox_layout)

        # Add select all/none buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        select_all_btn = QPushButton("Select All")
        select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #3F51B5;
                border: 1px solid #3F51B5;
                min-width: 100px;
            }
        """)
        select_all_btn.clicked.connect(lambda: select_all_questions(window))
        buttons_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("Select None")
        select_none_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #757575;
                border: 1px solid #BDBDBD;
                min-width: 100px;
            }
        """)
        select_none_btn.clicked.connect(lambda: select_no_questions(window))
        buttons_layout.addWidget(select_none_btn)

        window.question_selection_layout.addLayout(buttons_layout)

    else:
        window.question_selection_group.setVisible(False)

    # Update the question summary display
    update_question_summary(window)


def select_all_questions(window):
    """
    Select all question checkboxes.

    Args:
        window: The parent window object
    """
    if hasattr(window, 'question_checkboxes'):
        for checkbox in window.question_checkboxes.values():
            checkbox.setChecked(True)


def select_no_questions(window):
    """
    Deselect all question checkboxes.

    Args:
        window: The parent window object
    """
    if hasattr(window, 'question_checkboxes'):
        for checkbox in window.question_checkboxes.values():
            checkbox.setChecked(False)


def clear_layout(layout):
    """
    Clear all widgets from a layout.

    Args:
        layout: The layout to clear
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()

        if widget:
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())