# Rubric Grading Tool

A professional, cross-platform desktop application for educators to create, manage, and use grading rubrics for student assessments — with full ABET program-outcome tracking, semester-level aggregation, and documentation-ready reporting.

---

## Features

### Core Grading
- Load rubrics from JSON or CSV
- Grade assignments with customizable criteria and achievement levels
- Automatic point calculation from level selection
- Flexible grading modes: grade all attempted questions and count the best N, or grade only selected questions
- Real-time score summary with color-coded totals
- Save and load assessment JSON files
- Export to PDF with score summary and comments
- Batch PDF export across an entire assessment folder
- Auto-save every 3 minutes
- Analytics dashboard: histograms, score distributions, per-question stats

### ABET Assessment (Phases 1–4)

The ABET system is designed around one principle: **grade once, collect ABET evidence automatically**.

- **Embedded outcome mappings** — `program_outcomes`, `course_outcomes`, and `assessment_tags` stored directly in the rubric JSON; no separate mapping file required
- **Outcome profiles** — course-specific LO and program-outcome definitions, keyword rules, performance bands, and LO→SO crosswalks in `config/outcome_profiles/`
- **Auto-map from title** — keyword rules infer course LOs and program outcomes from criterion titles with one click
- **Full ABET Mapping dialog** — checkboxes for every LO and SO per criterion, validation, profile reload, import/export, save-into-rubric
- **Assignment-level ABET report** — mean, median, std dev, performance bands, target achievement per outcome; JSON + CSV + XLSX export
- **Semester-level ABET report** — aggregate multiple assignments; weighted-mean formula; outcome-by-assignment table; evidence coverage matrix; student-outcome rows; closing-the-loop notes; JSON + CSV + XLSX export
- **Validation** — ERROR/WARNING/INFO issues before generating any report (duplicate IDs, unmapped criteria, unknown outcome IDs)
- **Performance bands**: Excellent ≥ 90%, Adequate 75–89.99%, Needs Improvement 40–74.99%, Inadequate < 40%

### Outcome Profiles (Phase 5)

Pre-built profiles for four courses, each defining course LOs, program outcomes, LO→SO crosswalk, keyword-to-LO rules, performance bands, and target percentage:

| Profile ID | Course |
|---|---|
| `cs2500_algorithms` | CS 2500 Algorithms (default) |
| `cs5480_deep_learning` | CS 5480 Deep Learning |
| `cs5001_information_retrieval` | CS 5001 Information Retrieval |
| `cs1575_data_structures` | CS 1575 Data Structures |
| `generic_course` | Blank template for any course |

### Rubric Templates (Phase 5)

Ready-to-use ABET-aware rubric templates in `templates/`:

**CS 2500 Algorithms** (8 templates)
- `ps_asymptotic_analysis`, `ps_divide_conquer`, `ps_dynamic_programming`, `ps_greedy`, `ps_graphs`, `ps_np_completeness`, `ps_sorting`, `exam_template`

**CS 5480 Deep Learning** — `nn_design_assignment`

**CS 5001 Information Retrieval** — `ir_system_assignment`

All templates are schema 2.0 with stable criterion IDs, `program_outcomes`, `course_outcomes`, and `assessment_tags` pre-filled.

### CLI Tools (Phase 6)

| Tool | Purpose |
|---|---|
| `tools/migrate_rubrics_to_abet.py` | Upgrade old rubrics to schema 2.0; single-file or batch; auto-map from titles |
| `tools/validate_abet_rubric.py` | Validate a rubric and/or assessment directory before reporting; `--strict` for CI |
| `tools/create_semester_config.py` | Scan a semester folder and generate `semester.json` for the semester report |

---

## Installation

### Prerequisites

- Python 3.8 or later
- PyQt5
- ReportLab
- NumPy
- QtAwesome
- Matplotlib
- openpyxl (for XLSX export)

### Setup

```bash
git clone https://github.com/shubham526/grading_app.git
cd grading_app
pip install -r requirements.txt
python src/main.py
```

