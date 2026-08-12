# Rubric Format Specification

The Rubric Grading Tool supports rubrics in both JSON and CSV formats. JSON is
the preferred format because it can persist stable criterion IDs, question
metadata, outcome mappings, and achievement levels.

## JSON Format

### Basic Structure

```json
{
  "schema_version": "2.0",
  "title": "Assignment Title",
  "criteria": [
    {
      "id": "PS3_Q2_RUNTIME",
      "question_id": "Q2",
      "title": "Question 2 - Runtime Analysis",
      "description": "Analyze the asymptotic runtime.",
      "points": 4,
      "course_outcomes": ["LO1"],
      "program_outcomes": ["SO1", "SO6"],
      "abet_outcomes": ["SO1", "SO6"],
      "assessment_tags": ["runtime", "asymptotic-analysis"],
      "levels": [
        {
          "title": "Excellent",
          "description": "Correct and complete analysis.",
          "points": 4
        }
      ]
    }
  ]
}
```

### Criterion Fields

- **id** (string): Stable machine-readable criterion identifier. Missing IDs are generated on load and persisted when the rubric is saved.
- **question_id** (string, optional): Canonical assignment-question identifier used by the v2.1 question-centric workflow.
- **title** (string): Human-readable criterion title.
- **description** (string, optional): Description of what is being evaluated.
- **points** (number): Maximum points possible for the criterion.
- **levels** (array, optional): Achievement-level definitions.
- **course_outcomes** (array, optional): Course/learning-outcome mappings.
- **program_outcomes** (array, optional): Canonical program/ABET outcome mappings.
- **abet_outcomes** (array, optional): Backward-compatible alias for program outcome mappings.
- **assessment_tags** (array, optional): Criterion-level tags used by assessment/reporting workflows.

## Question IDs in v2.1

A question can contain multiple rubric criteria. For example, all of these can
share the same question ID:

```json
[
  {"id": "Q2_DESIGN", "question_id": "Q2", "title": "Q2 Algorithm Design", "points": 4},
  {"id": "Q2_PROOF", "question_id": "Q2", "title": "Q2 Correctness Proof", "points": 4},
  {"id": "Q2_RUNTIME", "question_id": "Q2", "title": "Q2 Runtime Analysis", "points": 2}
]
```

Canonical IDs use forms such as:

- `Q1`
- `Q1A`
- `Q1B`
- `Q2`
- `Q10`

When `question_id` is missing, the loader attempts to infer it from common title
forms:

| Criterion title | Inferred question_id |
|---|---|
| `Question 1 - Runtime` | `Q1` |
| `Q2 Correctness` | `Q2` |
| `Problem 3: DP` | `Q3` |
| `P4 Reduction` | `Q4` |
| `Question 1(a)` | `Q1A` |
| `Q2(b) Runtime` | `Q2B` |

If inference succeeds, the rubric is marked dirty so the inferred metadata can
be saved. If inference fails, the rubric still loads. In question-by-question
mode the criterion appears under **Criteria without question assignment**
(`UNASSIGNED`).

An explicit non-empty `question_id` is preserved rather than replaced by title
inference.

## CSV Format

CSV format is provided for simplicity and compatibility with spreadsheet
applications.

### Basic Structure

```text
Criterion Title, Description, Points, Level1 Title, Level1 Points, Level2 Title, Level2 Points, ...
Question 2 - Runtime Analysis, Analyze asymptotic runtime, 4, Excellent, 4, Good, 3, ...
```

### Format Rules

1. The first row contains headers.
2. Each subsequent row represents one criterion.
3. The first column is the criterion title.
4. The second column is the criterion description.
5. The third column is the maximum points.
6. Subsequent columns come in pairs: level title followed by level points.
7. Stable criterion IDs are generated in memory.
8. In v2.1, `question_id` is inferred from the criterion title when possible.

CSV cannot directly persist all JSON-only metadata, so saving an updated rubric
as JSON is recommended after IDs/question IDs are generated.

## Saved Assessment Metadata

Saved assessment files remain backward compatible with v2.0 and can additionally
contain v2.1 question/grading metadata.

A saved criterion can include:

```json
{
  "id": "PS3_Q2_RUNTIME",
  "question_id": "Q2",
  "points_awarded": 3,
  "points_possible": 4,
  "grading_status": {
    "graded": true,
    "graded_at": "2026-08-31T14:05:00+00:00",
    "graded_by": "instructor"
  }
}
```

`grading_status` distinguishes an untouched criterion from a criterion that was
intentionally awarded zero points. Legacy assessments without this object remain
supported; for those files, a non-`null` `points_awarded` value is treated as
graded.

Question-centric saves can also include navigation metadata:

```json
{
  "grading_progress": {
    "mode": "question_centric",
    "completed_questions": ["Q1", "Q2"],
    "last_question": "Q2",
    "last_student_id": "alice",
    "last_updated": "2026-08-31T14:00:00+00:00"
  }
}
```

This metadata is for navigation/progress only. It does not alter total scores,
selected/counted question logic, best-N-of-M behavior, analytics, PDF export, or
ABET calculations.

## Programmatic Rubric Creation

The tools directory contains utilities such as:

- `rubric_template.py`: Generate rubric templates.
- `rubric_converter.py`: Convert between supported formats.

For long-lived course rubrics, prefer JSON and assign explicit stable `id` and
`question_id` fields.
