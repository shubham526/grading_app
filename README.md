# Rubric Grading Tool

A professional, cross-platform desktop application for educators to efficiently create, manage, and use grading rubrics for student assessments with integrated ABET outcome tracking and reporting.

## Features

### Core Grading Features
- Create and load rubrics from JSON or CSV formats
- Grade assignments with customizable criteria
- Support for achievement levels with automatic point calculation
- Flexible grading modes for various assessment types:
  - Grade specific questions selected by instructor
  - Grade all attempted questions and count best scores
- Configure how many questions to count in the final score (e.g., best 5 of 7)
- Dynamic question summary showing performance across all questions
- Save and load assessment data
- Export assessments to professional PDF reports with score summary table
- Auto-save functionality to prevent data loss
- Clean, intuitive Material Design interface

### ABET Assessment Features
- **Map rubric criteria to ABET Student Outcomes** (SO1-SO6)
- **Automatic ABET data collection** during normal grading (no extra work!)
- **Generate comprehensive ABET reports** with one button click
- **Performance level analysis** (Exemplary, Proficient, Developing, Unsatisfactory)
- **Target achievement tracking** (e.g., "70% of students Proficient or higher")
- **Multi-outcome support** with weighted scoring
- **Visual results display** with color-coded performance indicators
- **Export-ready reports** for ABET documentation

## Installation

### Prerequisites

- Python 3.6 or later
- PyQt5
- ReportLab
- NumPy
- QtAwesome (for icons)
- Matplotlib (for analytics)

### Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/shubham526/grading_app.git
   cd grading_app
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python src/main.py
   ```

## Quick Start Guide

### Basic Grading Workflow

1. **Load a rubric** → Click "Load Rubric" and select your JSON/CSV file
2. **Configure grading** → Set how many questions to count
3. **Grade students** → Enter points and comments for each criterion
4. **Save assessments** → Click "Save Assessment" for each student
5. **Export to PDF** → Generate professional reports for students

### ABET Workflow (Optional)

1. **Create ABET mapping** (one-time setup) → Map criteria to outcomes
2. **Grade normally** → No changes to your grading process!
3. **Generate ABET report** → Click button after grading all students
4. **View results** → See performance on each Student Outcome

## Detailed Usage Guide

### Loading a Rubric

1. Click the "Load Rubric" button in the toolbar
2. Select a JSON or CSV file containing your rubric definition
3. The rubric will be displayed with all criteria and achievement levels
4. The grading configuration dialog will appear to set up question requirements

**Tip:** See the `src/examples/` folder for sample rubrics.

### Configuring Grading Options

1. Click "Grading Config" to open the configuration dialog
2. Select a grading mode:
   - **Best Scores**: Grade all attempted questions but count only the highest-scoring ones
   - **Selected Questions Only**: Grade only the specific questions you select
3. Specify how many questions to count in the final score (e.g., best 5 of 7)
4. Choose between:
   - **Fixed total points** (recommended for consistent grading)
   - **Variable total** based on actual questions graded
5. Set points per question if using fixed total
6. Click "OK" to apply settings

### Grading with the Rubric

1. **Enter student information**
   - Student name (required)
   - Assignment name (auto-filled from rubric)

2. **Select attempted questions**
   - Check boxes for questions the student attempted
   - In "Best Scores" mode: check all attempted questions
   - In "Selected" mode: check exactly the required number

3. **Grade each criterion**
   - Click achievement level checkboxes for quick grading, or
   - Enter points manually using the spinner (supports 0.5 increments)
   - Add detailed comments in the text area (supports Markdown)
   - Comments appear in the PDF export

4. **Monitor progress**
   - View real-time question summary showing which questions count
   - See color-coded total score (green ≥90%, orange ≥70%, red <70%)
   - Check auto-save status in the status bar

5. **Save the assessment**
   - Click "Save Assessment" 
   - Use naming convention: `assignment_studentname.json`
   - Store in organized folders (e.g., `assessments/midterm1/`)

### Batch Operations

**Batch Export to PDF:**
1. Click "Batch Export" button
2. Select multiple assessment JSON files
3. Choose output directory
4. Tool generates PDFs for all selected assessments

**Analytics:**
1. Click "Analytics" button
2. Select directory containing assessments
3. View histograms and statistics for:
   - Individual question performance
   - Overall score distribution
   - Class-wide trends

### Saving and Loading Assessments

**Save Assessment:**
- Click "Save Assessment" to save as JSON
- Assessments include all rubric data, points, comments, and configurations
- Auto-save runs every 3 minutes to prevent data loss
- Auto-saved files stored in system temp directory

**Load Assessment:**
- Click "Load Assessment" to open previously saved work
- Tool will prompt to load associated rubric if different from current
- All points, comments, and selections are restored

## ABET Assessment Integration

The Rubric Grading Tool includes powerful ABET outcome tracking that works seamlessly with your normal grading workflow.

### Key Principle: Grade Once, Collect ABET Data Automatically

**You do NOT grade twice.** ABET data is calculated automatically from your regular grading using outcome mappings.

### ABET Setup (One-Time per Rubric)

#### Step 1: Understand ABET Student Outcomes

The tool supports ABET Computer Science outcomes (2025-2026 criteria):

- **SO1:** Analyze a complex computing problem and apply principles of computing and other relevant disciplines to identify solutions
- **SO2:** Design, implement, and evaluate a computing-based solution to meet given requirements
- **SO3:** Communicate effectively in a variety of professional contexts
- **SO4:** Recognize professional responsibilities and make informed judgments based on legal and ethical principles
- **SO5:** Function effectively as a team member or leader
- **SO6:** Apply computer science theory and software development fundamentals

#### Step 2: Create ABET Mapping

**Option A: Create Mapping in the Tool**

1. Load your rubric first
2. Click "ABET Mapping" button
3. A dialog opens showing all rubric criteria in rows and outcomes (SO1-SO6) in columns
4. Check boxes to indicate which outcome(s) each criterion assesses
   - Example: "Algorithm Design" might assess SO1 and SO2
   - Example: "Written Explanation" might assess SO3
5. Click "Save Mapping" and save as `coursecode_assessment_mapping.json`
6. Store in an `abet_mappings/` folder

**Option B: Use Pre-Made Mapping**

For CS 2500 Algorithms courses, a complete pre-made mapping is available:

1. Save the provided `cs2500_midterm1_abet_mapping.json` file
2. Use it directly when generating reports (skip manual mapping)

**Mapping Guidelines:**
- A single criterion can assess multiple outcomes (weighted automatically)
- Focus on what skills students demonstrate in their answers
- Consider both primary and secondary skills (e.g., an algorithm question primarily assesses SO1 but may also assess SO3 if it requires written explanation)

#### Step 3: Map Your Rubric (Example)

For an algorithms exam:

| Criterion | SO1 (Analyze) | SO2 (Design) | SO3 (Communicate) |
|-----------|---------------|--------------|-------------------|
| Derive time complexity formula | ✓ | | |
| Write Big-O notation | ✓ | | ✓ |
| Design recursive algorithm | | ✓ | ✓ |
| Prove algorithm correctness | ✓ | | ✓ |
| Trace algorithm execution | | ✓ | |

### Normal Grading (Nothing Changes!)

**Grade students exactly as you normally would:**

1. Load rubric
2. Enter student name and assignment
3. Select attempted questions
4. Enter points and comments
5. Click "Save Assessment"
6. Move to next student

**Behind the scenes:** The tool automatically:
- Reads which outcomes each criterion assesses (from your mapping)
- Calculates weighted scores for each outcome
- Stores ABET data with the assessment
- **You see nothing different during grading!**

### Generate ABET Report (After Grading All Students)

#### Step 1: Click "ABET Report" Button

The ABET Report Generator dialog opens.

#### Step 2: Enter Course Information

```
Course Code:          CS 2500
Course Name:          Algorithms
Semester:             Fall 2024
Assessment:           Midterm 1
Target % (Proficient+): 70
```

**Target Percentage:** The minimum percentage of students who should score "Proficient or higher" on each outcome (typically 70%).

#### Step 3: Select Assessment Directory

1. Click "Browse..." next to "Assessment directory"
2. Navigate to the folder containing ALL graded student assessments
   - Example: `assessments/midterm1/`
   - Should contain: `student1.json`, `student2.json`, etc.
3. Click "Select Folder"

The tool will automatically find and load all JSON assessment files.

#### Step 4: Select ABET Mapping File

1. Click "Browse..." next to "Mapping file"
2. Select your mapping file (e.g., `cs2500_midterm1_abet_mapping.json`)
3. Click "Open"

#### Step 5: Generate Report

1. Click the green "Generate ABET Report" button
2. Choose where to save the report
   - Recommended: `abet_reports/abet_report_coursecode_assessment.json`
3. Wait a few seconds while processing

#### Step 6: View Results

A results dialog displays:

**Summary Table:**
| Outcome | Mean Score | Proficient+ | Target | Meets Target? | Distribution |
|---------|------------|-------------|--------|---------------|--------------|
| SO1     | 78.5%      | 72%         | 70%    | ✓ Yes         | E:12 P:20 D:10 U:3 |
| SO2     | 85.0%      | 80%         | 70%    | ✓ Yes         | E:15 P:21 D:7 U:2  |
| SO3     | 76.5%      | 71%         | 70%    | ✓ Yes         | E:10 P:22 D:11 U:2 |

**Legend:**
- **E** = Exemplary (≥90%)
- **P** = Proficient (80-89%)
- **D** = Developing (70-79%)
- **U** = Unsatisfactory (<70%)

**Detailed Summary:** Scroll down to see comprehensive statistics including:
- Mean, median, standard deviation for each outcome
- Min/max scores
- Number of students assessed
- Performance level distributions

### Understanding ABET Results

#### Performance Levels

- **Exemplary (≥90%):** Student demonstrates exceptional mastery
- **Proficient (80-89%):** Student demonstrates solid understanding
- **Developing (70-79%):** Student demonstrates partial understanding
- **Unsatisfactory (<70%):** Student does not demonstrate adequate understanding

#### Interpreting Outcomes

**SO1 (Analyze Complex Problems):**
- Assessed by: Mathematical proofs, complexity analysis, algorithm analysis
- Good performance: Students can derive formulas, analyze recurrences
- Needs work: Students struggle with formal proofs, mathematical reasoning

**SO2 (Design/Implement Solutions):**
- Assessed by: Pseudocode writing, algorithm design, tracing execution
- Good performance: Students create correct, efficient algorithms
- Needs work: Students have implementation errors, miss edge cases

**SO3 (Communicate Effectively):**
- Assessed by: Written explanations, proper notation, clear documentation
- Good performance: Students use correct notation, explain reasoning clearly
- Needs work: Students skip steps, use informal language, incomplete explanations

#### Taking Action on Results

**If an outcome is below target:**
1. Identify specific weak areas from question-level data
2. Add more practice on those topics
3. Provide additional resources (tutorials, examples)
4. Adjust instruction emphasis next semester

**If an outcome exceeds target:**
1. Document successful teaching strategies
2. Consider raising difficulty/expectations
3. Share approaches with department

### ABET Documentation

#### What to Save for ABET

1. **The JSON report file**
   - Contains all raw data and statistics
   - Example: `abet_report_cs2500_midterm1.json`

2. **Printed summary** (copy from results dialog)
   - Paste into Word/PDF for readability
   - Include in course assessment reports

3. **Sample student work** (optional)
   - Keep 3-5 anonymized assessments showing range of performance
   - Use exported PDFs

4. **Reflection notes**
   - What worked well?
   - Where did students struggle?
   - What will you change?

#### Organize for ABET Review

```
ABET_Documentation/
├── Fall2024/
│   ├── CS2500_Midterm1/
│   │   ├── abet_report_cs2500_midterm1.json
│   │   ├── summary_report.pdf
│   │   ├── sample_assessments/
│   │   └── reflection_notes.txt
│   ├── CS2500_Midterm2/
│   ├── CS2500_Final/
│   └── CS2500_Projects/
└── Spring2025/
```

#### Annual ABET Reporting

Combine data from multiple assessments:

1. Generate reports for each major assessment (midterms, final, projects)
2. Calculate weighted averages based on assessment weight in course
3. Report aggregate performance across all assessments

**Example calculation:**
```
SO1_course = 0.20 × SO1_midterm1 + 0.20 × SO1_midterm2 + 
             0.30 × SO1_projects + 0.30 × SO1_final
