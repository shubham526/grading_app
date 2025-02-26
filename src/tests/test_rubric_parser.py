"""
Tests for the rubric parser module.
"""

import os
import unittest
import tempfile
import json
import csv
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.rubric_parser import parse_rubric_file, parse_json_rubric, parse_csv_rubric


class TestRubricParser(unittest.TestCase):
    """Test cases for the rubric parser module."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a sample rubric for testing
        self.sample_rubric = {
            "title": "Test Rubric",
            "criteria": [
                {
                    "title": "Criterion 1",
                    "description": "Description 1",
                    "points": 10,
                    "levels": [
                        {"title": "Excellent", "points": 10, "description": ""},
                        {"title": "Good", "points": 8, "description": ""}
                    ]
                },
                {
                    "title": "Criterion 2",
                    "description": "Description 2",
                    "points": 20
                }
            ]
        }

        # Create temporary files for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.json_path = os.path.join(self.temp_dir.name, "test_rubric.json")
        self.csv_path = os.path.join(self.temp_dir.name, "test_rubric.csv")
        self.invalid_path = os.path.join(self.temp_dir.name, "invalid_file.txt")

        # Write the sample rubric to a JSON file
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(self.sample_rubric, f)

        # Write a sample CSV rubric
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Title", "Description", "Points", "Level1 Title", "Level1 Points"])
            writer.writerow(["Criterion 1", "Description 1", "10", "Excellent", "10"])
            writer.writerow(["Criterion 2", "Description 2", "20"])

        # Create an invalid text file
        with open(self.invalid_path, 'w', encoding='utf-8') as f:
            f.write("This is not a valid rubric file")

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_parse_json_rubric(self):
        """Test parsing a JSON rubric file."""
        rubric = parse_json_rubric(self.json_path)
        self.assertEqual(rubric["title"], "Test Rubric")
        self.assertEqual(len(rubric["criteria"]), 2)
        self.assertEqual(rubric["criteria"][0]["title"], "Criterion 1")
        self.assertEqual(rubric["criteria"][0]["points"], 10)
        self.assertEqual(len(rubric["criteria"][0]["levels"]), 2)

    def test_parse_csv_rubric(self):
        """Test parsing a CSV rubric file."""
        rubric = parse_csv_rubric(self.csv_path)
        self.assertEqual(rubric["title"], "test_rubric")
        self.assertEqual(len(rubric["criteria"]), 2)
        self.assertEqual(rubric["criteria"][0]["title"], "Criterion 1")
        self.assertEqual(rubric["criteria"][0]["points"], 10)
        self.assertTrue("levels" in rubric["criteria"][0])
        self.assertEqual(len(rubric["criteria"][0]["levels"]), 1)

    def test_parse_rubric_file(self):
        """Test the main parse_rubric_file function."""
        # Test with JSON file
        json_rubric = parse_rubric_file(self.json_path)
        self.assertEqual(json_rubric["title"], "Test Rubric")

        # Test with CSV file
        csv_rubric = parse_rubric_file(self.csv_path)
        self.assertEqual(csv_rubric["title"], "test_rubric")

        # Test with non-existent file
        with self.assertRaises(FileNotFoundError):
            parse_rubric_file("non_existent_file.json")

        # Test with unsupported file format
        with self.assertRaises(ValueError):
            parse_rubric_file(self.invalid_path)


if __name__ == '__main__':
    unittest.main()