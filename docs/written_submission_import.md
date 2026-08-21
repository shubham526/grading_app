# Written Submission Import

Written / Text grading accepts the established canonical submission types and,
in v2.3.4.2, adds Overleaf-style LaTeX project ZIPs.

## Entry point

From **Assessment Home**, load the rubric, roster, and Grades + Evidence
workspace, then click **Open Written Grader**. Use **Import Submissions** from
the Written workflow.

## Supported Written import shapes

The Written importer supports the existing flows for:

- `.tex` — single-file LaTeX source;
- `.pdf` — PDF evidence/accommodation according to the existing explicit PDF
  accommodation rules;
- `.zip` — multi-file LaTeX / Overleaf project.

A ZIP is not treated as a Programming submission in Written mode.

## Student mapping and preview

Files are first discovered and mapped to roster students using the canonical
importer. Review the student, filename/type, duplicate state, and validation
status before committing imports.

For a valid project ZIP, preflight safely inspects the archive and discovers
candidate root documents without compiling student TeX in the UI thread.

A project with one clear root can proceed automatically. An ambiguous project
shows **Choose project root**. When **Import Selected** is clicked, the
**Select LaTeX Project Root** dialog lists the discovered complete candidates.
No ambiguous root is preselected silently.

## Canonical import and grading evidence

The source ZIP is committed canonically first. Derived LaTeX-project evidence
is then prepared from that immutable submission:

```text
canonical ZIP
→ verified project extraction
→ resolved root
→ whole-project compilation
→ compiled PDF
→ ParsedSubmission
→ normal Written viewer
```

For project ZIPs the compiled PDF is exposed through the same grading-facing
`compiled_pdf` contract used by the existing single-file LaTeX workflow. The
PDF therefore appears in the normal left-hand Written viewer while the rubric
and grading controls remain on the right.

## Duplicate behavior

After a successful canonical import, the same source ZIP is correctly reported
as an exact duplicate if it remains in the import dialog or is selected again.
Recovery from a compilation failure must operate on the existing canonical
attempt rather than creating a duplicate upload.

## Failure and recovery

A compilation failure opens **LaTeX Project Diagnostics** after the import
summary. Depending on persisted project state, the instructor can view the log,
open the extracted source project, retry compilation, or choose another valid
root.

If the project no longer passes integrity verification, recovery is blocked.
The instructor should not edit the canonical extracted copy in place.

## History and restart

The chosen root, compilation history, archive/manifest hashes, and compiled-PDF
hash are persisted under the canonical submission's derived LaTeX-project tree.
Reopening the same assessment/workspace reuses the active canonical attempt and
its verified grading evidence.