```

**Example ABET statement:**
> "In CS 2500 Fall 2024, 78% of students achieved Proficient or higher on SO1 (analyze complex computing problems), exceeding our target of 70%. Students demonstrated strong skills in complexity analysis and recurrence relations but need additional support with formal mathematical proofs."

### ABET Workflow Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    ONE-TIME SETUP                       │
│                                                         │
│  1. Load rubric                                         │
│  2. Click "ABET Mapping"                                │
│  3. Check outcome boxes for each criterion              │
│  4. Save mapping file                                   │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                   GRADE STUDENTS                        │
│              (Nothing different here!)                  │
│                                                         │
│  For each student:                                      │
│    1. Load rubric                                       │
│    2. Enter name                                        │
│    3. Grade questions                                   │
│    4. Save assessment                                   │
│                                                         │
│  ABET data captured automatically ✓                     │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│              GENERATE ABET REPORT                       │
│                                                         │
│  1. Click "ABET Report" button                          │
│  2. Enter course info                                   │
│  3. Select assessments folder                           │
│  4. Select mapping file                                 │
│  5. Click "Generate"                                    │
│  6. View results!                                       │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                 INTERPRET RESULTS                       │
│                                                         │
│  • Review mean scores per outcome                       │
│  • Check % Proficient or higher                         │
│  • Identify weak areas                                  │
│  • Document for ABET                                    │
│  • Plan improvements                                    │
└─────────────────────────────────────────────────────────┘
```

