"""
Data processing for analytics in the Rubric Grading Tool.

This module provides functionality for collecting and analyzing assessment data
for visualization and statistical analysis.
"""

import os
import re
import json
import glob
import numpy as np
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
from PyQt5.QtCore import Qt

from src.core.grader import extract_question_number


def collect_assessments(self):
    """
    Collect and process assessment data from a directory of JSON files.

    Args:
        self: The parent window object (used for dialogs)

    Returns:
        dict: Dictionary with aggregated assessment data, or None if canceled
    """
    # Let user select a directory containing assessments
    directory = QFileDialog.getExistingDirectory(
        self,
        "Select Assessment Directory",
        "",
        QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
    )

    if not directory:
        return None

    # Find all assessment JSON files in the directory
    assessment_files = glob.glob(os.path.join(directory, "*.json"))

    if not assessment_files:
        QMessageBox.warning(
            self,
            "No Assessments Found",
            "No assessment files (*.json) were found in the selected directory."
        )
        return None

    # Initialize data structures
    question_data = {}
    assignment_name = ""
    total_students = len(assessment_files)

    # Process each assessment file
    progress = QProgressDialog("Loading assessments...", "Cancel", 0, len(assessment_files), self)
    progress.setWindowTitle("Loading Assessments")
    progress.setWindowModality(Qt.WindowModal)

    for i, file_path in enumerate(assessment_files):
        progress.setValue(i)
        if progress.wasCanceled():
            break

        try:
            with open(file_path, 'r') as file:
                assessment = json.load(file)

                # Use the assignment name from the first valid assessment
                if not assignment_name and "assignment_name" in assessment:
                    assignment_name = assessment["assignment_name"]

                # Process question data
                process_question_data(question_data, assessment)

        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")

    progress.setValue(len(assessment_files))

    # Calculate overall scores
    overall_scores = calculate_overall_scores(assessment_files)

    # Return the collected data
    return {
        "question_data": question_data,
        "assignment_name": assignment_name,
        "file_count": len(assessment_files),
        "overall_data": {
            "overall_scores": overall_scores,
            "num_students": len(overall_scores)
        }
    }


def process_question_data(question_data, assessment):
    """
    Process question data from an assessment.

    Args:
        question_data (dict): Dictionary to update with question data
        assessment (dict): Assessment data to process
    """
    for criterion in assessment.get("criteria", []):
        # Extract question number using regex
        title = criterion.get("title", "")
        match = re.search(r"Question\s+(\d+)", title)
        if not match:
            continue

        q_num = match.group(1)

        if q_num not in question_data:
            question_data[q_num] = {
                "scores": [],
                "percentages": [],
                "max_points": criterion.get("points_possible", 0),
                "num_students": 0,
                "title": title
            }

        # Add score
        awarded = criterion.get("points_awarded", 0)
        possible = criterion.get("points_possible", 0)
        question_data[q_num]["scores"].append(awarded)

        # Calculate percentage
        if possible > 0:
            percentage = (awarded / possible) * 100
        else:
            percentage = 0
        question_data[q_num]["percentages"].append(percentage)

        # Update max points if needed
        if possible > question_data[q_num]["max_points"]:
            question_data[q_num]["max_points"] = possible

        # Increment student count
        question_data[q_num]["num_students"] += 1


def calculate_overall_scores(assessment_files):
    """
    Calculate overall scores from a list of assessment files.

    Args:
        assessment_files (list): List of paths to assessment files

    Returns:
        list: List of overall percentage scores
    """
    overall_scores = []

    for file_path in assessment_files:
        try:
            with open(file_path, 'r') as file:
                assessment = json.load(file)

            # Try to get direct overall scores if available
            if "total_awarded" in assessment and "total_possible" in assessment:
                if assessment["total_possible"] > 0:
                    percentage = (assessment["total_awarded"] / assessment["total_possible"]) * 100
                    overall_scores.append(percentage)
                    continue

            # Otherwise calculate from criteria
            student_total_awarded = 0
            student_total_possible = 0

            for criterion in assessment.get("criteria", []):
                student_total_awarded += criterion.get("points_awarded", 0)
                student_total_possible += criterion.get("points_possible", 0)

            if student_total_possible > 0:
                percentage = (student_total_awarded / student_total_possible) * 100
                overall_scores.append(percentage)

        except Exception as e:
            print(f"Error calculating overall score for {file_path}: {str(e)}")

    return overall_scores


def gather_analytics_data(self):
    """
    Gather data for analytics from loaded assessments or generate sample data.

    Args:
        self: The parent window object with question_groups

    Returns:
        dict: Dictionary with analytics data
    """
    # Try to collect real assessment data
    collected_data = collect_assessments(self)

    if collected_data:
        return collected_data

    # If user canceled or no data found, generate sample data
    return generate_sample_data(self)


def generate_sample_data(self):
    """
    Generate sample data for analytics when no real data is available.

    Args:
        self: The parent window object with question_groups

    Returns:
        dict: Dictionary with sample analytics data
    """
    question_data = {}
    num_students = 30  # Sample size

    # Create sample data for each question
    for q in self.question_groups.keys():
        # Calculate maximum points for this question
        max_points = sum(widget.get_possible_points() for widget in self.question_groups[q])

        # Generate random scores with a normal distribution
        mean_percent = 70  # Mean score (as percentage)
        std_dev = 15  # Standard deviation

        # Generate scores and clip to valid range
        scores = np.random.normal(mean_percent * max_points / 100,
                                  std_dev * max_points / 100,
                                  num_students)
        scores = np.clip(scores, 0, max_points)

        # Calculate percentages
        percentages = [(s / max_points * 100) for s in scores]

        question_data[q] = {
            "scores": scores,
            "percentages": percentages,
            "max_points": max_points,
            "num_students": num_students,
            "title": f"Question {q}"
        }

    # Generate overall scores
    overall_scores = np.random.normal(70, 15, num_students)
    overall_scores = np.clip(overall_scores, 0, 100)

    return {
        "question_data": question_data,
        "overall_data": {
            "overall_scores": overall_scores,
            "num_students": num_students
        },
        "assignment_name": "Sample Data"
    }