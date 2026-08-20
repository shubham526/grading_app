"""Shared assessment setup/home workspace for v2.3.4.1 Commit 4.

This page owns no grading data.  It presents the shared setup that both Written
and Programming grading require, then emits semantic requests back to
``RubricGrader``.  Mode-specific configuration remains inside the respective
workspace.
"""

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui.modes import GradingMode


class _SetupCard(QFrame):
    """One shared setup step with status and a single explicit action."""

    requested = pyqtSignal()

    def __init__(self, title, description, button_text, parent=None):
        super().__init__(parent)
        self.setObjectName("assessmentHomeSetupCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "QFrame#assessmentHomeSetupCard {"
            "  background: #FFFFFF;"
            "  border: 1px solid #D9DEE7;"
            "  border-radius: 10px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(7)

        title_label = QLabel(title, self)
        title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        description_label = QLabel(description, self)
        description_label.setWordWrap(True)
        description_label.setStyleSheet("font-size: 12px; color: #667085;")
        layout.addWidget(description_label)

        self.status_label = QLabel("Not configured", self)
        self.status_label.setObjectName("assessmentHomeSetupStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #B54708; font-weight: 600;")
        layout.addWidget(self.status_label)

        action = QPushButton(button_text, self)
        action.setMinimumHeight(36)
        action.clicked.connect(lambda _checked=False: self.requested.emit())
        layout.addWidget(action)
        self.action_button = action

    def set_status(self, text, ready=False, tooltip=None):
        self.status_label.setText(text or "Not configured")
        self.status_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: {};".format(
                "#027A48" if ready else "#B54708"
            )
        )
        self.status_label.setToolTip(tooltip or "")


