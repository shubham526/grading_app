#!/usr/bin/env python3
"""Export the v2.2.1 Master ABET Evidence Sheet.

Semester mode::

    python tools/export_master_abet_evidence.py \
        --semester-config semester.json \
        --output-dir reports/master_evidence \
        --formats csv,xlsx,json \
        --evidence-policy counted_only

Single-assignment mode::

    python tools/export_master_abet_evidence.py \
        --rubric rubrics/ps3.json \
        --assessments-dir assessments/ps3 \
        --assignment-id PS3 \
        --assignment-title "Dynamic Programming" \
        --course-code "CS 2500" \
        --semester "Fall 2026" \
        --output-dir reports/ps3_master_evidence

The CLI is intentionally thin: grading/evidence semantics live in
``src.tools.master_evidence_export`` and are shared with the future UI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence

# Match the repository's existing standalone tools: allow invocation from the
# repo root without installing the package.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.tools.master_evidence_export import (  # noqa: E402
    SUPPORTED_MASTER_EVIDENCE_FORMATS,
    VALID_EVIDENCE_POLICIES,
    collect_master_evidence_for_assignment,
    collect_master_evidence_for_semester,
    export_master_evidence,
)


# Strict mode is deliberately narrower than "any warning".  Missing optional
# descriptive metadata is valid in the design and must remain exportable.
# These codes indicate that evidence was skipped or points required to audit a
# score are missing.
STRICT_CRITICAL_WARNING_CODES = frozenset({
    "no_assignments_configured",
    "missing_rubric_path",
    "rubric_file_missing",
    "rubric_file_unreadable",
    "missing_assessments_dir",
    "assessments_dir_missing",
    "assessment_file_unreadable",
    "missing_points",
})


def _load_json_object(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        with source.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} not found: {source}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _parse_formats(value: str) -> List[str]:
    requested: List[str] = []
    for raw in str(value or "").split(","):
        fmt = raw.strip().lower()
        if not fmt:
            continue
        if fmt not in SUPPORTED_MASTER_EVIDENCE_FORMATS:
            raise argparse.ArgumentTypeError(
                f"unsupported format {fmt!r}; choose from csv,xlsx,json"
            )
        if fmt not in requested:
            requested.append(fmt)
    if not requested:
        raise argparse.ArgumentTypeError("at least one format is required")
    return requested


def _course_meta_from_args(args: argparse.Namespace) -> dict:
    return {
        "semester": args.semester or "",
        "course_code": args.course_code or "",
        "course_name": args.course_name or "",
        "section": args.section or "",
    }


def _course_meta_from_semester_config(config: Mapping[str, object]) -> dict:
    return {
        "semester": str(config.get("semester") or ""),
        "course_code": str(config.get("course_code") or ""),
        "course_name": str(config.get("course_name") or ""),
        "section": str(config.get("section") or ""),
    }


def _critical_warnings(warnings: Iterable[Mapping[str, object]]) -> List[Mapping[str, object]]:
    return [
        warning
        for warning in warnings
        if str(warning.get("code") or "") in STRICT_CRITICAL_WARNING_CODES
    ]


def _print_warning_summary(warnings: Sequence[Mapping[str, object]]) -> None:
    if not warnings:
        print("Warnings: 0")
        return

    print(f"Warnings: {len(warnings)}")
    counts = {}
    for warning in warnings:
        code = str(warning.get("code") or "warning")
        counts[code] = counts.get(code, 0) + 1
    for code in sorted(counts):
        print(f"  - {code}: {counts[code]}")


def _print_exports(paths: Mapping[str, Optional[str]]) -> None:
    print("Master ABET evidence export complete.")
    print("Files:")
    preferred_order = ("csv", "xlsx", "json", "warnings_csv")
    for key in preferred_order:
        if key not in paths:
            continue
        path = paths[key]
        label = "warnings CSV" if key == "warnings_csv" else key.upper()
        if path:
            print(f"  - {label}: {path}")
        else:
            print(f"  - {label}: unavailable (optional dependency not installed)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export row-level Master ABET Evidence for one assignment or a semester.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--semester-config",
        metavar="FILE",
        help="Semester config JSON. Relative assignment paths resolve from this file.",
    )
    mode.add_argument(
        "--rubric",
        metavar="FILE",
        help="Rubric JSON for single-assignment mode.",
    )

    parser.add_argument(
        "--assessments-dir",
        metavar="DIR",
        help="Student assessment JSON directory for single-assignment mode.",
    )
    parser.add_argument("--assignment-id", default="")
    parser.add_argument("--assignment-title", default="")
    parser.add_argument("--assignment-type", default="")
    parser.add_argument("--assignment-date", default="")
    parser.add_argument("--course-code", default="")
    parser.add_argument("--course-name", default="")
    parser.add_argument("--semester", default="")
    parser.add_argument("--section", default="")

    parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="Directory that receives master_abet_evidence.* files.",
    )
    parser.add_argument(
        "--formats",
        type=_parse_formats,
        default=_parse_formats("csv,xlsx,json"),
        metavar="LIST",
        help="Comma-separated formats: csv,xlsx,json (default: all).",
    )
    parser.add_argument(
        "--evidence-policy",
        choices=sorted(VALID_EVIDENCE_POLICIES),
        default="counted_only",
        help="Evidence policy used when selecting criterion rows.",
    )
    parser.add_argument(
        "--include-excluded",
        action="store_true",
        help="Include rows excluded by the selected evidence policy, preserving flags.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit nonzero when critical evidence is missing/skipped. Optional metadata "
            "warnings remain non-fatal."
        ),
    )
    return parser


def _validate_mode_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.semester_config:
        if args.assessments_dir:
            parser.error("--assessments-dir is only valid with --rubric assignment mode")
        return
    if not args.assessments_dir:
        parser.error("--assessments-dir is required when --rubric is used")


def _collect_assignment(args: argparse.Namespace):
    rubric_path = Path(args.rubric).expanduser().resolve()
    rubric = _load_json_object(str(rubric_path), "rubric")
    if not isinstance(rubric.get("criteria"), list):
        raise ValueError("rubric must contain a criteria list")

    assessments_dir = Path(args.assessments_dir).expanduser().resolve()
    if not assessments_dir.is_dir():
        raise FileNotFoundError(f"Assessments directory not found: {assessments_dir}")

    assignment_meta = {
        "assignment_id": args.assignment_id or str(rubric.get("assessment_id") or ""),
        "assignment_title": args.assignment_title or str(rubric.get("title") or ""),
        "assignment_type": args.assignment_type or "",
        "assignment_date": args.assignment_date or "",
    }
    course_meta = _course_meta_from_args(args)

    result = collect_master_evidence_for_assignment(
        rubric,
        str(assessments_dir),
        assignment_meta,
        course_meta,
        evidence_policy=args.evidence_policy,
        include_excluded=args.include_excluded,
    )
    return result, course_meta


def _collect_semester(args: argparse.Namespace):
    config_path = Path(args.semester_config).expanduser().resolve()
    config = _load_json_object(str(config_path), "semester config")
    result = collect_master_evidence_for_semester(
        config,
        evidence_policy=args.evidence_policy,
        include_excluded=args.include_excluded,
        base_dir=str(config_path.parent),
    )
    return result, _course_meta_from_semester_config(config)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_mode_arguments(parser, args)

    try:
        if args.semester_config:
            result, course_meta = _collect_semester(args)
        else:
            result, course_meta = _collect_assignment(args)

        paths = export_master_evidence(
            result.rows,
            args.output_dir,
            formats=args.formats,
            warnings=result.warnings,
            course_meta=course_meta,
            evidence_policy=args.evidence_policy,
        )
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
        print(f"[master-evidence] ERROR: {exc}", file=sys.stderr)
        return 1

    _print_exports(paths)
    _print_warning_summary(result.warnings)

    if args.strict:
        critical = _critical_warnings(result.warnings)
        if critical:
            print(
                f"[master-evidence] STRICT: {len(critical)} critical warning(s); "
                "exiting with code 1.",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
