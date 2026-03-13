import re

def extract_question_number(title):
    """
    Extract the main question number or section/question composite from a criterion title.

    Args:
        title (str): The criterion title to extract from

    Returns:
        str or None: The extracted main question identifier, or None if not found

    Examples:
        >>> extract_question_number("Question 1: Introduction")
        '1'
        >>> extract_question_number("Question 2a: Part 1")
        '2'
        >>> extract_question_number("Question A.1(a)")
        'A.1'
        >>> extract_question_number("Section B: Question 2(b)")
        'B.2'
    """
    if not isinstance(title, str):
        return None

    # 1. Check for a Section identifier (e.g., "Section A")
    section_match = re.search(r'Section\s+([A-Z0-9]+)', title, re.IGNORECASE)

    # 2. Extract the base question identifier
    # Matches:
    #   Question 1      -> 1
    #   Question 2a     -> 2
    #   Question A.1(a) -> A.1
    #   Q 11            -> 11
    q_match = re.search(
        r'(?:Question|Q)\s*([A-Z]+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)',
        title,
        re.IGNORECASE
    )

    if section_match and q_match:
        q_id = q_match.group(1).upper()
        s_id = section_match.group(1).upper()

        # Prevent duplication if question already includes section
        if q_id.startswith(s_id + "."):
            return q_id
        return f"{s_id}.{q_id}"

    if q_match:
        return q_match.group(1).upper()

    if section_match:
        return section_match.group(1).upper()

    return None