---

## Repository Structure

```
grading_app/
├── src/
│   ├── main.py
│   ├── core/
│   │   ├── assessment.py        # Saves ABET metadata with every graded criterion
│   │   ├── grader.py
│   │   ├── outcome_profile.py   # OutcomeProfile class; load_profile(); keyword inference
│   │   ├── rubric.py            # Schema 2.0 loader; ID generation; outcome normalisation
│   │   └── utils.py             # generate_criterion_id(); normalize_title_to_id()
│   ├── tools/
│   │   ├── abet_export.py       # Assignment + semester CSV/XLSX export
│   │   ├── abet_scoring.py      # Scoring engine; performance bands; check_targets()
│   │   ├── abet_tool.py         # ABETAssessmentAnalyzer; generate_abet_report()
│   │   ├── abet_validation.py   # ERROR/WARNING/INFO validation engine
│   │   ├── rubric_template.py   # create_from_template_file(); create_blank_rubric()
│   │   ├── rubric_converter.py
│   │   └── semester_abet_report.py  # SemesterABETReport; from_folder(); from_config()
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── dialogs/
│   │   │   ├── abet_dialogs.py  # ABETMappingDialog, ABETReportDialog,
│   │   │   │                    # ABETResultsDialog, SemesterABETReportDialog
│   │   │   ├── analytics.py
│   │   │   └── config.py
│   │   └── widgets/
│   │       └── criterion.py     # get_data() includes criterion id
│   ├── utils/
│   │   ├── file_io.py           # Handles (rubric, is_dirty) tuple
│   │   ├── rubric_parser.py     # Thin shim → src.core.rubric
│   │   └── ...
│   ├── tests/
│   │   ├── test_scoring.py      # Scoring engine, validation, profiles
│   │   ├── test_rubric.py       # Rubric loading, ID generation, normalisation
│   │   ├── test_semester.py     # Semester aggregation, weighted means, export
│   │   ├── test_templates.py    # Template files, new profiles, rubric_template.py
│   │   ├── test_tools.py        # Migration, validation CLI, semester config
│   │   ├── test_grader.py       # CriterionWidget logic
│   │   └── test_rubric_parser.py
│   ├── examples/
│   └── docs/
├── config/
│   └── outcome_profiles/        # Profile JSON files (one per course)
│       ├── cs2500_algorithms.json
│       ├── cs5480_deep_learning.json
│       ├── cs5001_information_retrieval.json
│       ├── cs1575_data_structures.json
│       └── generic_course.json
├── templates/                   # ABET-ready rubric templates
│   ├── cs2500/                  # 8 templates
│   ├── cs5480/
│   └── cs5001/
├── tools/                       # CLI utilities
│   ├── migrate_rubrics_to_abet.py
│   ├── validate_abet_rubric.py
│   └── create_semester_config.py
├── requirements.txt
└── README.md
```

---

## Quick Start

### Basic Grading

1. **Load rubric** → Click "Load Rubric", select a JSON or CSV file
2. **Configure grading** → Set how many questions to count
3. **Grade students** → Select achievement levels or enter points; add comments
4. **Save assessment** → Click "Save Assessment" for each student
5. **Export to PDF** → Generate per-student reports

### ABET Workflow

#### One-time setup per rubric

**Option A — Use an existing template (recommended):**
```
File → New from Template → templates/cs2500/ps_greedy.json
```
Templates already have `program_outcomes`, `course_outcomes`, and `assessment_tags` filled in. Skip to grading.

**Option B — Map an existing rubric:**
1. Load your rubric
2. Click **"ABET Mapping"**
3. Check LO and SO boxes for each criterion, or click **"Auto-map from title"** to apply keyword rules
4. Click **"Save into rubric"** — mappings are embedded in the rubric file; no separate mapping file needed

