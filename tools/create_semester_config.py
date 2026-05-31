#!/usr/bin/env python3
"""
create_semester_config.py
=========================

Generate a semester config JSON by scanning a semester folder.

Expected folder layout::

    CS2500_Fall2026/
        PS1/
            assessments/   ← contains graded student JSONs
            rubric.json    ← optional
        PS2/assessments/
        Midterm/assessments/
        Final/assessments/

Usage::

    python tools/create_semester_config.py \\
        --folder CS2500_Fall2026/ \\
        --output CS2500_Fall2026/semester.json \\
        --course "CS 2500" \\
        --name "Algorithms" \\
        --semester "Fall 2026" \\
        --profile cs2500_algorithms \\
        --target 75

The generated semester.json can be loaded directly by:
  - SemesterABETReport.from_config()
  - SemesterABETReportDialog (Load semester config… button)
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def scan_semester_folder(folder: str, weight: float = 1.0) -> list:
    """
    Scan a semester folder and return a list of assessment config dicts.

    Each sub-directory that contains an assessments/ sub-folder with at
    least one JSON file is treated as one assessment.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Semester folder not found: {folder}")

    entries = []
    for name in sorted(os.listdir(folder)):
        sub = os.path.join(folder, name)
        if not os.path.isdir(sub):
            continue
        adir = os.path.join(sub, "assessments")
        if not os.path.isdir(adir):
            continue
        jsons = [f for f in os.listdir(adir) if f.endswith(".json")]
        if not jsons:
            continue

        # Look for an associated rubric
        rubric_path = ""
        for rname in ("rubric.json", f"{name.lower()}_rubric.json"):
            candidate = os.path.join(sub, rname)
            if os.path.exists(candidate):
                rubric_path = candidate
                break

        entries.append({
            "assessment_id":   f"{name.upper()}",
            "assessment_name": name,
            "assessment_dir":  adir,
            "rubric_path":     rubric_path,
            "include_in_abet": True,
            "weight":          weight,
        })

    return entries


def create_semester_config(
    folder:      str,
    output_path: str,
    course_code: str = "",
    course_name: str = "",
    semester:    str = "",
    instructor:  str = "",
    profile_id:  str = "cs2500_algorithms",
    target_pct:  float = 75.0,
    weight:      float = 1.0,
) -> dict:
    """
    Build and write a semester config JSON.

    All assessment_dir and rubric_path values are stored as paths relative
    to the directory that contains output_path.  This keeps the semester
    folder portable — you can move the whole tree and the config still works.

    Returns the config dict.
    """
    assessments = scan_semester_folder(folder, weight=weight)

    # Resolve paths relative to the config file's directory so the
    # semester folder is self-contained (Fix 1).
    base_dir = os.path.dirname(os.path.abspath(output_path))
    for a in assessments:
        a["assessment_dir"] = os.path.relpath(
            os.path.abspath(a["assessment_dir"]), base_dir)
        if a.get("rubric_path"):
            a["rubric_path"] = os.path.relpath(
                os.path.abspath(a["rubric_path"]), base_dir)

    config = {
        "schema_version":      "2.0",
        "course_code":          course_code,
        "course_name":          course_name,
        "semester":             semester,
        "instructor":           instructor,
        "profile_id":           profile_id,
        "target_percentage":    target_pct,
        "created_date":         datetime.now().isoformat(),
        "assessments":          assessments,
        "reflection":           "",
        "planned_improvements": "",
        "notes_for_next_offering": "",
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)

    return config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a semester config JSON from a semester folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--folder",    required=True,
                        help="Path to the semester folder.")
    parser.add_argument("--output",    required=True,
                        help="Output path for the semester config JSON.")
    parser.add_argument("--course",    default="",   dest="course_code",
                        help="Course code (e.g. 'CS 2500').")
    parser.add_argument("--name",      default="",   dest="course_name",
                        help="Course name (e.g. 'Algorithms').")
    parser.add_argument("--semester",  default="",
                        help="Semester string (e.g. 'Fall 2026').")
    parser.add_argument("--instructor", default="",
                        help="Instructor name.")
    parser.add_argument("--profile",   default="cs2500_algorithms",
                        help="Outcome profile ID.")
    parser.add_argument("--target",    type=float, default=75.0,
                        help="Target passing percentage (default: 75).")
    parser.add_argument("--weight",    type=float, default=1.0,
                        help="Default assignment weight (default: 1.0).")
    parser.add_argument("--print",     action="store_true",
                        help="Print the config to stdout after writing.")

    args = parser.parse_args()

    try:
        config = create_semester_config(
            folder      = args.folder,
            output_path = args.output,
            course_code = args.course_code,
            course_name = args.course_name,
            semester    = args.semester,
            instructor  = args.instructor,
            profile_id  = args.profile,
            target_pct  = args.target,
            weight      = args.weight,
        )
    except Exception as exc:
        print(f"[create_semester_config] ERROR: {exc}", file=sys.stderr)
        return 1

    n = len(config["assessments"])
    print(f"[create_semester_config] Found {n} assessment(s):")
    config_dir = os.path.dirname(os.path.abspath(args.output))

    for a in config["assessments"]:
        rubric_note = f"  (rubric: {os.path.basename(a['rubric_path'])})" \
            if a["rubric_path"] else ""

        assessment_dir = a["assessment_dir"]
        if not os.path.isabs(assessment_dir):
            assessment_dir = os.path.join(config_dir, assessment_dir)

        n_files = len([
            f for f in os.listdir(assessment_dir)
            if f.endswith(".json")
        ])

        print(f"  {a['assessment_name']:<20}  {n_files} student files{rubric_note}")

    print(f"\n[create_semester_config] Config written to: {args.output}")

    if args.print:
        print(json.dumps(config, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