class _ModeCard(QFrame):
    """Mode-specific entry card gated by shared setup readiness."""

    selected = pyqtSignal(object)

    def __init__(self, mode, title, description, button_text, parent=None):
        super().__init__(parent)
        self.mode = GradingMode.coerce(mode)
        self.setObjectName("assessmentHomeModeCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(190)
        self.setStyleSheet(
            "QFrame#assessmentHomeModeCard {"
            "  background: #FFFFFF;"
            "  border: 1px solid #D9DEE7;"
            "  border-radius: 12px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title_label = QLabel(title, self)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 19px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        description_label = QLabel(description, self)
        description_label.setWordWrap(True)
        description_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        description_label.setStyleSheet("font-size: 12px; color: #475467;")
        layout.addWidget(description_label, 1)

        button = QPushButton(button_text, self)
        button.setMinimumHeight(40)
        button.setProperty("buttonRole", "primary")
        button.clicked.connect(lambda _checked=False: self.selected.emit(self.mode))
        layout.addWidget(button)
        self.open_button = button

    def set_ready(self, ready, missing_labels=()):
        self.open_button.setEnabled(bool(ready))
        if ready:
            self.open_button.setToolTip("")
        else:
            missing = ", ".join(missing_labels) if missing_labels else "shared setup"
            self.open_button.setToolTip("Complete shared setup first: {}".format(missing))


class AssessmentHomeWorkspace(QWidget):
    """Welcome page for shared assessment setup and grading-mode entry."""

    load_rubric_requested = pyqtSignal()
    load_roster_requested = pyqtSignal()
    choose_workspace_requested = pyqtSignal()
    mode_selected = pyqtSignal(object)

    _REQUIRED_KEYS = ("rubric", "roster", "workspace")
    _DISPLAY_NAMES = {
        "rubric": "rubric",
        "roster": "roster",
        "workspace": "workspace",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("assessmentHomeWorkspace")

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 28)
        root.setSpacing(18)

        title = QLabel("Welcome to the Rubric Grading Tool", self)
        title.setObjectName("assessmentHomeTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 27px; font-weight: 700; color: #111827;")
        root.addWidget(title)

        subtitle = QLabel(
            "Set up the assessment once. The rubric, roster, and Grades + Evidence "
            "workspace are shared by Written / Text and Programming grading.",
            self,
        )
        subtitle.setObjectName("assessmentHomeSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #667085;")
        root.addWidget(subtitle)

        setup_heading = QLabel("Shared Assessment Setup", self)
        setup_heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #111827;")
        root.addWidget(setup_heading)

        setup_grid = QGridLayout()
        setup_grid.setHorizontalSpacing(12)
        setup_grid.setVerticalSpacing(12)

        self.rubric_card = _SetupCard(
            "1. Rubric / Assessment Definition",
            "Load the common rubric and assessment identity. Written grading configuration "
            "is adjusted later inside the Written workspace.",
            "Load Rubric",
            self,
        )
        self.roster_card = _SetupCard(
            "2. Roster",
            "Load the students once so both grading modes use the same identities and navigation.",
            "Load Roster",
            self,
        )
        self.workspace_card = _SetupCard(
            "3. Grades + Evidence Workspace",
            "Choose the persistent folder used for assessment JSON, canonical submissions, "
            "evidence, and autograding history.",
            "Choose Workspace",
            self,
        )
        setup_grid.addWidget(self.rubric_card, 0, 0)
        setup_grid.addWidget(self.roster_card, 0, 1)
        setup_grid.addWidget(self.workspace_card, 0, 2)
        root.addLayout(setup_grid)

        self.rubric_card.requested.connect(self.load_rubric_requested.emit)
        self.roster_card.requested.connect(self.load_roster_requested.emit)
        self.workspace_card.requested.connect(self.choose_workspace_requested.emit)

        self.readiness_label = QLabel(
            "Complete all three shared setup steps to open a grading workspace.", self
        )
        self.readiness_label.setObjectName("assessmentHomeReadiness")
        self.readiness_label.setAlignment(Qt.AlignCenter)
        self.readiness_label.setWordWrap(True)
        self.readiness_label.setStyleSheet("font-size: 12px; color: #B54708; font-weight: 600;")
        root.addWidget(self.readiness_label)

        mode_heading = QLabel("Choose Grading Mode", self)
        mode_heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #111827;")
        root.addWidget(mode_heading)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.written_card = _ModeCard(
            GradingMode.WRITTEN,
            "Written / Text",
            "PDF, LaTeX, scans, manual rubric grading, reference solutions, "
            "written evidence, and similarity review.",
            "Open Written Grader",
            self,
        )
        self.programming_card = _ModeCard(
            GradingMode.PROGRAMMING,
            "Programming",
            "Python submissions, instructor test bundles, isolated Docker/pytest execution, "
            "batch grading, and immutable run history.",
            "Open Programming Grader",
            self,
        )
        self.written_card.selected.connect(self.mode_selected.emit)
        self.programming_card.selected.connect(self.mode_selected.emit)
        mode_row.addWidget(self.written_card, 1)
        mode_row.addWidget(self.programming_card, 1)
        root.addLayout(mode_row, 1)

        self.title_label = title
        self.subtitle_label = subtitle
        self.set_context({})

    def set_context(self, context):
        """Render one plain shared-context dictionary from MainWindow."""

        context = dict(context or {})
        rubric_path = str(context.get("rubric_path") or "").strip()
        assessment_id = str(context.get("assessment_id") or "").strip()
        rubric_title = str(context.get("rubric_title") or "").strip()
        roster_count = int(context.get("roster_count") or 0)
        roster_path = str(context.get("roster_path") or "").strip()
        workspace_path = str(context.get("workspace_path") or "").strip()

        rubric_ready = bool(context.get("rubric_ready"))
        roster_ready = bool(context.get("roster_ready"))
        workspace_ready = bool(context.get("workspace_ready"))

        if rubric_ready:
            label = assessment_id or rubric_title or Path(rubric_path).name or "Rubric loaded"
            self.rubric_card.set_status("✓ {}".format(label), True, rubric_path)
        else:
            self.rubric_card.set_status("Not configured", False)

        if roster_ready:
            suffix = "student" if roster_count == 1 else "students"
            self.roster_card.set_status(
                "✓ {} {} loaded".format(roster_count, suffix), True, roster_path
            )
        else:
            self.roster_card.set_status("Not configured", False)

        if workspace_ready:
            display = Path(workspace_path).name or workspace_path
            self.workspace_card.set_status("✓ {}".format(display), True, workspace_path)
        else:
            self.workspace_card.set_status("Not configured", False)

        readiness = {
            "rubric": rubric_ready,
            "roster": roster_ready,
            "workspace": workspace_ready,
        }
        missing = [
            self._DISPLAY_NAMES[key]
            for key in self._REQUIRED_KEYS
            if not readiness[key]
        ]
        ready = not missing
        self.written_card.set_ready(ready, missing)
        self.programming_card.set_ready(ready, missing)

        if ready:
            self.readiness_label.setText(
                "✓ Shared setup is ready. Choose Written / Text or Programming grading."
            )
            self.readiness_label.setStyleSheet(
                "font-size: 12px; color: #027A48; font-weight: 600;"
            )
        else:
            self.readiness_label.setText(
                "Complete shared setup first: {}.".format(", ".join(missing))
            )
            self.readiness_label.setStyleSheet(
                "font-size: 12px; color: #B54708; font-weight: 600;"
            )

        return ready


__all__ = ["AssessmentHomeWorkspace"]