**Option C — Migrate a legacy rubric:**
```bash
python tools/migrate_rubrics_to_abet.py \
    --input old_rubric.json \
    --output new_rubric.json \
    --profile cs2500_algorithms \
    --auto-map
```

#### Grade normally

Grade students exactly as before. ABET evidence is collected automatically from every saved assessment.

#### Generate assignment-level report

1. Click **"ABET Report"**
2. Enter course code, name, semester, assessment name, and target %
3. Browse to the assessments directory
4. Click **"Generate ABET Report"** → JSON + CSV + XLSX written to an export folder

#### Generate semester report

1. Click **"Semester Report"**
2. Load a `semester.json` config file, or scan a semester folder directly
3. Click **"Generate Semester Report"**
4. View outcome summary, by-assignment table, evidence coverage matrix, and closing-the-loop notes
5. Click **"Export XLSX / CSV"** for ABET documentation

---

## ABET Rubric Format (Schema 2.0)

Every criterion must have a stable ID, `course_outcomes`, `program_outcomes`, and `assessment_tags`:

```json
{
  "schema_version": "2.0",
  "title": "PS3 - Greedy Algorithms",
  "profile_id": "cs2500_algorithms",
  "criteria": [
    {
      "id": "PS3_Q1_RUNTIME",
      "title": "Question 1 - Runtime Analysis",
      "description": "Derive the asymptotic runtime of the algorithm.",
      "points": 4,
      "course_outcomes":  ["LO1"],
      "program_outcomes": ["SO1", "SO6"],
      "abet_outcomes":    ["SO1", "SO6"],
      "assessment_tags":  ["runtime", "asymptotic-analysis"],
      "levels": [
        {"title": "Complete",  "points": 4, "description": "Correct with justification."},
        {"title": "Partial",   "points": 2, "description": "Minor errors."},
        {"title": "Incorrect", "points": 0, "description": "Incorrect or missing."}
      ]
    }
  ]
}
```

**Field notes:**
- `id` — stable uppercase token; auto-generated from title if missing on load
- `program_outcomes` — canonical field (replaces old `abet_outcomes`)
- `abet_outcomes` — kept as backward-compatible alias; always kept in sync with `program_outcomes`
- `profile_id` — links the rubric to an outcome profile for keyword inference and bands

Legacy rubrics (schema 1.0, no IDs, no outcome fields) load and work correctly. IDs are generated automatically on first load and you are prompted to save.

---

## Outcome Profiles

A profile is a JSON file in `config/outcome_profiles/` that defines:

```json
{
  "schema_version": "2.0",
  "profile_id": "cs2500_algorithms",
  "course_code": "CS 2500",
  "course_name": "Algorithms",
  "course_outcomes": {
    "LO1": "Analyze asymptotic complexity of algorithms.",
    "LO4": "Prove algorithm correctness."
  },
  "program_outcomes": {
    "SO1": "Analyze a complex computing problem...",
    "SO6": "Apply computer science theory..."
  },
  "default_course_to_program": {
    "LO1": ["SO1", "SO6"],
    "LO4": ["SO1", "SO6"]
  },
  "performance_bands": {
    "excellent":         [90.0, 100.0],
    "adequate":          [75.0,  89.99],
    "needs_improvement": [40.0,  74.99],
    "inadequate":        [ 0.0,  39.99]
  },
  "passing_bands": ["excellent", "adequate"],
  "target_percentage": 75.0,
  "keyword_to_course_outcome": {
    "LO1": ["runtime", "complexity", "asymptotic", "big-o"],
    "LO4": ["proof", "correctness", "induction", "invariant"]
  }
}
```

To create a profile for a new course, copy `generic_course.json` and fill in the fields.

---

## CLI Tools

### Migrate legacy rubrics

```bash
# Single file
python tools/migrate_rubrics_to_abet.py \
    --input old_rubric.json \
    --output new_rubric.json \
    --profile cs2500_algorithms \
    --auto-map

# Entire directory
python tools/migrate_rubrics_to_abet.py \
    --batch-dir rubrics/ \
    --output-dir rubrics_v2/ \
    --profile cs2500_algorithms \
    --auto-map

# Preview changes without writing
python tools/migrate_rubrics_to_abet.py \
    --input old_rubric.json \
    --output new_rubric.json \
    --dry-run
```

