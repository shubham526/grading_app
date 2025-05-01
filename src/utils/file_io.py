"""
File I/O utilities for the Rubric Grading Tool.

This module provides functions for loading and saving files,
including rubrics, assessments, and auto-save functionality.
"""

import os
import json
import time
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.QtCore import QTimer

from src.core.rubric import load_rubric_from_file
from src.core.assessment import get_assessment_data
from src.core.grader import is_valid_assessment


def load_rubric(window, file_path=None, show_config_on_load=True):
    """
    Load a rubric from a file (JSON or CSV).

    Args:
        window: The parent window object
        file_path (str, optional): Path to the rubric file. If None, will prompt the user.
        show_config_on_load (bool): Whether to show the grading config dialog after loading

    Returns:
        bool: True if loaded successfully, False otherwise
    """
    if not file_path:
        file_path, _ = QFileDialog.getOpenFileName(
            window,
            "Open Rubric File",
            "",
            "Rubric Files (*.json *.csv);;JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )

    if not file_path:
        return False

    try:
        window.rubric_data = load_rubric_from_file(file_path)
        window.rubric_file_path = file_path

        # Update UI
        if hasattr(window, 'setup_rubric_ui'):
            window.setup_rubric_ui()

        if hasattr(window, 'export_btn'):
            window.export_btn.setEnabled(True)

        if hasattr(window, 'config_btn'):
            window.config_btn.setEnabled(True)

        if hasattr(window, 'analytics_btn'):
            window.analytics_btn.setEnabled(True)

        if hasattr(window, 'status_bar'):
            window.status_bar.set_status(f"Loaded rubric: {os.path.basename(file_path)}")

        if hasattr(window, 'status_label'):
            window.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")

        # Only show grading config if the flag is True
        if show_config_on_load and hasattr(window, 'show_grading_config'):
            window.show_grading_config()

        return True

    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to load rubric: {str(e)}")
        return False


def save_assessment(window):
    """
    Save the current assessment to a JSON file.

    Args:
        window: The parent window object

    Returns:
        bool: True if saved successfully, False otherwise
    """
    if not window.criterion_widgets:
        QMessageBox.warning(window, "Warning", "No rubric loaded to save.")
        return False

    assessment_data = get_assessment_data(window)
    if not assessment_data:
        return False

    # If we have a current path, use it as the default
    default_path = ""
    if window.current_assessment_path:
        default_path = window.current_assessment_path
    else:
        # Create a suggested filename based on student and assignment
        student = window.student_name_edit.text()
        assignment = window.assignment_name_edit.text()
        if student and assignment:
            safe_student = ''.join(c if c.isalnum() else '_' for c in student)
            safe_assignment = ''.join(c if c.isalnum() else '_' for c in assignment)
            default_path = f"{safe_assignment}_{safe_student}.json"

    file_path, _ = QFileDialog.getSaveFileName(
        window,
        "Save Assessment",
        default_path,
        "JSON Files (*.json);;All Files (*)"
    )

    if not file_path:
        return False

    # Ensure .json extension
    if not file_path.lower().endswith('.json'):
        file_path += '.json'

    try:
        with open(file_path, 'w') as file:
            json.dump(assessment_data, file, indent=2)

        # Update current assessment path
        window.current_assessment_path = file_path

        # Update status
        if hasattr(window, 'status_bar'):
            window.status_bar.set_status(f"Saved to: {os.path.basename(file_path)}")
            window.status_bar.show_temporary_message("Assessment saved successfully")

        QMessageBox.information(window, "Success", "Assessment saved successfully.")
        return True
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to save assessment: {str(e)}")
        return False


def load_assessment(window):
    """
    Load a previously saved assessment.

    Args:
        window: The parent window object

    Returns:
        bool: True if loaded successfully, False otherwise
    """
    file_path, _ = QFileDialog.getOpenFileName(
        window,
        "Open Assessment File",
        "",
        "JSON Files (*.json);;All Files (*)"
    )

    if not file_path:
        return False

    try:
        with open(file_path, 'r') as file:
            assessment_data = json.load(file)

        # Validate the assessment data
        if not is_valid_assessment(assessment_data):
            QMessageBox.warning(
                window,
                "Invalid Assessment",
                "The selected file does not contain a valid assessment."
            )
            return False

        # Check if we have a rubric file path in the assessment data
        rubric_path = assessment_data.get("rubric_path")

        # If the rubric isn't loaded or is different from the one in the assessment, try to load it
        if rubric_path and (not window.rubric_file_path or window.rubric_file_path != rubric_path):
            if os.path.exists(rubric_path):
                reply = QMessageBox.question(
                    window,
                    "Load Rubric",
                    f"This assessment was created with a different rubric. Would you like to load the associated rubric?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    load_rubric(window, rubric_path)
            else:
                QMessageBox.warning(
                    window,
                    "Rubric Not Found",
                    f"The original rubric file could not be found. Please load the correct rubric first."
                )

        # Check if we have a rubric loaded
        if not window.criterion_widgets:
            QMessageBox.warning(window, "Warning", "Please load a rubric first.")
            return False

        # Fill in the form
        window.student_name_edit.setText(assessment_data.get("student_name", ""))
        window.assignment_name_edit.setText(assessment_data.get("assignment_name", ""))

        # Load grading configuration if present
        if "grading_config" in assessment_data:
            window.grading_config = assessment_data["grading_config"]
            window.update_config_info()

        # Update question selection if it exists
        selected_questions = assessment_data.get("selected_questions", [])
        if hasattr(window, 'question_checkboxes') and selected_questions:
            for q, checkbox in window.question_checkboxes.items():
                checkbox.setChecked(q in selected_questions)

        # Fill in criteria data if it matches the current rubric
        criteria_data = assessment_data.get("criteria", [])
        if len(criteria_data) != len(window.criterion_widgets):
            QMessageBox.warning(
                window,
                "Warning",
                "The assessment criteria don't match the current rubric."
            )
        else:
            for i, criterion_data in enumerate(criteria_data):
                widget = window.criterion_widgets[i]
                widget.set_data(criterion_data)

        # Update current assessment path
        window.current_assessment_path = file_path

        # Update status
        if hasattr(window, 'status_bar'):
            window.status_bar.set_status(f"Loaded from: {os.path.basename(file_path)}")
            window.status_bar.show_temporary_message("Assessment loaded successfully")

        # Update total points
        if hasattr(window, 'update_total_points'):
            window.update_total_points()

        QMessageBox.information(window, "Success", "Assessment loaded successfully.")
        return True
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to load assessment: {str(e)}")
        return False


def setup_auto_save(window, interval=180000):
    """
    Set up the auto-save timer.

    Args:
        window: The parent window object
        interval (int): Auto-save interval in milliseconds (default: 3 minutes)
    """
    window.auto_save_timer = QTimer(window)
    window.auto_save_timer.timeout.connect(lambda: auto_save_assessment(window))
    window.auto_save_timer.start(interval)


def auto_save_assessment(window):
    """
    Automatically save the current assessment to a temporary file.

    Args:
        window: The parent window object
    """
    # Only auto-save if there's a rubric loaded and some data entered
    if not window.rubric_data or not window.criterion_widgets:
        return

    # Get assessment data without validation
    assessment_data = get_assessment_data(window, validate=False)
    if not assessment_data:
        return

    # Create a unique filename based on student name and timestamp
    student_name = window.student_name_edit.text() or "unnamed_student"
    student_name = ''.join(c if c.isalnum() else '_' for c in student_name)  # Sanitize filename
    timestamp = int(time.time())
    filename = f"autosave_{student_name}_{timestamp}.json"
    file_path = os.path.join(window.auto_save_dir, filename)

    try:
        with open(file_path, 'w') as file:
            json.dump(assessment_data, file, indent=2)

        # Update status bar
        if hasattr(window, 'status_bar'):
            current_time = time.strftime("%H:%M:%S")
            window.status_bar.set_auto_save_status(f"Saved at {current_time}")
            window.status_bar.show_temporary_message("Assessment auto-saved")

        # Clean up old auto-save files (keep only the 5 most recent)
        cleanup_auto_save_files(window)
    except Exception as e:
        if hasattr(window, 'status_bar'):
            window.status_bar.set_auto_save_status(f"Failed: {str(e)}", is_error=True)


def cleanup_auto_save_files(window):
    """
    Remove old auto-save files, keeping only the most recent ones.

    Args:
        window: The parent window object
    """
    try:
        # Get all auto-save files for the current student
        student_name = window.student_name_edit.text() or "unnamed_student"
        student_name = ''.join(c if c.isalnum() else '_' for c in student_name)

        all_files = []
        for filename in os.listdir(window.auto_save_dir):
            if filename.startswith(f"autosave_{student_name}_") and filename.endswith(".json"):
                file_path = os.path.join(window.auto_save_dir, filename)
                all_files.append((file_path, os.path.getmtime(file_path)))

        # Sort by modification time (newest first)
        all_files.sort(key=lambda x: x[1], reverse=True)

        # Keep only the 5 most recent files
        for file_path, _ in all_files[5:]:
            os.remove(file_path)
    except Exception:
        # Silently fail - this is just cleanup
        pass