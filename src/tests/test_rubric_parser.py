"""
test_rubric_parser.py
=====================

Tests for the rubric parser module (src/utils/rubric_parser.py).

Uses direct module loading to avoid the PyQt5 import chain that goes through
src/utils/__init__.py → file_io.py → PyQt5.
"""

import csv
import json
import os
import sys
import tempfile
import unittest
import importlib.util

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


def _load_parser():
    """Load rubric_parser.py directly, bypassing src/utils/__init__.py."""
    spec = importlib.util.spec_from_file_location(
        "rubric_parser",
        os.path.join(_REPO_ROOT, "src", "utils", "rubric_parser.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRubricParser(unittest.TestCase):

    def setUp(self):
        self.parser = _load_parser()
        self.temp_dir = tempfile.TemporaryDirectory()

        self.sample_rubric = {
            "title": "Test Rubric",
            "criteria": [
                {
                    "title": "Criterion 1",
                    "description": "Description 1",
                    "points": 10,
                    "levels": [
                        {"title": "Excellent", "points": 10, "description": ""},
                        {"title": "Good",      "points":  8, "description": ""},
                    ],
                },
                {
                    "title": "Criterion 2",
                    "description": "Description 2",
                    "points": 20,
                },
            ],
        }

        self.json_path = os.path.join(self.temp_dir.name, "test_rubric.json")
        with open(self.json_path, "w", encoding="utf-8") as fh:
            json.dump(self.sample_rubric, fh)

        self.csv_path = os.path.join(self.temp_dir.name, "test_rubric.csv")
        with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Title", "Description", "Points",
                             "Level1 Title", "Level1 Points"])
            writer.writerow(["Criterion 1", "Description 1", "10", "Excellent", "10"])
            writer.writerow(["Criterion 2", "Description 2", "20"])

        self.invalid_path = os.path.join(self.temp_dir.name, "invalid_file.txt")
        with open(self.invalid_path, "w", encoding="utf-8") as fh:
            fh.write("This is not a valid rubric file")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_json_rubric(self):
        rubric = self.parser.parse_json_rubric(self.json_path)
        self.assertEqual(rubric["title"], "Test Rubric")
        self.assertEqual(len(rubric["criteria"]), 2)
        self.assertEqual(rubric["criteria"][0]["title"], "Criterion 1")
        self.assertEqual(rubric["criteria"][0]["points"], 10)
        self.assertEqual(len(rubric["criteria"][0]["levels"]), 2)

    def test_parse_csv_rubric(self):
        rubric = self.parser.parse_csv_rubric(self.csv_path)
        self.assertEqual(rubric["title"], "test_rubric")
        self.assertEqual(len(rubric["criteria"]), 2)
        self.assertEqual(rubric["criteria"][0]["title"], "Criterion 1")
        self.assertEqual(rubric["criteria"][0]["points"], 10)
        self.assertIn("levels", rubric["criteria"][0])
        self.assertEqual(len(rubric["criteria"][0]["levels"]), 1)

    def test_parse_rubric_file_json(self):
        rubric = self.parser.parse_rubric_file(self.json_path)
        self.assertEqual(rubric["title"], "Test Rubric")

    def test_parse_rubric_file_csv(self):
        rubric = self.parser.parse_rubric_file(self.csv_path)
        self.assertEqual(rubric["title"], "test_rubric")

    def test_parse_rubric_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.parser.parse_rubric_file("non_existent_file.json")

    def test_parse_rubric_file_unsupported_format(self):
        with self.assertRaises(ValueError):
            self.parser.parse_rubric_file(self.invalid_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)