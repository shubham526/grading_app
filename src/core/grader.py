"""
Grader module for the Rubric Grading Tool.

This module handles core grading functionality independent of the UI.
"""

from src.core.utils import extract_question_number


def extract_main_questions(self):
    """Extract and return list of main question identifiers from criteria titles."""
    main_questions = []

    for criterion in self.rubric_data["criteria"]:
        title = criterion["title"]
        main_question = extract_question_number(title)

        if main_question and main_question not in main_questions:
            main_questions.append(main_question)

    return sorted(main_questions)

def is_valid_assessment(assessment):
    """
    Check if the given dictionary is a valid assessment.

    Args:
        assessment (dict): The assessment data to validate

    Returns:
        bool: True if valid, False otherwise
    """
    # Check for minimum required fields for your JSON format
    required_fields = ["student_name", "criteria"]

    for field in required_fields:
        if field not in assessment:
            return False

    # Check if criteria contains question data
    has_questions = False
    for criterion in assessment.get("criteria", []):
        if "Question" in criterion.get("title", ""):
            has_questions = True
            break

    return has_questions


def calculate_question_scores(question_groups):
    """
    Calculate scores for each question group.

    Args:
        question_groups (dict): Dictionary mapping question numbers to criterion widgets

    Returns:
        dict: Dictionary with question scores information
    """
    question_scores = {}

    for q, widgets in question_groups.items():
        awarded = sum(widget.get_awarded_points() for widget in widgets)
        possible = sum(widget.get_possible_points() for widget in widgets)
        percentage = (awarded / possible * 100) if possible > 0 else 0
        question_scores[q] = {
            "awarded": awarded,
            "possible": possible,
            "percentage": percentage
        }

    return question_scores


def calculate_best_questions(question_scores, selected_questions, questions_to_count):
    """
    Calculate the best performing questions based on scores.

    Args:
        question_scores (dict): Dictionary of question scores
        selected_questions (list): List of selected question numbers
        questions_to_count (int): Number of questions to count

    Returns:
        list: List of the best performing question numbers
    """
    # Filter to only include selected questions
    selected_scores = {q: data for q, data in question_scores.items()
                       if q in selected_questions}

    # Sort by percentage (highest first)
    sorted_questions = sorted(
        selected_scores.items(),
        key=lambda x: x[1]["percentage"],
        reverse=True
    )

    # Take the best N questions
    count_to_use = min(questions_to_count, len(sorted_questions))
    return [q for q, _ in sorted_questions[:count_to_use]]


def calculate_final_score(question_scores, best_questions, use_fixed_total=False, fixed_total=100):
    """
    Calculate the final score based on the best questions.

    Args:
        question_scores (dict): Dictionary of question scores
        best_questions (list): List of the best performing question numbers
        use_fixed_total (bool): Whether to use a fixed total
        fixed_total (int): The fixed total to use

    Returns:
        tuple: (earned_total, possible_total, percentage)
    """
    # Sum points from the best questions
    earned_total = sum(question_scores[q]["awarded"] for q in best_questions if q in question_scores)

    if use_fixed_total:
        possible_total = fixed_total
    else:
        possible_total = sum(question_scores[q]["possible"] for q in best_questions if q in question_scores)

    percentage = (earned_total / possible_total * 100) if possible_total > 0 else 0

    return earned_total, possible_total, percentage