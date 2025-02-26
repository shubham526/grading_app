# Rubric Grading Tool - User Guide

This comprehensive guide will help you get started with the Rubric Grading Tool and make the most of its features.

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Working with Rubrics](#working-with-rubrics)
4. [Grading Assignments](#grading-assignments)
5. [Saving and Loading Assessments](#saving-and-loading-assessments)
6. [Exporting to PDF](#exporting-to-pdf)
7. [Tips and Best Practices](#tips-and-best-practices)
8. [Troubleshooting](#troubleshooting)

## Introduction

The Rubric Grading Tool is designed to streamline the assessment process for educators. It allows you to:

- Create and use detailed grading rubrics
- Consistently apply assessment criteria
- Track achievement levels
- Save assessments for future reference
- Generate professional PDF reports

## Getting Started

### Installation

1. Ensure you have Python 3.6 or later installed
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the application:
   ```bash
   python src/main.py
   ```

### Interface Overview

The main application window is divided into several sections:

- **Header Bar**: Contains controls for loading rubrics, entering student and assignment information, and exporting to PDF
- **Criteria Area**: Displays all the criteria from the loaded rubric
- **Status Bar**: Shows the total points and other information
- **Control Buttons**: For clearing the form, saving, and loading assessments

## Working with Rubrics

### Creating Rubrics

Rubrics can be created in either JSON or CSV format. For detailed specifications, see [Rubric Format](rubric_format.md).

You can also use the included template generator to create new rubrics:

```bash
python tools/rubric_template.py essay my_essay_rubric.json --title "Literary Analysis Essay"
```

### Loading a Rubric

1. Click the "Load Rubric" button in the top-left corner
2. Browse to and select your JSON or CSV rubric file
3. The rubric will be loaded and displayed in the main window

### Converting Between Formats

Use the rubric converter to switch between JSON and CSV formats:

```bash
python tools/rubric_converter.py my_rubric.json my_rubric.csv
```

## Grading Assignments

### Basic Grading

1. Enter the student name and assignment name (if not already populated)
2. For each criterion:
   - Review the criterion description
   - Select an achievement level if available
   - Or manually adjust the points using the spinner
   - Add comments in the text box provided

### Using Achievement Levels

If your rubric includes achievement levels:

1. Click on the checkbox next to the appropriate level
2. The points will automatically be set to the value for that level
3. You can still manually adjust the points if needed

### Adding Comments

For each criterion, you can add detailed comments in the text area provided. These comments will be included in the PDF export and saved with the assessment.

## Saving and Loading Assessments

### Saving an Assessment

1. Click the "Save Assessment" button
2. Choose a location and enter a filename
3. The assessment will be saved in JSON format

### Loading an Assessment

1. Click the "Load Assessment" button
2. Browse to and select a previously saved assessment file
3. The assessment data will be loaded into the form

> **Note**: The assessment can only be loaded if the same rubric is currently loaded.

## Exporting to PDF

1. Complete the assessment form
2. Click the "Export to PDF" button
3. Choose a location and enter a filename
4. A professional PDF report will be generated with:
   - Student and assignment information
   - Overall score and grade
   - Individual criterion scores and comments
   - Date of assessment

## Tips and Best Practices

### Efficient Grading

- Load the appropriate rubric before starting grading
- Use achievement levels to ensure consistency
- Add specific, actionable comments
- Save assessments regularly

### Managing Multiple Assessments

- Use a consistent naming convention for saved assessments
- Create a separate directory for each assignment
- Consider using the student name and assignment in the filename

### Customizing Rubrics

- Start with one of the provided templates
- Adjust criteria weights to match assignment priorities
- Include clear descriptions for achievement levels
- Test your rubric with sample assessments

## Troubleshooting

### Common Issues

**Problem**: Rubric fails to load
**Solution**: Ensure the file is in the correct JSON or CSV format

**Problem**: Assessment won't load
**Solution**: Make sure you have the same rubric loaded that was used to create the assessment

**Problem**: PDF export fails
**Solution**: Check that you have the required permissions to write to the selected directory

### Getting Help

If you encounter issues not covered in this guide:

1. Check the logs for error messages
2. Consult the [Rubric Format](rubric_format.md) documentation
3. Submit an issue on the project's GitHub page
4. Contact the development team for support