# LaTeX Project / Overleaf ZIP Ingestion

v2.3.4.2 extends the existing Written-mode LaTeX workflow from one `.tex` file
to a complete multi-file project exported as a ZIP, such as an Overleaf project
archive.

The core invariant remains unchanged:

```text
LaTeX source
    ↓
restricted application compiler
    ↓
compiled PDF
    ↓
normal Written grading viewer
```

For a project ZIP, the source side is richer:

```text
original project ZIP
    ↓
archive validation
    ↓
immutable canonical storage
    ↓
safe extraction + manifest
    ↓
project discovery / root resolution
    ↓
restricted whole-project LaTeX compilation
    ↓
compiled PDF
    ↓
existing Written grading pipeline
```

## What is preserved

The canonical submission keeps the original ZIP exactly as imported. The LaTeX
project store records the archive SHA-256, extracted-file manifest, individual
source hashes, resolved root, root-resolution method, compiler provenance,
compilation attempts, logs, and the compiled-PDF SHA-256.

The original ZIP remains authoritative submitted evidence. Extracted files and
the compiled PDF are derived evidence.

## Archive validation

Before extraction, the importer rejects unsafe or unreasonable archive shapes,
including traversal/absolute paths, symlink-style entries, duplicate canonical
members, dangerous path conflicts, excessive file/member/total sizes, and
excessive compression ratios. Corrupt or non-ZIP data is rejected rather than
passed to the project resolver.

The extracted project is verified against its persisted manifest before
compilation or recovery. If the original archive or extracted project no longer
matches the canonical hashes, regeneration is blocked instead of trusting
modified bytes.

## Root-document resolution

The resolver identifies complete LaTeX documents from project structure and
source evidence such as `\documentclass`, `\begin{document}`, and
`\input` / `\include` relationships.

If there is one clear root, the importer can select it deterministically. If
more than one complete root remains plausible, the UI shows **Choose project
root** and requires the instructor to choose explicitly. It does not silently
pick one ambiguous document.

The selected root is persisted. If the instructor later recovers a failed
project by choosing a different root, that new root survives application
restart and is reused for the active canonical attempt.

## Compilation model and security boundary

Whole-project compilation deliberately reuses the application's existing
restricted host LaTeX compiler. It stages only files from the verified project
manifest into a disposable compilation directory and runs the configured engine
with bounded passes/time/log/output sizes.

`pdflatex` remains the default engine. Compilation uses `-no-shell-escape` and
restrictive TeX I/O environment settings. Unknown compiler options are rejected;
project import cannot enable shell escape through the UI or bridge.

This restricted host compiler is **not an OS/container sandbox**. The feature
does not claim process-level isolation equivalent to Docker or a VM. A future
containerized TeX environment would be a separate hardening feature.

## Compilation failure and diagnostics

A canonical ZIP can import successfully even if derived PDF preparation fails.
In that case the app shows **LaTeX Project Diagnostics**, including structured
status/reason information and, when available:

- resolved root;
- compiler engine;
- persisted compilation log;
- source-project location;
- **Retry Compilation**;
- **Choose Different Root**.

Compilation failures remain attached to the existing canonical attempt rather
than forcing another upload.

## Recovery

If a derived compiled PDF disappears but the canonical project still verifies,
the app can safely regenerate the PDF without re-importing the original ZIP.
The new compilation is appended to provenance rather than overwriting history.

If integrity verification fails, recovery controls are disabled. The app does
not silently rebuild from altered extracted files or a changed original ZIP.

## Written-mode boundary

LaTeX project ZIP ingestion belongs to **Written / Text** grading. It does not
change Programming submission routing, Python execution, autograding bundles,
or programming-score semantics.
