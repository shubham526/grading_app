"""
Layout utilities for the Rubric Grading Tool.

v2.1 keeps the legacy ``window.question_groups`` used by best-N/selected
scoring and adds a separate ``window.workflow_question_groups`` keyed by
canonical question IDs (Q1, Q1A, ..., UNASSIGNED) for manual navigation.
"""

from PyQt5.QtWidgets import QLabel, QHBoxLayout, QPushButton, QCheckBox

from src.core.assessment import update_question_summary
from src.core.question_utils import resolve_criterion_question_id


def setup_rubric_ui(window):
    """Set up criterion widgets and both legacy/workflow question groupings."""
    clear_layout(window.criteria_layout)
    window.criterion_widgets = []
    window.question_groups = {}
    window.workflow_question_groups = {}
    window.question_summary_card.setVisible(True)

    if not window.rubric_data or "criteria" not in window.rubric_data:
        window.status_bar.set_status("Invalid rubric format.")
        window.status_label.setText("Invalid rubric format.")
        return

    if "title" in window.rubric_data and not window.assignment_name_edit.text():
        window.assignment_name_edit.setText(window.rubric_data["title"])

    from src.ui.widgets import CriterionWidget
    from src.core.utils import extract_question_number

    for criterion in window.rubric_data["criteria"]:
        criterion_widget = CriterionWidget(criterion)
        criterion_widget.points_changed.connect(window.on_criterion_points_changed)
        if hasattr(criterion_widget, "content_changed") and hasattr(window, "on_criterion_content_changed"):
            criterion_widget.content_changed.connect(window.on_criterion_content_changed)

        window.criteria_layout.addWidget(criterion_widget)
        window.criterion_widgets.append(criterion_widget)

        # Existing scoring grouping: do not change its identifier semantics.
        main_question = extract_question_number(criterion.get("title", ""))
        if main_question:
            window.question_groups.setdefault(main_question, []).append(criterion_widget)

        # New v2.1 workflow grouping: canonical question_id/UNASSIGNED.
        workflow_qid = resolve_criterion_question_id(criterion)
        window.workflow_question_groups.setdefault(workflow_qid, []).append(criterion_widget)

    setup_question_selection(window)
    window.criteria_layout.addStretch()

    from src.core.assessment import update_total_points
    update_total_points(window)
    window.update_config_info()
    update_question_summary(window)

    if hasattr(window, "refresh_workflow_questions"):
        window.refresh_workflow_questions()


def apply_workflow_question_filter(window, question_id):
    """Show only widgets belonging to ``question_id`` in question-centric mode."""
    visible = set(window.workflow_question_groups.get(question_id, []))
    for widget in window.criterion_widgets:
        widget.setVisible(widget in visible)


def show_all_criteria(window):
    """Restore the existing student-centric full-rubric view."""
    for widget in window.criterion_widgets:
        widget.setVisible(True)


def setup_question_selection(window):
    """Set up existing selected/attempted-question checkboxes."""
    clear_layout(window.question_selection_layout)

    grading_mode = window.grading_config["grading_mode"]
    questions_to_count = window.grading_config["questions_to_count"]

    if len(window.question_groups) > 1:
        window.question_selection_group.setVisible(True)
        window.question_checkboxes = {}

        if grading_mode == "best_scores":
            helper_text = "Select ALL questions the student attempted:"
        else:
            helper_text = f"Select the {questions_to_count} questions to grade:"

        helper_label = QLabel(helper_text)
        helper_label.setStyleSheet("font-weight: bold; margin-bottom: 8px;")
        window.question_selection_layout.addWidget(helper_label)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(16)

        for q in sorted(window.question_groups.keys(), key=str):
            checkbox = QCheckBox(f"Question {q}")
            checkbox.setChecked(True)
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
        window.question_checkboxes = {}

    update_question_summary(window)


def select_all_questions(window):
    if hasattr(window, 'question_checkboxes'):
        for checkbox in window.question_checkboxes.values():
            checkbox.setChecked(True)


def select_no_questions(window):
    if hasattr(window, 'question_checkboxes'):
        for checkbox in window.question_checkboxes.values():
            checkbox.setChecked(False)


def clear_layout(layout):
    """Recursively clear all widgets/layouts from a Qt layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()

        if widget:
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())