### ABET FAQs

**Q: Do I have to grade students twice?**
A: No! You grade once normally. ABET data is calculated automatically from that single grading.

**Q: Does ABET slow down grading?**
A: No! Zero extra time during grading. You only spend 2 minutes at the end clicking "Generate Report."

**Q: What if I forget to create the mapping?**
A: You can create it anytime, even after grading all students. Just need it before generating the report.

**Q: Can I use this for non-ABET courses?**
A: Yes! You can skip all ABET features and just use the regular grading tools.

**Q: Can I map one question to multiple outcomes?**
A: Yes! The tool automatically calculates weighted scores when a criterion assesses multiple outcomes.

**Q: What if students attempt different questions?**
A: The tool handles this automatically. It only includes attempted questions in the ABET calculations for each student.

**Q: How often should I collect ABET data?**
A: Every major assessment (2-3 times per semester minimum). More data = better understanding of student performance.

**Q: Can I edit a mapping after creating it?**
A: Yes! Load it in the ABET Mapping dialog, make changes, and save again.

**Q: What if my program uses different outcome names?**
A: The tool uses standard ABET CS outcomes (SO1-SO6), but you can adapt by mapping to whichever outcomes your program uses.

## Exporting to PDF

### Individual Export

1. Complete an assessment
2. Click "Export to PDF"
3. Choose location and filename
4. PDF includes:
   - Student and assignment information
   - Score summary table with letter grade
   - Question summary (which questions counted toward final score)
   - Grading configuration details
   - Detailed assessment with all criteria, achievement levels, points, and comments
   - Comments rendered with Markdown formatting support

### Batch Export

1. Click "Batch Export" button
2. Select multiple assessment JSON files
3. Choose output directory
4. Tool generates individual PDFs for each assessment
5. Creates batch summary file with metadata

## Rubric Format

### JSON Format (Recommended)

```json
{
  "title": "Assignment Title",
  "description": "Optional description",
  "criteria": [
    {
      "title": "Criterion Title",
      "description": "What is being evaluated",
      "points": 10,
      "levels": [
        {
          "title": "Excellent (8-10 pts)",
          "description": "Description of excellent work",
          "points": 10
        },
        {
          "title": "Good (6-7 pts)",
          "description": "Description of good work",
          "points": 7
        }
      ]
    }
  ]
}
```

### CSV Format

```csv
Criterion Title, Description, Points, Level1 Title, Level1 Points, Level2 Title, Level2 Points
Introduction, Clear introduction, 10, Excellent, 10, Good, 8
```

For complete format specifications, see [Rubric Format Documentation](src/docs/rubric_format.md).

## Project Structure

```
grading_app/
├── src/
│   ├── main.py                 # Application entry point
│   ├── __init__.py
│   ├── analytics/              # Analytics and data processing
│   │   ├── __init__.py
│   │   └── data_processor.py
│   ├── core/                   # Core business logic
│   │   ├── __init__.py
│   │   ├── assessment.py       # Assessment data handling
│   │   ├── grader.py          # Grading logic
│   │   ├── rubric.py          # Rubric handling
│   │   └── utils.py           # Utility functions
│   ├── tools/                  # Utility tools
│   │   ├── __init__.py
│   │   ├── abet_tool.py       # ABET assessment logic
│   │   ├── rubric_converter.py
│   │   └── rubric_template.py
│   ├── ui/                     # User interface
│   │   ├── __init__.py
│   │   ├── main_window.py     # Main application window
│   │   ├── dialogs/           # Dialog windows
│   │   │   ├── __init__.py
│   │   │   ├── analytics.py
│   │   │   ├── abet_dialogs.py
│   │   │   └── config.py
│   │   └── widgets/           # Custom UI components
│   ├── utils/                  # Utility modules
│   │   ├── __init__.py
│   │   ├── file_io.py
│   │   ├── layout.py
│   │   ├── pdf.py
│   │   ├── pdf_generator.py
│   │   ├── rubric_parser.py
│   │   ├── splash_screen.py
│   │   └── styles.py
│   ├── docs/                   # Documentation
│   │   ├── rubric_format.md
│   │   └── user_guide.md
│   ├── examples/               # Example rubrics
│   │   ├── essay_assignment.json
│   │   └── ir_assignment.json
│   └── tests/                  # Unit tests
├── requirements.txt
├── README.md
└── LICENSE
```

