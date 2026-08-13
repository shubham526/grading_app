"""Application header widget.

The Commit-5 visual refresh keeps the header deliberately quiet: the grading
workspace should dominate the window, while the application identity remains
clear and native-looking on macOS and other platforms.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class HeaderWidget(QWidget):
    """Compact application header with title and optional context text.

    The constructor remains backwards compatible with the pre-v2.2 call site,
    which simply instantiates ``HeaderWidget()``.
    """

    def __init__(self, parent=None, title="Rubric Grading Tool"):
        super().__init__(parent)
        self._title = str(title)
        self._subtitle = ""
        self.setup_ui()

    def setup_ui(self):
        """Build the responsive header UI."""
        self.setObjectName("appHeader")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(52)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 4, 2, 8)
        outer.setSpacing(12)

        text_container = QWidget(self)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.title_label = QLabel(self._title, text_container)
        self.title_label.setObjectName("appHeaderTitle")
        title_font = QFont(self.font())
        title_font.setPointSizeF(max(15.0, title_font.pointSizeF() + 5.0))
        title_font.setWeight(QFont.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        text_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("", text_container)
        self.subtitle_label.setObjectName("appHeaderSubtitle")
        subtitle_font = QFont(self.font())
        subtitle_font.setPointSizeF(max(10.0, subtitle_font.pointSizeF() - 0.5))
        self.subtitle_label.setFont(subtitle_font)
        self.subtitle_label.setVisible(False)
        self.subtitle_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_layout.addWidget(self.subtitle_label)

        outer.addWidget(text_container, 1)
        outer.addStretch(1)

        self.setStyleSheet(
            """
            QWidget#appHeader {
                background: transparent;
                border: none;
            }
            QLabel#appHeaderTitle {
                color: #1F2937;
                background: transparent;
            }
            QLabel#appHeaderSubtitle {
                color: #667085;
                background: transparent;
            }
            """
        )

    def set_title(self, title):
        """Update the displayed application title."""
        self._title = str(title or "")
        self.title_label.setText(self._title)

    def set_subtitle(self, subtitle):
        """Set optional secondary context shown below the title."""
        self._subtitle = str(subtitle or "").strip()
        self.subtitle_label.setText(self._subtitle)
        self.subtitle_label.setVisible(bool(self._subtitle))

    @property
    def title(self):
        return self._title

    @property
    def subtitle(self):
        return self._subtitle
