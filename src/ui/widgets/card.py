from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt


class CardWidget(QFrame):
    """Card-style container widget with title and content."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.setup_ui()

    def setup_ui(self):
        """Set up the card UI."""
        self.setStyleSheet("""
            CardWidget {
                background-color: white;
                border-radius: 4px;
                border: 1px solid #EEEEEE;
                margin: 8px 0px;
            }
            QLabel[labelType="cardTitle"] {
                font-size: 14px;
                font-weight: bold;
                color: white;
                padding: 8px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setStyleSheet("background-color: #3F51B5; border-radius: 4px 4px 0 0;")
        title_layout = QHBoxLayout(title_bar)

        title_label = QLabel(self.title)
        title_label.setProperty("labelType", "cardTitle")
        title_layout.addWidget(title_label)

        main_layout.addWidget(title_bar)

        # Content container
        self.content = QFrame()
        self.content.setStyleSheet("border-radius: 0 0 4px 4px;")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 12, 12, 12)

        main_layout.addWidget(self.content)

    def get_content_layout(self):
        """Get the layout for adding content."""
        return self.content_layout