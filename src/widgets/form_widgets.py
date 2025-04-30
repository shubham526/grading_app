from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFormLayout


class FormField(QWidget):
    """A styled form field with label and input."""

    def __init__(self, label_text, input_widget, parent=None):
        super().__init__(parent)
        self.setup_ui(label_text, input_widget)

    def setup_ui(self, label_text, input_widget):
        """Set up the form field UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Label
        label = QLabel(label_text)
        label.setStyleSheet("color: #757575; font-size: 12px;")
        layout.addWidget(label)

        # Input
        layout.addWidget(input_widget)


class StyledFormLayout(QWidget):
    """A styled form layout with consistent spacing and alignment."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(16)

    def add_field(self, label_text, input_widget):
        """Add a field to the form."""
        field = FormField(label_text, input_widget)
        self.layout.addWidget(field)
        return field

    def add_row(self, widgets):
        """Add a row with multiple widgets side by side."""
        row = QHBoxLayout()
        for widget in widgets:
            row.addWidget(widget)
        self.layout.addLayout(row)