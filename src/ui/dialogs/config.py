from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from src.utils.styles import VisibleArrowComboBox, VisibleArrowSpinBox


class GradingConfigDialog(QDialog):
    """Dialog for configuring grading options.

    Combo boxes and spin boxes use the application's light Fusion control
    style.  This avoids macOS Dark-appearance native editors rendering black
    inside the application's intentionally light configuration dialog.
    """

    def __init__(self, total_questions, parent=None):
        super().__init__(parent)
        self.total_questions = max(1, int(total_questions or 1))
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Grading Configuration")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title_label = QLabel("Configure Grading Options")
        title_label.setProperty("labelType", "heading")
        layout.addWidget(title_label)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.grading_mode = VisibleArrowComboBox()
        self.grading_mode.setMinimumWidth(250)
        self.grading_mode.addItem("Use best scores", "best_scores")
        self.grading_mode.addItem("Use selected questions", "selected")
        self.grading_mode.currentIndexChanged.connect(self.update_mode_description)
        form.addRow("Grading Mode:", self.grading_mode)

        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("color: #667085; font-style: italic;")
        form.addRow("", self.mode_description)

        self.questions_to_count = self._make_spin_box(1, self.total_questions, min(5, self.total_questions))
        self.questions_to_count.valueChanged.connect(self.update_fixed_total)
        form.addRow("Questions to Count:", self.questions_to_count)

        self.points_per_question = self._make_spin_box(1, 100, 10)
        self.points_per_question.valueChanged.connect(self.update_fixed_total)
        form.addRow("Points per Question:", self.points_per_question)

        self.use_fixed_total = QCheckBox("Use fixed total points")
        self.use_fixed_total.setChecked(True)
        form.addRow("", self.use_fixed_total)

        self.fixed_total = self._make_spin_box(1, 1000, 1)
        form.addRow("Fixed Total Points:", self.fixed_total)

        layout.addLayout(form)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.update_mode_description()
        self.update_fixed_total()

    @staticmethod
    def _make_spin_box(minimum, maximum, value):
        spin = VisibleArrowSpinBox()
        spin.setRange(int(minimum), int(maximum))
        spin.setValue(int(value))
        spin.setMinimumWidth(120)
        spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        return spin

    def update_mode_description(self):
        mode = self.grading_mode.currentData()
        if mode == "best_scores":
            desc = "Automatically use the highest-scoring questions for the final grade."
        else:
            desc = "Only count questions that are explicitly selected for grading."
        self.mode_description.setText(desc)

    def update_fixed_total(self):
        self.fixed_total.setValue(
            self.questions_to_count.value() * self.points_per_question.value()
        )

    def get_config(self):
        return {
            "grading_mode": self.grading_mode.currentData(),
            "questions_to_count": self.questions_to_count.value(),
            "points_per_question": self.points_per_question.value(),
            "use_fixed_total": self.use_fixed_total.isChecked(),
            "fixed_total": self.fixed_total.value(),
        }
