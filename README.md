# Rubric Grading Tool

A professional, cross-platform desktop application for educators to efficiently create, manage, and use grading rubrics for student assessments.

## Features

- Create and load rubrics from JSON or CSV formats
- Grade assignments with customizable criteria
- Support for achievement levels with automatic point calculation
- Save and load assessment data
- Export assessments to professional PDF reports
- Clean, intuitive user interface

## Installation

### Prerequisites

- Python 3.6 or later
- PyQt5
- ReportLab

### Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/rubric-grading-app.git
   cd rubric-grading-app
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python src/main.py
   ```

## Usage

### Loading a Rubric

1. Click the "Load Rubric" button
2. Select a JSON or CSV file containing your rubric definition
3. The rubric will be displayed with all criteria and achievement levels

### Grading with the Rubric

1. Enter the student name and assignment name (if not already populated)
2. For each criterion:
   - Select an achievement level if available, or
   - Manually enter points using the spinner
   - Add comments in the text area
3. The total score is calculated and displayed automatically

### Saving and Loading Assessments

- Click "Save Assessment" to save the current assessment as a JSON file
- Click "Load Assessment" to open a previously saved assessment

### Exporting to PDF

- Click "Export to PDF" to generate a professional report of the assessment
- The PDF includes all criteria, achievement levels, points, and comments

## Rubric Format

For details on the supported rubric formats, see [docs/rubric_format.md](docs/rubric_format.md).

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.