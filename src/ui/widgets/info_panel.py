from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

class RubricInfoWidget(QFrame):
    """Widget displaying information about the loaded rubric."""

    def __init__(self, parent=None):
        """Initialize the widget."""
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        self.title_label = QLabel("No rubric loaded")
        layout.addWidget(self.title_label)

        self.criteria_count_label = QLabel("Criteria: 0")
        layout.addWidget(self.criteria_count_label)

        self.points_label = QLabel("Total points: 0")
        layout.addWidget(self.points_label)

    def update_info(self, rubric_data):
        """Update the widget with information from the rubric data."""
        if not rubric_data:
            self.reset()
            return

        self.title_label.setText(rubric_data.get("title", "Untitled Rubric"))

        criteria_count = len(rubric_data.get("criteria", []))
        self.criteria_count_label.setText(f"Criteria: {criteria_count}")

        total_points = sum(c.get("points", 0) for c in rubric_data.get("criteria", []))
        self.points_label.setText(f"Total points: {total_points}")

    def reset(self):
        """Reset the widget to its initial state."""
        self.title_label.setText("No rubric loaded")
        self.criteria_count_label.setText("Criteria: 0")
        self.points_label.setText("Total points: 0")