### Validate before reporting

```bash
# Validate rubric alone
python tools/validate_abet_rubric.py --rubric PS3/rubric.json

# Validate rubric + all student assessments
python tools/validate_abet_rubric.py \
    --rubric PS3/rubric.json \
    --assessments PS3/assessments/ \
    --profile cs2500_algorithms

# Fail with exit code 1 on any ERROR (useful in CI)
python tools/validate_abet_rubric.py --rubric rubric.json --strict

# Machine-readable JSON output
python tools/validate_abet_rubric.py --rubric rubric.json --json
```

### Generate a semester config

```bash
python tools/create_semester_config.py \
    --folder CS2500_Fall2026/ \
    --output CS2500_Fall2026/semester.json \
    --course "CS 2500" \
    --name "Algorithms" \
    --semester "Fall 2026" \
    --profile cs2500_algorithms \
    --target 75
```

Expected folder layout for the semester folder:
```
CS2500_Fall2026/
├── PS1/
│   └── assessments/    ← graded student JSON files
├── PS2/
│   └── assessments/
├── Midterm/
│   └── assessments/
└── Final/
    └── assessments/
```

### Create a rubric from a template

```bash
# From a template file
python -m src.tools.rubric_template from-template \
    templates/cs2500/ps_greedy.json \
    --output PS3/rubric.json \
    --title "PS3 - Greedy Algorithms" \
    --id F2026_PS3

# Blank rubric pre-wired to a profile
python -m src.tools.rubric_template blank \
    --output midterm2_rubric.json \
    --profile cs2500_algorithms \
    --questions 5 \
    --points 20

# List available templates
python -m src.tools.rubric_template list
```

---

## Running the Tests

```bash
# Run all tests from the repo root
python -m unittest discover -s src/tests

# or with pytest if you have it installed
python -m pytest src/tests/ -v
```

Individual suites with pytest:
```bash
python -m pytest src/tests/test_scoring.py    # scoring engine, validation, profiles
python -m pytest src/tests/test_rubric.py     # rubric loading, IDs, normalisation
python -m pytest src/tests/test_semester.py   # semester aggregation and export
python -m pytest src/tests/test_templates.py  # template files and new profiles
python -m pytest src/tests/test_tools.py      # CLI tools
```

The automated tests run headlessly and do not require launching the GUI. Current validation: `python -m unittest discover` passes 342 tests.

---

## Semester Folder and Config Format

The semester config (`semester.json`) is generated by `create_semester_config.py` and can also be written by hand:

```json
{
  "schema_version": "2.0",
  "course_code": "CS 2500",
  "course_name": "Algorithms",
  "semester": "Fall 2026",
  "instructor": "Shubham Chatterjee",
  "profile_id": "cs2500_algorithms",
  "target_percentage": 75.0,
  "assessments": [
    {
      "assessment_id":   "F2026_PS1",
      "assessment_name": "Problem Set 1",
      "assessment_dir":  "PS1/assessments",
      "include_in_abet": true,
      "weight": 1.0
    },
    {
      "assessment_id":   "F2026_MIDTERM",
      "assessment_name": "Midterm",
      "assessment_dir":  "Midterm/assessments",
      "include_in_abet": true,
      "weight": 2.0
    }
  ],
  "reflection": "Students performed well on runtime analysis.",
  "planned_improvements": "Add more graph algorithm problems.",
  "notes_for_next_offering": ""
}
```

All `assessment_dir` paths are stored relative to the config file so the semester folder is portable.

---

## Scoring Formula

For a student with criteria mapped to an outcome:

```
outcome_percentage = sum(awarded_i × weight_i) / sum(possible_i × weight_i) × 100
```

