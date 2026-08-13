"""Reusable neutral card/section widget for the grading UI."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget


class CardWidget(QFrame):
    """Subtle bordered section with a compact title row and content area.

    This preserves the existing ``get_content_layout()`` API used throughout
    ``main_window.py`` while replacing the previous saturated title bar.
    """

    def __init__(self, title, parent=None, *, collapsible=False, initially_collapsed=False):
        super().__init__(parent)
        self.title = str(title)
        self.collapsible = bool(collapsible)
        self._collapsed = False
        self.setup_ui()
        if self.collapsible and initially_collapsed:
            self.set_collapsed(True)

    def setup_ui(self):
        self.setObjectName("sectionCard")
        self.setFrameShape(QFrame.NoFrame)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = QWidget(self)
        self.header.setObjectName("sectionCardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(14, 10, 12, 8)
        header_layout.setSpacing(8)

        self.title_label = QLabel(self.title, self.header)
        self.title_label.setObjectName("sectionCardTitle")
        self.title_label.setProperty("labelType", "cardTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)

        self.collapse_button = QToolButton(self.header)
        self.collapse_button.setObjectName("sectionCardCollapseButton")
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.setCursor(Qt.PointingHandCursor)
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        self.collapse_button.setVisible(self.collapsible)
        header_layout.addWidget(self.collapse_button)

        main_layout.addWidget(self.header)

        self.header_divider = QFrame(self)
        self.header_divider.setObjectName("sectionCardDivider")
        self.header_divider.setFrameShape(QFrame.HLine)
        self.header_divider.setFixedHeight(1)
        main_layout.addWidget(self.header_divider)

        self.content = QWidget(self)
        self.content.setObjectName("sectionCardContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(14, 12, 14, 14)
        self.content_layout.setSpacing(8)
        main_layout.addWidget(self.content)

        self._update_collapse_button()
        self.setStyleSheet(
            """
            QFrame#sectionCard {
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 8px;
            }
            QWidget#sectionCardHeader,
            QWidget#sectionCardContent {
                background: transparent;
                border: none;
            }
            QLabel#sectionCardTitle {
                color: #1F2937;
                font-size: 14px;
                font-weight: 600;
                background: transparent;
            }
            QFrame#sectionCardDivider {
                background-color: #E6E9EF;
                border: none;
            }
            QToolButton#sectionCardCollapseButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: #667085;
                padding: 3px 6px;
                min-width: 22px;
            }
            QToolButton#sectionCardCollapseButton:hover {
                background-color: #F2F4F7;
                color: #1F2937;
            }
            """
        )

    def get_content_layout(self):
        """Return the layout used by existing callers to add card content."""
        return self.content_layout

    def set_title(self, title):
        self.title = str(title)
        self.title_label.setText(self.title)

    def set_collapsible(self, collapsible):
        self.collapsible = bool(collapsible)
        self.collapse_button.setVisible(self.collapsible)
        if not self.collapsible and self._collapsed:
            self.set_collapsed(False)

    def is_collapsed(self):
        return self._collapsed

    def set_collapsed(self, collapsed):
        if not self.collapsible and collapsed:
            return
        self._collapsed = bool(collapsed)
        self.content.setVisible(not self._collapsed)
        self.header_divider.setVisible(not self._collapsed)
        self._update_collapse_button()

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def _update_collapse_button(self):
        if self._collapsed:
            self.collapse_button.setText("▸")
            self.collapse_button.setToolTip(f"Expand {self.title}")
        else:
            self.collapse_button.setText("▾")
            self.collapse_button.setToolTip(f"Collapse {self.title}")
