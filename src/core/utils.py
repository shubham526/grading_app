import re


# ---------------------------------------------------------------------------
# Criterion ID generation
# ---------------------------------------------------------------------------

def normalize_title_to_id(title: str) -> str:
    """
    Convert a human-readable criterion title to a stable uppercase ID token.

    Examples:
        "Question 2 - Runtime Analysis" -> "QUESTION_2_RUNTIME_ANALYSIS"
        "Q3: Correctness Proof"         -> "Q3_CORRECTNESS_PROOF"
    """
    # Uppercase
    s = title.upper()
    # Replace any non-alphanumeric run with a single underscore
    s = re.sub(r'[^A-Z0-9]+', '_', s)
    # Strip leading/trailing underscores
    s = s.strip('_')
    return s


def generate_criterion_id(title: str, index: int, assessment_prefix: str = "") -> str:
    """
    Generate a stable machine-readable criterion ID.

    Preferred format:  <ASSESSMENT>_<QUESTION>_<SKILL>
    Fallback format:   CRITERION_<index:03d>

    Args:
        title:             The criterion title string.
        index:             Zero-based position of the criterion in the rubric
                           (used as fallback).
        assessment_prefix: Optional prefix such as "PS3" or "MIDTERM".

    Returns:
        A stable uppercase ID string, e.g. "PS3_Q2_RUNTIME_ANALYSIS".
    """
    if not title or not title.strip():
        return f"CRITERION_{index:03d}"

    normalized = normalize_title_to_id(title)
    if not normalized:
        return f"CRITERION_{index:03d}"

    if assessment_prefix:
        prefix = normalize_title_to_id(assessment_prefix)
        return f"{prefix}_{normalized}"

    return normalized


def extract_question_number(title):
    """
    Extract a normalized main question identifier from rubric titles.

    Examples:
        Question 1: Intro                    -> 1
        Question 2a: Part 1                  -> 2
        Question A.1(a)                      -> A.1
        Section B: Question 2(b)             -> B.2
        Bonus Question 1(a)(i)               -> BONUS.1
        Part I Question 1(a)(i)              -> I.1
        Part II: Section B: Question 2(b)    -> II.B.2
    """
    if not isinstance(title, str):
        return None

    title = title.strip()

    # Only treat Part as structural if it appears at the beginning
    part_match = re.match(r'^\s*Part\s+([A-Z0-9]+)\b[:\s,-]*', title, re.IGNORECASE)

    # Section can appear after Part, or by itself
    section_match = re.search(r'\bSection\s+([A-Z0-9]+)\b', title, re.IGNORECASE)

    # Bonus should also be treated as structural only near the beginning
    bonus_match = re.match(r'^\s*(?:Part\s+[A-Z0-9]+\s*)?Bonus\b', title, re.IGNORECASE)

    # Main question identifier
    q_match = re.search(
        r'\b(?:Question|Q)\s*([A-Z]+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)',
        title,
        re.IGNORECASE
    )

    parts = []

    if part_match:
        parts.append(part_match.group(1).upper())

    if bonus_match:
        parts.append("BONUS")

    if section_match:
        parts.append(section_match.group(1).upper())

    if q_match:
        q_id = q_match.group(1).upper()

        # Avoid duplication like "Section A: Question A.1"
        if parts:
            last = parts[-1]
            if q_id.startswith(last + "."):
                return ".".join(parts[:-1] + [q_id])

        parts.append(q_id)
        return ".".join(parts)

    if parts:
        return ".".join(parts)

    return None