"""Programming workspace placeholder for v2.3.4.1 Commit 1.

Commit 1 establishes the application shell only. The roster/status programming
dashboard is intentionally introduced in Commit 3.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class ProgrammingGradingWorkspace(QWidget):
    """Minimal placeholder proving independent programming-workspace routing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("programmingGradingWorkspace")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(14)
        layout.addStretch(1)

        title = QLabel("Programming Grading", self)
        title.setObjectName("programmingWorkspaceTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 28px; font-weight: 700; color: #111827;"
        )
        layout.addWidget(title)

        body = QLabel(
            "The dual-mode application shell is active. The dedicated "
            "programming roster/status dashboard is introduced in v2.3.4.1 "
            "Commit 3. Existing v2.3.3 autograding services and evidence "
            "remain unchanged.",
            self,
        )
        body.setObjectName("programmingWorkspacePlaceholderText")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        body.setStyleSheet("font-size: 14px; color: #667085;")
        body.setMaximumWidth(720)
        layout.addWidget(body, 0, Qt.AlignHCenter)

        choose_mode = QPushButton("Choose Another Grading Mode", self)
        choose_mode.setObjectName("programmingPlaceholderChooseModeButton")
        choose_mode.setAccessibleName("Choose another grading mode")
        choose_mode.setMaximumWidth(280)
        layout.addWidget(choose_mode, 0, Qt.AlignHCenter)

        layout.addStretch(1)

        self.title_label = title
        self.description_label = body
        self.choose_mode_button = choose_mode
