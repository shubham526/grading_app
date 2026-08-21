# Grading App — Revised v2.3.x Design Set

**Prepared:** August 18, 2026

This directory contains the revised design specifications after restructuring the v2.3.x roadmap around shared dependencies.

## Revised release order

```text
v2.3.1   Advanced Similarity Review                 COMPLETE

v2.3.2   Submission Core & Provenance Foundation
    ↓
v2.3.3   Programming Submission & Autograding
    ↓
v2.3.4   Overleaf / LaTeX Project ZIP Ingestion
    ↓
v2.3.5   Structured Regrade Adjudication & Grade Revision
    ↓
v2.3.6.1 Canvas Connection, Course/Roster/Assignment Sync
    ↓
v2.3.6.2 Canvas Submission & File Sync
    ↓
v2.3.6.3 Controlled Canvas Grade & Feedback Publishing
    ↓
v2.3.6.4 Canvas Reconciliation, Conflict Detection & Audit
```

## Why the order changed

The old v2.3.2 autograding design contained submission identity, provenance, attempt, hashing, and storage responsibilities that are also required by ZIP ingestion and Canvas.

Those responsibilities are now isolated in **v2.3.2** so all later features share one canonical submission model.

## Fall 2026 ABET

The previously drafted Fall 2026 ABET design is **not discarded**, but it is no longer part of the urgent dependency chain.

It should be renumbered/revised as:

```text
v2.3.7 — Fall 2026 ABET Evidence & Course Alignment
```

and handled separately after the submission/regrade/Canvas path is stable.

## Microsoft automations

The existing Microsoft Forms + SharePoint + Power Automate workflows for:

```text
regrades
absences
late days
```

are not replaced wholesale.

For regrades, v2.3.5 makes the grading app the academic adjudication/grade-revision frontend while preserving the existing intake/status-notification workflow.

Absence and late-day systems remain outside this grading-app roadmap.

## Canvas definition of done

`v2.3.6` means full grading integration, not read-only integration.

The four Canvas sub-releases deliberately progress from:

```text
read metadata
→ read submissions/files
→ controlled writes
→ reconciliation/audit
```

so each safety boundary can be tested independently.

## Files

- `v2.3.2_submission_core_provenance_design.md`
- `v2.3.3_programming_submission_autograding_design.md`
- `v2.3.4.2_overleaf_latex_zip_ingestion_design.md`
- `retired/v2.3.5_structured_regrade_adjudication_design.md`
- `retired/v2.3.6_canvas_grading_integration_overview.md`
- `retired/v2.3.6.1_canvas_connection_course_sync_design.md`
- `retired/v2.3.6.2_canvas_submission_file_sync_design.md`
- `retired/v2.3.6.3_canvas_grade_feedback_publishing_design.md`
- `retired/v2.3.6.4_canvas_reconciliation_audit_design.md`
