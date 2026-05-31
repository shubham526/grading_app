#!/usr/bin/env python3
"""
migrate_rubrics_to_abet.py  (Phase 6 rewrite)
=============================================

Upgrade rubric JSON files to ABET-aware schema 2.0.

Single-file mode::

    python tools/migrate_rubrics_to_abet.py \\
        --input old_rubric.json \\
        --output new_rubric.json \\
        --profile cs2500_algorithms \\
        --auto-map

Batch mode (migrate every *.json in a directory)::

    python tools/migrate_rubrics_to_abet.py \\
        --batch-dir rubrics/ \\
        --output-dir rubrics_v2/ \\
        --profile cs2500_algorithms \\
        --auto-map

    # Or migrate in-place (overwrites originals — back up first):
    python tools/migrate_rubrics_to_abet.py \\
        --batch-dir rubrics/ \\
        --profile cs2500_algorithms \\
        --in-place

Dry-run mode (print changes, write nothing)::

    python tools/migrate_rubrics_to_abet.py --input old.json --output new.json --dry-run

What it does:
    1. Adds schema_version = "2.0"
    2. Adds stable criterion IDs (generated from titles if missing)
    3. Adds course_outcomes / program_outcomes / abet_outcomes / assessment_tags defaults
    4. Optionally infers course_outcomes from criterion titles (--auto-map)
    5. Optionally derives program_outcomes from the LO→PO crosswalk
    6. Prints a validation summary after migration
"""

import argparse
import json
import os
import sys
from glob import glob
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.utils import generate_criterion_id
from src.core.outcome_profile import load_profile, load_default_profile, OutcomeProfile


# ---------------------------------------------------------------------------
# Single-rubric migration
# ---------------------------------------------------------------------------

