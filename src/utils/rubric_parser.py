"""
Rubric Parser for the Rubric Grading Tool.

This module provides functions to parse rubric definitions from JSON and CSV files.
"""

import os
import json
import csv


def parse_rubric_file(file_path):
    """
    Parse a rubric file in either JSON or CSV format.

    Args:
        file_path (str): Path to the rubric file

    Returns:
        dict: Parsed rubric data structure

    Raises:
        ValueError: If the file format is not supported
        FileNotFoundError: If the file does not exist
        json.JSONDecodeError: If the JSON file is malformed
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if file_path.lower().endswith('.json'):
        return parse_json_rubric(file_path)
    elif file_path.lower().endswith('.csv'):
        return parse_csv_rubric(file_path)
    else:
        raise ValueError(f"Unsupported file format: {os.path.splitext(file_path)[1]}")


def parse_json_rubric(file_path):
    """
    Parse a rubric from a JSON file.

    Args:
        file_path (str): Path to the JSON file

    Returns:
        dict: Parsed rubric data structure
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        rubric_data = json.load(file)

    # Validate the structure
    if not isinstance(rubric_data, dict):
        raise ValueError("Invalid JSON format: root must be an object")

    if "criteria" not in rubric_data or not isinstance(rubric_data["criteria"], list):
        raise ValueError("Invalid rubric format: missing 'criteria' array")

    # Set default title if not present
    if "title" not in rubric_data:
        rubric_data["title"] = os.path.basename(file_path)

    return rubric_data


def parse_csv_rubric(file_path):
    """
    Parse a rubric from a CSV file.

    Expected CSV format:
    Title, Description, Points, Level1_Title, Level1_Points, Level2_Title, Level2_Points, ...

    Args:
        file_path (str): Path to the CSV file

    Returns:
        dict: Parsed rubric data structure
    """
    rubric = {
        "title": os.path.splitext(os.path.basename(file_path))[0],
        "criteria": []
    }

    with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader, None)

        if not headers:
            return rubric

        # Simple CSV format where each row is a criterion
        for row in reader:
            if len(row) < 2 or not row[0].strip():
                continue

            criterion = {
                "title": row[0].strip(),
                "description": row[1].strip() if len(row) > 1 else "",
                "points": int(row[2]) if len(row) > 2 and row[2].strip().isdigit() else 10
            }

            # Check if there are achievement levels defined
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