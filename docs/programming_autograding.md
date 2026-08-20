# Programming Autograding — Instructor Guide

This guide documents the programming-autograding workflow as exposed by the
v2.3.4.1 Programming dashboard. The underlying execution, scoring, persistence,
and hidden-test protections remain the v2.3.3 subsystem.

## 1. Prerequisites

Programming autograding requires:

- shared Assessment Home setup: rubric/assessment definition, roster, and
  Grades + Evidence workspace;
- canonical Python submissions imported through **Import Submissions**;
- Docker Desktop / Docker Engine running;
- the dedicated grading image built locally;
- an instructor test bundle whose assessment ID matches the current assessment.

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

## 2. Open the Programming dashboard

Launch the app and complete **Assessment Home**:

1. **Load Rubric**.
2. **Load Roster**.
3. **Choose Workspace**.
4. Click **Open Programming Grader**.

You do not need to enter the Written workspace first.

The dashboard contains:

```text
Configure Autograder
Import Submissions
Check Runtime
Grade Selected
Grade All
Run History
```

The student table shows the active attempt, grading status, score, and last run.
The Latest Result panel summarizes the selected student's current active
attempt.

## 3. Instructor test-bundle format

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

`autograder.json` defines the assessment, entrypoint, required files, test IDs,
public/hidden visibility, points, timeouts, and resource limits.

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

The bundle is validated and copied immutably into the assessment workspace.
Byte-identical grader content reuses the same bundle identity; changed grader
bytes create a new immutable bundle version.

## 4. Import programming submissions

Click **Import Submissions** in the Programming dashboard and use the canonical
v2.3.2 import workflow. Python files are stored as immutable attempts with
provenance.

The autograder grades one exact canonical attempt. The dashboard uses the active
attempt by default. Historical attempts remain available and are never
overwritten.

For multi-file assignments, the grader config may require files such as:

```text
main.py
helpers.py
src/algorithm.py
```

The execution plan verifies the configured entrypoint and required files before
Docker is invoked.

A roster student with no active programming submission remains **No submission**
and is not given a fabricated attempt.

## 5. Configure the autograder

Click **Configure Autograder**.

For the current assessment:

1. Import a test-bundle folder, or select an already imported immutable bundle.
2. Confirm that the selected bundle belongs to the current assessment.
3. Set the runtime image, normally:

   ```text
   grading-app-python312-pytest:9.1.1
   ```

4. Check the runtime if desired.
5. Use/save the selected bundle.

The app remembers the selected bundle ID and runtime image per assessment. It
does not silently select a replacement if the immutable bundle later becomes
missing or corrupt.

## 6. Check Runtime

Click **Check Runtime** on the Programming dashboard.

The check runs through the existing background worker boundary so the GUI
remains responsive. If the configured Docker runtime is unavailable, the app
reports that state rather than falling back to host execution.

## 7. Grade Selected

Select a student row and click **Grade Selected**.

Before execution, the existing confirmation flow identifies the intended:

- student;
- active canonical attempt;
- grader bundle;
- Docker runtime image.

The service performs:

```text
active canonical submission
→ verified ExecutionPlan
→ structured Docker pytest run
→ deterministic scoring
→ immutable run persistence
→ instructor result
```

After completion, the dashboard refreshes the selected student's status, score,
last run, and Latest Result panel.

## 8. Active-attempt behavior

Autograding history is bound to the exact submission ID/attempt that was graded.
If a student imports a new active attempt after an older attempt was graded, the
new row must show **Not graded** and no score until that new attempt is run.

The previous attempt's score remains in history; it is not carried forward as
if it belonged to the new code.

## 9. Interpret results

The instructor result view includes the overall score/review state plus
individual test outcomes. Hidden-test diagnostics may be visible to the
instructor.

Student-safe report builders continue to redact hidden identities and
instructor-only diagnostics. Do not copy an instructor report directly into
student feedback.

Default scoring semantics remain:

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

## 10. Run History, View Results, and Grade Again

Use **Run History** for the selected student to inspect immutable prior runs.
The Latest Result panel also exposes **View Results**, **Grade Again**, and
**View History** when applicable.

Every rerun creates a distinct immutable run. Opening a historical run performs
integrity verification before display.

## 11. Grade All

Click **Grade All** to start the existing batch workflow.

The app preflights the loaded roster. Students whose active canonical
submissions do not satisfy the Python grader contract are skipped/ineligible
rather than guessed or partially executed. One student's error does not abort
the entire batch.

### Cancellation

Use **Cancel After Current Student** in the batch dialog. Cancellation remains
cooperative: the current Docker job finishes or reaches its configured timeout,
then no next student is started.

## 12. Manual rubric grades remain separate

Programming-autograding scores are persisted separately from manual Written
rubric scoring. v2.3.4.1 does not automatically write an autograding score into
manual rubric criterion widgets or a saved manual assessment score.

## 13. Security model

Student code never runs directly in the desktop app's Python process.

The Docker backend uses the existing controls, including:

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

There is no automatic fallback to host execution if Docker is unavailable, and
the Docker socket is not mounted into the student container.

## 14. Switching modes safely

Use **File → Assessment Home…** to leave Programming or switch to Written.

If a programming grading/runtime worker or batch operation is still active, the
app blocks the transition until the operation finishes. Shared assessment,
roster, workspace, submission history, and autograding history remain available
when you return.
