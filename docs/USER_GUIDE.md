# User Guide — Rubric Grading Tool

This guide walks through the complete workflow from creating a rubric to generating
semester-level ABET reports. Follow the sections in order for a new course setup,
or jump to a specific section if you are already set up.

---

## Table of Contents

1. [Concepts you need to know first](#1-concepts-you-need-to-know-first)
2. [Step 1 — Create your rubric JSON](#2-step-1--create-your-rubric-json)
3. [Step 2 — Load the rubric and fix the IDs](#3-step-2--load-the-rubric-and-fix-the-ids)
4. [Step 3 — Grade students](#4-step-3--grade-students)
5. [Step 4 — Export PDFs](#5-step-4--export-pdfs)
6. [Step 5 — Set up ABET outcome mappings](#6-step-5--set-up-abet-outcome-mappings)
7. [Step 6 — Generate an assignment-level ABET report](#7-step-6--generate-an-assignment-level-abet-report)
8. [Step 7 — Generate a semester-level ABET report](#8-step-7--generate-a-semester-level-abet-report)
9. [Using the CLI tools](#9-using-the-cli-tools)
10. [Folder organisation that works](#10-folder-organisation-that-works)
11. [Frequently asked questions](#11-frequently-asked-questions)

---

## 1. Concepts you need to know first

Before you touch the app, it helps to understand four concepts.

### Rubric vs Assessment

A **rubric** is the template — it defines the criteria, point values, and achievement
levels for an assignment. One rubric is shared across all students.

An **assessment** is a graded instance of that rubric for one student. When you grade
Alice, you produce `ps1_alice.json`. When you grade Bob, you produce `ps1_bob.json`.
The rubric file itself never changes when you grade.

### Schema 1.0 vs Schema 2.0

Old rubrics (schema 1.0) have no `schema_version` field and no criterion `id` fields.
They work fine for basic grading.

New rubrics (schema 2.0) add:
- `schema_version: "2.0"` at the top
- A stable `id` on every criterion
- `course_outcomes`, `program_outcomes`, `abet_outcomes`, `assessment_tags` on every criterion
- A `profile_id` linking the rubric to an outcome profile

You need schema 2.0 for ABET reporting. The app upgrades schema 1.0 rubrics automatically
when you load them, or you can migrate them with the CLI tool.

### Criterion IDs

A criterion ID is a short stable string that permanently identifies one criterion, e.g.
`P1C_SPECTRAL_RADIUS` or `AS4_PART2C_ATTENTION`. It is generated once from the criterion
title and then never changes, even if you rename the title later.

IDs matter because they are the link between a saved student assessment and the rubric
entry it came from. Without them, the scoring engine matches criteria by title — which
breaks the moment you fix a typo.

**Best practice:** after the app auto-generates IDs, open the rubric JSON and manually
shorten them to something concise and structural before grading anyone. Once you start
grading, do not change the IDs.

### Outcome Profiles

An outcome profile is a JSON file in `config/outcome_profiles/` that defines the course
learning outcomes (LOs), program/ABET outcomes (SOs), the LO→SO crosswalk, keyword
rules for auto-mapping, and performance bands for a specific course. Built-in profiles:

| Profile | Course |
|---|---|
| `cs2500_algorithms` | CS 2500 Algorithms |
| `cs5480_deep_learning` | CS 5480 Deep Learning |
| `cs5001_information_retrieval` | CS 5001 Information Retrieval |
| `cs1575_data_structures` | CS 1575 Data Structures |
| `generic_course` | Starting point for any course |

---

## 2. Step 1 — Create your rubric JSON

You have four options. Use whichever suits your situation.

### Option A — Start from a built-in template (recommended for CS 2500, CS 5480, CS 5001)

Templates in `templates/` are schema 2.0 with IDs and outcome fields already filled in.

```bash
python -m src.tools.rubric_template from-template \
    templates/cs2500/ps_greedy.json \
    --output assignments/PS3/rubric.json \
    --title "PS3 - Greedy Algorithms" \
    --id F2026_PS3
```

Open the output file, keep the criteria that match your assignment, delete the rest,
and add any criteria specific to your questions. The IDs and outcome fields are already
correct — you may only need to adjust point values.

Available templates:
```
templates/cs2500/ps_asymptotic_analysis.json
templates/cs2500/ps_divide_conquer.json
templates/cs2500/ps_dynamic_programming.json
templates/cs2500/ps_greedy.json
templates/cs2500/ps_graphs.json
templates/cs2500/ps_np_completeness.json
templates/cs2500/ps_sorting.json
templates/cs2500/exam_template.json
templates/cs5480/nn_design_assignment.json
templates/cs5001/ir_system_assignment.json
```

### Option B — Start from a blank profile-wired rubric

```bash
python -m src.tools.rubric_template blank \
    --output assignments/AS4/rubric.json \
    --profile cs5480_deep_learning \
    --title "AS4 - RNNs and Attention" \
    --questions 8 \
    --points 10
```

This creates 8 empty criteria with `course_outcomes: []`, `program_outcomes: []`, etc.
already in place. You fill in the titles, descriptions, point values, levels, and
outcome fields.

### Option C — Write it from scratch

Schema 2.0 rubric with one criterion shown in full. Copy and extend.

```json
{
  "schema_version": "2.0",
  "title": "AS4 - RNNs and Attention",
  "profile_id": "cs5480_deep_learning",
  "criteria": [
    {
      "id": "AS4_P1C_SPECTRAL",
      "title": "Part 1(c): Spectral Radius Tracking",
      "description": "Compute largest singular value of W_hh at init and after each epoch; plot with rho=1 reference line.",
      "points": 5,
      "course_outcomes": ["LO4"],
      "program_outcomes": ["SO1"],
      "abet_outcomes":    ["SO1"],
      "assessment_tags":  ["analysis", "rnn"],
      "levels": [
        {
          "title": "Full Credit",
          "points": 5,
          "description": "Correct SVD-based computation; tracked per epoch; rho=1 line shown; init and final values printed."
        },
        {
          "title": "Partial Credit",
          "points": 3,
          "description": "Mostly correct but reference line missing or not tracked per epoch."
        },
        {
          "title": "No Credit",
          "points": 0,
          "description": "Incorrect computation or plot absent."
        }
      ]
    }
  ]
}
```

**ID naming convention** — keep IDs short and structural, not derived from the full
title text. A good pattern: `<ASSIGNMENT>_<PART>_<KEYWORD>`.

| Long auto-generated | Better manual ID |
|---|---|
| `PART_1_B_STEP_1_GRADIENT_NORM_PLOT_AT_INITIALIZATION_T_IN_10_25_50` | `AS4_P1B_S1` |
| `PART_1_C_SPECTRAL_RADIUS_TRACKING` | `AS4_P1C_SPECTRAL` |
| `PART_2_C_ATTENTION_MODULE_IMPLEMENTATION` | `AS4_P2C_ATTN` |
| `BONUS_1_A_WINDOWED_ATTENTION` | `AS4_BONUS1A` |

### Option D — Migrate an existing schema 1.0 rubric

If you already have a rubric from a previous semester without IDs or outcome fields:

```bash
python tools/migrate_rubrics_to_abet.py \
    --input old_rubric.json \
    --output assignments/AS4/rubric.json \
    --profile cs5480_deep_learning \
    --auto-map
```

Then open the output file and manually shorten the auto-generated IDs before grading.

---

## 3. Step 2 — Load the rubric and fix the IDs

### Loading

1. Launch the app: `python src/main.py`
2. Click **Load Rubric**
3. Select your rubric JSON file

### The "missing stable criterion IDs" prompt

If your rubric is schema 1.0 (no IDs), the app shows:

> *This rubric is missing stable criterion IDs (required for ABET reporting).
> Would you like to save the updated rubric with IDs now?*

**What to do:**

1. Click **No** for now
2. Open the rubric JSON in a text editor
3. The app has added IDs in memory — to see what they look like, run:
   ```bash
   python tools/migrate_rubrics_to_abet.py \
       --input your_rubric.json \
       --output preview.json \
       --dry-run
   ```
4. Shorten the IDs to your own naming convention (see the table above)
5. Save the rubric file
6. Reload it in the app — no prompt this time

If you don't care about ABET reporting right now, click **Yes** and accept the
auto-generated IDs. You can always manually edit them later before generating reports.

### Configure grading options

After loading, the Grading Configuration panel shows. Set:
- **Grading mode**: "Best N of M" counts the highest N scores from all attempted questions;
  "Selected only" counts exactly the questions you check
- **Number to count**: e.g., best 5 of 7
- **Total points**: fixed (e.g., always 50) or variable (sum of counted questions)

---

## 4. Step 3 — Grade students

### One student at a time

1. Type the student name in the **Student** field
2. Check the boxes for which questions the student attempted
3. For each criterion:
   - Click an achievement level checkbox (points are set automatically), or
   - Type points directly in the spinner (supports 0.5 increments)
   - Add comments in the text area (supports Markdown and LaTeX math with `$...$`)
4. Click **Save Assessment**
5. Name the file `as4_alice.json` and save it in your assessments folder
6. Click **Clear Form** and move to the next student

### Folder structure that works

```
assignments/
└── AS4/
    ├── rubric.json              ← the shared rubric
    └── assessments/
        ├── as4_alice.json
        ├── as4_bob.json
        └── as4_carol.json
```

Keep all assessments for one assignment in the same `assessments/` subfolder.
The ABET report generator and semester aggregator both expect this layout.

### Auto-save

The app auto-saves every 3 minutes to the system temp directory. The status bar
shows the last auto-save time. Manual save is still recommended after each student.

---

## 5. Step 4 — Export PDFs

### Single student

After grading and saving, click **Export to PDF** to generate a report for the
current student. The PDF includes criterion scores, achievement levels, comments,
and total score.

### All students at once

1. Click **Batch Export**
2. Select all the assessment JSON files for the assignment
3. Choose an output folder
4. The tool generates one PDF per assessment

---

## 6. Step 5 — Set up ABET outcome mappings

Skip this section if you only want PDF exports and don't need ABET reports.

ABET mappings connect each criterion to course learning outcomes (LOs) and
program/ABET outcomes (SOs). Once mappings are embedded in the rubric, every
assessment graded with that rubric automatically carries ABET evidence — no
extra steps during grading.

### Option A — Use a template (already mapped)

If you started from a template in `templates/`, the outcome fields are already
filled in. Skip to Step 6.

### Option B — Use the ABET Mapping dialog

1. Load your rubric
2. Click **ABET Mapping**
3. The dialog shows a table: one row per criterion, columns for each LO and SO
4. Check the boxes for each outcome a criterion assesses
5. Or click **Auto-map from title** — the app applies keyword rules from the
   loaded profile to check boxes automatically. Review and adjust the results.
6. Click **Save into rubric** — the mappings are embedded directly in the rubric
   JSON. No separate mapping file is needed.
7. When prompted, save the rubric file.

### What each outcome field means

| Field | What to put there |
|---|---|
| `course_outcomes` | LOs from your course (e.g. `["LO1", "LO4"]`) |
| `program_outcomes` | ABET SOs (e.g. `["SO1", "SO6"]`) |
| `abet_outcomes` | Same as `program_outcomes` — kept in sync automatically |
| `assessment_tags` | Optional keywords for your own filtering (e.g. `["runtime", "proof"]`) |

### Example mapping for a deep learning assignment

| Criterion | `course_outcomes` | `program_outcomes` |
|---|---|---|
| Part 1(c): Spectral Radius Tracking | `["LO4"]` | `["SO1"]` |
| Part 2(c): Attention Implementation | `["LO2"]` | `["SO2", "SO6"]` |
| Part 3(b): Gradient Check | `["LO3"]` | `["SO2", "SO6"]` |
| Part 4(a): BERT Fine-Tuning | `["LO5"]` | `["SO2", "SO6"]` |
| Part 2 Analysis Q1: Written Explanation | `["LO7"]` | `["SO3"]` |

### Validate before grading

After mapping, run the validation tool to catch any issues:

```bash
python tools/validate_abet_rubric.py \
    --rubric assignments/AS4/rubric.json \
    --profile cs5480_deep_learning
```

Fix any ERRORs before grading. WARNINGs (e.g. unmapped criteria) are non-blocking
but worth reviewing.

---

## 7. Step 6 — Generate an assignment-level ABET report

Do this after you have graded all students for one assignment.

### In the app

1. Click **ABET Report**
2. Fill in the course information:
   - Course Code: `CS 5480`
   - Course Name: `Deep Learning`
   - Semester: `Fall 2026`
   - Assessment Name: `Assignment 4`
   - Target %: `75` (percentage of students who must score Adequate or higher)
3. Click **Browse…** next to Assessment Directory and select your `assessments/` folder
4. The mapping file field can be left blank — mappings are embedded in the rubric
5. Select the outcome profile from the dropdown
6. Click **Run Validation** first to check for issues
7. Click **Generate ABET Report**

The report is saved to a folder alongside your assessments. It contains:
- `abet_report.json` — full report data
- `abet_assignment_so_summary.csv` — one row per program outcome: mean, adequate+%, meets target
- `abet_assignment_lo_summary.csv` — same for course LOs
- `abet_student_outcomes.csv` — one row per student per outcome
- `abet_assignment_so_summary.xlsx` — all the above in a single workbook

### What the report shows

For each outcome (LO and SO):
- **Mean %** across all students
- **Performance band distribution**: how many students are Excellent / Adequate / Needs Improvement / Inadequate
- **Adequate+ %**: percentage of students scoring Adequate or higher
- **Meets target**: Yes/No based on your target % setting

---

## 8. Step 7 — Generate a semester-level ABET report

Do this at the end of the semester after all assignments are graded.

### Step 7a — Create a semester config

```bash
python tools/create_semester_config.py \
    --folder CS5480_Fall2026/ \
    --output CS5480_Fall2026/semester.json \
    --course "CS 5480" \
    --name "Deep Learning" \
    --semester "Fall 2026" \
    --instructor "Shubham Chatterjee" \
    --profile cs5480_deep_learning \
    --target 75
```

This scans your semester folder and generates `semester.json`. It expects this layout:

```
CS5480_Fall2026/
├── AS1/assessments/
├── AS2/assessments/
├── AS3/assessments/
├── AS4/assessments/
├── Midterm/assessments/
└── Final/assessments/
```

Open the generated `semester.json` and:
1. Check that all assignments were detected
2. Set `weight` for each assignment if some count more than others (default is `1.0`)
3. Any assignment you want to exclude, set `"include_in_abet": false`
4. Fill in `reflection`, `planned_improvements`, and `notes_for_next_offering` — these
   are expected by ABET reviewers and appear in the exported report

Example semester.json after editing:
```json
{
  "course_code": "CS 5480",
  "course_name": "Deep Learning",
  "semester": "Fall 2026",
  "profile_id": "cs5480_deep_learning",
  "target_percentage": 75.0,
  "assessments": [
    {"assessment_name": "AS1", "weight": 1.0, "include_in_abet": true, ...},
    {"assessment_name": "AS2", "weight": 1.0, "include_in_abet": true, ...},
    {"assessment_name": "Midterm", "weight": 2.0, "include_in_abet": true, ...},
    {"assessment_name": "Final",   "weight": 2.0, "include_in_abet": true, ...}
  ],
  "reflection": "Students struggled with the attention implementation in AS4. Added more worked examples to lectures.",
  "planned_improvements": "Add a scaffolded lab on scaled dot-product attention before AS4.",
  "notes_for_next_offering": "Consider splitting AS4 into two smaller assignments."
}
```

### Step 7b — Generate the report in the app

1. Click **Semester Report**
2. Click **Load semester config…** and select your `semester.json`
3. Click **Generate Semester Report**
4. Review the five result tabs:
   - **Program Outcomes** — semester mean, adequate+%, meets target per SO
   - **By Assessment** — how each SO scored on each assignment (spot which assessments drove the outcome)
   - **Coverage Matrix** — which assignments covered which LOs (check for gaps)
   - **Course LOs** — same as Program Outcomes but for LOs
   - **Closing the Loop** — the reflection fields from your config
5. Click **Export XLSX / CSV** to save everything for your ABET documentation

### What to look for in the semester report

**Coverage matrix** — every LO should appear in at least 2–3 assignments. If LO5
only appears in the Final, that's a gap worth noting in your reflection.

**By Assessment table** — if SO1 scores dropped sharply on the Midterm but recovered
on the Final, that's a teaching signal worth documenting.

**Meets target** — any outcome that doesn't meet your target % needs a planned
improvement noted in `planned_improvements`.

---

## 9. Using the CLI tools

### Migrate old rubrics

```bash
# Single file — preview changes without writing
python tools/migrate_rubrics_to_abet.py \
    --input old_rubric.json \
    --output new_rubric.json \
    --profile cs5480_deep_learning \
    --dry-run

# Single file — write output
python tools/migrate_rubrics_to_abet.py \
    --input old_rubric.json \
    --output new_rubric.json \
    --profile cs5480_deep_learning \
    --auto-map

# Whole directory of rubrics
python tools/migrate_rubrics_to_abet.py \
    --batch-dir old_rubrics/ \
    --output-dir new_rubrics/ \
    --profile cs5480_deep_learning \
    --auto-map
```

### Validate a rubric

```bash
# Rubric only
python tools/validate_abet_rubric.py \
    --rubric assignments/AS4/rubric.json \
    --profile cs5480_deep_learning

# Rubric + all student assessments
python tools/validate_abet_rubric.py \
    --rubric assignments/AS4/rubric.json \
    --assessments assignments/AS4/assessments/ \
    --profile cs5480_deep_learning

# Fail with exit code 1 on any ERROR (useful in a grading script)
python tools/validate_abet_rubric.py \
    --rubric assignments/AS4/rubric.json \
    --strict
```

### Create a rubric from a template

```bash
# List available templates
python -m src.tools.rubric_template list

# From an existing template file
python -m src.tools.rubric_template from-template \
    templates/cs5480/nn_design_assignment.json \
    --output assignments/AS2/rubric.json \
    --title "AS2 - CNNs and Regularization"

# Blank rubric wired to a profile
python -m src.tools.rubric_template blank \
    --output assignments/AS4/rubric.json \
    --profile cs5480_deep_learning \
    --title "AS4 - RNNs and Attention" \
    --questions 10 \
    --points 5
```

---

## 10. Folder organisation that works

One semester, one course:

```
CS5480_Fall2026/
├── semester.json                   ← generated by create_semester_config.py
├── AS1/
│   ├── rubric.json                 ← schema 2.0, IDs set, outcomes mapped
│   └── assessments/
│       ├── as1_alice.json
│       ├── as1_bob.json
│       └── ...
├── AS2/
│   ├── rubric.json
│   └── assessments/
├── AS3/
│   ├── rubric.json
│   └── assessments/
├── AS4/
│   ├── rubric.json
│   └── assessments/
├── Midterm/
│   ├── rubric.json
│   └── assessments/
├── Final/
│   ├── rubric.json
│   └── assessments/
└── reports/
    ├── abet_AS1_report/            ← assignment-level reports
    ├── abet_AS2_report/
    └── abet_semester_report/       ← semester-level report
```

Multiple courses, multiple semesters:

```
teaching/
├── CS2500/
│   ├── Fall2025/
│   └── Fall2026/
│       ├── semester.json
│       ├── PS1/ ...
│       └── reports/
├── CS5480/
│   ├── Spring2026/
│   └── Fall2026/
└── CS5001/
    └── Spring2026/
```

---

## 11. Frequently asked questions

**Do I have to use ABET features to use the app?**

No. Load a rubric, grade students, export PDFs. The ABET fields in schema 2.0 rubrics
are empty lists by default and don't affect anything until you generate a report.

**I already graded students with an unmapped rubric. Can I add mappings now?**

Yes, but with a limitation. You can add outcome mappings to the rubric at any time.
However, the already-saved assessment JSONs won't have outcome fields. To score them
for ABET, re-open each assessment, load it, and re-save it — the app will copy the
outcome fields from the current rubric into the saved assessment on re-save. Alternatively,
run the migration tool on the assessment files to add the fields programmatically.

**What is the difference between `course_outcomes` and `program_outcomes`?**

`course_outcomes` are your LOs — the specific learning objectives for your course
(e.g., LO1: "Analyse asymptotic complexity"). `program_outcomes` are the ABET SOs
that your department reports on (e.g., SO1: "Analyse a complex computing problem").
One LO typically maps to one or two SOs via the crosswalk in the outcome profile.

**Can I use the same rubric across multiple sections?**

Yes. The rubric is a template — it defines criteria and outcome mappings. Each section
has its own `assessments/` folder. When generating a semester report, you can include
assessments from multiple sections in the same semester config by listing them all
under `assessments`.

**The auto-generated IDs are very long. Can I shorten them after grading has started?**

No. Once you have saved even one student assessment with a given criterion ID, do not
change that ID in the rubric. The assessment JSON references the criterion by ID —
changing the rubric ID orphans all existing assessment data for that criterion. Always
set your IDs to their final form before grading the first student.

**I need a profile for a course not in the built-in list.**

Copy `config/outcome_profiles/generic_course.json` to a new file, fill in your
course LOs, program outcomes, crosswalk, and keyword rules, and set a unique
`profile_id`. The app will pick it up automatically from the `config/outcome_profiles/`
directory.

**What does "Adequate or higher" mean?**

The performance bands are:

| Band | Score range |
|---|---|
| Excellent | 90–100% |
| Adequate | 75–89.99% |
| Needs Improvement | 40–74.99% |
| Inadequate | 0–39.99% |

"Adequate or higher" = Excellent + Adequate. The target percentage (default 75%) means:
"at least 75% of students must score Adequate or higher on this outcome for the course
to meet its assessment target."

**The semester report says SO1 doesn't meet target. What do I do?**

1. Fill in the `planned_improvements` field in `semester.json` describing what you
   will change — this is required for ABET documentation.
2. Identify which assignments drove the low score using the By Assessment table.
3. Check the Coverage Matrix to see if SO1 has sufficient evidence (enough assignments
   covered it).
4. Document the action taken in `notes_for_next_offering` so future-you remembers.

**How do I run the tests?**

```bash
python -m unittest discover -s src/tests
```

All tests run headlessly. No Qt installation or GUI is required.