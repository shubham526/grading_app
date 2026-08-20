"""Startup grading-mode selection page for v2.3.4.1."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .grading_mode import GradingMode


class _ModeCard(QFrame):
    selected = pyqtSignal(object)

    def __init__(self, mode, title, description, parent=None):
        super().__init__(parent)
        self.mode = GradingMode.coerce(mode)
        self.setObjectName("gradingModeCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(330, 250)
        self.setMaximumWidth(520)
        self.setStyleSheet(
            "QFrame#gradingModeCard {"
            "  background: #FFFFFF;"
            "  border: 1px solid #D9DEE7;"
            "  border-radius: 12px;"
            "}"
            "QLabel#modeCardTitle {"
            "  color: #111827;"
            "  font-size: 21px;"
            "  font-weight: 700;"
            "}"
            "QLabel#modeCardDescription {"
            "  color: #475467;"
            "  font-size: 13px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        title_label = QLabel(title, self)
        title_label.setObjectName("modeCardTitle")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        description_label = QLabel(description, self)
        description_label.setObjectName("modeCardDescription")
        description_label.setWordWrap(True)
        description_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(description_label, 1)

        button = QPushButton("Open {} Grading".format(title), self)
        button.setObjectName("open{}ModeButton".format(self.mode.name.title()))
        button.setMinimumHeight(42)
        button.setProperty("buttonRole", "primary")
        button.setAccessibleName("Open {} grading mode".format(title))
        button.clicked.connect(
            lambda _checked=False: self.selected.emit(self.mode)
        )
        layout.addWidget(button)

        self.open_button = button


class ModeSelectionPage(QWidget):
    """First-page chooser for Written/Text vs Programming grading."""

    mode_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gradingModeSelectionPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 36, 36, 36)
        outer.setSpacing(18)
        outer.addStretch(1)

        title = QLabel("What type of assignment are you grading?", self)
        title.setObjectName("gradingModeSelectionTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "QLabel#gradingModeSelectionTitle {"
            "  color: #111827;"
            "  font-size: 28px;"
            "  font-weight: 700;"
            "}"
        )
        outer.addWidget(title)

        subtitle = QLabel(
            "Choose a workspace. Both modes use the same assessment, roster, "
            "canonical submission, and evidence infrastructure.",
            self,
        )
        subtitle.setObjectName("gradingModeSelectionSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #667085; font-size: 13px;")
        outer.addWidget(subtitle)

        cards = QWidget(self)
        cards_layout = QHBoxLayout(cards)
        cards_layout.setContentsMargins(0, 16, 0, 0)
        cards_layout.setSpacing(24)
        cards_layout.addStretch(1)

        self.written_card = _ModeCard(
            GradingMode.WRITTEN,
            "Written / Text",
            "Grade PDF, LaTeX, typed, or scanned written work using the "
            "existing rubric, question-centric/student-centric navigation, "
            "evidence, similarity review, and manual feedback workflow.",
            cards,
        )
        self.written_card.selected.connect(self.mode_selected.emit)
        cards_layout.addWidget(self.written_card, 1)

        self.programming_card = _ModeCard(
            GradingMode.PROGRAMMING,
            "Programming",
            "Grade canonical Python submissions using instructor test bundles, "
            "the isolated Docker/pytest runtime, deterministic scoring, batch "
            "grading, and immutable run history.",
            cards,
        )
        self.programming_card.selected.connect(self.mode_selected.emit)
        cards_layout.addWidget(self.programming_card, 1)

        cards_layout.addStretch(1)
        outer.addWidget(cards, 2)
        outer.addStretch(1)

        self.title_label = title
        self.subtitle_label = subtitle
