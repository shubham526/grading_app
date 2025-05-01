"""
Rubric module for the Rubric Grading Tool.

This module provides functionality for working with rubrics, including loading,
validating, and extracting information from rubric data.
"""

import os
import json
import csv


def load_rubric_from_file(file_path):
    """
    Load a rubric from a file (JSON or CSV).

    Args:
        file_path (str): Path to the rubric file

    Returns:
        dict: The loaded rubric data

    Raises:
        ValueError: If the file format is not supported
        FileNotFoundError: If the file does not exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Rubric file not found: {file_path}")

    file_extension = os.path.splitext(file_path)[1].lower()

    if file_extension == '.json':
        return load_json_rubric(file_path)
    elif file_extension == '.csv':
        return load_csv_rubric(file_path)
    else:
        raise ValueError(f"Unsupported file format: {file_extension}")


def load_json_rubric(file_path):
    """
    Load a rubric from a JSON file.

    Args:
        file_path (str): Path to the JSON file

    Returns:
        dict: The loaded rubric data
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        rubric_data = json.load(file)

    # Validate the rubric data
    if not isinstance(rubric_data, dict):
        raise ValueError("Invalid rubric format: root must be an object")

    if "criteria" not in rubric_data or not isinstance(rubric_data["criteria"], list):
        raise ValueError("Invalid rubric format: missing 'criteria' array")

    # Set default title if not present
    if "title" not in rubric_data:
        rubric_data["title"] = os.path.basename(file_path)

    return rubric_data


def load_csv_rubric(file_path):
    """
    Load a rubric from a CSV file.

    Args:
        file_path (str): Path to the CSV file

    Returns:
        dict: The loaded rubric data
    """
    rubric = {
        "title": os.path.splitext(os.path.basename(file_path))[0],
        "criteria": []
    }

    with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader, None)  # Skip header row

        if not headers:
            return rubric

        for row in reader:
            if len(row) < 3 or not row[0].strip():
                continue

            criterion = {
                "title": row[0].strip(),
                "description": row[1].strip() if len(row) > 1 else "",
                "points": int(row[2]) if len(row) > 2 and row[2].strip().isdigit() else 10
            }

            # Process achievement levels if present
            if len(row) > 3:
                levels = []
                for i in range(3, len(row), 2):
                    if i + 1 < len(row) and row[i].strip() and row[i + 1].strip():
                        try:
                            points = float(row[i + 1])
                        except ValueError:
                            points = 0

                        levels.append({
                            "title": row[i].strip(),
                            "points": points,
                            "description": ""
                        })

                if levels:
                    criterion["levels"] = levels

            rubric["criteria"].append(criterion)

    return rubric


def validate_rubric(rubric_data):
    """
    Validate rubric data structure.

    Args:
        rubric_data (dict): The rubric data to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not isinstance(rubric_data, dict):
        return False

    if "criteria" not in rubric_data or not isinstance(rubric_data["criteria"], list):
        return False

    if not rubric_data["criteria"]:
        return False

    # Validate each criterion
    for criterion in rubric_data["criteria"]:
        if not isinstance(criterion, dict):
            return False

        if "title" not in criterion or "points" not in criterion:
            return False

        # Validate levels if present
        if "levels" in criterion:
            if not isinstance(criterion["levels"], list):
                return False

            for level in criterion["levels"]:
                if not isinstance(level, dict):
                    return False

                if "title" not in level or "points" not in level:
                    return False

    return True


def get_total_points(rubric_data):
    """
    Calculate the total points in a rubric.

    Args:
        rubric_data (dict): The rubric data

    Returns:
        int: The total possible points
    """
    if not rubric_data or "criteria" not in rubric_data:
        return 0

    return sum(criterion.get("points", 0) for criterion in rubric_data["criteria"])


def get_criterion_by_title(rubric_data, title):
    """
    Get a criterion by its title.

    Args:
        rubric_data (dict): The rubric data
        title (str): The criterion title to find

    Returns:
        dict or None: The criterion if found, None otherwise
    """
    if not rubric_data or "criteria" not in rubric_data:
        return None

    for criterion in rubric_data["criteria"]:
        if criterion.get("title") == title:
            return criterion

    return None


def group_criteria_by_question(rubric_data):
    """
    Group criteria by their main question number.

    Args:
        rubric_data (dict): The rubric data

    Returns:
        dict: Dictionary mapping question numbers to criteria
    """
    from .grader import extract_question_number

    question_groups = {}

    if not rubric_data or "criteria" not in rubric_data:
        return question_groups

    for criterion in rubric_data["criteria"]:
        title = criterion.get("title", "")
        question_number = extract_question_number(title)

        if question_number:
            if question_number not in question_groups:
                question_groups[question_number] = []

            question_groups[question_number].append(criterion)

    return question_groups