def migrate_rubric(
    input_path:  str,
    output_path: str,
    profile:     Optional[OutcomeProfile] = None,
    auto_map:    bool = False,
    dry_run:     bool = False,
) -> Tuple[dict, List[dict]]:
    """
    Migrate one rubric file to schema 2.0.

    Returns:
        (migrated_rubric_dict, list_of_change_records)
        Each change record: {"criterion": title, "field": name, "value": new_value}
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as fh:
        rubric = json.load(fh)

    if not isinstance(rubric, dict) or "criteria" not in rubric:
        raise ValueError("Input file does not contain a valid rubric (missing 'criteria').")

    changes: List[dict] = []
    seen_ids: set = set()   # Fix 3: track generated IDs to avoid collisions

    # 1. Schema version
    if rubric.get("schema_version") != "2.0":
        rubric["schema_version"] = "2.0"
        changes.append({"field": "schema_version", "value": "2.0"})

    # 2. profile_id
    if profile and not rubric.get("profile_id"):
        rubric["profile_id"]     = profile.profile_id
        rubric["outcome_profile"] = profile.profile_id
        changes.append({"field": "profile_id", "value": profile.profile_id})

    for idx, crit in enumerate(rubric.get("criteria", [])):
        title = crit.get("title", "")

        # 3. Stable ID — Fix 3: deduplicate generated IDs
        if not crit.get("id"):
            candidate = generate_criterion_id(title, idx)
            # If this generated ID already exists (duplicate titles), append index
            if candidate in seen_ids:
                candidate = f"{candidate}_{idx:03d}"
            crit["id"] = candidate
            changes.append({"criterion": title, "field": "id", "value": crit["id"]})

        # Track all IDs (generated or pre-existing) for collision detection
        seen_ids.add(crit["id"])

        # 4. Ensure outcome fields
        crit.setdefault("course_outcomes",  [])
        crit.setdefault("program_outcomes", [])
        crit.setdefault("abet_outcomes",    [])
        crit.setdefault("assessment_tags",  [])

        # Normalise legacy abet_outcomes → program_outcomes
        if crit["abet_outcomes"] and not crit["program_outcomes"]:
            crit["program_outcomes"] = list(crit["abet_outcomes"])
            changes.append({"criterion": title, "field": "program_outcomes",
                             "value": crit["program_outcomes"],
                             "note": "copied from abet_outcomes"})

        # Fix 2: sync program_outcomes → abet_outcomes alias
        if crit["program_outcomes"] and not crit["abet_outcomes"]:
            crit["abet_outcomes"] = list(crit["program_outcomes"])
            changes.append({"criterion": title, "field": "abet_outcomes",
                             "value": crit["abet_outcomes"],
                             "note": "copied from program_outcomes"})

        # 5. Auto-map
        if auto_map and profile:
            if not crit["course_outcomes"]:
                inferred_lo = profile.infer_los_from_title(title)
                if inferred_lo:
                    crit["course_outcomes"] = inferred_lo
                    changes.append({"criterion": title, "field": "course_outcomes",
                                    "value": inferred_lo, "note": "auto-mapped from title"})

            if not crit["program_outcomes"] and crit["course_outcomes"]:
                inferred_po = profile.derive_program_from_los(crit["course_outcomes"])
                if inferred_po:
                    crit["program_outcomes"] = inferred_po
                    crit["abet_outcomes"]    = inferred_po
                    changes.append({"criterion": title, "field": "program_outcomes",
                                    "value": inferred_po, "note": "derived from LOs"})

    # Validation summary
    validation_issues = _validate_migrated(rubric, profile)

    if dry_run:
        _print_migration_report(input_path, changes, validation_issues, dry_run=True)
        return rubric, changes

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(rubric, fh, indent=2, ensure_ascii=False)

    _print_migration_report(input_path, changes, validation_issues, dry_run=False,
                             output_path=output_path)
    return rubric, changes


# ---------------------------------------------------------------------------
# Batch migration
# ---------------------------------------------------------------------------

def migrate_batch(
    input_dir:   str,
    output_dir:  Optional[str] = None,
    in_place:    bool = False,
    profile:     Optional[OutcomeProfile] = None,
    auto_map:    bool = False,
    dry_run:     bool = False,
    recursive:   bool = False,
) -> List[dict]:
    """
    Migrate all *.json files in input_dir.

    Args:
        input_dir:  Directory containing rubric JSON files.
        output_dir: Write migrated files here (created if needed).
                    If None and in_place=False, defaults to input_dir + "_v2".
        in_place:   Overwrite the original files (back up first!).
        profile:    OutcomeProfile to use for auto-mapping.
        auto_map:   Whether to infer LOs/SOs from criterion titles.
        dry_run:    Print changes without writing.
        recursive:  Search input_dir recursively.

    Returns:
        List of per-file migration summary dicts.
    """
    pattern   = "**/*.json" if recursive else "*.json"
    all_paths = sorted(glob(os.path.join(input_dir, pattern), recursive=recursive))

    if not all_paths:
        print(f"[batch] No JSON files found in: {input_dir}")
        return []

    if not in_place and output_dir is None:
        output_dir = input_dir.rstrip("/\\") + "_v2"

    summaries: List[dict] = []
    ok_count  = 0
    err_count = 0

    print(f"\n[batch] Migrating {len(all_paths)} file(s)...")
    print(f"        Input:  {input_dir}")
    if not in_place:
        print(f"        Output: {output_dir}")
    print(f"        Auto-map: {auto_map}  Dry-run: {dry_run}\n")

    for src in all_paths:
        if in_place:
            dst = src
        else:
            rel = os.path.relpath(src, input_dir)
            dst = os.path.join(output_dir, rel)

        try:
            rubric, changes = migrate_rubric(
                src, dst, profile=profile, auto_map=auto_map, dry_run=dry_run)
            summaries.append({
                "input":   src,
                "output":  dst,
                "changes": len(changes),
                "status":  "ok",
            })
            ok_count += 1
        except Exception as exc:
            print(f"  [ERROR] {src}: {exc}")
            summaries.append({"input": src, "output": dst, "status": "error",
                               "error": str(exc)})
            err_count += 1

    print(f"\n[batch] Complete: {ok_count} succeeded, {err_count} failed.")
    return summaries


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_migrated(rubric: dict, profile: Optional[OutcomeProfile]) -> List[dict]:
    """Run validation after migration and return issues list."""
    try:
        from src.tools.abet_validation import validate_rubric
        lo_ids = list(profile.course_outcomes.keys()) if profile else None
        so_ids = list(profile.program_outcomes.keys()) if profile else None
        return validate_rubric(rubric, lo_ids, so_ids)
    except Exception:
        return []


def _print_migration_report(input_path, changes, issues, dry_run, output_path=""):
    fname = os.path.basename(input_path)
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}{fname}:")

    if changes:
        for ch in changes:
            crit = ch.get("criterion", "rubric-level")
            note = f"  ({ch['note']})" if ch.get("note") else ""
            print(f"  + {crit}: {ch['field']} = {ch['value']}{note}")
    else:
        print("  (no changes needed)")

    if issues:
        errors   = [i for i in issues if i["level"] == "ERROR"]
        warnings = [i for i in issues if i["level"] == "WARNING"]
        infos    = [i for i in issues if i["level"] == "INFO"]
        if errors:
            for i in errors:
                print(f"  [ERROR]   {i['code']}: {i['message']}")
        if warnings:
            for i in warnings:
                print(f"  [WARNING] {i['code']}: {i['message']}")
        if infos:
            for i in infos:
                print(f"  [INFO]    {i['code']}: {i['message']}")
    else:
        print("  Validation: OK")

    if output_path and not dry_run:
        print(f"  → Written: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate rubric JSON files to ABET-aware schema 2.0.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode: single file or batch
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input",     metavar="FILE",
                      help="Single rubric file to migrate.")
    mode.add_argument("--batch-dir", metavar="DIR",
                      help="Migrate all *.json files in this directory.")

    # Output options
    parser.add_argument("--output",     metavar="FILE",
                        help="Output path for single-file mode.")
    parser.add_argument("--output-dir", metavar="DIR",
                        help="Output directory for batch mode (default: input_dir + _v2).")
    parser.add_argument("--in-place",   action="store_true",
                        help="Overwrite originals in batch mode (back up first!).")
    parser.add_argument("--recursive",  action="store_true",
                        help="Search batch-dir recursively.")

    # Mapping options
    parser.add_argument("--profile",  default="cs2500_algorithms",
                        help="Outcome profile ID or path (default: cs2500_algorithms).")
    parser.add_argument("--auto-map", action="store_true",
                        help="Infer course_outcomes / program_outcomes from criterion titles.")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Print planned changes without writing files.")

    args = parser.parse_args()

    # Load profile
    profile = None
    try:
        profile = load_profile(args.profile)
        print(f"[migrate] Profile: {profile.profile_id}")
    except FileNotFoundError:
        print(f"[migrate] WARNING: Profile '{args.profile}' not found; "
              f"auto-map and ID validation disabled.")

    # Single-file mode
    if args.input:
        if not args.output:
            parser.error("--output is required with --input")
        try:
            migrate_rubric(
                args.input, args.output,
                profile=profile,
                auto_map=args.auto_map,
                dry_run=args.dry_run,
            )
            return 0
        except Exception as exc:
            print(f"[migrate] ERROR: {exc}", file=sys.stderr)
            return 1

    # Batch mode
    summaries = migrate_batch(
        args.batch_dir,
        output_dir=args.output_dir,
        in_place=args.in_place,
        profile=profile,
        auto_map=args.auto_map,
        dry_run=args.dry_run,
        recursive=args.recursive,
    )
    errors = [s for s in summaries if s.get("status") == "error"]
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
