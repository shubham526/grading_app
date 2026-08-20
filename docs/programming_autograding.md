# Programming Autograding — Instructor Guide

This guide documents the v2.3.3 Python programming-autograding workflow.

## 1. Prerequisites

Programming autograding requires:

- a normal grading-app workspace with a stable assessment ID;
- a loaded roster;
- canonical Python submissions imported through **Import Submissions**;
- Docker Desktop / Docker Engine running;
- the dedicated grading image built locally;
- an instructor test bundle matching the assessment ID.

Build the runtime once from the repository root:

```bash
docker build \
  -t grading-app-python312-pytest:9.1.1 \
  docker/autograding/python312-pytest
```

Verify it:

```bash
docker run --rm --network none --pull=never \
  grading-app-python312-pytest:9.1.1 \
  python -c 'import pytest; print(pytest.__version__)'
```

The expected pytest version is `9.1.1`.

## 2. Instructor test-bundle format

A bundle has this shape:

```text
my_autograder/
├── autograder.json
├── tests/
│   ├── test_public.py
│   └── test_hidden.py
├── support/              optional
└── requirements.txt      optional/preserved only
```

`autograder.json` defines the assessment, entrypoint, required files, test IDs, public/hidden visibility, points, timeouts, and resource limits.

Example:

```json
{
  "schema_version": "1.0",
  "assessment_id": "LAB1",
  "language": "python",
  "runner_type": "pytest",
  "entrypoint": "main.py",
  "max_points": 10,
  "tests": [
    {
      "test_id": "public_basic",
      "name": "Basic behavior",
      "visibility": "public",
      "points": 4,
      "metadata": {
        "pytest_nodeid": "tests/test_public.py::test_basic"
      }
    },
    {
      "test_id": "hidden_edge",
      "name": "Hidden edge behavior",
      "visibility": "hidden",
      "points": 6,
      "metadata": {
        "pytest_nodeid": "tests/test_hidden.py::test_edge"
      }
    }
  ]
}
```

The bundle is validated and copied immutably into the assessment workspace. Re-importing byte-identical grader content reuses the same bundle identity; changed grader bytes create a new immutable bundle version.

## 3. Import programming submissions

Use the normal **Import Submissions** workflow. Python files are stored in the canonical v2.3.2 repository and remain immutable per attempt.

The autograder always grades one exact canonical attempt. By default the UI grades the active attempt. Historical attempts remain available as evidence and are never overwritten.

For multi-file assignments, the grader config may require files such as:

```text
main.py
helpers.py
src/algorithm.py
```

The execution plan verifies the configured entrypoint and required files before Docker is invoked.

## 4. Configure the autograder

Open:

```text
Tools → Programming Autograding → Configure Autograder…
```

For the current assessment:

1. Import a test-bundle folder, or select an already imported immutable bundle.
2. Confirm the selected bundle belongs to the current assessment.
3. Set the runtime image, normally:

   ```text
   grading-app-python312-pytest:9.1.1
   ```

4. Click **Check Runtime**.
5. Confirm the runtime reports available.
6. Save/accept the configuration.

The app remembers the selected bundle ID and runtime image per assessment. It does not silently select a replacement if that immutable bundle later becomes missing or corrupt.

## 5. Grade the current submission

Select the desired student in the normal grading workspace, then open:

```text
Tools → Programming Autograding → Grade Current Submission
```

Before execution, confirm the dialog shows the intended:

- student;
- active canonical attempt;
- grader bundle;
- Docker runtime image.

After confirmation, grading runs in a background worker so the GUI remains responsive.

The service performs:

```text
active canonical submission
→ verified ExecutionPlan
→ structured Docker pytest run
→ deterministic scoring
→ immutable run persistence
→ instructor results dialog
```

## 6. Interpret the results dialog

The instructor results dialog shows the overall score or review-required state plus individual test rows.

Typical columns include:

- test name;
- public/hidden visibility;
- status;
- awarded / possible points;
- runtime;
- message.

Selecting a test may show instructor-only traceback and captured stdout/stderr.

Hidden tests are intentionally visible to the instructor. Do not copy the full instructor report directly into student feedback. Student-safe report builders redact hidden identities and diagnostics.

## 7. Outcome and scoring semantics

Default policy:

| Outcome | Default score behavior |
| --- | --- |
| `passed` | full configured credit |
| `xfail` | full configured credit |
| `xpass` | full configured credit |
| student `failed` | zero |
| student `error` | zero |
| per-test `timeout` | zero |
| `skipped` | unresolved / review |
| `infrastructure_error` | unresolved / review |
| run-level timeout | unresolved / review |

A grader or infrastructure failure does not silently become a student zero.

If the run is structurally suspicious or review-required, the persisted run keeps `final_score = None` even when some test-level evidence is known.

## 8. Manual rubric grades are separate

v2.3.3 does **not** automatically write the programming-autograding score into the manual rubric criterion widgets or saved manual assessment score.

This is deliberate. Autograding evidence is persisted separately so an instructor can inspect it before any future explicit merge/publish workflow.

## 9. Autograding history

Open:

```text
Tools → Programming Autograding → Autograding History…
```

History is scoped to the current assessment and student. Every rerun remains a separate immutable row.

A historical run includes:

- run ID;
- submission ID and attempt;
- grader bundle ID/hash;
- runtime environment and image digest;
- structured test results;
- score/review state;
- execution stdout/stderr evidence.

Opening a historical run performs integrity verification before displaying it.

## 10. Batch grading

Open:

```text
Tools → Programming Autograding → Grade All Active Submissions…
```

The app first preflights the loaded roster. Students whose active canonical submissions do not satisfy the Python grader contract are skipped/ineligible rather than guessed or partially executed.

The batch dialog then grades eligible students sequentially in a background worker and reports per-student status/score.

One student's error does not abort the entire batch.

### Cancellation

Use **Cancel After Current Student**.

Cancellation is cooperative: the currently running Docker job is allowed to complete or reach its configured timeout so verified cleanup still occurs. Remaining students are then marked cancelled and are not started.

## 11. Security model

Student code never runs directly in the desktop app's Python process.

The Docker backend uses:

- no external network;
- read-only root filesystem;
- read-only student/grader/runtime mounts;
- non-root UID/GID;
- dropped capabilities;
- `no-new-privileges`;
- memory/CPU/PID limits;
- bounded output capture;
- wall timeout;
- fresh ephemeral staging;
- verified cleanup.

There is no automatic fallback to host execution if Docker is unavailable.

The app also does not mount the Docker socket into the student container.

## 12. Troubleshooting

### Runtime unavailable

Check:

```bash
docker version
```

Then verify the grading image:

```bash
docker image inspect grading-app-python312-pytest:9.1.1
```

If the image is absent, build it using the repository Dockerfile. The app does not auto-build or auto-pull it.

### Wrong pytest version

Verify:

```bash
docker run --rm --network none --pull=never \
  grading-app-python312-pytest:9.1.1 \
  python -c 'import pytest; print(pytest.__version__)'
```

The v2.3.3 runtime expects `9.1.1`.

### No canonical programming submission

Import the student's `.py` submission through **Import Submissions** and confirm an active canonical attempt exists in **Submission History**.

### Required file missing

Compare the active submission's canonical artifact list with `entrypoint` and `required_files` in `autograder.json`.

### Requires review

Open the results details. Review-required runs may indicate collection/selection problems, infrastructure errors, run-level timeout, skipped/unresolved tests, or other structural issues. Do not convert these automatically to zero.

### Batch student skipped

The roster student either has no active canonical submission or the active submission does not satisfy the selected grader's programming file contract.
