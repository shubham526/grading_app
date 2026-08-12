"""
Roster and student-list helpers for question-centric grading.

The v2.1 question-by-question workflow needs a stable list of students before
all assessment files necessarily exist.  This module keeps student discovery
and roster parsing independent of the PyQt UI so the same model can be reused
by later submission-ingestion releases.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import csv
import json
import os
import re
from typing import Iterable, List, Optional, Sequence


@dataclass
class StudentRecord:
    """One student in a grading session."""

    student_id: str
    student_name: str
    assessment_path: Optional[str] = None

    @property
    def display_name(self) -> str:
        if self.student_name and self.student_id and self.student_name != self.student_id:
            return f"{self.student_name} ({self.student_id})"
        return self.student_name or self.student_id


def normalize_student_key(value: object) -> str:
    """Normalize an ID/name for conservative cross-source matching."""
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def safe_student_filename(value: str) -> str:
    """Return a filesystem-safe stem for a student assessment filename."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip()).strip("._-")
    return stem or "unnamed_student"


def assessment_path_for_student(student: StudentRecord, assessments_dir: str) -> str:
    """Return the existing or default assessment path for ``student``."""
    if student.assessment_path:
        return student.assessment_path

    identity = student.student_id or student.student_name
    return os.path.join(assessments_dir, f"{safe_student_filename(identity)}.json")


def load_roster_csv(file_path: str) -> List[StudentRecord]:
    """
    Load a roster CSV with ``student_id,student_name`` columns.

    Header matching is case-insensitive and surrounding whitespace is ignored.
    Blank rows are skipped. Duplicate non-empty student IDs are rejected because
    they would make assessment-path and progress matching ambiguous.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Roster file not found: {file_path}")

    records: List[StudentRecord] = []
    seen_ids = set()

    with open(file_path, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("Roster CSV is missing a header row.")

        header_map = {str(name).strip().casefold(): name for name in reader.fieldnames if name}
        if "student_id" not in header_map or "student_name" not in header_map:
            raise ValueError(
                "Roster CSV must contain columns named 'student_id' and 'student_name'."
            )

        id_header = header_map["student_id"]
        name_header = header_map["student_name"]

        for row_number, row in enumerate(reader, start=2):
            student_id = str(row.get(id_header, "") or "").strip()
            student_name = str(row.get(name_header, "") or "").strip()

            if not student_id and not student_name:
                continue
            if not student_id:
                # Manual/name-only records remain supported, but derive a stable
                # ID token so progress and filenames have an identity.
                student_id = safe_student_filename(student_name)
            if not student_name:
                student_name = student_id

            key = normalize_student_key(student_id)
            if key in seen_ids:
                raise ValueError(
                    f"Duplicate student_id '{student_id}' in roster row {row_number}."
                )
            seen_ids.add(key)
            records.append(StudentRecord(student_id=student_id, student_name=student_name))

    if not records:
        raise ValueError("Roster CSV contains no students.")

    return records


def _load_assessment_identity(path: str) -> Optional[StudentRecord]:
    """Load just enough of a JSON file to decide whether it is a student assessment."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(data, dict) or not isinstance(data.get("criteria"), list):
        return None

    student_id = str(data.get("student_id") or "").strip()
    student_name = str(data.get("student_name") or "").strip()
    if not student_id and not student_name:
        return None

    if not student_id:
        # Existing v2.0 assessments typically have only student_name. Use the
        # filename stem as the stable ID when possible, matching the design's
        # assessments/alice.json convention.
        student_id = os.path.splitext(os.path.basename(path))[0] or safe_student_filename(student_name)
    if not student_name:
        student_name = student_id

    return StudentRecord(
        student_id=student_id,
        student_name=student_name,
        assessment_path=os.path.abspath(path),
    )


def load_students_from_assessment_dir(assessments_dir: str) -> List[StudentRecord]:
    """Discover students from valid assessment JSON files in a directory."""
    if not assessments_dir or not os.path.isdir(assessments_dir):
        raise ValueError(f"Assessment directory does not exist: {assessments_dir}")

    records: List[StudentRecord] = []
    for filename in sorted(os.listdir(assessments_dir)):
        if not filename.lower().endswith(".json"):
            continue
        record = _load_assessment_identity(os.path.join(assessments_dir, filename))
        if record is not None:
            records.append(record)

    return records


def _record_aliases(record: StudentRecord) -> Iterable[str]:
    for value in (record.student_id, record.student_name):
        key = normalize_student_key(value)
        if key:
            yield key


def merge_student_records(
    roster_records: Sequence[StudentRecord],
    assessment_records: Sequence[StudentRecord],
    assessments_dir: Optional[str] = None,
) -> List[StudentRecord]:
    """
    Merge a roster with discovered assessment files.

    Roster order is preserved. Existing assessment paths are attached by ID or,
    for legacy files, by student name. Assessment-only students are appended so
    no existing work disappears merely because a roster is incomplete.
    """
    assessment_by_alias = {}
    for record in assessment_records:
        for alias in _record_aliases(record):
            assessment_by_alias.setdefault(alias, record)

    merged: List[StudentRecord] = []
    used_assessment_paths = set()

    for roster_record in roster_records:
        match = None
        for alias in _record_aliases(roster_record):
            if alias in assessment_by_alias:
                match = assessment_by_alias[alias]
                break

        if match is not None:
            path = match.assessment_path
            used_assessment_paths.add(os.path.abspath(path) if path else "")
            merged.append(replace(roster_record, assessment_path=path))
        elif assessments_dir:
            merged.append(
                replace(
                    roster_record,
                    assessment_path=assessment_path_for_student(roster_record, assessments_dir),
                )
            )
        else:
            merged.append(replace(roster_record))

    for assessment_record in assessment_records:
        normalized_path = (
            os.path.abspath(assessment_record.assessment_path)
            if assessment_record.assessment_path else ""
        )
        if normalized_path and normalized_path in used_assessment_paths:
            continue

        # Avoid appending an assessment-only record that already matched the
        # roster by another alias but happened to have no path.
        assessment_aliases = set(_record_aliases(assessment_record))
        if any(assessment_aliases.intersection(set(_record_aliases(r))) for r in merged):
            continue
        merged.append(replace(assessment_record))

    return merged
