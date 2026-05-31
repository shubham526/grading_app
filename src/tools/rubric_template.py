"""
Rubric Template Generator — Rubric Grading Tool (Phase 5 rewrite)
==================================================================

Creates new rubric JSON files from:
  1. Pre-built templates in ``templates/<course>/``
  2. An outcome profile (for blank rubrics with profile metadata)
  3. Programmatically-defined criteria dicts

All generated rubrics are schema 2.0 with:
  - stable criterion IDs
  - course_outcomes, program_outcomes, abet_outcomes, assessment_tags
  - outcome_profile field pointing at the loaded profile

CLI usage::

    # List available templates
    python -m src.tools.rubric_template list

    # Create from a template file
    python -m src.tools.rubric_template from-template templates/cs2500/ps_greedy.json \\
        --output my_ps3.json --title "PS3 - Greedy Algorithms"

    # Create a blank rubric pre-wired to a profile
    python -m src.tools.rubric_template blank --profile cs2500_algorithms \\
        --title "Midterm 2" --output midterm2_rubric.json

    # Create from the old built-in named templates (backward compat)
    python -m src.tools.rubric_template essay my_essay.json
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import List, Optional

# ---------------------------------------------------------------------------
# Built-in legacy templates (kept for backward compat with old callers)
# ---------------------------------------------------------------------------

_LEGACY_TEMPLATES = {
    "essay": {
        "title": "Essay Assignment",
        "criteria": [
            {"title": "Thesis Statement",          "points": 10},
            {"title": "Organization",               "points": 20},
            {"title": "Evidence & Support",         "points": 25},
            {"title": "Analysis & Critical Thinking", "points": 25},
            {"title": "Grammar & Mechanics",        "points": 10},
            {"title": "Style & Voice",              "points": 10},
        ],
    },
    "presentation": {
        "title": "Oral Presentation",
        "criteria": [
            {"title": "Content & Organization",   "points": 30},
            {"title": "Delivery & Speaking Skills", "points": 25},
            {"title": "Visual Aids",               "points": 20},
            {"title": "Audience Interaction",      "points": 15},
            {"title": "Time Management",           "points": 10},
        ],
    },
    "project": {
        "title": "Group Project",
        "criteria": [
            {"title": "Project Outcome",      "points": 40},
            {"title": "Methodology",          "points": 20},
            {"title": "Teamwork",             "points": 15},
            {"title": "Documentation",        "points": 15},
            {"title": "Presentation",         "points": 10},
        ],
    },
    "empty": {
        "title": "New Rubric",
        "criteria": [
            {"title": "Criterion 1", "points": 25},
            {"title": "Criterion 2", "points": 25},
            {"title": "Criterion 3", "points": 25},
            {"title": "Criterion 4", "points": 25},
        ],
    },
}

_DEFAULT_LEVELS = [
    ("Excellent",         "Exceeds expectations",         100),
    ("Good",              "Meets all expectations",        80),
    ("Satisfactory",      "Meets basic expectations",      60),
    ("Needs Improvement", "Partially meets expectations",  40),
    ("Unsatisfactory",    "Does not meet expectations",    20),
]


# ---------------------------------------------------------------------------
# Template discovery
# ---------------------------------------------------------------------------

def _template_root() -> str:
    """Return the repo-level templates/ directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "templates"))


def list_template_files() -> List[str]:
    """Return all .json template paths relative to the templates/ root."""
    root = _template_root()
    paths: List[str] = []
    if not os.path.isdir(root):
        return paths
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if f.endswith(".json"):
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                paths.append(rel)
    return paths


