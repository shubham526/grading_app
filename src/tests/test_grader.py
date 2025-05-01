"""
Tests for the grader module.
"""

import os
import unittest
import sys
import json
import tempfile
from unittest.mock import MagicMock, patch

# Add the src directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock PyQt5 modules
sys.modules['PyQt5'] = MagicMock()
sys.modules['PyQt5.QtWidgets'] = MagicMock()
sys.modules['PyQt5.QtGui'] = MagicMock()
sys.modules['PyQt5.QtCore'] = MagicMock()

# Now we can import our modules that use PyQt5
from src.utils.rubric_parser import parse_rubric_file
from src.ui.widgets import CriterionWidget


class TestCriterionWidget(unittest.TestCase):
    """Test cases for the CriterionWidget class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a sample criterion for testing
        self.criterion_data = {
            "title": "Test Criterion",
            "description": "Test Description",
            "points": 10,
            "levels": [
                {"title": "Excellent", "points": 10, "description": "Perfect work"},
                {"title": "Good", "points": 8, "description": "Above average work"},
                {"title": "Satisfactory", "points": 6, "description": "Average work"}
            ]
        }

        # Mock the QFrame parent class
        with patch('src.widgets.criterion_widget.QFrame'):
            self.widget = CriterionWidget(self.criterion_data)

            # Mock the widget's UI components
            self.widget.points_spinbox = MagicMock()
            self.widget.points_spinbox.value = MagicMock(return_value=8)

            self.widget.comments_edit = MagicMock()
            self.widget.comments_edit.toPlainText = MagicMock(return_value="Test comment")

            # Create mock level checkboxes
            checkbox1 = MagicMock()
            checkbox1.isChecked = MagicMock(return_value=False)
            checkbox1.text = MagicMock(return_value="Excellent (10 pts)")

            checkbox2 = MagicMock()
            checkbox2.isChecked = MagicMock(return_value=True)
            checkbox2.text = MagicMock(return_value="Good (8 pts)")

            checkbox3 = MagicMock()
            checkbox3.isChecked = MagicMock(return_value=False)
            checkbox3.text = MagicMock(return_value="Satisfactory (6 pts)")

            self.widget.level_checkboxes = [
                (checkbox1, 10),
                (checkbox2, 8),
                (checkbox3, 6)
            ]

    def test_get_data(self):
        """Test getting data from the criterion widget."""
        data = self.widget.get_data()

        self.assertEqual(data["title"], "Test Criterion")
        self.assertEqual(data["points_awarded"], 8)
        self.assertEqual(data["points_possible"], 10)
        self.assertEqual(data["selected_level"], "Good")
        self.assertEqual(data["comments"], "Test comment")

    def test_set_data(self):
        """Test setting data on the criterion widget."""
        criterion_data = {
            "points_awarded": 6,
            "comments": "Updated comment",
            "selected_level": "Satisfactory"
        }

        self.widget.set_data(criterion_data)

        # Verify points spinbox was updated
        self.widget.points_spinbox.setValue.assert_called_with(6)

        # Verify comments text was updated
        self.widget.comments_edit.setPlainText.assert_called_with("Updated comment")

        # Check that the right checkbox was selected
        for checkbox, points in self.widget.level_checkboxes:
            if checkbox.text() == "Satisfactory (6 pts)":
                checkbox.setChecked.assert_called_with(True)

    def test_reset(self):
        """Test resetting the criterion widget."""
        self.widget.reset()

        # Verify points spinbox was reset
        self.widget.points_spinbox.setValue.assert_called_with(0)

        # Verify comments were cleared
        self.widget.comments_edit.clear.assert_called_once()

        # Verify checkboxes were unchecked
        for checkbox, _ in self.widget.level_checkboxes:
            checkbox.setChecked.assert_called_with(False)

    def test_get_awarded_points(self):
        """Test getting awarded points."""
        points = self.widget.get_awarded_points()
        self.assertEqual(points, 8)

    def test_get_possible_points(self):
        """Test getting possible points."""
        points = self.widget.get_possible_points()
        self.assertEqual(points, 10)


class TestRubricParser(unittest.TestCase):
    """Test cases for rubric parsing functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory and files
        self.temp_dir = tempfile.TemporaryDirectory()

        # Create a sample rubric
        self.sample_rubric = {
            "title": "Test Rubric",
            "criteria": [
                {
                    "title": "Criterion 1",
                    "description": "Description 1",
                    "points": 10
                },
                {
                    "title": "Criterion 2",
                    "description": "Description 2",
                    "points": 20
                }
            ]
        }

        # Save the sample rubric to a JSON file
        self.json_path = os.path.join(self.temp_dir.name, "test_rubric.json")
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(self.sample_rubric, f)

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_parse_rubric_file(self):
        """Test parsing a rubric file."""
        rubric = parse_rubric_file(self.json_path)

        self.assertEqual(rubric["title"], "Test Rubric")
        self.assertEqual(len(rubric["criteria"]), 2)
        self.assertEqual(rubric["criteria"][0]["title"], "Criterion 1")
        self.assertEqual(rubric["criteria"][1]["title"], "Criterion 2")
        self.assertEqual(rubric["criteria"][0]["points"], 10)
        self.assertEqual(rubric["criteria"][1]["points"], 20)


if __name__ == '__main__':
    unittest.main()