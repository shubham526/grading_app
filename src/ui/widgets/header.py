from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtCore import Qt


class HeaderWidget(QWidget):
    """Custom app header with logo and title."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Set up the header UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create logo (placeholder - replace with actual logo)
        logo_label = QLabel()
        logo_pixmap = QPixmap(32, 32)
        logo_pixmap.fill(Qt.transparent)
        logo_label.setPixmap(logo_pixmap)
        layout.addWidget(logo_label)

        # App title
        title_label = QLabel("Rubric Grading Tool")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #3F51B5;")
        layout.addWidget(title_label)

        # Fill remaining space
        layout.addStretch()

        # Set fixed height
        self.setFixedHeight(48)
        self.setStyleSheet("background-color: white; border-bottom: 1px solid #BDBDBD;")