def load_template_file(rel_or_abs_path: str) -> dict:
    """
    Load a template JSON file.

    Accepts either an absolute path or a path relative to templates/.
    """
    if os.path.isabs(rel_or_abs_path) or os.path.exists(rel_or_abs_path):
        path = rel_or_abs_path
    else:
        path = os.path.join(_template_root(), rel_or_abs_path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Template not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Core creation functions
# ---------------------------------------------------------------------------

def create_from_template_file(
    template_path: str,
    output_path: str,
    title: Optional[str] = None,
    assessment_id: Optional[str] = None,
    course_code: Optional[str] = None,
    semester: Optional[str] = None,
) -> dict:
    """
    Create a new rubric JSON from an existing template file.

    Stamps the new rubric with schema 2.0, a fresh assessment_id (if given),
    and an optional title override.  All criteria IDs, outcome fields, and
    tags from the template are preserved.

    Returns the rubric dict (also written to output_path).
    """
    template = load_template_file(template_path)

    rubric = dict(template)
    rubric["schema_version"] = "2.0"
    if title:
        rubric["title"] = title
    if assessment_id:
        rubric["assessment_id"] = assessment_id
    if course_code:
        rubric["course_code"] = course_code
    if semester:
        rubric["semester"] = semester

    rubric["created_from_template"] = os.path.basename(template_path)
    rubric["created_date"]          = datetime.now().isoformat()

    # Ensure every criterion has stable IDs and outcome fields
    from src.core.rubric import _ensure_criterion_ids
    _ensure_criterion_ids(rubric)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(rubric, fh, indent=2, ensure_ascii=False)

    return rubric


def create_blank_rubric(
    output_path: str,
    title: str = "New Rubric",
    profile_id: str = "cs2500_algorithms",
    num_questions: int = 5,
    points_each: int = 20,
) -> dict:
    """
    Create a blank ABET-ready rubric wired to a specific outcome profile.

    Each question criterion has empty outcome lists ready to be filled via
    the ABET Mapping dialog or auto-map.

    Returns the rubric dict (also written to output_path).
    """
    rubric = {
        "schema_version": "2.0",
        "title":          title,
        "profile_id":     profile_id,
        "outcome_profile": profile_id,
        "created_date":   datetime.now().isoformat(),
        "criteria": [],
    }

    for i in range(1, num_questions + 1):
        rubric["criteria"].append({
            "id":               f"Q{i}_CRITERION",
            "title":            f"Question {i}",
            "description":      "",
            "points":           points_each,
            "course_outcomes":  [],
            "program_outcomes": [],
            "abet_outcomes":    [],
            "assessment_tags":  [],
            "levels": [
                {"title": "Complete",    "points": points_each,     "description": ""},
                {"title": "Partial",     "points": points_each // 2,"description": ""},
                {"title": "Incorrect",   "points": 0,               "description": ""},
            ],
        })

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(rubric, fh, indent=2, ensure_ascii=False)

    return rubric


def create_rubric_template(
    template_name: str,
    output_path: str,
    title: Optional[str] = None,
    include_levels: bool = True,
    scale: int = 100,
) -> bool:
    """
    Legacy function: create from one of the built-in named templates.
    Kept for backward compat with existing callers.
    """
    if template_name not in _LEGACY_TEMPLATES:
        print(f"Unknown template: {template_name}")
        print(f"Available: {', '.join(_LEGACY_TEMPLATES.keys())}")
        return False

    template = dict(_LEGACY_TEMPLATES[template_name])
    if title:
        template["title"] = title

    template["schema_version"] = "2.0"

    total_pts = sum(c["points"] for c in template["criteria"])
    factor    = scale / total_pts

    for idx, criterion in enumerate(template["criteria"]):
        pts = round(criterion["points"] * factor)
        criterion["points"] = pts
        criterion.setdefault("id",               "")
        criterion.setdefault("course_outcomes",  [])
        criterion.setdefault("program_outcomes", [])
        criterion.setdefault("abet_outcomes",    [])
        criterion.setdefault("assessment_tags",  [])

        if include_levels:
            criterion["levels"] = [
                {
                    "title":       lv_title,
                    "description": lv_desc,
                    "points":      round(pts * lv_pct / 100),
                }
                for lv_title, lv_desc, lv_pct in _DEFAULT_LEVELS
            ]

    from src.core.rubric import _ensure_criterion_ids
    _ensure_criterion_ids(template)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(template, fh, indent=2, ensure_ascii=False)
        print(f"Template created: {output_path}")
        return True
    except Exception as e:
        print(f"Error writing template: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rubric template generator (Phase 5).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    # list
    sub.add_parser("list", help="List available template files and legacy templates.")

    # from-template
    ft = sub.add_parser("from-template",
                        help="Create a rubric from a template JSON file.")
    ft.add_argument("template",   help="Path to template JSON (abs or relative to templates/).")
    ft.add_argument("--output",   required=True, help="Output path for new rubric JSON.")
    ft.add_argument("--title",    help="Override rubric title.")
    ft.add_argument("--id",       dest="assessment_id", help="Assessment ID (e.g. F2026_PS3).")
    ft.add_argument("--course",   dest="course_code",   help="Course code.")
    ft.add_argument("--semester", help="Semester string.")

    # blank
    bl = sub.add_parser("blank", help="Create a blank ABET-ready rubric.")
    bl.add_argument("--output",    required=True, help="Output path.")
    bl.add_argument("--title",     default="New Rubric", help="Rubric title.")
    bl.add_argument("--profile",   default="cs2500_algorithms", help="Outcome profile ID.")
    bl.add_argument("--questions", type=int, default=5, help="Number of question criteria.")
    bl.add_argument("--points",    type=int, default=20, help="Points per question.")

    # Legacy named templates (backward compat)
    for name in _LEGACY_TEMPLATES:
        lp = sub.add_parser(name, help=f"Legacy: create {name} template.")
        lp.add_argument("output",           help="Output path.")
        lp.add_argument("--title",          help="Override title.")
        lp.add_argument("--no-levels",      action="store_true")
        lp.add_argument("--scale", type=int, default=100)

    args = parser.parse_args()

    if args.cmd is None or args.cmd == "list":
        print("=== Template files (templates/) ===")
        for t in list_template_files():
            print(f"  {t}")
        print("\n=== Legacy named templates ===")
        for name, tmpl in _LEGACY_TEMPLATES.items():
            print(f"  {name}: {tmpl['title']}")
        return 0

    if args.cmd == "from-template":
        try:
            rubric = create_from_template_file(
                args.template, args.output,
                title=args.title,
                assessment_id=getattr(args, "assessment_id", None),
                course_code=getattr(args, "course_code", None),
                semester=getattr(args, "semester", None),
            )
            print(f"Created: {args.output}  ({len(rubric['criteria'])} criteria)")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    if args.cmd == "blank":
        rubric = create_blank_rubric(
            args.output, title=args.title,
            profile_id=args.profile,
            num_questions=args.questions,
            points_each=args.points,
        )
        print(f"Created blank rubric: {args.output}  ({len(rubric['criteria'])} criteria)")
        return 0

    if args.cmd in _LEGACY_TEMPLATES:
        result = create_rubric_template(
            args.cmd, args.output,
            title=args.title,
            include_levels=not args.no_levels,
            scale=args.scale,
        )
        return 0 if result else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
