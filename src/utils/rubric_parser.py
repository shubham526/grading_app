"""
Rubric Parser — Rubric Grading Tool
=====================================

Thin compatibility shim.  All real loading now goes through
``src.core.rubric.load_rubric_from_file`` which handles:
  - Schema version stamping
  - Stable criterion ID generation
  - program_outcomes / abet_outcomes normalisation
  - Dirty-flag tracking

These functions are kept for backward compatibility with existing callers
(old tests, external scripts).  They return plain dicts (no tuple).
"""

import os
import json
import csv


def parse_rubric_file(file_path: str) -> dict:
    """
    Parse a rubric file (JSON or CSV) and return the rubric dict.

    Delegates to src.core.rubric so that ID generation, schema versioning,
    and outcome-field normalisation all happen in one place.

    Returns:
        dict — fully normalised rubric data (schema_version, IDs, outcome fields)
    Raises:
        FileNotFoundError, ValueError
    """
    from src.core.rubric import load_rubric_from_file
    rubric, _is_dirty = load_rubric_from_file(file_path)
    return rubric


def parse_json_rubric(file_path: str) -> dict:
    """Parse a JSON rubric file.  Returns plain dict (no dirty flag)."""
    from src.core.rubric import load_json_rubric
    rubric, _is_dirty = load_json_rubric(file_path)
    return rubric


def parse_csv_rubric(file_path: str) -> dict:
    """Parse a CSV rubric file.  Returns plain dict."""
    from src.core.rubric import load_csv_rubric
    return load_csv_rubric(file_path)