## Tips and Best Practices

### Efficient Grading

1. **Grade by question, not by student**
   - Grade Q1 for all students, then Q2, etc.
   - Ensures consistent grading standards

2. **Use achievement levels**
   - Faster than manually entering points
   - Ensures consistency across students

3. **Add meaningful comments**
   - Helps students improve
   - Documents your grading decisions

4. **Save frequently**
   - Auto-save runs every 3 minutes
   - Manual save recommended after each student

### Managing Multiple Assessments

1. **Organize by folders**
   ```
   assessments/
   ├── midterm1/
   ├── midterm2/
   ├── final/
   └── projects/
   ```

2. **Use consistent naming**
   - Format: `assessment_studentname.json`
   - Example: `midterm1_john_smith.json`

3. **Keep rubrics with assessments**
   - Store rubric file in assessment folder
   - Ensures you can reload assessments later

### Designing Effective Rubrics

1. **Clear criteria titles**
   - Use descriptive names
   - Example: "Algorithm Efficiency Analysis" not "Part 2"

2. **Specific achievement levels**
   - Include point ranges in level titles
   - Example: "Excellent (8-10 pts)"

3. **Detailed descriptions**
   - Explain what constitutes each level
   - Helps students understand expectations

4. **Appropriate point weights**
   - Align points with importance
   - Total points should be reasonable (typically 50-100)

### ABET Best Practices

1. **Map thoughtfully**
   - Consider primary vs. secondary skills
   - A criterion can assess multiple outcomes

2. **Collect data regularly**
   - Every major assessment (minimum 2-3 per semester)
   - More data = better insights

3. **Review and act on results**
   - Don't just collect data
   - Use results to improve teaching

4. **Document everything**
   - Keep all reports and mappings
   - Add reflection notes

5. **Share with department**
   - Discuss trends and improvements
   - Coordinate across sections

## Troubleshooting

### Common Issues

**Rubric won't load**
- Verify JSON/CSV format is correct
- Check for syntax errors (missing commas, brackets)
- Ensure file encoding is UTF-8

**Assessment won't load**
- Ensure the same rubric is loaded
- Check if assessment file is corrupted
- Verify file is valid JSON

**PDF export fails**
- Check write permissions for output directory
- Ensure ReportLab is installed: `pip install reportlab`
- Try a different output location

**ABET Mapping button disabled**
- Load a rubric first
- Check that `abet_tool.py` is installed correctly

**ABET Report shows 0 students**
- Verify assessment folder contains JSON files
- Check that files are saved from current rubric
- Ensure mapping file matches rubric criteria names

**Auto-save not working**
- Check system temp directory permissions
- Verify timer is running (check status bar)

### Getting Help

1. Check the error message in the console
2. Review the [User Guide](src/docs/user_guide.md)
3. Check [Rubric Format](src/docs/rubric_format.md) documentation
4. Submit an issue on GitHub with:
   - Error message
   - Steps to reproduce
   - Python version and OS

## Contributing

Contributions are welcome! Areas for contribution:

- Additional rubric templates
- Support for additional export formats
- Integration with Learning Management Systems (LMS)
- Additional analytics visualizations
- ABET reporting enhancements
- Internationalization

Please submit a Pull Request with:
1. Clear description of changes
2. Tests for new features
3. Updated documentation

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with PyQt5 for cross-platform compatibility
- Uses ReportLab for PDF generation
- Material Design inspired UI
- ABET CS criteria based on 2025-2026 standards

## Version History

- **v1.0.0** - Initial release with core grading features and ABET integration
  - Rubric loading and grading
  - Achievement levels support
  - Flexible grading modes
  - PDF export
  - ABET outcome mapping and reporting
  - Analytics dashboard
  - Auto-save functionality

---

**Made with ❤️ for educators**

For questions or support, please open an issue on GitHub.