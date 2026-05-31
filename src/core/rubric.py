"""
Rubric module for the Rubric Grading Tool.

Schema version 2.0 additions:
  - Stable criterion IDs generated on load if missing (rubric marked dirty).
  - Embedded course_outcomes, abet_outcomes, assessment_tags per criterion.
  - assessment_id and schema_version at rubric level.
  - save_rubric() persists IDs and metadata without silent overwrites.
"""

import os
import json
import csv
from typing import Optional, Tuple, Dict

from .utils import generate_criterion_id

SCHEMA_VERSION = "2.0"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rubric_from_file(file_path: str) -> Tuple[dict, bool]:
    """
    Load a rubric from a JSON or CSV file.

    Returns:
        (rubric_data, is_dirty)
        is_dirty is True when IDs were auto-generated (caller should offer to save).

    Raises:
        ValueError: unsupported format or invalid structure.
        FileNotFoundError: file not found.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Rubric file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".json":
        rubric_data, is_dirty = load_json_rubric(file_path)
    elif ext == ".csv":
        rubric_data = load_csv_rubric(file_path)
        is_dirty = True  # CSV rubrics never have IDs
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    return rubric_data, is_dirty


def load_json_rubric(file_path: str) -> Tuple[dict, bool]:
    """
    Load a rubric from a JSON file.

    Returns:
        (rubric_data, is_dirty)
    """
    with open(file_path, "r", encoding="utf-8") as fh:
        rubric_data = json.load(fh)

    if not isinstance(rubric_data, dict):
        raise ValueError("Invalid rubric format: root must be an object")
    if "criteria" not in rubric_data or not isinstance(rubric_data["criteria"], list):
        raise ValueError("Invalid rubric format: missing 'criteria' array")

    # Default title
    if "title" not in rubric_data:
        rubric_data["title"] = os.path.basename(file_path)

    # Ensure schema_version present
    rubric_data.setdefault("schema_version", SCHEMA_VERSION)

    # Generate IDs for any criterion that lacks one — mark dirty
    is_dirty = _ensure_criterion_ids(rubric_data)

    return rubric_data, is_dirty


def load_csv_rubric(file_path: str) -> dict:
    """Load a rubric from a CSV file (IDs always generated in-memory)."""
    rubric = {
        "schema_version": SCHEMA_VERSION,
        "title": os.path.splitext(os.path.basename(file_path))[0],
        "criteria": [],
    }

    with open(file_path, "r", newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader, None)
        if not headers:
            return rubric

        for idx, row in enumerate(reader):
            if len(row) < 3 or not row[0].strip():
                continue

            criterion = {
                "id": generate_criterion_id(row[0].strip(), idx),
                "title": row[0].strip(),
                "description": row[1].strip() if len(row) > 1 else "",
                "points": int(row[2]) if len(row) > 2 and row[2].strip().isdigit() else 10,
                "course_outcomes": [],
                "abet_outcomes": [],
                "assessment_tags": [],
            }

            if len(row) > 3:
                levels = []
                for i in range(3, len(row), 2):
                    if i + 1 < len(row) and row[i].strip() and row[i + 1].strip():
                        try:
                            pts = float(row[i + 1])
                        except ValueError:
                            pts = 0.0
                        levels.append({"title": row[i].strip(), "points": pts, "description": ""})
                if levels:
                    criterion["levels"] = levels

            rubric["criteria"].append(criterion)

    _ensure_criterion_ids(rubric)
    return rubric


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_rubric(rubric_data: dict, file_path: str) -> None:
    """
    Save rubric to a JSON file, persisting all IDs and ABET metadata.
    Does NOT silently overwrite; caller must choose the path explicitly.
    """
    # Ensure every criterion has an ID before saving
    _ensure_criterion_ids(rubric_data)
    rubric_data["schema_version"] = SCHEMA_VERSION

    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(rubric_data, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_criterion_ids(rubric_data: dict) -> bool:
    """
    Assign a stable ID to every criterion that lacks one.
    Normalise field names: ``abet_outcomes`` → ``program_outcomes`` (keeps both).

    Rules (Fix 7):
      - Missing id        → generate, mark dirty.
      - Generated id collision → append suffix, mark dirty.
      - Manual id collision   → leave untouched; validation reports DUPLICATE_ID.

    Returns True if any IDs were generated (rubric is dirty), False otherwise.
    """
    dirty    = False
    seen_ids: Dict[str, int] = {}

    for idx, criterion in enumerate(rubric_data.get("criteria", [])):
        was_missing = not criterion.get("id")

        if was_missing:
            criterion["id"] = generate_criterion_id(
                criterion.get("title", ""), idx
            )
            dirty = True

        # Ensure outcome fields exist and stay in sync.
        # Canonical name is program_outcomes; abet_outcomes is a backward-compat alias.
        # Three cases:
        #   A. program_outcomes present, abet_outcomes absent → populate alias
        #   B. abet_outcomes present (legacy), program_outcomes absent → normalise + populate alias
        #   C. neither present → default both to []
        criterion.setdefault("assessment_tags", [])
        criterion.setdefault("course_outcomes",  [])

        has_po = bool(criterion.get("program_outcomes"))
        has_ao = bool(criterion.get("abet_outcomes"))

        if has_po and not has_ao:
            # Case A: canonical present, alias missing
            criterion["abet_outcomes"] = list(criterion["program_outcomes"])
        elif has_ao and not has_po:
            # Case B: legacy field present, normalise to canonical
            criterion["program_outcomes"] = list(criterion["abet_outcomes"])
        else:
            # Case C: both absent (or both already present → keep both)
            criterion.setdefault("program_outcomes", [])
            criterion.setdefault("abet_outcomes",    [])
            # If both were provided, keep both as-is (caller's responsibility)

        cid = criterion["id"]
        if cid in seen_ids:
            if was_missing:
                criterion["id"] = f"{cid}_{idx:03d}"
                dirty = True
            # else: manual duplicate — leave for validation
        else:
            seen_ids[cid] = idx

    return dirty


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_rubric(rubric_data: dict) -> bool:
    """Basic structural validation. Returns True if valid."""
    if not isinstance(rubric_data, dict):
        return False
    if "criteria" not in rubric_data or not isinstance(rubric_data["criteria"], list):
        return False
    if not rubric_data["criteria"]:
        return False

    for criterion in rubric_data["criteria"]:
        if not isinstance(criterion, dict):
            return False
        if "title" not in criterion or "points" not in criterion:
            return False
        if "levels" in criterion:
            if not isinstance(criterion["levels"], list):
                return False
            for level in criterion["levels"]:
                if not isinstance(level, dict):
                    return False
                if "title" not in level or "points" not in level:
                    return False
    return True


# ---------------------------------------------------------------------------
# Utility queries
# ---------------------------------------------------------------------------

def get_total_points(rubric_data: dict) -> int:
    if not rubric_data or "criteria" not in rubric_data:
        return 0
    return sum(c.get("points", 0) for c in rubric_data["criteria"])


def get_criterion_by_id(rubric_data: dict, criterion_id: str) -> Optional[dict]:
    """Look up a criterion by its stable ID."""
    for c in rubric_data.get("criteria", []):
        if c.get("id") == criterion_id:
            return c
    return None


def get_criterion_by_title(rubric_data: dict, title: str) -> Optional[dict]:
    """Legacy lookup by title (fallback for old data)."""
    for c in rubric_data.get("criteria", []):
        if c.get("title") == title:
            return c
    return None


def group_criteria_by_question(rubric_data: dict) -> dict:
    """Group criteria by their main question number."""
    from .utils import extract_question_number

    groups: dict = {}
    for criterion in rubric_data.get("criteria", []):
        qn = extract_question_number(criterion.get("title", ""))
        if qn:
            groups.setdefault(qn, []).append(criterion)
    return groups
