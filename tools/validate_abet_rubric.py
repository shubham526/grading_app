#!/usr/bin/env python3
"""
validate_abet_rubric.py
=======================

Validate an ABET-aware rubric and/or a directory of student assessments
before generating a report.  Prints ERROR / WARNING / INFO messages.

Usage::

    # Validate a rubric file alone
    python tools/validate_abet_rubric.py --rubric rubric.json

    # Validate rubric + assessments directory
    python tools/validate_abet_rubric.py \\
        --rubric PS3/rubric.json \\
        --assessments PS3/assessments/ \\
        --profile cs2500_algorithms

    # Fail with exit-code 1 if any ERRORs (useful in CI)
    python tools/validate_abet_rubric.py --rubric rubric.json --strict

    # JSON output for machine consumption
    python tools/validate_abet_rubric.py --rubric rubric.json --json
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_assessments(directory: str, quiet: bool = False):
    assessments = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path) as fh:
                data = json.load(fh)
            if "criteria" in data:
                assessments.append(data)
        except Exception as exc:
            # Always print to stderr so JSON stdout is never corrupted (Fix 4)
            print(f"  [SKIP] {os.path.basename(path)}: {exc}", file=sys.stderr)
    return assessments


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate ABET rubric and/or assessment collection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--rubric",      metavar="FILE",
                        help="Rubric JSON file to validate.")
    parser.add_argument("--assessments", metavar="DIR",
                        help="Directory of student assessment JSON files.")
    parser.add_argument("--profile",     default="cs2500_algorithms",
                        help="Outcome profile ID for known-ID validation.")
    parser.add_argument("--policy",      default="counted_only",
                        choices=["counted_only", "selected_only", "all"])
    parser.add_argument("--strict",      action="store_true",
                        help="Exit with code 1 if any ERROR-level issues found.")
    parser.add_argument("--json",        action="store_true",
                        help="Output validation results as JSON instead of text.")

    args = parser.parse_args()

    if not args.rubric and not args.assessments:
        parser.error("Provide at least --rubric or --assessments.")

    # Load profile
    profile = None
    lo_ids, so_ids = None, None
    try:
        from src.core.outcome_profile import load_profile
        profile = load_profile(args.profile)
        lo_ids  = list(profile.course_outcomes.keys())
        so_ids  = list(profile.program_outcomes.keys())
    except FileNotFoundError:
        msg = (f"[validate] WARNING: Profile '{args.profile}' not found; "
               f"ID-based validation disabled.")
        # Always stderr — must not corrupt JSON stdout (Fix 4)
        print(msg, file=sys.stderr)

    # Load rubric
    rubric = {"criteria": []}
    if args.rubric:
        if not os.path.exists(args.rubric):
            print(f"[validate] ERROR: Rubric file not found: {args.rubric}")
            return 1
        with open(args.rubric) as fh:
            rubric = json.load(fh)

    # Load assessments
    assessments = []
    if args.assessments:
        if not os.path.isdir(args.assessments):
            print(f"[validate] ERROR: Assessments directory not found: {args.assessments}")
            return 1
        assessments = load_assessments(args.assessments, quiet=args.json)
        if not args.json:
            print(f"[validate] Loaded {len(assessments)} assessment(s).")

    # Run validation
    from src.tools.abet_validation import validate_all, has_errors, issues_summary

    issues = validate_all(rubric, assessments, lo_ids, so_ids, policy=args.policy)
    summary = issues_summary(issues)

    # Output
    if args.json:
        print(json.dumps({"summary": summary, "issues": issues}, indent=2))
    else:
        print(f"\n=== ABET Validation: {summary} ===\n")
        if not issues:
            print("  ✓ No issues found.")
        for iss in issues:
            icon = {"ERROR": "✗", "WARNING": "⚠", "INFO": "ℹ"}.get(
                iss["level"], "?")
            cid  = f" [{iss['criterion_id']}]" if iss.get("criterion_id") else ""
            print(f"  {icon} [{iss['level']}] {iss['code']}{cid}: {iss['message']}")

    if args.strict and has_errors(issues):
        if not args.json:
            print("\n[validate] Exiting with code 1 (errors found).")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
