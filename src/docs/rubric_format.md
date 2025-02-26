# Rubric Format Specification

The Rubric Grading Tool supports rubrics in both JSON and CSV formats. This document describes the expected format for each.

## JSON Format

JSON is the preferred format as it provides the most flexibility and features.

### Basic Structure

```json
{
  "title": "Assignment Title",
  "description": "Optional description of the assignment",
  "criteria": [
    {
      "title": "Criterion Title",
      "description": "Description of what is being evaluated",
      "points": 10,
      "levels": [
        {
          "title": "Level Title",
          "description": "Description of this achievement level",
          "points": 10
        },
        ...
      ]
    },
    ...
  ]
}
```

### Fields

- **title** (string): The title of the rubric/assignment
- **description** (string, optional): A description of the assignment
- **criteria** (array): An array of criterion objects

Each criterion object has the following fields:
- **title** (string): The name of the criterion
- **description** (string, optional): A description of what is being evaluated
- **points** (number): The maximum points possible for this criterion
- **levels** (array, optional): An array of achievement level objects

Each achievement level object has the following fields:
- **title** (string): The name of the achievement level (e.g., "Excellent", "Good")
- **description** (string, optional): A description of this achievement level
- **points** (number): The points awarded for this achievement level

### Example

See the examples directory for complete JSON rubric examples.

## CSV Format

CSV format is provided for simplicity and compatibility with spreadsheet applications.

### Basic Structure

```
Criterion Title, Description, Points, Level1 Title, Level1 Points, Level2 Title, Level2 Points, ...
Introduction, Introduces topic clearly, 10, Excellent, 10, Good, 8, Satisfactory, 6, Needs Improvement, 4
```

### Format Rules

1. The first row should contain headers (not used by the application)
2. Each subsequent row represents one criterion
3. The first column is the criterion title
4. The second column is the criterion description
5. The third column is the maximum points
6. Subsequent columns come in pairs: level title followed by level points

### CSV Limitations

The CSV format has some limitations compared to JSON:

- Cannot include level descriptions
- Cannot include a rubric description
- Less readable for complex rubrics

## Programmatic Rubric Creation

You can also create rubrics programmatically using the tools provided in the `tools` directory:

- `rubric_template.py`: Generate new rubric templates
- `rubric_converter.py`: Convert between formats

## Extending the Format

The application is designed to be extensible. Future versions may support additional fields such as:

- Rubric categories or sections
- Weights for criteria
- Custom scoring algorithms
- Feedback templates