A criterion mapped to `[SO1, SO6]` contributes its full percentage to **both** SO1 and SO6 independently — there is no splitting.

Semester aggregation supports assignment weights using a weighted-mean formula when weights are specified. All assignments default to `weight: 1.0` if not set.

---

## ABET Best Practices

1. **Map once, grade many times.** Embed outcome mappings into the rubric file and reuse it across semesters. Only update the rubric when the assessment structure changes.

2. **Use templates.** Start from `templates/cs2500/` rather than building rubrics from scratch. All templates have stable IDs and pre-filled outcome fields.

3. **Validate before reporting.** Run `validate_abet_rubric.py --strict` before generating any report to catch unmapped criteria or unknown outcome IDs early.

4. **Keep a semester config.** Use `create_semester_config.py` at the start of each semester to generate `semester.json`. Update weights if some assessments count more than others.

5. **Fill in the closing-the-loop fields.** The `reflection`, `planned_improvements`, and `notes_for_next_offering` fields in the semester config are included in the semester report and expected by ABET reviewers.

6. **Collect at minimum 2–3 assessments per semester** for reliable outcome evidence.

---

## Troubleshooting

**Profile not found**
```
FileNotFoundError: Outcome profile not found: config/outcome_profiles/cs2500_algorithms.json
```
The `config/outcome_profiles/` directory is missing. Copy all five profile JSON files there from the repo.

**ABET Mapping button disabled**
Load a rubric first. The button enables after a rubric is loaded.

**Semester report shows no assessments**
Check that each `assessment_dir` in `semester.json` contains at least one `*.json` file and that the path is relative to the config file location, not to the working directory.

**Rubric won't load**
Verify the JSON is valid (use `python -m json.tool rubric.json`). Check for missing commas or unclosed brackets. Ensure the file is UTF-8 encoded.

**PDF export fails**
Check write permissions on the output directory. Ensure ReportLab is installed: `pip install reportlab`.

**ABET report shows 0 students**
Verify the assessments directory contains JSON files saved from the current rubric version. Run the validation CLI to check for mismatches.

**Migration produces duplicate IDs**
If two criteria have identical titles, `migrate_rubrics_to_abet.py` appends `_001`, `_002` suffixes to generated IDs automatically. Review the migration report printed to stdout.

---

## Contributing

Contributions welcome. Areas most useful:

- Additional outcome profiles for new courses
- Additional rubric templates
- LMS integration (Canvas, Gradescope)
- Additional export formats
- Internationalisation

Please open a Pull Request with:
1. A clear description of the change
2. Tests for any new behaviour
3. Updated documentation

---

## License

MIT License — see the LICENSE file for details.

---

## Acknowledgments

- Built with PyQt5 for cross-platform compatibility
- PDF generation via ReportLab
- ABET-oriented outcome tracking based on configurable program outcome profiles
- Semester aggregation supports assignment weights using a weighted-mean formula when weights are specified

---

## Version History

**v2.0.0** — ABET-Ready Release
- Schema 2.0 rubric format with stable criterion IDs
- Embedded outcome mappings (`program_outcomes`, `course_outcomes`, `assessment_tags`)
- Outcome profile system: CS 2500, CS 5480, CS 5001, CS 1575, generic
- Full ABET Mapping dialog with auto-map, profile reload, save-into-rubric
- Assignment-level ABET report with performance bands and target tracking
- Semester-level ABET aggregation with weighted means and coverage matrix
- CSV + XLSX export for all report types
- CLI tools: `migrate_rubrics_to_abet.py`, `validate_abet_rubric.py`, `create_semester_config.py`
- Rubric template generator with 10 pre-built templates
- 193+ automated tests

**v1.0.0** — Initial release
- Core rubric grading with achievement levels
- Flexible grading modes (best N of M)
- PDF export
- Basic ABET outcome mapping and reporting
- Analytics dashboard
- Auto-save

---

*Made with ❤️ for educators. For questions or support, open an issue on GitHub.*