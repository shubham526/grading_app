# Dual-Mode Grading Interface

This guide documents the v2.3.4.1 application workflow. The app has one shared
assessment setup and two explicit grading workspaces:

- **Written / Text** for PDFs, LaTeX, scans, manual rubric grading, written
  submission evidence, reference solutions, and similarity review;
- **Programming** for canonical Python submissions, instructor test bundles,
  isolated Docker/pytest execution, deterministic scoring, batch grading, and
  immutable autograding history.

The app never infers the grading mode from a filename or submission type. The
instructor chooses the mode explicitly.

## 1. Start at Assessment Home

Every launch opens **Assessment Home**. Complete the shared setup once before
entering either grading mode:

1. **Load Rubric** — establishes the common rubric/assessment definition and
   stable assessment identity.
2. **Load Roster** — establishes the student identities used by both modes.
3. **Choose Workspace** — selects the Grades + Evidence directory used for
   assessment JSON, canonical submissions, evidence, and autograding history.

The **Open Written Grader** and **Open Programming Grader** buttons remain
disabled until all three shared setup steps are ready.

Loading the rubric from Assessment Home does **not** open Written-only grading
configuration. That configuration remains inside the Written workspace.

## 2. Shared state

The following context belongs to the application rather than either grading
mode:

- rubric / assessment identity;
- roster;
- Grades + Evidence workspace;
- current assessment/session context;
- canonical submission/evidence roots associated with that assessment.

Switching modes does not destroy this shared context.

## 3. Written / Text workspace

From Assessment Home, click **Open Written Grader**.

The Written workspace preserves the established manual-grading interface and
its behavior. Shared setup controls are intentionally removed from its toolbar:

- the old visible **Load Rubric** button is hidden;
- **Choose Workspace…** and **Load Roster…** are not in Written Setup.

**Written Setup** contains Written-specific actions such as:

- **Load Reference Solution…**;
- **Add PDF Accommodation…**.

Other Written-specific capabilities remain available in the existing Written
interface, including:

- canonical written submission import;
- grading configuration;
- student-centric and question-centric grading;
- rubric scoring and partial save/resume;
- submission evidence and history;
- PDF/LaTeX viewing;
- similarity review;
- ABET mapping/reporting and existing reports.

Programming-autograding commands are not exposed in the Written **Tools** menu.

## 4. Programming workspace

From Assessment Home, click **Open Programming Grader**. You do not need to
enter Written first.

The Programming dashboard exposes these top-level actions:

- **Configure Autograder**;
- **Import Submissions**;
- **Check Runtime**;
- **Grade Selected**;
- **Grade All**;
- **Run History**.

The main table is roster/batch-centric and reports:

- student;
- active attempt;
- status;
- score;
- last run.

The Latest Result panel shows the selected student's current active-attempt
result and links to detailed results, rerun, and history.

A historical score is not presented as the score of a newly imported active
attempt. A new active attempt starts as **Not graded** until that exact attempt
has its own autograding run.

Programming autograding continues to use the v2.3.3 backend, Docker sandbox,
structured pytest protocol, deterministic scoring, provenance, and immutable
run repository. v2.3.4.1 changes the application interface and orchestration,
not the execution/scoring policy.

## 5. Switching grading modes

Use:

**File → Assessment Home…**

Assessment Home is the navigation hub for switching modes. A normal sequence is:

```text
Assessment Home
→ Written / Text
→ Assessment Home
→ Programming
→ Assessment Home
→ Written / Text
```

The shared rubric, roster, and workspace remain loaded through these
transitions.

## 6. Transition safety

### Unsaved Written work

If the current Written assessment has unsaved changes, returning to Assessment
Home uses the established **Save / Discard / Cancel** safety prompt. Choosing
Cancel keeps the instructor in Written mode.

### Active Programming operation

If a programming grading/runtime worker or batch operation is active, the app
blocks leaving Programming until the operation finishes. This avoids orphaning
an in-flight Docker/run-history operation while the workspace is changing.

## 7. Score separation

Programming autograding scores remain separate from manual Written rubric
scores in v2.3.4.1. Running the autograder does not silently write a score into
manual rubric criterion widgets or overwrite a manually saved assessment.

## 8. Current boundaries

v2.3.4.1 does not add:

- LaTeX/Overleaf ZIP ingestion;
- Canvas synchronization or publishing;
- automatic merge of programming scores into manual rubric grades;
- LLM-assisted grading;
- additional programming languages beyond the existing Python autograding
  subsystem.

Those are separate roadmap items and should not be inferred from the dual-mode
interface.
