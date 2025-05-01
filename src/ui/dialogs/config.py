from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QSpinBox, QCheckBox, QDialogButtonBox, QLabel


class GradingConfigDialog(QDialog):
    """Dialog for configuring grading options."""

    def __init__(self, total_questions, parent=None):
        """Initialize the dialog with the number of available questions."""
        super().__init__(parent)
        self.total_questions = total_questions
        self.init_ui()

    def init_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Grading Configuration")
        self.setMinimumWidth(400)

        # Create layout for the dialog
        layout = QVBoxLayout(self)

        # Add title
        title_label = QLabel("Configure Grading Options")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3F51B5;")
        layout.addWidget(title_label)

        # Create form for configuration options
        form = QFormLayout()
        form.setSpacing(10)

        # Grading mode selection
        self.grading_mode = QComboBox()
        self.grading_mode.addItem("Use best scores", "best_scores")
        self.grading_mode.addItem("Use selected questions", "selected")
        self.grading_mode.currentIndexChanged.connect(self.update_mode_description)
        form.addRow("Grading Mode:", self.grading_mode)

        # Mode description
        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("color: #757575; font-style: italic;")
        form.addRow("", self.mode_description)

        # Questions to count
        self.questions_to_count = QSpinBox()
        self.questions_to_count.setRange(1, self.total_questions)
        self.questions_to_count.setValue(min(5, self.total_questions))
        form.addRow("Questions to Count:", self.questions_to_count)

        # Points per question
        self.points_per_question = QSpinBox()
        self.points_per_question.setRange(1, 100)
        self.points_per_question.setValue(10)
        self.points_per_question.valueChanged.connect(self.update_fixed_total)
        form.addRow("Points per Question:", self.points_per_question)

        # Use fixed total option
        self.use_fixed_total = QCheckBox("Use fixed total points")
        self.use_fixed_total.setChecked(True)
        form.addRow("", self.use_fixed_total)

        # Fixed total
        self.fixed_total = QSpinBox()
        self.fixed_total.setRange(1, 1000)
        self.fixed_total.setValue(50)
        form.addRow("Fixed Total Points:", self.fixed_total)

        layout.addLayout(form)

        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Initial update of the mode description
        self.update_mode_description()

    def update_mode_description(self):
        """Update the description based on the selected grading mode."""
        mode = self.grading_mode.currentData()
        if mode == "best_scores":
            desc = "Automatically use the highest-scoring questions for the final grade."
        else:
            desc = "Only count questions that are explicitly selected for grading."
        self.mode_description.setText(desc)

    def update_fixed_total(self):
        """Update the fixed total based on questions and points per question."""
        self.fixed_total.setValue(self.questions_to_count.value() * self.points_per_question.value())

    def get_config(self):
        """Return the configuration as a dictionary."""
        return {
            "grading_mode": self.grading_mode.currentData(),
            "questions_to_count": self.questions_to_count.value(),
            "points_per_question": self.points_per_question.value(),
            "use_fixed_total": self.use_fixed_total.isChecked(),
            "fixed_total": self.fixed_total.value()
        }

    def toggle_summary_content(self, event):
        """Toggle the visibility of the question summary content."""
        self.summary_content_visible = not self.summary_content_visible
        self.summary_content.setVisible(self.summary_content_visible)

        # Update the indicator
        if self.summary_content_visible:
            self.toggle_indicator.setText("▼")  # Down arrow
        else:
            self.toggle_indicator.setText("▶")  # Right arrow

        # Adjust the window to show more of the grading area
        if not self.summary_content_visible:
            # Add some delay to let the UI update
            QTimer.singleShot(100, self.adjust_window_for_grading)

    def adjust_window_for_grading(self):
        """Adjust the window to show more of the grading area."""
        # Find the criteria scroll area and give it more space
        if hasattr(self, 'scroll_area'):
            self.scroll_area.setMinimumHeight(350)  # Set a larger minimum height

    def update_fixed_total(self):
        """Update the fixed total based on questions and points per question."""
        self.fixed_total.setValue(self.questions_to_count.value() * self.points_per_question.value())

    def get_config(self):
        """Return the configuration as a dictionary."""
        return {
            "grading_mode": self.grading_mode.currentData(),
            "questions_to_count": self.questions_to_count.value(),
            "points_per_question": self.points_per_question.value(),
            "use_fixed_total": self.use_fixed_total.isChecked(),
            "fixed_total": self.fixed_total.value()
        }