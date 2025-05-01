from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PyQt5.QtCore import pyqtSignal

class GradeScaleWidget(QWidget):
    """Widget for displaying and selecting grade scales."""

    scale_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        """Initialize the widget."""
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Grade Scale:"))

        self.scale_combo = QComboBox()
        self.scale_combo.addItems([
            "Default (A-F)",
            "Points Only",
            "Percentage Only",
            "Pass/Fail"
        ])
        self.scale_combo.currentTextChanged.connect(self.scale_changed)
        header_layout.addWidget(self.scale_combo)

        layout.addLayout(header_layout)