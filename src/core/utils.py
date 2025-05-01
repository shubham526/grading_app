"""
Core utility functions shared across multiple modules.
"""


def extract_question_number(title):
    """
    Extract the main question number from a criterion title.

    Args:
        title (str): The criterion title to extract from

    Returns:
        str or None: The extracted question number or None if not found

    Examples:
        >>> extract_question_number("Question 1: Introduction")
        '1'
        >>> extract_question_number("Question 2a: Part 1")
        '2'
        >>> extract_question_number("Not a question")
        None
    """
    if not isinstance(title, str) or not title.startswith("Question "):
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