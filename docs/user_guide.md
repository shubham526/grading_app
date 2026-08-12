# Comprehensive User Guide: Rubric Grading Tool

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Working with Rubrics](#working-with-rubrics)
4. [Grading Assignments](#grading-assignments)
   - [Student-by-student workflow](#student-by-student-workflow)
   - [Question-by-question workflow](#question-by-question-workflow)
   - [Loading an assessment folder](#loading-an-assessment-folder)
   - [Loading a roster CSV](#loading-a-roster-csv)
   - [Navigating students and questions](#navigating-students-and-questions)
   - [Saving partial grades](#saving-partial-grades)
   - [Progress tracking](#progress-tracking)
5. [Saving and Loading Assessments](#saving-and-loading-assessments)
6. [Exporting to PDF](#exporting-to-pdf)
7. [Tips and Best Practices](#tips-and-best-practices)
8. [Troubleshooting](#troubleshooting)

## Introduction

The Rubric Grading Tool supports detailed criterion-level grading, selected or
best-N question scoring, ABET/outcome reporting, analytics, PDF export, and two
manual grading workflows:

- **Student-by-student**: grade all questions for one student, then move to the next student.
- **Question-by-question**: grade one question for every student, then move to the next question.

Question-by-question grading was added in v2.1.0 to improve consistency and
speed when the same rubric context should be applied across an entire class.
It changes navigation/filtering and partial-save behavior only; it does not
change the existing scoring or ABET rules.

## Getting Started

1. Install the required dependencies.
2. Launch the application with the repository's normal entry point.
3. Click **Load Rubric** and choose a JSON or CSV rubric.
4. Configure the existing score-selection rules with **Grading Config** if needed.
5. Choose a manual grading workflow from the **Manual Grading Workflow** card.

### Interface Overview

The main window contains:

- rubric loading and assignment/student information;
- grading configuration (best-N vs selected-question scoring);
- manual grading workflow controls;
- attempted/selected-question controls;
- criterion score/comment widgets;
- question score summary and total;
- save/load, PDF, analytics, and ABET actions.

The **Manual Grading Workflow** selector is independent of the existing
**Grading Config**. Changing the workflow does not change which questions count
toward a student's final score.

## Working with Rubrics

### Question IDs

v2.1 rubrics can store a `question_id` on every criterion:

```json
{
  "id": "PS3_Q2_RUNTIME",
  "question_id": "Q2",
  "title": "Question 2 - Runtime Analysis",
  "points": 4
}
```

Multiple criteria can share a question ID. When an older rubric has no
`question_id`, the application tries to infer it from titles such as `Q2`,
`Question 2`, `Problem 2`, `P2`, and subparts such as `Q2(b)`/`Question 2(b)`.
If IDs are inferred, the application offers to save the normalized rubric.

Criteria that cannot be assigned to a question are not dropped. They are
available in question-by-question mode under **Criteria without question
assignment**.

See [Rubric Format](rubric_format.md) for the full format.

## Grading Assignments

### Student-by-student workflow

This remains the default and preserves the pre-v2.1 workflow:

1. Select **Student-by-student**.
2. Enter the student name and assignment name.
3. Grade all visible criteria.
4. Select the questions the student attempted when applicable.
5. Click **Save Assessment**.
6. Clear/load the next student and continue.

All rubric criteria remain visible in this mode.

### Question-by-question workflow

1. Load the rubric.
2. Select **Question-by-question** in the Manual Grading Workflow card.
3. Load an existing assessment folder and/or a roster CSV.
4. Choose a question (for example, `Q1`).
5. Grade that question for the current student.
6. Click **Save and Next Student** to continue through the class while staying on the same question.
7. After finishing the class, use **Next Question** to move to `Q2`, `Q3`, and so on.

Only criteria belonging to the selected canonical `question_id` are visible.
The other criterion widgets remain loaded in memory so their saved scores and
comments are preserved.

### Loading an assessment folder

Click **Assessment Folder** and select the directory containing student
assessment JSON files. Existing files are used to build the student list.
Unrelated/malformed JSON files are ignored.

If a roster is also loaded, existing assessment files are matched to roster
students by stable student ID when possible and by student name for legacy
assessment files.

### Loading a roster CSV

Click **Load Roster CSV**. The supported format is:

```csv
student_id,student_name
alice,Alice Smith
bob,Bob Chen
chen,Chen Wang
```

Roster order becomes the grading order. Students without an existing assessment
file receive a blank assessment skeleton automatically when reached. On the
first save, choose an assessment directory if one has not already been selected.

If no roster/folder is loaded, the existing manual student-name behavior remains
available for a single student.

### Navigating students and questions

In question-by-question mode:

- **Previous Student / Next Student** keep the same selected question.
- **Save and Next Student** saves the visible question and advances.
- Selecting another student from the dropdown saves dirty question data before loading the new student.
- **Previous Question / Next Question** change the filtered question.
- When moving to another question, the application can restart at the first student.
- Direct question changes prompt when the current question contains unsaved changes.

### Using achievement levels and comments

Achievement levels continue to set point values as before. Manual point edits
and achievement-level choices mark the criterion as graded. An intentional score
of zero is recorded as graded even though zero is also the visual default.

Comments support the existing Markdown/LaTeX input behavior. Comment-only edits
participate in dirty-state/save prompts but do not by themselves mark the score
as graded.

### Saving partial grades

In question-by-question mode, **Save** does not overwrite the entire assessment
with only the visible criteria. Instead it:

1. loads the existing full student assessment, or creates a blank full assessment;
2. merges the visible question's criteria by stable criterion ID;
3. preserves scores/comments/grading state for hidden questions;
4. refreshes selected/counted flags and derived total/question-summary metadata;
5. preserves ABET/outcome metadata;
6. writes the full assessment JSON back to the student's file.

This means Q1 can be graded and saved today without erasing an already graded Q2.

### Marking a question complete

**Mark Question Complete** is available only when every criterion visible for the
current student/question has been explicitly graded. The completion marker is
navigation metadata; it does not force the question to count toward the final
score.

### Progress tracking

Question mode shows:

- **Question progress**: number of students for whom every criterion in the current question is graded, plus partial counts when applicable.
- **Overall progress**: number of explicitly graded criterion/student pairs across the session.

Missing assessment files count as ungraded. A deliberately awarded zero counts
as graded when its explicit v2.1 grading status is present.

## Saving and Loading Assessments

### Student-by-student save

**Save Assessment** retains its existing full-assessment behavior.

### Question-by-question save

The main **Save Assessment** button routes to the same partial-save operation as
**Save** in the question workflow card. Hidden-question scores are preserved.

### Loading an assessment

**Load Assessment** still loads a single JSON assessment. Criterion data is now
matched by stable criterion ID first, with a title fallback for legacy criteria
that genuinely lack IDs. This is safer than relying on rubric/assessment array
position.

## Exporting to PDF

PDF export continues to use the saved assessment/scoring data. Question-centric
workflow metadata does not change PDF score calculations.

## Tips and Best Practices

### Efficient grading

- Put explicit `question_id` fields in long-lived rubrics rather than depending only on inference.
- Use one assessment directory per assignment.
- Load the roster before grading so students without existing files are included in progress counts.
- Use **Save and Next Student** for the fastest question-by-question pass.
- Mark a question complete only after all of its criteria have been scored.

### Managing assessments

- Use stable, unique `student_id` values in roster CSV files.
- Keep existing assessment JSON files in the selected assignment directory.
- Do not manually delete criterion IDs from saved files; stable IDs drive safe partial merges.

### Designing rubrics

- Give every criterion a stable `id`.
- Give every criterion an explicit `question_id` when possible.
- Multiple criteria for the same assignment question should share the same `question_id`.
- Keep outcome mappings and assessment tags at criterion level as before.

## Troubleshooting

**Problem: a criterion appears under “Criteria without question assignment.”**  
Its rubric criterion has no explicit `question_id` and the title did not match a
supported inference pattern. Add a `question_id` to the rubric and save it.

**Problem: progress shows a student as ungraded.**  
Confirm that the roster identity matches the assessment's student ID/name and
that the criterion has been explicitly graded. Legacy files are supported, but
saving them through v2.1 adds clearer identity/grading metadata.

**Problem: changing questions asks about unsaved work.**  
This is intentional. Save to merge the current visible question into the full
assessment, discard to reload the student's persisted data, or cancel navigation.

**Problem: PDF/ABET totals look different after selecting attempted questions.**  
Question-centric mode does not define the scoring policy. Review **Grading Config**
and the existing attempted/selected-question controls; those continue to decide
selected/counted behavior.

For other issues, consult the Rubric Format documentation and the project's
existing reporting/ABET documentation.
