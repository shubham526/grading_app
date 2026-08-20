"""Main window implementation for the Rubric Grading Tool.

v2.1 provides student-centric and question-centric manual grading with stable
criterion/question identity and partial-save behavior. v2.2 Commit 5 integrates
the submission backend into that same workflow: persistent LaTeX/PDF evidence,
a Gradescope-style submission-left / grading-right workspace, explicit
PDF-accommodation handling, background Ollama transcription jobs, and
non-scoring submission metadata.

All potentially slow submission work runs through ``SubmissionWorker``. The
window remains the UI/session orchestrator; parsing, persistence, and inference
remain in ``src.submissions`` via ``SubmissionController``. Scoring, best-N,
selected/counted, analytics, and ABET semantics are intentionally unchanged.
"""

import json
import os
import tempfile
import time

from src.ui.dialogs.abet_dialogs import (
    ABETMappingDialog, ABETReportDialog, SemesterABETReportDialog,
)
from src.ui.dialogs.master_evidence_export_dialog import MasterEvidenceExportDialog
from src.ui.dialogs.similarity_dialog import SimilarityReviewDialog
from src.ui.dialogs.submission_history_dialog import SubmissionHistoryDialog
from src.ui.dialogs.submission_import_dialog import SubmissionImportDialog
from src.ui.dialogs.autograding_setup_dialog import AutogradingSetupDialog
from src.ui.dialogs.autograding_results_dialog import AutogradingResultsDialog
from src.ui.dialogs.autograding_history_dialog import AutogradingHistoryDialog
from src.ui.dialogs.autograding_batch_dialog import AutogradingBatchDialog

from PyQt5.QtWidgets import (
    QAction, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea,
    QLineEdit, QMessageBox, QGroupBox, QInputDialog, QMenu, QToolButton,
    QFrame, QSplitter, QSplitterHandle, QDialog, QComboBox, QSizePolicy,
    QStackedWidget,
)
from PyQt5.QtCore import Qt, QSettings, QThreadPool, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QColor, QPainter
import qtawesome as qta

from src.core.assessment import (
    create_blank_assessment_from_rubric,
    get_assessment_data,
    merge_partial_criteria_update,
    update_grading_progress_metadata,
    update_total_points,
)
from src.core.grader import is_valid_assessment
from src.core.question_utils import (
    UNASSIGNED,
    compute_overall_criteria_progress,
    compute_question_progress,
    get_question_ids,
)
from src.core.roster import (
    StudentRecord,
    assessment_path_for_student,
    load_roster_csv,
    load_students_from_assessment_dir,
    merge_student_records,
    safe_student_filename,
)
from src.core.rubric import load_rubric_from_file
from src.submissions import SubmissionRepository, load_reference_solution
from src.autograding.execution.docker_pytest_backend import DEFAULT_DOCKER_PYTEST_IMAGE
from src.autograding.service import AutogradingGradeResult, AutogradingService

from src.ui.widgets.header import HeaderWidget
from src.ui.widgets.status_bar import StatusBarWidget
from src.ui.widgets.card import CardWidget
from src.ui.widgets.submission_workspace import SubmissionWorkspace
from src.ui.submission_controller import SubmissionController
from src.grading_session import (
    GradingSessionCheckpoint,
    load_grading_session_checkpoint,
    save_grading_session_checkpoint,
)
from src.ui.workers.autograding_worker import (
    AutogradingOperation,
    AutogradingWorker,
)
from src.ui.modes import GradingMode
from src.ui.modes.mode_selection_page import ModeSelectionPage
from src.ui.workspaces import ProgrammingGradingWorkspace
from src.ui.workers.submission_worker import (
    SubmissionOperation,
    SubmissionWorker,
    new_request_id,
)
from src.ui.dialogs.submission_settings import (
    SETTINGS_APPLICATION,
    SETTINGS_ORGANIZATION,
    SubmissionSettingsDialog,
    load_submission_settings,
)

from src.utils.layout import (
    apply_workflow_question_filter,
    setup_question_selection,
    show_all_criteria,
)
from src.utils.styles import COLORS, VisibleArrowComboBox
from src.utils.pdf import export_to_pdf, batch_export_assessments

from src.analytics.data_processor import collect_assessments


STUDENT_CENTRIC = "student_centric"
QUESTION_CENTRIC = "question_centric"

_UI_SETTINGS_GROUP = "main_window_v2_2"
_UI_GEOMETRY_KEY = "geometry"
_UI_MAXIMIZED_KEY = "maximized"
_UI_SESSION_SPLITTER_KEY = "session_workspace_splitter_v2"
_UI_WORKSPACE_SPLITTER_KEY = "workspace_splitter_horizontal_v2"
_UI_GRADING_SPLITTER_KEY = "grading_splitter"
_UI_QUESTION_SUMMARY_COLLAPSED_KEY = "question_summary_collapsed"
_UI_ATTEMPTED_QUESTIONS_VISIBLE_KEY = "attempted_questions_visible"

_BASE_WINDOW_TITLE = "Rubric Grading Tool"


class GripSplitterHandle(QSplitterHandle):
    """Splitter handle that remains visibly draggable in every state."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setCursor(Qt.SplitHCursor if orientation == Qt.Horizontal else Qt.SplitVCursor)
        self.setToolTip("Drag to resize")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#E4E7EC"))

        # A persistent center grip avoids the almost-invisible native Qt handle
        # that caused confusion during the manual acceptance pass.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#667085"))
        center = self.rect().center()
        if self.orientation() == Qt.Horizontal:
            for dy in (-8, 0, 8):
                painter.drawRoundedRect(center.x() - 2, center.y() + dy - 2, 4, 4, 2, 2)
        else:
            for dx in (-8, 0, 8):
                painter.drawRoundedRect(center.x() + dx - 2, center.y() - 2, 4, 4, 2, 2)


class PersistentGripSplitter(QSplitter):
    """QSplitter with a persistent, easy-to-hit resize handle."""

    def createHandle(self):
        return GripSplitterHandle(self.orientation(), self)


class RubricGrader(QMainWindow):
    """Main application window for the Rubric Grading Tool."""

    def __init__(self):
        super().__init__()
        self.rubric_data = None
        self.criterion_widgets = []

        # Existing scoring grouping; identifiers/semantics are intentionally
        # unchanged because best-N, selected/counted, analytics, and ABET use it.
        self.question_groups = {}

        # v2.1 canonical workflow grouping (Q1/Q1A/.../UNASSIGNED).
        self.workflow_question_groups = {}
        self.workflow_mode = STUDENT_CENTRIC
        self.current_question_id = None

        # Question-centric student/session state.
        self.roster_records = []
        self.student_records = []
        self.current_student_index = -1
        self.assessments_dir = None
        self.roster_file_path = None
        self.question_mode_dirty = False
        self.student_mode_dirty = False
        self._loading_question_student = False
        self._changing_workflow_mode = False
        self._changing_question_combo = False
        self._changing_student_combo = False
        self._restoring_grading_session = False
        self._resume_checkpoint_prompted_for = set()

        self.student_name = ""
        self.assignment_name = ""
        self.rubric_file_path = None
        self.current_assessment_path = None

        # v2.2 Commit 5 submission/evidence state. Parsing and inference remain
        # outside the GUI thread; this window owns only session/UI orchestration.
        self.submission_controller = SubmissionController()
        self.current_submission = None
        self.submissions_dir = None
        self.reference_solution = None

        self.submission_thread_pool = QThreadPool.globalInstance()
        self._submission_workers = {}
        self.active_submission_requests = {}
        self._submission_request_meta = {}
        self._latest_folder_request_id = None
        self._latest_request_by_student = {}
        self._latest_connection_request_id = None
        self._latest_reference_request_id = None
        self._submission_settings_dialog = None

        # v2.3.3 programming-autograding UI orchestration. Backend execution,
        # scoring, and persistence remain in src.autograding.
        self._autograding_service = None
        self._autograding_workers = {}
        self._autograding_batch_dialog = None

        # v2.3.4.1 explicit top-level workflow state. ``None`` means that the
        # startup/mode-selection page is visible. Assignment type is never
        # inferred from a file extension.
        self.current_grading_mode = None
        self._written_central_widget = None
        self._mode_stack = None
        self.mode_selection_page = None
        self.programming_workspace = None

        self.submission_inference_settings = load_submission_settings()
        self._submission_focus_mode = False
        self._workspace_sizes_before_focus = None
        self._session_sizes_before_focus = None
        self._workspace_popout_dialog = None
        self._workspace_popout_context_label = None

        self.ui_settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)

        self.auto_save_timer = None
        self.auto_save_interval = 3 * 60 * 1000
        self.auto_save_dir = os.path.join(tempfile.gettempdir(), "rubric_grader_autosave")
        if not os.path.exists(self.auto_save_dir):
            os.makedirs(self.auto_save_dir)

        # Existing score-selection configuration. Do not confuse this with
        # workflow_mode above.
        self.grading_config = {
            "grading_mode": "best_scores",
            "questions_to_count": 5,
            "points_per_question": 10,
            "use_fixed_total": True,
            "fixed_total": 50,
        }

        self.setWindowTitle(_BASE_WINDOW_TITLE)
        self.setMinimumSize(900, 600)
        self.resize(1400, 900)

        self.init_ui()
        self._install_grading_mode_shell()
        self._restore_ui_preferences()
        self.setup_auto_save()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def init_ui(self):
        self.status_bar = StatusBarWidget(self)
        self.setStatusBar(self.status_bar)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(10)

        self.header = HeaderWidget()
        self.header.set_subtitle(
            "Question-centric grading with persistent LaTeX/PDF submission evidence"
        )
        main_layout.addWidget(self.header)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {COLORS['divider'].name()}; border: none;")
        main_layout.addWidget(divider)

        # ---------------------- primary action toolbar ----------------------
        # Routine grading keeps only the two most common actions visible.
        # One-time setup, reporting, legacy compatibility, and settings live in
        # compact menus so the grading workspace owns the visual hierarchy.
        toolbar_container = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        self.load_btn = QPushButton("Load Rubric")
        self.load_btn.setIcon(qta.icon('fa5s.folder-open'))
        self.load_btn.setProperty("buttonRole", "primary")
        self.load_btn.clicked.connect(self.load_rubric)
        toolbar_layout.addWidget(self.load_btn)

        self.import_submissions_btn = QPushButton("Import Submissions")
        self.import_submissions_btn.setIcon(qta.icon('fa5s.file-upload'))
        self.import_submissions_btn.setToolTip(
            "Import local submission files into canonical attempt/provenance storage"
        )
        self.import_submissions_btn.clicked.connect(self.show_submission_import_dialog)
        toolbar_layout.addWidget(self.import_submissions_btn)

        toolbar_layout.addStretch(1)

        setup_menu = QMenu(self)
        self.load_assessment_folder_action = QAction(
            qta.icon('fa5s.folder'), "Choose Workspace…", self
        )
        self.load_assessment_folder_action.setToolTip(
            "Choose where assessment JSON files and persistent submission evidence are stored"
        )
        self.load_assessment_folder_action.triggered.connect(self.load_assessment_folder)
        setup_menu.addAction(self.load_assessment_folder_action)

        self.load_roster_action = QAction(qta.icon('fa5s.users'), "Load Roster…", self)
        self.load_roster_action.triggered.connect(self.load_roster)
        setup_menu.addAction(self.load_roster_action)

        self.load_reference_solution_action = QAction(
            qta.icon('fa5s.check-circle'), "Load Reference Solution…", self
        )
        self.load_reference_solution_action.setToolTip(
            "Load an instructor reference solution; LaTeX is recommended, digital PDF is supported"
        )
        self.load_reference_solution_action.triggered.connect(self.load_reference_solution_file)
        setup_menu.addAction(self.load_reference_solution_action)
        setup_menu.addSeparator()

        self.add_pdf_accommodation_action = QAction(
            qta.icon('fa5s.file-pdf'), "Add PDF Accommodation…", self
        )
        self.add_pdf_accommodation_action.setToolTip(
            "Explicitly associate a PDF-only accommodation submission with a student"
        )
        self.add_pdf_accommodation_action.triggered.connect(self.add_pdf_accommodation)
        setup_menu.addAction(self.add_pdf_accommodation_action)

        # Compatibility aliases retained for callers that still reference the
        # previous button attributes. These are QAction objects in v2.3.2+.
        self.load_assessment_folder_btn = self.load_assessment_folder_action
        self.load_roster_btn = self.load_roster_action
        self.load_reference_solution_btn = self.load_reference_solution_action
        self.add_pdf_accommodation_btn = self.add_pdf_accommodation_action

        self.setup_menu_button = QToolButton()
        self.setup_menu_button.setText("Setup")
        self.setup_menu_button.setIcon(qta.icon('fa5s.folder-plus'))
        self.setup_menu_button.setProperty("toolbarMenu", True)
        self.setup_menu_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setup_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.setup_menu_button.setMenu(setup_menu)
        toolbar_layout.addWidget(self.setup_menu_button)

        reports_menu = QMenu(self)
        self.analytics_btn = QAction(qta.icon('fa5s.chart-bar'), "Analytics", self)
        self.analytics_btn.triggered.connect(self.show_analytics)
        self.analytics_btn.setEnabled(False)
        reports_menu.addAction(self.analytics_btn)
        reports_menu.addSeparator()

        self.abet_report_btn = QAction(qta.icon('fa5s.file-contract'), "ABET Report", self)
        self.abet_report_btn.triggered.connect(self.show_abet_report)
        reports_menu.addAction(self.abet_report_btn)

        self.semester_abet_btn = QAction(qta.icon('fa5s.calendar-alt'), "Semester Report", self)
        self.semester_abet_btn.triggered.connect(self.show_semester_abet_report)
        reports_menu.addAction(self.semester_abet_btn)

        self.master_evidence_btn = QAction(
            qta.icon('fa5s.table'), "Master ABET Evidence Sheet", self
        )
        self.master_evidence_btn.setToolTip(
            "Export row-level ABET evidence for one assignment or a full semester"
        )
        self.master_evidence_btn.triggered.connect(self.show_master_abet_evidence_export)
        reports_menu.addAction(self.master_evidence_btn)
        reports_menu.addSeparator()

        self.export_btn = QAction(qta.icon('fa5s.file-export'), "Export Current Assessment to PDF", self)
        self.export_btn.triggered.connect(self.export_to_pdf)
        self.export_btn.setEnabled(False)
        reports_menu.addAction(self.export_btn)

        self.batch_export_action = QAction(qta.icon('fa5s.copy'), "Batch Export Assessments", self)
        self.batch_export_action.triggered.connect(self.batch_export_assessments)
        reports_menu.addAction(self.batch_export_action)

        self.reports_menu_button = QToolButton()
        self.reports_menu_button.setText("Reports")
        self.reports_menu_button.setIcon(qta.icon('fa5s.file-alt'))
        self.reports_menu_button.setProperty("toolbarMenu", True)
        self.reports_menu_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.reports_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.reports_menu_button.setMenu(reports_menu)
        toolbar_layout.addWidget(self.reports_menu_button)

        tools_menu = QMenu(self)
        self.similarity_review_action = QAction(
            qta.icon('fa5s.search'), "Submission Similarity Review", self
        )
        self.similarity_review_action.setToolTip(
            "Compare student submissions using deterministic, explainable similarity signals"
        )
        self.similarity_review_action.triggered.connect(self.show_similarity_review)
        tools_menu.addAction(self.similarity_review_action)

        self.submission_history_action = QAction(
            qta.icon('fa5s.history'), "Submission History", self
        )
        self.submission_history_action.setToolTip(
            "View immutable canonical attempts for the current student and switch the active attempt"
        )
        self.submission_history_action.triggered.connect(self.show_submission_history)
        tools_menu.addAction(self.submission_history_action)

        autograding_menu = QMenu("Programming Autograding", self)
        autograding_menu.setIcon(qta.icon('fa5s.code'))

        self.configure_autograder_action = QAction(
            qta.icon('fa5s.cogs'), "Configure Autograder…", self
        )
        self.configure_autograder_action.setToolTip(
            "Import/select an immutable test bundle and Docker pytest runtime"
        )
        self.configure_autograder_action.triggered.connect(self.show_autograding_setup)
        autograding_menu.addAction(self.configure_autograder_action)
        autograding_menu.addSeparator()

        self.grade_current_programming_action = QAction(
            qta.icon('fa5s.play'), "Grade Current Submission", self
        )
        self.grade_current_programming_action.setToolTip(
            "Run the current student's active canonical Python attempt in the isolated pytest runtime"
        )
        self.grade_current_programming_action.triggered.connect(
            self.grade_current_programming_submission
        )
        autograding_menu.addAction(self.grade_current_programming_action)

        self.grade_all_programming_action = QAction(
            qta.icon('fa5s.tasks'), "Grade All Active Submissions…", self
        )
        self.grade_all_programming_action.setToolTip(
            "Batch-grade all roster students whose active canonical submission satisfies the programming contract"
        )
        self.grade_all_programming_action.triggered.connect(
            self.grade_all_programming_submissions
        )
        autograding_menu.addAction(self.grade_all_programming_action)

        self.autograding_history_action = QAction(
            qta.icon('fa5s.history'), "Autograding History…", self
        )
        self.autograding_history_action.setToolTip(
            "View immutable programming-autograding runs for the current student"
        )
        self.autograding_history_action.triggered.connect(self.show_autograding_history)
        autograding_menu.addAction(self.autograding_history_action)

        tools_menu.addMenu(autograding_menu)

        self.resume_grading_session_action = QAction(
            qta.icon('fa5s.play-circle'), "Resume Grading Session", self
        )
        self.resume_grading_session_action.setToolTip(
            "Resume the last saved question/student position for the current assessment workspace"
        )
        self.resume_grading_session_action.triggered.connect(self.resume_grading_session)
        tools_menu.addAction(self.resume_grading_session_action)
        tools_menu.addSeparator()

        legacy_menu = QMenu("Legacy", self)
        legacy_menu.setIcon(qta.icon('fa5s.archive'))
        self.load_submissions_btn = QAction(
            qta.icon('fa5s.file-code'), "Load LaTeX Submissions (v2.2)…", self
        )
        self.load_submissions_btn.setToolTip(
            "Legacy v2.2 LaTeX-folder loader; canonical Import Submissions is preferred"
        )
        self.load_submissions_btn.triggered.connect(self.load_submissions_folder)
        legacy_menu.addAction(self.load_submissions_btn)
        tools_menu.addMenu(legacy_menu)

        self.tools_menu_button = QToolButton()
        self.tools_menu_button.setText("Tools")
        self.tools_menu_button.setIcon(qta.icon('fa5s.tools'))
        self.tools_menu_button.setProperty("toolbarMenu", True)
        self.tools_menu_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.tools_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.tools_menu_button.setMenu(tools_menu)
        toolbar_layout.addWidget(self.tools_menu_button)

        settings_menu = QMenu(self)
        self.config_btn = QAction(qta.icon('fa5s.sliders-h'), "Grading Configuration", self)
        self.config_btn.triggered.connect(self.show_grading_config)
        self.config_btn.setEnabled(False)
        settings_menu.addAction(self.config_btn)

        self.abet_mapping_btn = QAction(qta.icon('fa5s.clipboard-check'), "ABET Mapping", self)
        self.abet_mapping_btn.triggered.connect(self.show_abet_mapping)
        self.abet_mapping_btn.setEnabled(False)
        settings_menu.addAction(self.abet_mapping_btn)
        settings_menu.addSeparator()

        self.submission_settings_action = QAction(
            qta.icon('fa5s.robot'), "Submission & AI Settings", self
        )
        self.submission_settings_action.triggered.connect(self.show_submission_settings)
        settings_menu.addAction(self.submission_settings_action)

        self.settings_menu_button = QToolButton()
        self.settings_menu_button.setText("Settings")
        self.settings_menu_button.setIcon(qta.icon('fa5s.cog'))
        self.settings_menu_button.setProperty("toolbarMenu", True)
        self.settings_menu_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.settings_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.settings_menu_button.setMenu(settings_menu)
        toolbar_layout.addWidget(self.settings_menu_button)

        main_layout.addWidget(toolbar_container)

        # Setup/navigation lives in the upper child of a vertical splitter.
        # The actual grading workspace is the lower child, so instructors can
        # devote most of the screen to PDF + grading during routine marking.
        self.session_panel = QWidget()
        self.session_panel.setObjectName("sessionPanel")
        session_layout = QVBoxLayout(self.session_panel)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setSpacing(10)

        # ----------------------- compact assessment context -----------------------
        self.info_widget = QFrame()
        self.info_widget.setObjectName("assessmentContextStrip")
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(12, 7, 12, 7)
        info_layout.setSpacing(8)

        assessment_caption = QLabel("Assessment")
        assessment_caption.setObjectName("contextCaption")
        info_layout.addWidget(assessment_caption)

        self.assignment_name_edit = QLineEdit()
        self.assignment_name_edit.setPlaceholderText("Assignment name")
        self.assignment_name_edit.setMinimumWidth(260)
        self.assignment_name_edit.setMaximumWidth(520)
        self.assignment_name_edit.setToolTip("Current assessment title")
        info_layout.addWidget(self.assignment_name_edit, 2)

        self.status_label = QLabel("No rubric loaded")
        self.status_label.setObjectName("contextMeta")
        self.status_label.setWordWrap(False)
        info_layout.addWidget(self.status_label, 1)
        info_layout.addStretch(1)

        workspace_caption = QLabel("Workspace")
        workspace_caption.setObjectName("contextCaption")
        info_layout.addWidget(workspace_caption)
        self.assessment_folder_label = QLabel("Not selected")
        self.assessment_folder_label.setObjectName("workspacePathLabel")
        self.assessment_folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.assessment_folder_label.setMinimumWidth(180)
        info_layout.addWidget(self.assessment_folder_label, 1)
        session_layout.addWidget(self.info_widget)

        # ------------------------- workflow/context card -------------------------
        self.workflow_card = CardWidget("Grading Context")
        workflow_layout = self.workflow_card.get_content_layout()

        workflow_top = QHBoxLayout()
        workflow_top.setSpacing(8)
        workflow_top.addWidget(QLabel("Workflow"))
        self.workflow_mode_combo = VisibleArrowComboBox()
        self.workflow_mode_combo.addItem("Student-by-student", STUDENT_CENTRIC)
        self.workflow_mode_combo.addItem("Question-by-question", QUESTION_CENTRIC)
        self.workflow_mode_combo.setMinimumWidth(190)
        self.workflow_mode_combo.setMaximumWidth(240)
        workflow_top.addWidget(self.workflow_mode_combo)
        workflow_top.addSpacing(10)

        self.config_info = QLabel()
        self.config_info.setObjectName("gradingSummaryLabel")
        self.config_info.setWordWrap(False)
        workflow_top.addWidget(self.config_info, 1)

        self.attempted_questions_button = QToolButton()
        self.attempted_questions_button.setText("Attempted Questions")
        self.attempted_questions_button.setCheckable(True)
        self.attempted_questions_button.setChecked(False)
        self.attempted_questions_button.setProperty("toolbarMenu", True)
        self.attempted_questions_button.setToolTip(
            "Show or hide the student's attempted-question controls"
        )
        self.attempted_questions_button.toggled.connect(
            self._set_questions_attempted_visible
        )
        workflow_top.addWidget(self.attempted_questions_button)
        workflow_layout.addLayout(workflow_top)
        self.update_config_info()

        # Question navigation appears only in Question-by-question mode.
        self.question_mode_controls = QWidget()
        self.question_mode_controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        question_mode_layout = QVBoxLayout(self.question_mode_controls)
        question_mode_layout.setContentsMargins(0, 2, 0, 0)
        question_mode_layout.setSpacing(6)

        question_row = QHBoxLayout()
        question_row.setSpacing(8)
        question_row.addWidget(QLabel("Question"))

        self.prev_question_btn = QPushButton("‹")
        self.prev_question_btn.setFixedWidth(36)
        self.prev_question_btn.setToolTip("Previous question")
        self.prev_question_btn.clicked.connect(lambda: self.navigate_question(-1))
        question_row.addWidget(self.prev_question_btn)

        self.question_combo = VisibleArrowComboBox()
        self.question_combo.setMinimumWidth(120)
        self.question_combo.setMaximumWidth(180)
        question_row.addWidget(self.question_combo)

        self.next_question_btn = QPushButton("›")
        self.next_question_btn.setFixedWidth(36)
        self.next_question_btn.setToolTip("Next question")
        self.next_question_btn.clicked.connect(lambda: self.navigate_question(1))
        question_row.addWidget(self.next_question_btn)
        question_row.addSpacing(10)

        self.question_progress_label = QLabel("Question progress: —")
        self.question_progress_label.setStyleSheet("font-weight: 600;")
        question_row.addWidget(self.question_progress_label)
        question_row.addSpacing(12)
        self.overall_progress_label = QLabel("Overall progress: —")
        question_row.addWidget(self.overall_progress_label)
        question_row.addStretch(1)
        question_mode_layout.addLayout(question_row)
        self.question_mode_controls.setVisible(False)
        workflow_layout.addWidget(self.question_mode_controls)

        # Student navigation is shared by both workflows. With a roster/folder,
        # use the stable record dropdown; without one, retain manual-name entry.
        self.student_navigation_controls = QWidget()
        student_row = QHBoxLayout(self.student_navigation_controls)
        student_row.setContentsMargins(0, 2, 0, 0)
        student_row.setSpacing(8)
        student_row.addWidget(QLabel("Student"))

        self.prev_student_btn = QPushButton("‹")
        self.prev_student_btn.setFixedWidth(36)
        self.prev_student_btn.setToolTip("Previous student")
        self.prev_student_btn.clicked.connect(lambda: self.navigate_student(-1))
        student_row.addWidget(self.prev_student_btn)

        self.student_combo = VisibleArrowComboBox()
        self.student_combo.setMinimumWidth(240)
        self.student_combo.setMaximumWidth(420)
        student_row.addWidget(self.student_combo, 1)

        self.student_name_edit = QLineEdit()
        self.student_name_edit.setPlaceholderText("Enter student name or load a roster")
        self.student_name_edit.editingFinished.connect(self._on_manual_student_context_changed)
        student_row.addWidget(self.student_name_edit, 1)

        self.next_student_btn = QPushButton("›")
        self.next_student_btn.setFixedWidth(36)
        self.next_student_btn.setToolTip("Next student")
        self.next_student_btn.clicked.connect(lambda: self.navigate_student(1))
        student_row.addWidget(self.next_student_btn)

        self.student_position_label = QLabel("No roster")
        self.student_position_label.setObjectName("contextMeta")
        self.student_position_label.setMinimumWidth(62)
        student_row.addWidget(self.student_position_label)
        student_row.addSpacing(8)

        self.question_mode_actions = QWidget()
        question_actions_layout = QHBoxLayout(self.question_mode_actions)
        question_actions_layout.setContentsMargins(0, 0, 0, 0)
        question_actions_layout.setSpacing(6)

        self.save_question_btn = QPushButton("Save Question")
        self.save_question_btn.setIcon(qta.icon('fa5s.save'))
        self.save_question_btn.setProperty("buttonRole", "primary")
        self.save_question_btn.setToolTip("Save the current question for the current student")
        self.save_question_btn.clicked.connect(
            lambda: self.save_current_question(show_success=True)
        )
        question_actions_layout.addWidget(self.save_question_btn)

        self.save_next_student_btn = QPushButton("Save + Next")
        self.save_next_student_btn.setToolTip(
            "Save the current question and move to the next student"
        )
        self.save_next_student_btn.clicked.connect(self.save_and_next_student)
        question_actions_layout.addWidget(self.save_next_student_btn)

        self.mark_question_complete_btn = QPushButton("Mark Complete")
        self.mark_question_complete_btn.setToolTip(
            "Mark the current question complete for this student"
        )
        self.mark_question_complete_btn.clicked.connect(self.mark_current_question_complete)
        question_actions_layout.addWidget(self.mark_question_complete_btn)
        student_row.addWidget(self.question_mode_actions)

        self.student_mode_actions = QWidget()
        student_actions_layout = QHBoxLayout(self.student_mode_actions)
        student_actions_layout.setContentsMargins(0, 0, 0, 0)
        student_actions_layout.setSpacing(6)
        self.save_next_assessment_btn = QPushButton("Save + Next Student")
        self.save_next_assessment_btn.setIcon(qta.icon('fa5s.step-forward'))
        self.save_next_assessment_btn.setToolTip(
            "Save the complete current assessment and move to the next student"
        )
        self.save_next_assessment_btn.clicked.connect(self.save_and_next_student_assessment)
        student_actions_layout.addWidget(self.save_next_assessment_btn)
        student_row.addWidget(self.student_mode_actions)

        workflow_layout.addWidget(self.student_navigation_controls)
        session_layout.addWidget(self.workflow_card)

        self.workflow_mode_combo.currentIndexChanged.connect(self.on_workflow_mode_changed)
        self.question_combo.currentIndexChanged.connect(self.on_question_combo_changed)
        self.student_combo.currentIndexChanged.connect(self.on_student_combo_changed)
        self._update_student_navigation_visibility()

        # Existing selected/attempted-question controls remain available because
        # the display workflow must not change selected/counted scoring semantics.
        self.question_selection_group = QGroupBox("Questions Attempted by Student")
        self.question_selection_layout = QHBoxLayout()
        self.question_selection_group.setLayout(self.question_selection_layout)
        self.question_selection_group.setVisible(False)
        session_layout.addWidget(self.question_selection_group)

        # ------------------------- submission workspace -------------------------
        # Manual grading uses a Gradescope-style arrangement: the rendered
        # submission remains visible on the left while rubric controls remain
        # visible on the right. Source/transcription text opens on demand.
        self.submission_workspace = SubmissionWorkspace(self)
        self.submission_workspace.setMinimumWidth(460)
        self.submission_workspace.open_source_requested.connect(self.open_submission_source)
        self.submission_workspace.refresh_requested.connect(self.refresh_submission_evidence)
        self.submission_workspace.generate_transcription_requested.connect(
            self.generate_submission_transcription
        )
        self.submission_workspace.focus_requested.connect(
            self._on_submission_focus_requested
        )
        self.submission_workspace.popout_workspace_requested.connect(
            self._pop_out_grading_workspace
        )

        # --------------------------- grading workspace ---------------------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")
        self.criteria_layout = QVBoxLayout(self.scroll_content)
        self.criteria_layout.setContentsMargins(12, 12, 12, 12)
        self.criteria_layout.setSpacing(8)
        self.scroll_area.setWidget(self.scroll_content)

        self.question_summary_card = CardWidget(
            "Question Scores Summary", collapsible=True, initially_collapsed=True
        )
        self.question_summary_layout = self.question_summary_card.get_content_layout()
        self.question_summary_card.collapsed_changed.connect(
            self._on_question_summary_collapsed_changed
        )

        self.main_splitter = PersistentGripSplitter(Qt.Vertical)
        self.main_splitter.setObjectName("gradingSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(7)
        self.main_splitter.addWidget(self.scroll_area)
        self.summary_container = QWidget()
        summary_layout = QVBoxLayout(self.summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.question_summary_card)
        self.main_splitter.addWidget(self.summary_container)
        self.main_splitter.setStretchFactor(0, 6)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([610, 80])

        self.grading_workspace = QWidget()
        self.grading_workspace.setObjectName("gradingWorkspace")
        self.grading_workspace.setMinimumWidth(420)
        grading_layout = QVBoxLayout(self.grading_workspace)
        grading_layout.setContentsMargins(0, 0, 0, 0)
        grading_layout.setSpacing(0)

        grading_header = QWidget(self.grading_workspace)
        grading_header.setObjectName("gradingPaneHeader")
        grading_header_layout = QHBoxLayout(grading_header)
        grading_header_layout.setContentsMargins(12, 8, 12, 8)
        self.grading_pane_title = QLabel("Grading", grading_header)
        self.grading_pane_title.setObjectName("gradingPaneTitle")
        grading_header_layout.addWidget(self.grading_pane_title)
        grading_header_layout.addStretch(1)
        grading_layout.addWidget(grading_header)
        grading_layout.addWidget(self.main_splitter, 1)

        # Main work splitter: submission on the left, grading on the right.
        # The 12px handle remains visible while hovered/pressed and neither
        # child can collapse to zero.
        self.workspace_splitter = PersistentGripSplitter(Qt.Horizontal)
        self.workspace_splitter.setObjectName("mainWorkspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(12)
        self.workspace_splitter.setOpaqueResize(True)
        self.workspace_splitter.addWidget(self.submission_workspace)
        self.workspace_splitter.addWidget(self.grading_workspace)
        self.workspace_splitter.setStretchFactor(0, 6)
        self.workspace_splitter.setStretchFactor(1, 5)
        self.workspace_splitter.setSizes([760, 640])
        self.workspace_splitter.setStyleSheet(
            "QWidget#gradingPaneHeader {"
            "background: #FFFFFF; border: 1px solid #D9DEE7;"
            "border-bottom: 1px solid #E6E9EF;"
            "}"
            "QLabel#gradingPaneTitle { color: #1F2937; font-weight: 600; }"
        )

        # Host remains in the main window even while the exact same two-panel
        # workspace is temporarily reparented into a pop-out window.
        self.workspace_host = QWidget()
        self.workspace_host.setObjectName("workspaceHost")
        self.workspace_host_layout = QVBoxLayout(self.workspace_host)
        self.workspace_host_layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_host_layout.setSpacing(0)
        self.workspace_host_layout.addWidget(self.workspace_splitter)

        self.workspace_popout_placeholder = QWidget(self.workspace_host)
        placeholder_layout = QVBoxLayout(self.workspace_popout_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        placeholder_label = QLabel(
            "Submission + grading workspace is open in a separate window.",
            self.workspace_popout_placeholder,
        )
        placeholder_label.setStyleSheet("color: #667085; font-weight: 600;")
        placeholder_layout.addWidget(placeholder_label, 0, Qt.AlignCenter)
        reattach_button = QPushButton("Reattach Workspace", self.workspace_popout_placeholder)
        reattach_button.clicked.connect(self._reattach_grading_workspace)
        placeholder_layout.addWidget(reattach_button, 0, Qt.AlignCenter)
        self.workspace_popout_placeholder.setVisible(False)
        self.workspace_host_layout.addWidget(self.workspace_popout_placeholder)

        # The upper setup/context area can itself be resized against the actual
        # grading workspace. A scroll area keeps controls reachable if the
        # instructor compresses this section aggressively.
        self.session_scroll = QScrollArea()
        self.session_scroll.setObjectName("sessionScrollArea")
        self.session_scroll.setWidgetResizable(True)
        self.session_scroll.setFrameShape(QFrame.NoFrame)
        self.session_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.session_scroll.setWidget(self.session_panel)

        self.session_workspace_splitter = PersistentGripSplitter(Qt.Vertical)
        self.session_workspace_splitter.setObjectName("sessionWorkspaceSplitter")
        self.session_workspace_splitter.setChildrenCollapsible(False)
        self.session_workspace_splitter.setHandleWidth(12)
        self.session_workspace_splitter.setOpaqueResize(True)
        self.session_workspace_splitter.addWidget(self.session_scroll)
        self.session_workspace_splitter.addWidget(self.workspace_host)
        self.session_workspace_splitter.setStretchFactor(0, 2)
        self.session_workspace_splitter.setStretchFactor(1, 7)
        self.session_workspace_splitter.setSizes([185, 715])
        main_layout.addWidget(self.session_workspace_splitter, 1)

        # ------------------------- bottom grading controls -------------------------
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 2, 0, 0)
        self.total_label = QLabel("Total: 0 / 0 points")
        self.total_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        bottom_layout.addWidget(self.total_label)
        bottom_layout.addStretch(1)

        clear_btn = QPushButton("Clear Form")
        clear_btn.setIcon(qta.icon('fa5s.eraser'))
        clear_btn.clicked.connect(self.clear_form)
        bottom_layout.addWidget(clear_btn)

        self.save_assessment_btn = QPushButton("Save Assessment")
        self.save_assessment_btn.setIcon(qta.icon('fa5s.save'))
        self.save_assessment_btn.setProperty("buttonRole", "primary")
        self.save_assessment_btn.setToolTip(
            "Save the complete current student's assessment"
        )
        self.save_assessment_btn.clicked.connect(
            lambda _checked=False: self.save_assessment(show_success=True)
        )
        bottom_layout.addWidget(self.save_assessment_btn)

        save_menu = QMenu(self)
        self.save_assessment_as_action = QAction(
            qta.icon('fa5s.file-export'), "Save Assessment As…", self
        )
        self.save_assessment_as_action.triggered.connect(
            lambda _checked=False: self.save_assessment_as(show_success=True)
        )
        save_menu.addAction(self.save_assessment_as_action)

        self.save_assessment_menu_button = QToolButton()
        self.save_assessment_menu_button.setIcon(qta.icon('fa5s.ellipsis-h'))
        self.save_assessment_menu_button.setToolTip("More save options")
        self.save_assessment_menu_button.setProperty("toolbarMenu", True)
        self.save_assessment_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.save_assessment_menu_button.setMenu(save_menu)
        bottom_layout.addWidget(self.save_assessment_menu_button)

        # Compatibility alias for callers/tests that referenced the previous
        # full-width Save Assessment As button.
        self.save_assessment_as_btn = self.save_assessment_as_action

        load_assessment_btn = QPushButton("Load Assessment")
        load_assessment_btn.setIcon(qta.icon('fa5s.file-upload'))
        load_assessment_btn.clicked.connect(self.load_assessment)
        bottom_layout.addWidget(load_assessment_btn)

        main_layout.addLayout(bottom_layout)
        self._update_submission_status()

    # ------------------------------------------------------------------
    # v2.3.4.1 dual-mode application shell
    # ------------------------------------------------------------------

    def _install_grading_mode_shell(self):
        """Wrap the exact v2.3.3 written UI in an explicit workspace host.

        Commit 1 deliberately does not rebuild or relocate the written grading
        controls. The already-constructed v2.3.3 central widget is detached as
        one intact QWidget and inserted into the mode stack. Its child widgets,
        signals, splitters, controller references, and grading state remain the
        same objects.
        """

        written_widget = self.takeCentralWidget()
        if written_widget is None:
            raise RuntimeError("Written grading UI was not constructed")

        written_widget.setObjectName("writtenGradingWorkspaceLegacyRoot")
        self._written_central_widget = written_widget

        self.mode_selection_page = ModeSelectionPage(self)
        self.programming_workspace = ProgrammingGradingWorkspace(self)

        self._mode_stack = QStackedWidget(self)
        self._mode_stack.setObjectName("gradingModeWorkspaceStack")
        self._mode_stack.addWidget(self.mode_selection_page)
        self._mode_stack.addWidget(self._written_central_widget)
        self._mode_stack.addWidget(self.programming_workspace)
        self.setCentralWidget(self._mode_stack)

        self.mode_selection_page.mode_selected.connect(self.set_grading_mode)
        self.programming_workspace.choose_mode_button.clicked.connect(
            self.show_grading_mode_selector
        )

        self._install_grading_mode_menu()
        self.show_grading_mode_selector()

    def _install_grading_mode_menu(self):
        """Install shared top-level navigation for switching grading modes."""

        self.file_menu = self.menuBar().addMenu("&File")
        self.switch_grading_mode_action = QAction(
            qta.icon("fa5s.exchange-alt"),
            "Switch Grading Mode…",
            self,
        )
        self.switch_grading_mode_action.setToolTip(
            "Choose between Written / Text and Programming grading workspaces"
        )
        self.switch_grading_mode_action.triggered.connect(
            self.show_grading_mode_selector
        )
        self.file_menu.addAction(self.switch_grading_mode_action)

    def show_grading_mode_selector(self, _checked=False):
        """Show the workflow chooser without destroying either workspace state."""

        if self._mode_stack is None or self.mode_selection_page is None:
            return
        self.current_grading_mode = None
        self._mode_stack.setCurrentWidget(self.mode_selection_page)
        self.setWindowTitle(_BASE_WINDOW_TITLE)
        if hasattr(self, "status_bar"):
            self.status_bar.set_status("Choose a grading mode")

    def set_grading_mode(self, mode):
        """Activate a top-level grading workspace.

        Commit 1 changes presentation only. Shared assessment, roster, canonical
        submission, existing written grading, and v2.3.3 autograding state
        remain owned by this window and are not reset by a mode change.
        """

        mode = GradingMode.coerce(mode)
        if self._mode_stack is None:
            raise RuntimeError("Grading mode shell is not initialized")

        if mode is GradingMode.WRITTEN:
            target = self._written_central_widget
        else:
            target = self.programming_workspace

        if target is None:
            raise RuntimeError("Grading workspace is not initialized")

        self.current_grading_mode = mode
        self._mode_stack.setCurrentWidget(target)
        self.setWindowTitle(
            "{} — {}".format(_BASE_WINDOW_TITLE, mode.display_name)
        )
        if hasattr(self, "status_bar"):
            self.status_bar.set_status(
                "{} grading mode".format(mode.display_name)
            )

    def active_grading_workspace(self):
        """Return the currently visible shell page."""

        if self._mode_stack is None:
            return None
        return self._mode_stack.currentWidget()

    def _written_central_layout(self):
        """Return the original v2.3.3 written root layout after shell wrapping."""

        if self._written_central_widget is None:
            return None
        return self._written_central_widget.layout()

    def _on_question_summary_collapsed_changed(self, collapsed):
        """Give the summary useful height immediately when the user shows it."""
        splitter = getattr(self, "main_splitter", None)
        if splitter is None:
            return
        sizes = list(splitter.sizes())
        total = sum(max(0, int(v)) for v in sizes)
        if total <= 0:
            total = 600
        if collapsed:
            summary_height = 58
        else:
            summary_height = min(280, max(190, total // 3))
        criteria_height = max(140, total - summary_height)
        splitter.setSizes([criteria_height, summary_height])

    def _set_questions_attempted_visible(self, visible):
        """Keep attempted-question controls available without consuming grading space."""
        visible = bool(visible)
        if hasattr(self, "attempted_questions_button"):
            self.attempted_questions_button.blockSignals(True)
            self.attempted_questions_button.setChecked(visible)
            self.attempted_questions_button.blockSignals(False)
        if hasattr(self, "question_selection_group"):
            self.question_selection_group.setVisible(visible and not self._submission_focus_mode)

    def _on_submission_focus_requested(self, enabled):
        """Toggle a distraction-free submission reading mode in the main window."""
        enabled = bool(enabled)
        if enabled == self._submission_focus_mode:
            self.submission_workspace.set_focus_mode(enabled)
            return

        # The whole two-pane workspace has its own pop-out mode. Focus mode is
        # only meaningful while that workspace is attached to the main window.
        if enabled and self._workspace_popout_dialog is not None:
            self._workspace_popout_dialog.raise_()
            self._workspace_popout_dialog.activateWindow()
            return

        self._submission_focus_mode = enabled
        self.submission_workspace.set_focus_mode(enabled)

        if enabled:
            self._workspace_sizes_before_focus = list(self.workspace_splitter.sizes())
            self._session_sizes_before_focus = list(self.session_workspace_splitter.sizes())
            self.session_scroll.setVisible(False)
            self.grading_workspace.setVisible(False)
        else:
            self.session_scroll.setVisible(True)
            self.grading_workspace.setVisible(True)
            self._set_questions_attempted_visible(
                self.attempted_questions_button.isChecked()
            )
            sizes = self._workspace_sizes_before_focus or [760, 640]
            self.workspace_splitter.setSizes(sizes)
            session_sizes = self._session_sizes_before_focus or [185, 715]
            self.session_workspace_splitter.setSizes(session_sizes)
            self._workspace_sizes_before_focus = None
            self._session_sizes_before_focus = None

        central_layout = self._written_central_layout()
        if central_layout is not None:
            central_layout.invalidate()
            central_layout.activate()

    def _workspace_context_text(self):
        student = self.student_name_edit.text().strip() if hasattr(self, "student_name_edit") else ""
        question = self.current_question_id if self.workflow_mode == QUESTION_CENTRIC else None
        if student and question:
            return f"{student} · {question}"
        if student:
            return student
        if question:
            return question
        return "Submission + grading workspace"

    def _update_workspace_popout_context(self):
        if self._workspace_popout_context_label is not None:
            self._workspace_popout_context_label.setText(self._workspace_context_text())

    def _pop_out_grading_workspace(self):
        """Move the exact live submission + grading workspace to a window.

        No grading widgets are duplicated. Reparenting the existing horizontal
        splitter guarantees scores, comments, PDF state, and question-summary
        state remain identical in attached and popped-out modes.
        """
        if self.current_submission is None:
            return
        if self._workspace_popout_dialog is not None:
            self._workspace_popout_dialog.show()
            self._workspace_popout_dialog.raise_()
            self._workspace_popout_dialog.activateWindow()
            return

        if self._submission_focus_mode:
            self._on_submission_focus_requested(False)

        dialog = QDialog(self)
        dialog.setWindowTitle("Submission + Grading Workspace")
        dialog.resize(1450, 900)
        dialog.setMinimumSize(980, 650)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(10, 10, 10, 10)
        dialog_layout.setSpacing(8)

        popout_header = QWidget(dialog)
        header_layout = QHBoxLayout(popout_header)
        header_layout.setContentsMargins(2, 0, 2, 0)
        self._workspace_popout_context_label = QLabel(
            self._workspace_context_text(), popout_header
        )
        self._workspace_popout_context_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #1F2937;"
        )
        header_layout.addWidget(self._workspace_popout_context_label)
        header_layout.addStretch(1)

        prev_q = QPushButton("Previous Question", popout_header)
        prev_q.clicked.connect(lambda: self.navigate_question(-1))
        prev_q.setVisible(self.workflow_mode == QUESTION_CENTRIC)
        header_layout.addWidget(prev_q)
        next_q = QPushButton("Next Question", popout_header)
        next_q.clicked.connect(lambda: self.navigate_question(1))
        next_q.setVisible(self.workflow_mode == QUESTION_CENTRIC)
        header_layout.addWidget(next_q)

        prev_student = QPushButton("Previous Student", popout_header)
        prev_student.clicked.connect(lambda: self.navigate_student(-1))
        prev_student.setVisible(bool(self.student_records))
        header_layout.addWidget(prev_student)
        next_student = QPushButton("Next Student", popout_header)
        next_student.clicked.connect(lambda: self.navigate_student(1))
        next_student.setVisible(bool(self.student_records))
        header_layout.addWidget(next_student)

        save_button = QPushButton(
            "Save Question" if self.workflow_mode == QUESTION_CENTRIC else "Save Assessment",
            popout_header,
        )
        save_button.setProperty("buttonRole", "primary")
        save_button.clicked.connect(
            lambda: self.save_current_question(show_success=True)
            if self.workflow_mode == QUESTION_CENTRIC
            else self.save_assessment()
        )
        header_layout.addWidget(save_button)

        if self.workflow_mode == QUESTION_CENTRIC:
            save_next = QPushButton("Save + Next", popout_header)
            save_next.clicked.connect(self.save_and_next_student)
            header_layout.addWidget(save_next)

            save_assessment = QPushButton("Save Assessment", popout_header)
            save_assessment.setToolTip("Save the complete current student's assessment")
            save_assessment.clicked.connect(
                lambda _checked=False: self.save_assessment(show_success=True)
            )
            header_layout.addWidget(save_assessment)
        elif self.student_records:
            save_next = QPushButton("Save + Next Student", popout_header)
            save_next.clicked.connect(self.save_and_next_student_assessment)
            header_layout.addWidget(save_next)

        reattach = QPushButton("Reattach", popout_header)
        reattach.clicked.connect(self._reattach_grading_workspace)
        header_layout.addWidget(reattach)
        dialog_layout.addWidget(popout_header)

        self.workspace_host_layout.removeWidget(self.workspace_splitter)
        self.workspace_splitter.setParent(dialog)
        dialog_layout.addWidget(self.workspace_splitter, 1)
        self.workspace_popout_placeholder.setVisible(True)

        self._workspace_popout_dialog = dialog
        dialog.finished.connect(
            lambda _result, d=dialog: self._on_workspace_popout_closed(d)
        )
        dialog.show()

    def _on_workspace_popout_closed(self, dialog):
        if dialog is self._workspace_popout_dialog:
            self._reattach_grading_workspace(close_dialog=False)

    def _reattach_grading_workspace(self, close_dialog=True):
        dialog = self._workspace_popout_dialog
        if dialog is None:
            return

        layout = dialog.layout()
        if layout is not None:
            layout.removeWidget(self.workspace_splitter)
        self.workspace_splitter.setParent(self.workspace_host)
        self.workspace_host_layout.insertWidget(0, self.workspace_splitter)
        self.workspace_popout_placeholder.setVisible(False)
        self._workspace_popout_dialog = None
        self._workspace_popout_context_label = None

        self._ensure_usable_splitter_sizes()
        if close_dialog:
            dialog.close()
            dialog.deleteLater()
        else:
            dialog.deleteLater()

    # ------------------------------------------------------------------
    # v2.2 submission-controller integration
    # ------------------------------------------------------------------

    def _submission_question_ids(self):
        """Return the canonical rubric question IDs used for submission splitting."""
        return get_question_ids(self.rubric_data or {}, include_unassigned=False)

    def _set_assessment_workspace_path(self, path):
        """Show a compact workspace path while retaining the full path as tooltip."""
        if not hasattr(self, "assessment_folder_label"):
            return
        if not path:
            self.assessment_folder_label.setText("Not selected")
            self.assessment_folder_label.setToolTip("")
            return
        absolute = os.path.abspath(path)
        base = os.path.basename(absolute.rstrip(os.sep)) or absolute
        parent = os.path.basename(os.path.dirname(absolute.rstrip(os.sep)))
        display = f"…/{parent}/{base}" if parent else base
        self.assessment_folder_label.setText(display)
        self.assessment_folder_label.setToolTip(absolute)

    def _configure_submission_evidence_root(self):
        """Point persistent evidence at the current assessment workspace."""
        if self.assessments_dir:
            return self.submission_controller.set_assessments_dir(self.assessments_dir)
        return self.submission_controller.set_evidence_root(None)

    def _active_submission_student_id(self):
        """Return the student identifier that owns the visible evidence context.

        Roster/assessment-folder loading establishes a current student even in
        student-centric mode.  Prefer that stable roster ID while the visible
        name still corresponds to the current record; otherwise preserve the
        legacy manual-name workflow.
        """
        record = self._current_student_record() if self.student_records else None
        name = self.student_name_edit.text().strip() if hasattr(self, "student_name_edit") else ""

        if self.workflow_mode == QUESTION_CENTRIC:
            if record is not None and record.student_id:
                return record.student_id
        elif record is not None and record.student_id and (
            not name or name == record.student_name
        ):
            return record.student_id

        if self.workflow_mode == STUDENT_CENTRIC and name:
            return safe_student_filename(name)

        if self.current_submission is not None and getattr(self.current_submission, "student_id", None):
            return self.current_submission.student_id

        return self.submission_controller.current_student_id

    def _sync_student_centric_record_context(self, *, load_persisted=True):
        """Immediately expose the current roster student's submission evidence.

        Loading a roster or assessment folder should not require a temporary
        switch to question-by-question mode before the submission pane updates.
        This helper changes evidence/session context only; it does not alter
        scores or criterion widgets.
        """
        if self.workflow_mode != STUDENT_CENTRIC:
            return None

        record = self._current_student_record()
        assessment_data = None
        if record is not None:
            self.student_name_edit.setText(record.student_name)
            if record.assessment_path:
                try:
                    assessment_data = self._read_assessment_file(record.assessment_path)
                except (OSError, ValueError):
                    # Optional evidence metadata must never make roster loading
                    # fail. Normal assessment loading still reports malformed
                    # files through its existing paths.
                    assessment_data = None

        return self._sync_submission_context(
            assessment_data,
            load_persisted=load_persisted,
        )

    def _notify_submission_context_changed(self):
        """Synchronize the visible evidence workspace with session context."""
        workspace = getattr(self, "submission_workspace", None)
        if workspace is not None:
            workspace.set_reference_solution(self.reference_solution)
            workspace.set_submission(self.current_submission)
            workspace.set_question(
                self.current_question_id if self.workflow_mode == QUESTION_CENTRIC else None
            )
        if hasattr(self, "grading_pane_title"):
            if self.workflow_mode == QUESTION_CENTRIC and self.current_question_id:
                self.grading_pane_title.setText(f"Grading — {self.current_question_id}")
            else:
                self.grading_pane_title.setText("Grading")
        self._update_workspace_popout_context()
        self._update_submission_status()

    def _sync_submission_context(self, assessment_data=None, *, load_persisted=True):
        """Synchronize controller state with the active rubric/student/question."""
        rubric = self.rubric_data or {}
        assessment_id = (
            rubric.get("assessment_id")
            or rubric.get("assignment_id")
            or None
        )
        self.submission_controller.set_assessment_id(assessment_id)
        self.submission_controller.set_question_ids(self._submission_question_ids())
        self.submission_controller.set_current_question(self.current_question_id)
        if self.assessments_dir:
            self._configure_submission_evidence_root()

        parsed = None
        if isinstance(assessment_data, dict):
            try:
                parsed = self.submission_controller.restore_from_assessment(assessment_data)
            except (ValueError, OSError):
                # Corrupt/missing optional evidence must not block grading or
                # assessment loading.  The future workspace can surface the
                # evidence warning separately.
                parsed = None

        student_id = self._active_submission_student_id()
        if parsed is None and student_id:
            try:
                parsed = self.submission_controller.activate_student(
                    student_id,
                    load_persisted=load_persisted,
                )
            except (ValueError, OSError):
                # Submission evidence is optional.  A broken/missing evidence
                # bundle must never make the manual grading workflow unusable.
                parsed = None
        elif parsed is None and not student_id:
            self.submission_controller.deactivate_student()

        self.current_submission = parsed
        self._notify_submission_context_changed()
        return parsed

    def register_loaded_submissions(self, parsed_by_student, *, submissions_dir=None):
        """Register parsed normal submissions returned by a background worker.

        An explicitly registered PDF accommodation takes precedence over a
        same-ID normal folder submission.  This prevents a later class-folder
        refresh from silently changing the student's submission mode.
        """
        normal_submissions = {}
        for raw_id, parsed in (parsed_by_student or {}).items():
            try:
                existing = self.submission_controller.submission_for_student(
                    raw_id, load_persisted=False
                )
            except ValueError:
                existing = None
            if existing is not None and getattr(existing, "accommodation_mode", False):
                continue
            normal_submissions[raw_id] = parsed

        registered = self.submission_controller.register_submissions(
            normal_submissions,
            submissions_dir=submissions_dir,
            replace=True,
        )
        self._sync_submission_context(load_persisted=False)
        return registered

    def register_pdf_accommodation(self, parsed_submission):
        """Register one explicitly parsed accommodation result on the UI thread."""
        parsed = self.submission_controller.register_submission(
            parsed_submission,
            replace=True,
        )
        active_id = self._active_submission_student_id()
        if active_id:
            try:
                if (
                    self.submission_controller.canonical_student_id(active_id)
                    == self.submission_controller.canonical_student_id(parsed.student_id)
                ):
                    self.submission_controller.activate_student(active_id, load_persisted=False)
                    self.current_submission = parsed
                    self._notify_submission_context_changed()
            except ValueError:
                pass
        return parsed

    def current_submission_answer(self, *, allow_full_submission_fallback=False):
        """Return the active student's extracted answer for the active question."""
        return self.submission_controller.current_answer(
            allow_full_submission_fallback=allow_full_submission_fallback,
        )

    def _merge_current_submission_into_assessment(self, assessment_data, student_id=None):
        """Attach optional evidence fields without touching score/criterion data."""
        if not isinstance(assessment_data, dict):
            return assessment_data
        target_id = student_id
        if not target_id and self.current_submission is not None:
            target_id = getattr(self.current_submission, "student_id", None)
        target_id = target_id or self._active_submission_student_id()
        return self.submission_controller.merge_submission_fields(
            assessment_data,
            student_id=target_id,
        )

    def _on_manual_student_context_changed(self):
        """Refresh evidence after manual student entry in student-centric mode."""
        if self.workflow_mode == STUDENT_CENTRIC:
            self.submission_controller.deactivate_student()
            self.current_submission = None
            self._sync_submission_context(load_persisted=True)

    def _update_submission_status(self):
        """Expose evidence state without treating AI availability as grading health."""
        status_bar = getattr(self, "status_bar", None)
        if status_bar is None:
            return
        parsed = self.current_submission
        if parsed is None:
            status_bar.set_submission_status("No submission", "neutral")
            return

        if getattr(parsed, "accommodation_mode", False):
            transcription = getattr(parsed, "transcription_metadata", {})
            transcription = transcription if isinstance(transcription, dict) else {}
            status = str(transcription.get("status") or "not_requested")
            cache = transcription.get("cache") if isinstance(transcription.get("cache"), dict) else {}
            if status == "successful":
                if cache.get("status") == "hit":
                    status_bar.set_submission_status("PDF · AI cached", "ready")
                else:
                    status_bar.set_submission_status("PDF · transcription ready", "ready")
            elif status in {"not_requested", ""}:
                status_bar.set_submission_status("PDF ready", "ready")
            else:
                status_bar.set_submission_status("PDF ready · AI unavailable", "warning")
            return

        compilation = getattr(parsed, "metadata", {}).get("compilation", {})
        compiled_ok = bool(isinstance(compilation, dict) and compilation.get("success"))
        if compiled_ok or getattr(parsed, "files", {}).get("compiled_pdf"):
            status_bar.set_submission_status("LaTeX ready", "ready")
        else:
            status_bar.set_submission_status("LaTeX source ready", "warning")

    # ------------------------------------------------------------------
    # v2.2 submission actions / background worker wiring
    # ------------------------------------------------------------------

    def _canonical_assessment_id(self):
        """Return the stable rubric assessment identity used by canonical storage."""
        rubric = self.rubric_data or {}
        value = rubric.get("assessment_id") or rubric.get("assignment_id") or ""
        return str(value).strip() or None

    def _ensure_canonical_submission_repository(self):
        """Return a canonical repository rooted in the current assessment workspace."""
        if not self._ensure_assessments_dir(allow_prompt=True):
            return None
        self._configure_submission_evidence_root()
        evidence_root = self.submission_controller.evidence_root
        if not evidence_root:
            return None
        repository = self.submission_controller.submission_repository
        if repository is None:
            repository = SubmissionRepository(evidence_root, create=True)
            self.submission_controller.set_submission_repository(repository)
        return repository

    def show_submission_import_dialog(self):
        """Open the canonical local-submission import preview/commit workflow."""
        if not self.rubric_data:
            QMessageBox.warning(self, "No Rubric", "Load the assignment rubric before importing submissions.")
            return

        assessment_id = self._canonical_assessment_id()
        if not assessment_id:
            QMessageBox.warning(
                self,
                "Missing Assessment ID",
                "The loaded rubric needs a stable assessment_id before canonical submissions can be imported.",
            )
            return

        if not self.student_records:
            self._ensure_manual_student_record()
        roster = self.student_records or self.roster_records
        if not roster:
            QMessageBox.warning(
                self,
                "No Roster",
                "Load a roster (or establish a current student) before importing submissions so files can be mapped safely.",
            )
            return

        repository = self._ensure_canonical_submission_repository()
        if repository is None:
            return

        self.submission_controller.set_assessment_id(assessment_id)
        dialog = SubmissionImportDialog(
            repository,
            assessment_id,
            roster,
            question_ids=self._submission_question_ids(),
            evidence_dir=self.submission_controller.evidence_root,
            thread_pool=self.submission_thread_pool,
            parent=self,
        )
        dialog.imports_committed.connect(self._on_canonical_imports_committed)
        dialog.exec_()

    def _on_canonical_imports_committed(self, payload):
        """Register completed canonical imports and parsed evidence on the UI thread."""
        if not isinstance(payload, dict):
            return
        result = payload.get("commit_result")
        submissions = list(getattr(result, "submissions", []) or [])
        if not submissions:
            return

        repository = self.submission_controller.submission_repository
        assessment_id = self._canonical_assessment_id()
        if repository is None or not assessment_id:
            return

        parsed_by_student = dict(payload.get("parsed_by_student", {}) or {})
        affected_students = sorted({submission.student_id for submission in submissions})
        for student_id in affected_students:
            active = repository.get_active_submission(assessment_id, student_id)
            if active is None:
                continue
            # Reassert the repository's final active pointer in controller state.
            # This also drops any ParsedSubmission cache linked to an older attempt.
            self.submission_controller.set_active_canonical_submission(
                student_id,
                active.submission_id,
                assessment_id=assessment_id,
            )
            parsed = parsed_by_student.get(student_id)
            if parsed is not None:
                self.submission_controller.register_canonical_submission(
                    active,
                    parsed=parsed,
                    replace=True,
                )

        active_student = self._active_submission_student_id()
        if active_student:
            try:
                canonical = self.submission_controller.canonical_student_id(active_student)
            except ValueError:
                canonical = None
            if canonical and canonical in parsed_by_student:
                self.submission_controller.activate_student(canonical, load_persisted=False)
                self.current_submission = parsed_by_student[canonical]
                self._notify_submission_context_changed()
            else:
                # Do not synchronously invoke a not-yet-installed programming/ZIP
                # handler merely to refresh the status bar. The repository state
                # is already committed and will be loaded when its handler exists.
                self._update_submission_status()

        imported_count = int(getattr(getattr(result, "batch", None), "imported_count", 0) or 0)
        pending = payload.get("handler_pending", {}) or {}
        parse_errors = payload.get("parse_errors", {}) or {}
        message = f"Imported {imported_count} canonical submission(s)"
        if pending:
            message += f" · {len(pending)} awaiting a later/explicit handler"
        if parse_errors:
            message += f" · {len(parse_errors)} evidence preparation warning(s)"
        self.status_bar.show_temporary_message(message)

    def show_submission_history(self):
        """Show immutable canonical attempts for the current student."""
        if not self.rubric_data:
            QMessageBox.warning(self, "No Rubric", "Load the assignment rubric first.")
            return
        assessment_id = self._canonical_assessment_id()
        if not assessment_id:
            QMessageBox.warning(self, "Missing Assessment ID", "The loaded rubric has no stable assessment_id.")
            return
        if not self._ensure_assessments_dir(allow_prompt=False):
            QMessageBox.information(
                self,
                "No Assessment Workspace",
                "Choose a Grades + Evidence Folder before viewing canonical submission history.",
            )
            return
        self._configure_submission_evidence_root()
        student_id = self._active_submission_student_id()
        if not student_id:
            QMessageBox.information(self, "No Student", "Select a student before viewing submission history.")
            return

        # Instantiate the lazy repository only when the history UI is requested.
        evidence_root = self.submission_controller.evidence_root
        if evidence_root and self.submission_controller.submission_repository is None:
            self.submission_controller.set_submission_repository(
                SubmissionRepository(evidence_root, create=False)
            )
        self.submission_controller.set_assessment_id(assessment_id)

        dialog = SubmissionHistoryDialog(
            self.submission_controller,
            student_id,
            assessment_id,
            parent=self,
        )
        dialog.submission_activated.connect(self._on_submission_history_activated)
        dialog.exec_()

    # ------------------------------------------------------------------
    # v2.3.3 programming autograding
    # ------------------------------------------------------------------

    def _autograding_settings_key(self, assessment_id, name):
        return "autograding/%s/%s" % (str(assessment_id), str(name))

    def _selected_autograding_bundle_id(self, assessment_id):
        value = self.ui_settings.value(
            self._autograding_settings_key(assessment_id, "bundle_id"), ""
        )
        return str(value or "").strip() or None

    def _autograding_runtime_image(self, assessment_id):
        value = self.ui_settings.value(
            self._autograding_settings_key(assessment_id, "runtime_image"),
            DEFAULT_DOCKER_PYTEST_IMAGE,
        )
        return str(value or DEFAULT_DOCKER_PYTEST_IMAGE).strip() or DEFAULT_DOCKER_PYTEST_IMAGE

    def _save_autograding_configuration(self, assessment_id, bundle_id, runtime_image):
        self.ui_settings.setValue(
            self._autograding_settings_key(assessment_id, "bundle_id"), bundle_id
        )
        self.ui_settings.setValue(
            self._autograding_settings_key(assessment_id, "runtime_image"), runtime_image
        )
        self.ui_settings.sync()

    def _ensure_autograding_service(self, *, allow_prompt=True):
        assessment_id = self._canonical_assessment_id()
        if not assessment_id:
            if allow_prompt:
                QMessageBox.warning(
                    self,
                    "Missing Assessment ID",
                    "Load a rubric with a stable assessment_id before using programming autograding.",
                )
            return None
        if not self._ensure_assessments_dir(allow_prompt=allow_prompt):
            return None
        repository = self._ensure_canonical_submission_repository()
        if repository is None:
            return None
        workspace = os.path.abspath(self.assessments_dir)
        evidence_root = os.path.abspath(self.submission_controller.evidence_root)
        current = self._autograding_service
        if (
            current is None
            or os.path.abspath(current.workspace_root) != workspace
            or os.path.abspath(current.evidence_root) != evidence_root
        ):
            current = AutogradingService(
                workspace,
                evidence_root=evidence_root,
                submission_repository=repository,
            )
            self._autograding_service = current
        return current

    def show_autograding_setup(self):
        service = self._ensure_autograding_service(allow_prompt=True)
        if service is None:
            return False
        assessment_id = self._canonical_assessment_id()
        dialog = AutogradingSetupDialog(
            service,
            assessment_id,
            selected_bundle_id=self._selected_autograding_bundle_id(assessment_id),
            runtime_image=self._autograding_runtime_image(assessment_id),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return False
        bundle_id = dialog.selected_bundle_id
        if not bundle_id:
            return False
        self._save_autograding_configuration(
            assessment_id, bundle_id, dialog.runtime_image
        )
        self.status_bar.show_temporary_message(
            "Programming autograder configured for %s" % assessment_id
        )
        return True

    def _require_autograding_configuration(self, service, assessment_id):
        bundle_id = self._selected_autograding_bundle_id(assessment_id)
        image = self._autograding_runtime_image(assessment_id)
        if bundle_id:
            try:
                service.load_bundle(assessment_id, bundle_id)
            except Exception:
                bundle_id = None
        if not bundle_id:
            if not self.show_autograding_setup():
                return None
            bundle_id = self._selected_autograding_bundle_id(assessment_id)
            image = self._autograding_runtime_image(assessment_id)
        return bundle_id, image

    def _current_autograding_student_id(self):
        record = self._current_student_record()
        if record is not None and record.student_id:
            return str(record.student_id).strip()
        value = self._active_submission_student_id()
        return None if not value else str(value).strip() or None

    def _set_autograding_actions_busy(self, busy):
        enabled = not bool(busy)
        for name in (
            "grade_current_programming_action",
            "grade_all_programming_action",
            "configure_autograder_action",
        ):
            action = getattr(self, name, None)
            if action is not None:
                action.setEnabled(enabled)

    def grade_current_programming_submission(self):
        service = self._ensure_autograding_service(allow_prompt=True)
        if service is None:
            return
        assessment_id = self._canonical_assessment_id()
        student_id = self._current_autograding_student_id()
        if not student_id:
            QMessageBox.warning(
                self,
                "No Current Student",
                "Select/load a student before grading a programming submission.",
            )
            return
        configured = self._require_autograding_configuration(service, assessment_id)
        if configured is None:
            return
        bundle_id, image = configured
        try:
            plan = service.build_plan(assessment_id, student_id, bundle_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Programming Submission Not Ready",
                str(exc),
            )
            return

        attempt = "—" if plan.attempt is None else str(plan.attempt)
        answer = QMessageBox.question(
            self,
            "Run Programming Autograder?",
            "Grade the active canonical programming submission?\n\n"
            "Student: %s\nAttempt: %s\nBundle: %s\nRuntime: %s\n\n"
            "This creates a new immutable autograding run and does not modify manual rubric scores."
            % (student_id, attempt, bundle_id, image),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        worker = AutogradingWorker(
            service,
            AutogradingOperation.GRADE_ONE,
            parameters={
                "assessment_id": assessment_id,
                "student_id": student_id,
                "bundle_id": bundle_id,
                "image": image,
                "metadata": {"ui_operation": "grade_current"},
            },
        )
        self._autograding_workers[worker.request_id] = worker
        worker.signals.started.connect(self._on_autograding_worker_started)
        worker.signals.completed.connect(self._on_autograding_worker_completed)
        worker.signals.failed.connect(self._on_autograding_worker_failed)
        worker.signals.finished.connect(self._on_autograding_worker_finished)
        self._set_autograding_actions_busy(True)
        self.submission_thread_pool.start(worker)

    def _on_autograding_worker_started(self, _request_id, _operation):
        self.status_bar.set_status("Programming autograding in progress…")
        self.status_bar.show_temporary_message(
            "Running isolated public/hidden pytest tests…"
        )

    def _on_autograding_worker_completed(self, _request_id, _operation, payload):
        if not isinstance(payload, AutogradingGradeResult):
            return
        summary = payload.scoring_result.score_summary
        if summary.final_score is None:
            message = "Autograding run completed and requires instructor review."
        else:
            message = "Autograding completed: %g / %g" % (
                summary.final_score,
                summary.max_score,
            )
        self.status_bar.set_status(message)
        self.status_bar.show_temporary_message(message)
        AutogradingResultsDialog(payload.stored_run, parent=self).exec_()

    def _on_autograding_worker_failed(
        self, _request_id, _operation, error_type, error_message
    ):
        QMessageBox.critical(
            self,
            "Programming Autograding Failed",
            "%s: %s" % (error_type, error_message),
        )
        self.status_bar.set_status("Programming autograding failed")

    def _on_autograding_worker_finished(self, request_id, _operation):
        self._autograding_workers.pop(request_id, None)
        if not self._autograding_workers:
            self._set_autograding_actions_busy(False)

    def grade_all_programming_submissions(self):
        service = self._ensure_autograding_service(allow_prompt=True)
        if service is None:
            return
        assessment_id = self._canonical_assessment_id()
        configured = self._require_autograding_configuration(service, assessment_id)
        if configured is None:
            return
        bundle_id, image = configured

        records = list(self.student_records or self.roster_records or ())
        student_ids = []
        labels = {}
        for record in records:
            student_id = str(getattr(record, "student_id", "") or "").strip()
            if not student_id or student_id in labels:
                continue
            student_ids.append(student_id)
            labels[student_id] = str(getattr(record, "student_name", "") or student_id)
        if not student_ids:
            QMessageBox.warning(
                self,
                "No Roster",
                "Load a roster before batch programming autograding.",
            )
            return

        eligible, rejected = service.eligible_active_students(
            assessment_id, student_ids, bundle_id
        )
        if not eligible:
            details = "\n".join(
                "%s: %s" % (student_id, reason)
                for student_id, reason in sorted(rejected.items())
            )
            QMessageBox.information(
                self,
                "No Eligible Programming Submissions",
                "No roster student currently has an active canonical submission that satisfies "
                "this autograder's Python file contract.\n\n%s" % details,
            )
            return
        if rejected:
            preview = "\n".join(
                "%s: %s" % (student_id, rejected[student_id])
                for student_id in list(sorted(rejected))[:8]
            )
            if len(rejected) > 8:
                preview += "\n… and %d more" % (len(rejected) - 8)
            QMessageBox.information(
                self,
                "Batch Eligibility",
                "%d student(s) are eligible. %d roster student(s) will be skipped because they "
                "have no compatible active programming submission.\n\n%s"
                % (len(eligible), len(rejected), preview),
            )

        dialog = AutogradingBatchDialog(
            service,
            assessment_id,
            bundle_id,
            eligible,
            student_labels=labels,
            image=image,
            thread_pool=self.submission_thread_pool,
            parent=self,
        )
        self._autograding_batch_dialog = dialog
        try:
            dialog.exec_()
        finally:
            self._autograding_batch_dialog = None

    def show_autograding_history(self):
        service = self._ensure_autograding_service(allow_prompt=True)
        if service is None:
            return
        assessment_id = self._canonical_assessment_id()
        student_id = self._current_autograding_student_id()
        if not student_id:
            QMessageBox.warning(
                self,
                "No Current Student",
                "Select/load a student before viewing programming-autograding history.",
            )
            return
        AutogradingHistoryDialog(
            service,
            assessment_id,
            student_id,
            parent=self,
        ).exec_()

    def _on_submission_history_activated(self, parsed_submission):
        """Refresh the visible workspace after a history dialog activates an attempt."""
        self.current_submission = parsed_submission
        self._notify_submission_context_changed()
        self.status_bar.show_temporary_message("Active submission attempt changed")

    def load_submissions_folder(self):
        """Load and persist normal LaTeX submissions in a background worker."""
        if not self.rubric_data:
            QMessageBox.warning(self, "No Rubric", "Load the assignment rubric before submissions.")
            return
        if not self._ensure_assessments_dir(allow_prompt=True):
            return

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select LaTeX Submissions Directory",
            self.submissions_dir or "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not directory:
            return

        self.submissions_dir = os.path.abspath(directory)
        self._configure_submission_evidence_root()
        self._start_submission_worker(
            SubmissionOperation.LOAD_NORMAL_SUBMISSIONS,
            parameters={
                "submissions_dir": self.submissions_dir,
                "question_ids": self._submission_question_ids(),
                "compile_pdf": True,
                "persist_evidence": True,
            },
        )

    def _load_persisted_reference_solution(self):
        if not self.assessments_dir:
            self.reference_solution = None
        else:
            try:
                self.reference_solution = load_reference_solution(self.assessments_dir)
            except (OSError, ValueError, json.JSONDecodeError):
                self.reference_solution = None
        workspace = getattr(self, "submission_workspace", None)
        if workspace is not None:
            workspace.set_reference_solution(self.reference_solution)
        return self.reference_solution

    def load_reference_solution_file(self):
        """Load one assignment-level instructor reference solution.

        LaTeX is preferred because it is canonical, math-safe, and directly
        machine-readable. A digital PDF is supported as a fallback.
        """
        if not self.rubric_data:
            QMessageBox.warning(self, "No Rubric", "Load the assignment rubric first.")
            return
        if not self._ensure_assessments_dir(allow_prompt=True):
            return

        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Reference Solution",
            "",
            "Reference Solutions (*.tex *.pdf);;LaTeX Files (*.tex);;PDF Files (*.pdf);;All Files (*)",
        )
        if not source_path:
            return

        if source_path.lower().endswith(".pdf"):
            reply = QMessageBox.question(
                self,
                "Use PDF Reference Solution",
                "LaTeX is recommended because mathematical notation and question boundaries "
                "remain directly machine-readable for future AI-assisted grading. A digital "
                "PDF with selectable text is supported as a fallback.\n\nContinue with this PDF?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

        self._start_submission_worker(
            SubmissionOperation.LOAD_REFERENCE_SOLUTION,
            parameters={
                "source_path": os.path.abspath(source_path),
                "assessments_dir": self.assessments_dir,
                "question_ids": self._submission_question_ids(),
            },
        )

    def _select_pdf_accommodation_student(self):
        """Return a student ID for explicit PDF accommodation ingestion."""
        if self.student_records:
            labels = [record.display_name for record in self.student_records]
            current = self.current_student_index if 0 <= self.current_student_index < len(labels) else 0
            label, accepted = QInputDialog.getItem(
                self,
                "PDF Accommodation",
                "Student",
                labels,
                current,
                False,
            )
            if not accepted:
                return None
            index = labels.index(label)
            return self.student_records[index].student_id

        name = self.student_name_edit.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "No Student",
                "Load a roster or enter the student name before adding a PDF accommodation.",
            )
            return None
        return safe_student_filename(name)

    def add_pdf_accommodation(self):
        """Explicitly ingest a PDF-only accommodation without storing a reason."""
        if not self.rubric_data:
            QMessageBox.warning(self, "No Rubric", "Load the assignment rubric first.")
            return
        student_id = self._select_pdf_accommodation_student()
        if not student_id:
            return
        if not self._ensure_assessments_dir(allow_prompt=True):
            return

        pdf_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Submitted PDF",
            "",
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not pdf_path:
            return

        reply = QMessageBox.question(
            self,
            "Use PDF Accommodation Mode",
            "The original selected PDF will be stored as authoritative evidence. "
            "Any extracted text or handwriting transcription is assistive only.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._configure_submission_evidence_root()
        self._start_submission_worker(
            SubmissionOperation.LOAD_PDF_ACCOMMODATION,
            student_id=student_id,
            parameters={
                "pdf_path": os.path.abspath(pdf_path),
                "question_ids": self._submission_question_ids(),
                "persist_evidence": True,
            },
        )

    def open_submission_source(self, path):
        """Open canonical/original submission evidence with the operating system."""
        target = os.path.abspath(os.path.expanduser(str(path or "")))
        if not target or not os.path.isfile(target):
            QMessageBox.warning(self, "Source Unavailable", "The submission source file is unavailable.")
            return False
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        if not opened:
            QMessageBox.warning(self, "Open Failed", f"Could not open:\n{target}")
        return bool(opened)

    def _submission_for_worker_student(self, student_id):
        try:
            return self.submission_controller.submission_for_student(
                student_id,
                load_persisted=True,
            )
        except (ValueError, OSError):
            return None

    def _pdf_path_for_student(self, student_id):
        parsed = self._submission_for_worker_student(student_id)
        if parsed is None or not getattr(parsed, "accommodation_mode", False):
            return None
        files = getattr(parsed, "files", {})
        path = files.get("pdf") if isinstance(files, dict) else None
        return str(path) if path else None

    def generate_submission_transcription(self, student_id):
        """Generate handwriting transcription cache-first for one accommodation."""
        pdf_path = self._pdf_path_for_student(student_id)
        if not pdf_path:
            self.status_bar.show_temporary_message("No PDF accommodation is available for transcription")
            return
        settings = self.submission_inference_settings
        self._start_submission_worker(
            SubmissionOperation.GENERATE_TRANSCRIPTION,
            student_id=student_id,
            parameters={
                "pdf_path": pdf_path,
                "question_ids": self._submission_question_ids(),
                "persist_evidence": True,
                "base_url": settings.base_url,
                "model": settings.model,
            },
        )

    def refresh_submission_evidence(self, student_id):
        """Refresh the current submission without changing any grading state."""
        parsed = self._submission_for_worker_student(student_id)
        if parsed is None:
            self.status_bar.show_temporary_message("No submission is available to refresh")
            return

        if getattr(parsed, "accommodation_mode", False):
            pdf_path = self._pdf_path_for_student(student_id)
            if not pdf_path:
                self.status_bar.show_temporary_message("Original accommodation PDF is unavailable")
                return
            transcription = getattr(parsed, "transcription_metadata", {})
            transcription = transcription if isinstance(transcription, dict) else {}
            if str(transcription.get("status") or "") == "successful":
                settings = self.submission_inference_settings
                self._start_submission_worker(
                    SubmissionOperation.REFRESH_TRANSCRIPTION,
                    student_id=student_id,
                    parameters={
                        "pdf_path": pdf_path,
                        "question_ids": self._submission_question_ids(),
                        "persist_evidence": True,
                        "base_url": settings.base_url,
                        "model": settings.model,
                    },
                )
            else:
                self._start_submission_worker(
                    SubmissionOperation.LOAD_PDF_ACCOMMODATION,
                    student_id=student_id,
                    parameters={
                        "pdf_path": pdf_path,
                        "question_ids": self._submission_question_ids(),
                        "persist_evidence": True,
                    },
                )
            return

        if not self.submissions_dir:
            self.status_bar.show_temporary_message(
                "The original submissions folder is not known; persisted LaTeX evidence remains available"
            )
            return
        self._start_submission_worker(
            SubmissionOperation.LOAD_NORMAL_SUBMISSIONS,
            parameters={
                "submissions_dir": self.submissions_dir,
                "question_ids": self._submission_question_ids(),
                "compile_pdf": True,
                "persist_evidence": True,
            },
        )

    def show_submission_settings(self):
        """Open endpoint/model settings while keeping connection tests asynchronous."""
        dialog = SubmissionSettingsDialog(self)
        self._submission_settings_dialog = dialog
        dialog.test_connection_requested.connect(self._on_submission_test_connection_requested)
        dialog.settings_saved.connect(self._on_submission_settings_saved)
        try:
            dialog.exec_()
        finally:
            if self._submission_settings_dialog is dialog:
                self._submission_settings_dialog = None

    def _on_submission_settings_saved(self, settings):
        self.submission_inference_settings = settings.normalized()
        self.status_bar.show_temporary_message("Submission & AI settings saved")

    def _on_submission_test_connection_requested(self, settings):
        self._latest_connection_request_id = self._start_submission_worker(
            SubmissionOperation.TEST_OLLAMA,
            parameters=settings.as_dict(),
        )

    def _start_submission_worker(self, operation, *, student_id=None, parameters=None):
        """Create, track, and start a submission worker on the shared thread pool."""
        operation = operation if isinstance(operation, SubmissionOperation) else SubmissionOperation(str(operation))
        request_id = new_request_id()
        target_student = str(student_id or "").strip()
        worker = SubmissionWorker(
            self.submission_controller,
            operation,
            student_id=target_student,
            request_id=request_id,
            parameters=parameters or {},
        )
        worker.signals.started.connect(self._on_submission_worker_started)
        worker.signals.progress.connect(self._on_submission_worker_progress)
        worker.signals.completed.connect(self._on_submission_worker_completed)
        worker.signals.failed.connect(self._on_submission_worker_failed)
        worker.signals.cancelled.connect(self._on_submission_worker_cancelled)
        worker.signals.finished.connect(self._on_submission_worker_finished)

        metadata = {
            "operation": operation.value,
            "student_id": target_student,
            "parameters": dict(parameters or {}),
        }
        self._submission_workers[request_id] = worker
        self.active_submission_requests[request_id] = metadata
        self._submission_request_meta[request_id] = metadata

        if operation == SubmissionOperation.LOAD_NORMAL_SUBMISSIONS:
            self._latest_folder_request_id = request_id
        elif operation == SubmissionOperation.TEST_OLLAMA:
            self._latest_connection_request_id = request_id
        elif operation == SubmissionOperation.LOAD_REFERENCE_SOLUTION:
            self._latest_reference_request_id = request_id
        elif target_student:
            try:
                canonical = self.submission_controller.canonical_student_id(target_student)
            except ValueError:
                canonical = target_student
            self._latest_request_by_student[canonical] = request_id

        self.submission_thread_pool.start(worker)
        return request_id

    def _submission_request_is_latest(self, request_id, student_id, operation):
        operation = str(operation)
        if operation == SubmissionOperation.LOAD_NORMAL_SUBMISSIONS.value:
            return request_id == self._latest_folder_request_id
        if operation == SubmissionOperation.TEST_OLLAMA.value:
            return request_id == self._latest_connection_request_id
        if operation == SubmissionOperation.LOAD_REFERENCE_SOLUTION.value:
            return request_id == self._latest_reference_request_id
        if student_id:
            try:
                canonical = self.submission_controller.canonical_student_id(student_id)
            except ValueError:
                canonical = str(student_id)
            return request_id == self._latest_request_by_student.get(canonical)
        return request_id in self.active_submission_requests

    def _worker_targets_active_student(self, student_id):
        if not student_id:
            return False
        active = self._active_submission_student_id()
        if not active:
            return False
        try:
            return (
                self.submission_controller.canonical_student_id(active)
                == self.submission_controller.canonical_student_id(student_id)
            )
        except ValueError:
            return False

    def _set_submission_workspace_busy(self, student_id, busy, message=""):
        if self._worker_targets_active_student(student_id):
            self.submission_workspace.set_busy(bool(busy), message or "Preparing submission evidence…")

    def _on_submission_worker_started(self, request_id, student_id, operation):
        if not self._submission_request_is_latest(request_id, student_id, operation):
            return
        if operation == SubmissionOperation.LOAD_NORMAL_SUBMISSIONS.value:
            self.status_bar.set_status("Loading LaTeX submissions…")
        elif operation == SubmissionOperation.TEST_OLLAMA.value:
            self.status_bar.show_temporary_message("Testing Ollama connection…")
        elif operation == SubmissionOperation.LOAD_REFERENCE_SOLUTION.value:
            self.status_bar.set_status("Preparing reference solution…")
        else:
            self._set_submission_workspace_busy(student_id, True)

    def _on_submission_worker_progress(self, request_id, student_id, operation, message):
        if not self._submission_request_is_latest(request_id, student_id, operation):
            return
        self.status_bar.show_temporary_message(message, duration=4000)
        if student_id:
            self._set_submission_workspace_busy(student_id, True, message)

    def _register_students_from_loaded_submissions(self, parsed_by_student):
        """Populate a usable student list when no roster/assessment list exists."""
        if self.student_records or not parsed_by_student:
            return
        records = []
        for raw_id in sorted(parsed_by_student):
            try:
                student_id = self.submission_controller.canonical_student_id(raw_id)
            except ValueError:
                continue
            assessment_path = (
                assessment_path_for_student(
                    StudentRecord(student_id=student_id, student_name=student_id),
                    self.assessments_dir,
                )
                if self.assessments_dir else None
            )
            records.append(
                StudentRecord(
                    student_id=student_id,
                    student_name=student_id,
                    assessment_path=assessment_path,
                )
            )
        self.student_records = records
        self.current_student_index = 0 if records else -1
        self._populate_student_combo()

    def _summarize_loaded_submission_mapping(self, parsed_by_student):
        loaded_ids = set()
        for raw_id in parsed_by_student or {}:
            try:
                loaded_ids.add(self.submission_controller.canonical_student_id(raw_id))
            except ValueError:
                pass

        roster_ids = set()
        for record in self.student_records:
            try:
                roster_ids.add(self.submission_controller.canonical_student_id(record.student_id))
            except ValueError:
                pass

        missing = len(roster_ids - loaded_ids) if roster_ids else 0
        unmatched = len(loaded_ids - roster_ids) if roster_ids else 0
        pieces = [f"Loaded {len(loaded_ids)} LaTeX submission(s)"]
        if missing:
            pieces.append(f"{missing} roster student(s) without a matched submission")
        if unmatched:
            pieces.append(f"{unmatched} submission(s) not in the current roster")
        return " · ".join(pieces)

    def _on_submission_worker_completed(self, request_id, student_id, operation, payload):
        if not self._submission_request_is_latest(request_id, student_id, operation):
            return

        if operation == SubmissionOperation.LOAD_NORMAL_SUBMISSIONS.value:
            metadata = self._submission_request_meta.get(request_id, {})
            parameters = metadata.get("parameters", {}) if isinstance(metadata, dict) else {}
            submissions_dir = parameters.get("submissions_dir") if isinstance(parameters, dict) else None
            self.register_loaded_submissions(payload or {}, submissions_dir=submissions_dir)
            self._register_students_from_loaded_submissions(payload or {})
            if self.workflow_mode == QUESTION_CENTRIC and self.student_records:
                self.load_question_mode_student(max(self.current_student_index, 0))
            else:
                self._sync_submission_context(load_persisted=False)
            summary = self._summarize_loaded_submission_mapping(payload or {})
            self.status_bar.set_status(summary)
            self.status_bar.show_temporary_message(summary, duration=5000)
            return

        if operation in {
            SubmissionOperation.LOAD_PDF_ACCOMMODATION.value,
            SubmissionOperation.GENERATE_TRANSCRIPTION.value,
            SubmissionOperation.REFRESH_TRANSCRIPTION.value,
        }:
            self.register_pdf_accommodation(payload)
            self._set_submission_workspace_busy(student_id, False)
            if operation == SubmissionOperation.LOAD_PDF_ACCOMMODATION.value:
                message = "PDF accommodation evidence prepared"
            else:
                transcription = getattr(payload, "transcription_metadata", {})
                transcription = transcription if isinstance(transcription, dict) else {}
                trans_status = str(transcription.get("status") or "")
                if trans_status == "successful":
                    cache = transcription.get("cache", {}) if isinstance(transcription.get("cache"), dict) else {}
                    if operation == SubmissionOperation.GENERATE_TRANSCRIPTION.value:
                        message = (
                            "Assistive transcription loaded from cache"
                            if cache.get("status") == "hit"
                            else "Assistive transcription generated"
                        )
                    else:
                        message = "Assistive transcription refreshed"
                    self.status_bar.set_submission_status("PDF · transcription ready", "ready")
                else:
                    preflight = transcription.get("preflight", {}) if isinstance(transcription.get("preflight"), dict) else {}
                    code = str(preflight.get("error_code") or "transcription_failed")
                    labels = {
                        "model_load_timeout": "model loading timed out",
                        "model_load_failure": "model could not be loaded",
                        "connection_timeout": "Ollama connection timed out",
                        "ollama_unavailable": "Ollama unavailable",
                        "model_not_installed": "model not installed",
                    }
                    message = f"Transcription unavailable · {labels.get(code, code.replace('_', ' '))}"
                    self.status_bar.set_submission_status("PDF ready · AI unavailable", "warning")
            self.status_bar.set_status(message)
            self.status_bar.show_temporary_message(message, duration=6000)
            return

        if operation == SubmissionOperation.LOAD_REFERENCE_SOLUTION.value:
            self.reference_solution = payload
            self.submission_workspace.set_reference_solution(payload)
            source_type = str(getattr(payload, "source_type", "") or "").lower()
            if source_type == "latex":
                message = "Reference solution ready · LaTeX canonical"
            else:
                selectable = bool(
                    getattr(payload, "metadata", {}).get("extraction", {}).get("selectable_text")
                )
                message = (
                    "Reference solution ready · PDF text extracted"
                    if selectable
                    else "Reference PDF loaded · no usable selectable text"
                )
            self.status_bar.set_status(message)
            self.status_bar.show_temporary_message(message, duration=5000)
            return

        if operation == SubmissionOperation.TEST_OLLAMA.value:
            dialog = self._submission_settings_dialog
            if dialog is not None and request_id == self._latest_connection_request_id:
                dialog.set_connection_test_result(payload)

    def _on_submission_worker_failed(
        self,
        request_id,
        student_id,
        operation,
        error_type,
        error_message,
    ):
        if not self._submission_request_is_latest(request_id, student_id, operation):
            return
        message = f"{error_type}: {error_message}" if error_type else str(error_message)
        if operation == SubmissionOperation.TEST_OLLAMA.value:
            dialog = self._submission_settings_dialog
            if dialog is not None:
                dialog.set_connection_test_failure(message)
            return
        if operation == SubmissionOperation.LOAD_REFERENCE_SOLUTION.value:
            self.status_bar.set_status("Reference solution unavailable")
            self.status_bar.show_temporary_message(message, duration=7000)
            return

        self._set_submission_workspace_busy(student_id, False)
        # Submission assistance failures never clear the authoritative/current
        # evidence already on screen and never invalidate manual grading.
        self.status_bar.set_status("Submission assistance unavailable")
        self.status_bar.set_submission_status("Evidence retained", "warning")
        self.status_bar.show_temporary_message(message, duration=7000)

    def _on_submission_worker_cancelled(self, request_id, student_id, operation):
        if self._submission_request_is_latest(request_id, student_id, operation):
            self._set_submission_workspace_busy(student_id, False)
            self.status_bar.show_temporary_message("Submission operation cancelled")

    def _on_submission_worker_finished(self, request_id, student_id, operation):
        if self._submission_request_is_latest(request_id, student_id, operation):
            self._set_submission_workspace_busy(student_id, False)
        self._submission_workers.pop(request_id, None)
        self.active_submission_requests.pop(request_id, None)
        self._submission_request_meta.pop(request_id, None)

    # ------------------------------------------------------------------
    # v2.2 window/splitter preference persistence
    # ------------------------------------------------------------------

    def _save_ui_preferences(self):
        store = self.ui_settings
        store.beginGroup(_UI_SETTINGS_GROUP)
        try:
            store.setValue(_UI_GEOMETRY_KEY, self.saveGeometry())
            store.setValue(_UI_MAXIMIZED_KEY, self.isMaximized())
            store.setValue(
                _UI_SESSION_SPLITTER_KEY, self.session_workspace_splitter.saveState()
            )
            store.setValue(_UI_WORKSPACE_SPLITTER_KEY, self.workspace_splitter.saveState())
            store.setValue(_UI_GRADING_SPLITTER_KEY, self.main_splitter.saveState())
            store.setValue(
                _UI_QUESTION_SUMMARY_COLLAPSED_KEY,
                self.question_summary_card.is_collapsed(),
            )
            store.setValue(
                _UI_ATTEMPTED_QUESTIONS_VISIBLE_KEY,
                self.attempted_questions_button.isChecked(),
            )
        finally:
            store.endGroup()
        store.sync()

    def _restore_ui_preferences(self):
        store = self.ui_settings
        store.beginGroup(_UI_SETTINGS_GROUP)
        try:
            geometry = store.value(_UI_GEOMETRY_KEY)
            maximized = store.value(_UI_MAXIMIZED_KEY, False, type=bool)
            session_state = store.value(_UI_SESSION_SPLITTER_KEY)
            workspace_state = store.value(_UI_WORKSPACE_SPLITTER_KEY)
            grading_state = store.value(_UI_GRADING_SPLITTER_KEY)
            question_summary_collapsed = store.value(
                _UI_QUESTION_SUMMARY_COLLAPSED_KEY, True, type=bool
            )
            attempted_questions_visible = store.value(
                _UI_ATTEMPTED_QUESTIONS_VISIBLE_KEY, False, type=bool
            )
        finally:
            store.endGroup()

        if geometry:
            self.restoreGeometry(geometry)
        if session_state:
            self.session_workspace_splitter.restoreState(session_state)
        if workspace_state:
            self.workspace_splitter.restoreState(workspace_state)
        if grading_state:
            self.main_splitter.restoreState(grading_state)

        # Saved QSplitter state contains orientation. Explicitly enforce the
        # v2 layout after restoration so legacy vertical workspace state can
        # never silently turn the Gradescope split vertical again.
        self.session_workspace_splitter.setOrientation(Qt.Vertical)
        self.workspace_splitter.setOrientation(Qt.Horizontal)
        self.main_splitter.setOrientation(Qt.Vertical)
        self.question_summary_card.set_collapsed(question_summary_collapsed)
        self.attempted_questions_button.setChecked(attempted_questions_visible)
        self._set_questions_attempted_visible(attempted_questions_visible)
        if maximized:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

        # Old saved splitter states may contain zero-sized children from the
        # pre-polish layout.  Normalize after Qt has completed the first layout
        # pass so the submission and grading panes always remain discoverable.
        QTimer.singleShot(0, self._ensure_usable_splitter_sizes)

    def _ensure_usable_splitter_sizes(self):
        self._normalize_splitter_sizes(
            self.session_workspace_splitter, minimums=(120, 320), fallback=(185, 715)
        )
        self._normalize_splitter_sizes(
            self.workspace_splitter, minimums=(460, 420), fallback=(760, 640)
        )
        # The score summary may be collapsed internally, so it only needs a
        # compact minimum allocation at the splitter level.
        self._normalize_splitter_sizes(
            self.main_splitter, minimums=(140, 44), fallback=(520, 90)
        )

    @staticmethod
    def _normalize_splitter_sizes(splitter, *, minimums, fallback):
        sizes = list(splitter.sizes())
        if len(sizes) != 2:
            splitter.setSizes(list(fallback))
            return

        first_min, second_min = (int(minimums[0]), int(minimums[1]))
        total = sum(max(0, int(value)) for value in sizes)
        if total <= 0:
            splitter.setSizes(list(fallback))
            return

        first, second = sizes
        if first >= first_min and second >= second_min:
            return

        target_total = max(total, first_min + second_min)
        first = max(first_min, first)
        second = max(second_min, target_total - first)
        if first + second > target_total:
            first = max(first_min, target_total - second)
        splitter.setSizes([first, second])

    # ------------------------------------------------------------------
    # Resumable grading-session checkpoint
    # ------------------------------------------------------------------

    def _current_assessment_id(self):
        rubric = self.rubric_data or {}
        value = rubric.get("assessment_id") or rubric.get("assignment_id")
        value = str(value or "").strip()
        return value or None

    def _write_grading_session_checkpoint(self):
        if self._restoring_grading_session or self.workflow_mode != QUESTION_CENTRIC:
            return False
        assessment_id = self._current_assessment_id()
        record = self._current_student_record()
        if not assessment_id or not self.assessments_dir or not self.current_question_id or record is None:
            return False
        try:
            save_grading_session_checkpoint(
                self.assessments_dir, assessment_id, self.current_question_id,
                record.student_id, workflow_mode=QUESTION_CENTRIC,
            )
            return True
        except Exception:
            return False

    def _available_grading_session_checkpoint(self):
        assessment_id = self._current_assessment_id()
        if not assessment_id or not self.assessments_dir:
            return None
        try:
            checkpoint = load_grading_session_checkpoint(self.assessments_dir, assessment_id)
        except Exception:
            return None
        if checkpoint is None or checkpoint.workflow_mode != QUESTION_CENTRIC:
            return None
        valid_questions = set(get_question_ids(self.rubric_data or {}, include_unassigned=True))
        valid_students = {record.student_id for record in self.student_records}
        if checkpoint.question_id not in valid_questions or checkpoint.student_id not in valid_students:
            return None
        return checkpoint

    def _restore_grading_session_checkpoint(self, checkpoint):
        if not isinstance(checkpoint, GradingSessionCheckpoint):
            return False
        student_index = next((i for i, record in enumerate(self.student_records)
                              if record.student_id == checkpoint.student_id), -1)
        question_index = self.question_combo.findData(checkpoint.question_id)
        if student_index < 0 or question_index < 0:
            return False
        if self.workflow_mode == QUESTION_CENTRIC and self.question_mode_dirty:
            if not self._confirm_dirty_navigation("resume the saved grading session"):
                return False
        self._restoring_grading_session = True
        try:
            self.workflow_mode = QUESTION_CENTRIC
            self._set_workflow_combo(QUESTION_CENTRIC)
            self.current_question_id = checkpoint.question_id
            self.current_student_index = student_index
            self._changing_question_combo = True
            try:
                self.question_combo.setCurrentIndex(question_index)
            finally:
                self._changing_question_combo = False
            self._populate_student_combo()
            self.apply_current_workflow_view()
            record = self._current_student_record()
            label = record.student_name if record is not None else checkpoint.student_id
            self.status_bar.set_status(f"Resumed grading session: {checkpoint.question_id} — {label}")
            self.status_bar.show_temporary_message("Previous grading position restored")
            return True
        finally:
            self._restoring_grading_session = False

    def _maybe_offer_resume_grading_session(self, allow_without_roster=False):
        if self._restoring_grading_session:
            return False
        if not allow_without_roster and not self.roster_records:
            return False
        checkpoint = self._available_grading_session_checkpoint()
        if checkpoint is None:
            return False
        prompt_key = (checkpoint.assessment_id, checkpoint.saved_at)
        if prompt_key in self._resume_checkpoint_prompted_for:
            return False
        self._resume_checkpoint_prompted_for.add(prompt_key)
        record = next((record for record in self.student_records
                       if record.student_id == checkpoint.student_id), None)
        student_label = record.student_name if record is not None else checkpoint.student_id
        reply = QMessageBox.question(
            self, "Resume Grading Session",
            f"Resume the previous question-by-question grading session at "
            f"{checkpoint.question_id} — {student_label}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        return self._restore_grading_session_checkpoint(checkpoint)

    def resume_grading_session(self):
        checkpoint = self._available_grading_session_checkpoint()
        if checkpoint is None:
            QMessageBox.information(
                self, "Resume Grading Session",
                "No resumable grading session was found for the current rubric, workspace, and roster.",
            )
            return False
        return self._restore_grading_session_checkpoint(checkpoint)

    # ------------------------------------------------------------------
    # Rubric loading / existing grading config
    # ------------------------------------------------------------------

    def load_rubric(self, file_path=None, show_config_on_load=True):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Rubric File",
                "",
                "Rubric Files (*.json *.csv);;JSON Files (*.json);;CSV Files (*.csv);;All Files (*)",
            )
        if not file_path:
            return

        try:
            result = load_rubric_from_file(file_path)
            if isinstance(result, tuple):
                self.rubric_data, is_dirty = result
            else:
                self.rubric_data, is_dirty = result, False
            self.rubric_file_path = file_path

            if is_dirty:
                reply = QMessageBox.question(
                    self,
                    "Rubric Metadata Updated",
                    "This rubric was normalized in memory (for example, missing "
                    "stable criterion IDs and/or question IDs were added).\n"
                    "Would you like to save the updated rubric metadata now?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    from src.core.rubric import save_rubric
                    save_rubric(self.rubric_data, file_path)
                    self.status_bar.show_temporary_message(
                        "Rubric saved with normalized metadata"
                    )

            from src.utils.layout import setup_rubric_ui
            setup_rubric_ui(self)

            # A small/new rubric should not retain the application's generic
            # 5-question/50-point defaults.  Clamp to the actual assignment
            # before opening the configuration dialog.
            question_count = max(1, len(self.question_groups))
            if self.grading_config["questions_to_count"] > question_count:
                self.grading_config["questions_to_count"] = question_count
                if self.grading_config.get("use_fixed_total"):
                    self.grading_config["fixed_total"] = (
                        question_count * self.grading_config["points_per_question"]
                    )
                self.update_config_info()

            self._set_questions_attempted_visible(
                self.attempted_questions_button.isChecked()
            )

            self.export_btn.setEnabled(True)
            self.config_btn.setEnabled(True)
            self.abet_mapping_btn.setEnabled(True)
            rubric_filename = os.path.basename(file_path)
            assessment_id = str(
                (self.rubric_data or {}).get("assessment_id")
                or (self.rubric_data or {}).get("assignment_id")
                or ""
            ).strip()
            self.status_bar.set_status(f"Loaded rubric: {rubric_filename}")
            self.status_label.setText(
                f"{assessment_id} · {rubric_filename}" if assessment_id else rubric_filename
            )
            self.status_label.setToolTip(os.path.abspath(file_path))
            self.analytics_btn.setEnabled(True)

            self.refresh_workflow_questions()
            self.apply_current_workflow_view()
            self._sync_submission_context(load_persisted=True)

            if show_config_on_load:
                self.show_grading_config()
            self._maybe_offer_resume_grading_session()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")

    def on_criterion_points_changed(self):
        update_total_points(self)
        if self._loading_question_student:
            return
        if self.workflow_mode == QUESTION_CENTRIC:
            self.question_mode_dirty = True
        else:
            self.student_mode_dirty = True

    def on_criterion_content_changed(self):
        if self._loading_question_student:
            return
        if self.workflow_mode == QUESTION_CENTRIC:
            self.question_mode_dirty = True
        else:
            self.student_mode_dirty = True

    def on_question_selection_changed(self):
        update_total_points(self)
        if self._loading_question_student:
            return
        if self.workflow_mode == QUESTION_CENTRIC:
            self.question_mode_dirty = True
        else:
            self.student_mode_dirty = True

    def get_selected_questions(self):
        if not hasattr(self, 'question_checkboxes') or not self.question_checkboxes:
            return list(self.question_groups.keys())
        return [q for q, cb in self.question_checkboxes.items() if cb.isChecked()]

    def update_config_info(self):
        if not self.grading_config:
            self.config_info.setText("")
            return

        config = self.grading_config
        total_questions = len(self.question_groups) if self.question_groups else "?"
        if config["grading_mode"] == "best_scores":
            summary = f"Best {config['questions_to_count']} of {total_questions} questions"
        else:
            summary = f"Count {config['questions_to_count']} selected question(s)"

        if config["use_fixed_total"]:
            total = config["fixed_total"]
        else:
            total = config["questions_to_count"] * config["points_per_question"]
        self.config_info.setText(f"{summary}  •  {total} points total")
        self.config_info.setTextFormat(Qt.PlainText)

    def show_grading_config(self):
        from src.ui.dialogs.config import GradingConfigDialog
        if not self.question_groups:
            QMessageBox.warning(self, "Warning", "Please load a rubric first.")
            return

        dialog = GradingConfigDialog(len(self.question_groups), self)
        index = dialog.grading_mode.findData(self.grading_config["grading_mode"])
        if index >= 0:
            dialog.grading_mode.setCurrentIndex(index)
        dialog.questions_to_count.setValue(self.grading_config["questions_to_count"])
        dialog.points_per_question.setValue(self.grading_config["points_per_question"])
        dialog.use_fixed_total.setChecked(self.grading_config["use_fixed_total"])
        dialog.fixed_total.setValue(self.grading_config["fixed_total"])

        if dialog.exec_() == QDialog.Accepted:
            self.grading_config = dialog.get_config()
            self.update_config_info()
            setup_question_selection(self)
            self._set_questions_attempted_visible(
                self.attempted_questions_button.isChecked()
            )
            update_total_points(self)
            if self.workflow_mode == QUESTION_CENTRIC:
                self.question_mode_dirty = True
            else:
                self.student_mode_dirty = True

    # ------------------------------------------------------------------
    # v2.1 workflow mode, question filtering, and student sources
    # ------------------------------------------------------------------

    def refresh_workflow_questions(self):
        """Populate canonical question navigation from the loaded rubric."""
        question_ids = get_question_ids(self.rubric_data or {}, include_unassigned=True)
        previous = self.current_question_id

        self._changing_question_combo = True
        try:
            self.question_combo.clear()
            for qid in question_ids:
                label = "Criteria without question assignment" if qid == UNASSIGNED else qid
                self.question_combo.addItem(label, qid)

            if previous in question_ids:
                index = question_ids.index(previous)
            else:
                index = 0 if question_ids else -1
            if index >= 0:
                self.question_combo.setCurrentIndex(index)
                self.current_question_id = question_ids[index]
            else:
                self.current_question_id = None
        finally:
            self._changing_question_combo = False

        self._update_question_navigation_buttons()

    def on_workflow_mode_changed(self, _index):
        if self._changing_workflow_mode:
            return

        requested = self.workflow_mode_combo.currentData() or STUDENT_CENTRIC
        if requested == self.workflow_mode:
            return

        if requested == QUESTION_CENTRIC and not self.rubric_data:
            QMessageBox.warning(self, "No Rubric", "Load a rubric before using question-by-question grading.")
            self._set_workflow_combo(self.workflow_mode)
            return

        if requested == QUESTION_CENTRIC:
            if self._maybe_offer_resume_grading_session(allow_without_roster=True):
                return

        if self.workflow_mode == QUESTION_CENTRIC and self.question_mode_dirty:
            if not self._confirm_dirty_navigation("switch grading workflows"):
                self._set_workflow_combo(self.workflow_mode)
                return
        elif self.workflow_mode == STUDENT_CENTRIC and self.student_mode_dirty:
            if not self.save_assessment(show_success=False):
                self._set_workflow_combo(self.workflow_mode)
                return

        self.workflow_mode = requested
        self.apply_current_workflow_view()
        if requested == QUESTION_CENTRIC:
            self._write_grading_session_checkpoint()

    def _set_workflow_combo(self, mode):
        self._changing_workflow_mode = True
        try:
            index = self.workflow_mode_combo.findData(mode)
            if index >= 0:
                self.workflow_mode_combo.setCurrentIndex(index)
        finally:
            self._changing_workflow_mode = False

    def apply_current_workflow_view(self):
        question_mode = self.workflow_mode == QUESTION_CENTRIC
        self.question_mode_controls.setVisible(question_mode)
        self.question_mode_actions.setVisible(question_mode)
        self.student_mode_actions.setVisible(not question_mode)
        self.workflow_card.setMinimumHeight(0)
        self.workflow_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        if question_mode:
            if self.current_question_id is None:
                self.refresh_workflow_questions()
            self.submission_controller.set_current_question(self.current_question_id)
            if self.current_question_id:
                apply_workflow_question_filter(self, self.current_question_id)

            if self.student_records:
                if not (0 <= self.current_student_index < len(self.student_records)):
                    self.current_student_index = 0
                self._populate_student_combo()
                self.load_question_mode_student(self.current_student_index)
            elif self.student_name_edit.text().strip():
                self._ensure_manual_student_record()
                self.load_question_mode_student(0)
            else:
                self._populate_student_combo()
                self.update_question_progress_display()
                self._notify_submission_context_changed()
        else:
            self.submission_controller.set_current_question(None)
            show_all_criteria(self)
            if self.student_records and self.rubric_data:
                if not (0 <= self.current_student_index < len(self.student_records)):
                    self.current_student_index = 0
                self._populate_student_combo()
                self.load_student_mode_student(self.current_student_index)
            else:
                self._sync_submission_context(load_persisted=True)

        self._update_student_navigation_visibility()
        self.workflow_card.updateGeometry()
        central_layout = self._written_central_layout()
        if central_layout is not None:
            central_layout.invalidate()
            central_layout.activate()
        QTimer.singleShot(0, self._stabilize_question_mode_layout)

    def _stabilize_question_mode_layout(self):
        """Remeasure the compact workflow card after mode-specific controls change."""
        self.question_mode_controls.adjustSize()
        self.student_navigation_controls.adjustSize()
        self.workflow_card.adjustSize()
        self.workflow_card.setMinimumHeight(self.workflow_card.sizeHint().height())
        self.workflow_card.updateGeometry()

    def load_assessment_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Assessment Directory",
            self.assessments_dir or "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not directory:
            return

        try:
            self.assessments_dir = os.path.abspath(directory)
            self._set_assessment_workspace_path(self.assessments_dir)
            self._configure_submission_evidence_root()
            self._load_persisted_reference_solution()
            assessment_records = load_students_from_assessment_dir(self.assessments_dir)
            if self.roster_records:
                self.student_records = merge_student_records(
                    self.roster_records,
                    assessment_records,
                    self.assessments_dir,
                )
            else:
                self.student_records = assessment_records

            if not self.student_records:
                # An empty assessment directory is a normal first-use state: it
                # is the destination for future assessment JSON/evidence files.
                # Do not interrupt the workflow with a modal dialog.
                self.status_bar.set_status("Assessment workspace ready")
                self.status_bar.show_temporary_message(
                    "Assessment folder selected; load a roster or submissions to begin"
                )

            self.current_student_index = 0 if self.student_records else -1
            self._populate_student_combo()
            if self.workflow_mode == QUESTION_CENTRIC and self.student_records:
                self.load_question_mode_student(self.current_student_index)
            elif self.workflow_mode == STUDENT_CENTRIC and self.student_records and self.rubric_data:
                self.load_student_mode_student(self.current_student_index)
            else:
                if self.student_records:
                    self._sync_student_centric_record_context(load_persisted=True)
                else:
                    self._sync_submission_context(load_persisted=True)
                self.update_question_progress_display()
            self._update_student_navigation_visibility()
            self._maybe_offer_resume_grading_session()
        except Exception as e:
            QMessageBox.critical(self, "Assessment Folder Error", str(e))

    def load_roster(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Roster CSV",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return

        try:
            self.roster_records = load_roster_csv(file_path)
            self.roster_file_path = file_path

            assessment_records = []
            if self.assessments_dir and os.path.isdir(self.assessments_dir):
                assessment_records = load_students_from_assessment_dir(self.assessments_dir)

            self.student_records = merge_student_records(
                self.roster_records,
                assessment_records,
                self.assessments_dir,
            )
            self.current_student_index = 0 if self.student_records else -1
            self._populate_student_combo()

            self.status_bar.show_temporary_message(
                f"Loaded roster with {len(self.student_records)} students"
            )
            if self.workflow_mode == QUESTION_CENTRIC and self.student_records:
                self.load_question_mode_student(self.current_student_index)
            elif self.workflow_mode == STUDENT_CENTRIC and self.student_records and self.rubric_data:
                self.load_student_mode_student(self.current_student_index)
            else:
                if self.student_records:
                    self._sync_student_centric_record_context(load_persisted=True)
                else:
                    self._sync_submission_context(load_persisted=True)
                self.update_question_progress_display()
            self._update_student_navigation_visibility()
            self._maybe_offer_resume_grading_session()
        except Exception as e:
            QMessageBox.critical(self, "Roster Error", f"Failed to load roster: {str(e)}")

    def _ensure_manual_student_record(self):
        if self.student_records:
            return
        name = self.student_name_edit.text().strip()
        if not name:
            return
        student_id = safe_student_filename(name)
        self.student_records = [StudentRecord(student_id=student_id, student_name=name)]
        self.current_student_index = 0
        self._populate_student_combo()

    def _populate_student_combo(self):
        self._changing_student_combo = True
        try:
            self.student_combo.clear()
            for record in self.student_records:
                self.student_combo.addItem(record.display_name, record.student_id)
            if self.student_records:
                index = min(max(self.current_student_index, 0), len(self.student_records) - 1)
                self.current_student_index = index
                self.student_combo.setCurrentIndex(index)
            else:
                self.current_student_index = -1
        finally:
            self._changing_student_combo = False
        self._update_student_navigation_buttons()
        self._update_student_navigation_visibility()

    def _update_student_navigation_visibility(self):
        has_records = bool(self.student_records)
        if hasattr(self, "student_combo"):
            self.student_combo.setVisible(has_records)
        if hasattr(self, "prev_student_btn"):
            self.prev_student_btn.setVisible(has_records)
        if hasattr(self, "next_student_btn"):
            self.next_student_btn.setVisible(has_records)
        if hasattr(self, "student_position_label"):
            self.student_position_label.setVisible(has_records)
        if hasattr(self, "student_name_edit"):
            self.student_name_edit.setVisible(not has_records)
            self.student_name_edit.setReadOnly(False)
        if hasattr(self, "question_mode_actions"):
            self.question_mode_actions.setVisible(self.workflow_mode == QUESTION_CENTRIC)
        if hasattr(self, "student_mode_actions"):
            self.student_mode_actions.setVisible(self.workflow_mode == STUDENT_CENTRIC)
        self._update_student_navigation_buttons()

    def load_student_mode_student(self, index=None):
        """Load the complete saved state/evidence for one roster student."""
        if not self.rubric_data:
            return False
        if index is not None:
            if not (0 <= index < len(self.student_records)):
                return False
            self.current_student_index = index

        record = self._current_student_record()
        if record is None:
            return False
        if self.assessments_dir and not record.assessment_path:
            record.assessment_path = assessment_path_for_student(record, self.assessments_dir)

        try:
            existing = self._read_assessment_file(record.assessment_path)
            if existing is None:
                existing = self._blank_assessment_for_record(record)
                existing.pop("selected_questions", None)
                is_blank = True
            else:
                is_blank = False

            self._apply_assessment_to_widgets(
                existing, blank_defaults_to_all_selected=is_blank
            )
            self.student_name_edit.setText(record.student_name)
            self.current_assessment_path = record.assessment_path
            self.student_mode_dirty = False
            self.submission_controller.set_current_question(None)
            show_all_criteria(self)
            self._sync_submission_context(existing, load_persisted=True)

            self._changing_student_combo = True
            try:
                if self.student_combo.currentIndex() != self.current_student_index:
                    self.student_combo.setCurrentIndex(self.current_student_index)
            finally:
                self._changing_student_combo = False

            self._update_student_navigation_buttons()
            self.status_bar.set_status(f"Student mode: {record.student_name}")
            update_total_points(self)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Load Student Error", f"Failed to load student assessment: {str(e)}")
            return False

    def _current_student_record(self):
        if 0 <= self.current_student_index < len(self.student_records):
            return self.student_records[self.current_student_index]
        return None

    def _ensure_assessments_dir(self, allow_prompt=True):
        if self.assessments_dir and os.path.isdir(self.assessments_dir):
            return True

        record = self._current_student_record()
        if record and record.assessment_path:
            parent = os.path.dirname(os.path.abspath(record.assessment_path))
            if os.path.isdir(parent):
                self.assessments_dir = parent
                self._set_assessment_workspace_path(parent)
                self._configure_submission_evidence_root()
                self._load_persisted_reference_solution()
                return True

        if not allow_prompt:
            return False

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Folder for Student Assessments",
            os.path.dirname(self.roster_file_path) if self.roster_file_path else "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not directory:
            return False

        self.assessments_dir = os.path.abspath(directory)
        self._set_assessment_workspace_path(self.assessments_dir)
        self._configure_submission_evidence_root()
        self._load_persisted_reference_solution()
        for record in self.student_records:
            if not record.assessment_path:
                record.assessment_path = assessment_path_for_student(record, self.assessments_dir)
        return True

    # ------------------------------------------------------------------
    # Question-centric assessment loading/saving
    # ------------------------------------------------------------------

    def _read_assessment_file(self, path):
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("criteria"), list):
            raise ValueError(f"Invalid assessment file: {path}")
        return data

    def _blank_assessment_for_record(self, record):
        return create_blank_assessment_from_rubric(
            self.rubric_data,
            student_name=record.student_name,
            student_id=record.student_id,
            assignment_name=self.assignment_name_edit.text() or (self.rubric_data or {}).get("title", ""),
            rubric_path=self.rubric_file_path,
            grading_config=self.grading_config,
        )

    def _apply_assessment_to_widgets(self, assessment_data, blank_defaults_to_all_selected=False):
        """Load criterion state by stable ID, with title fallback for legacy data."""
        self._loading_question_student = True
        try:
            self.student_name_edit.setText(assessment_data.get("student_name", ""))
            self.assignment_name_edit.setText(
                assessment_data.get("assignment_name", "") or (self.rubric_data or {}).get("title", "")
            )

            if "grading_config" in assessment_data and assessment_data["grading_config"]:
                self.grading_config = assessment_data["grading_config"]
                self.update_config_info()
                setup_question_selection(self)
                self._set_questions_attempted_visible(
                    self.attempted_questions_button.isChecked()
                )

            # Always reset first so a missing criterion cannot retain the prior
            # student's score/comment in memory.
            for widget in self.criterion_widgets:
                widget.reset()

            saved_criteria = [c for c in assessment_data.get("criteria", []) if isinstance(c, dict)]
            by_id = {c.get("id"): c for c in saved_criteria if c.get("id")}
            legacy_by_title = {
                c.get("title", ""): c for c in saved_criteria
                if not c.get("id") and c.get("title")
            }

            unmatched = 0
            for widget in self.criterion_widgets:
                cid = widget.criterion_data.get("id")
                title = widget.criterion_data.get("title", "")
                saved = by_id.get(cid) if cid else None
                if saved is None:
                    saved = legacy_by_title.get(title)
                if saved is not None:
                    widget.set_data(saved)
                else:
                    unmatched += 1

            selected_key_present = "selected_questions" in assessment_data
            selected_questions = list(assessment_data.get("selected_questions") or [])
            if hasattr(self, "question_checkboxes"):
                if blank_defaults_to_all_selected and not selected_key_present:
                    selected_questions = list(self.question_checkboxes.keys())
                for q, checkbox in self.question_checkboxes.items():
                    checkbox.setChecked(q in selected_questions)

            update_total_points(self)
            return unmatched
        finally:
            self._loading_question_student = False

    def load_question_mode_student(self, index=None):
        if not self.rubric_data:
            return False
        if index is not None:
            if not (0 <= index < len(self.student_records)):
                return False
            self.current_student_index = index

        record = self._current_student_record()
        if record is None:
            self._ensure_manual_student_record()
            record = self._current_student_record()
        if record is None:
            return False

        if self.assessments_dir and not record.assessment_path:
            record.assessment_path = assessment_path_for_student(record, self.assessments_dir)

        try:
            existing = self._read_assessment_file(record.assessment_path)
            if existing is None:
                existing = self._blank_assessment_for_record(record)
                # Existing student-centric behavior starts question selection as
                # all attempted; do the same for a new question-mode student.
                existing.pop("selected_questions", None)
                is_blank = True
            else:
                is_blank = False

            self._apply_assessment_to_widgets(
                existing,
                blank_defaults_to_all_selected=is_blank,
            )
            self.student_name_edit.setText(record.student_name)
            self.student_name_edit.setReadOnly(bool(self.student_records))
            self.current_assessment_path = record.assessment_path
            self.question_mode_dirty = False
            self._sync_submission_context(existing, load_persisted=True)

            self._changing_student_combo = True
            try:
                if self.student_combo.currentIndex() != self.current_student_index:
                    self.student_combo.setCurrentIndex(self.current_student_index)
            finally:
                self._changing_student_combo = False

            if self.current_question_id:
                apply_workflow_question_filter(self, self.current_question_id)
            self._update_student_navigation_buttons()
            self.update_question_progress_display()
            self.status_bar.set_status(
                f"Question mode: {self.current_question_id or '—'} — {record.student_name}"
            )
            return True
        except Exception as e:
            QMessageBox.critical(self, "Load Student Error", f"Failed to load student assessment: {str(e)}")
            return False

    def _current_question_widgets(self):
        if not self.current_question_id:
            return []
        return list(self.workflow_question_groups.get(self.current_question_id, []))

    def save_current_question(
        self,
        show_success=False,
        mark_complete=False,
        allow_directory_prompt=True,
    ):
        """Partially save only the visible question and merge it into the full assessment."""
        if self.workflow_mode != QUESTION_CENTRIC:
            return False
        if not self.rubric_data or not self.current_question_id:
            QMessageBox.warning(self, "Question Mode", "Load a rubric and select a question first.")
            return False

        self._ensure_manual_student_record()
        record = self._current_student_record()
        if record is None:
            QMessageBox.warning(
                self,
                "No Student",
                "Load an assessment folder/roster or enter a student name before saving.",
            )
            return False

        if not self._ensure_assessments_dir(allow_prompt=allow_directory_prompt):
            return False

        if not record.assessment_path:
            record.assessment_path = assessment_path_for_student(record, self.assessments_dir)
        target_path = record.assessment_path

        try:
            existing = self._read_assessment_file(target_path)
            if existing is None:
                existing = self._blank_assessment_for_record(record)

            # Full snapshot is used only for derived scoring/metadata. The actual
            # grade merge below contains only the current question's criteria.
            full_snapshot = get_assessment_data(self, validate=False)
            if not full_snapshot:
                return False

            visible_widgets = self._current_question_widgets()
            visible_ids = {
                widget.criterion_data.get("id")
                for widget in visible_widgets
                if widget.criterion_data.get("id")
            }
            visible_titles_without_id = {
                widget.criterion_data.get("title", "")
                for widget in visible_widgets
                if not widget.criterion_data.get("id")
            }

            updated_criteria = []
            for criterion in full_snapshot.get("criteria", []):
                cid = criterion.get("id")
                title = criterion.get("title", "")
                if (cid and cid in visible_ids) or (not cid and title in visible_titles_without_id):
                    updated_criteria.append(criterion)

            merged = merge_partial_criteria_update(existing, updated_criteria)

            # selected/counted flags are derived from assignment-level scoring
            # choices. Refresh only those flags for hidden criteria without
            # replacing their scores/comments/grading status.
            flag_updates = []
            for criterion in full_snapshot.get("criteria", []):
                update = {
                    "id": criterion.get("id", ""),
                    "title": criterion.get("title", ""),
                    "selected": criterion.get("selected", False),
                    "counted": criterion.get("counted", False),
                }
                if criterion.get("question_id"):
                    update["question_id"] = criterion["question_id"]
                flag_updates.append(update)
            merged = merge_partial_criteria_update(merged, flag_updates)

            for key in (
                "student_name", "assignment_name", "selected_questions",
                "counted_questions", "question_summary", "grading_config",
                "total_awarded", "total_possible", "percentage",
                "rubric_path", "abet_meta",
            ):
                if key in full_snapshot:
                    merged[key] = full_snapshot[key]
            merged["student_name"] = record.student_name
            merged["student_id"] = record.student_id

            all_current_graded = bool(visible_widgets) and all(
                bool(getattr(widget, "is_graded", False)) for widget in visible_widgets
            )
            completion_state = True if mark_complete else (False if not all_current_graded else None)
            merged = update_grading_progress_metadata(
                merged,
                mode=QUESTION_CENTRIC,
                question_id=self.current_question_id,
                student_id=record.student_id,
                question_complete=completion_state,
            )
            merged = self._merge_current_submission_into_assessment(
                merged,
                student_id=record.student_id,
            )

            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as fh:
                json.dump(merged, fh, indent=2, ensure_ascii=False)

            self.current_assessment_path = target_path
            record.assessment_path = target_path
            self.question_mode_dirty = False
            self._write_grading_session_checkpoint()
            self.update_question_progress_display()
            self.status_bar.set_status(f"Saved to: {os.path.basename(target_path)}")
            self.status_bar.show_temporary_message(
                f"Saved {self.current_question_id} for {record.student_name}"
            )
            if show_success:
                QMessageBox.information(
                    self,
                    "Saved",
                    f"Saved {self.current_question_id} for {record.student_name}.",
                )
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save current question: {str(e)}")
            return False

    def mark_current_question_complete(self):
        widgets = self._current_question_widgets()
        if not widgets:
            QMessageBox.warning(self, "Question Complete", "The selected question has no criteria.")
            return
        if not all(bool(getattr(widget, "is_graded", False)) for widget in widgets):
            QMessageBox.warning(
                self,
                "Question Incomplete",
                f"All criteria for {self.current_question_id} must be graded before marking it complete.",
            )
            return
        if self.save_current_question(show_success=False, mark_complete=True):
            QMessageBox.information(
                self,
                "Question Complete",
                f"{self.current_question_id} is marked complete for the current student.",
            )

    def save_and_next_student(self):
        if not self.save_current_question(show_success=False):
            return
        self._move_student_after_save(1)

    def save_and_next_student_assessment(self):
        """Save the full student assessment and advance in Student-by-student mode."""
        if self.workflow_mode != STUDENT_CENTRIC:
            return
        if not self.save_assessment(show_success=False):
            return
        self._move_student_after_save(1)

    # ------------------------------------------------------------------
    # Navigation / dirty-state handling
    # ------------------------------------------------------------------

    def _confirm_dirty_navigation(self, action_text):
        if not self.question_mode_dirty:
            return True

        reply = QMessageBox.question(
            self,
            "Unsaved Question Changes",
            f"The current question has unsaved changes. Save them before you {action_text}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Save:
            return self.save_current_question(show_success=False)
        if reply == QMessageBox.Discard:
            return self._discard_current_question_changes()
        return False

    def _discard_current_question_changes(self):
        record = self._current_student_record()
        if record is None:
            return True
        try:
            existing = self._read_assessment_file(record.assessment_path)
            if existing is None:
                existing = self._blank_assessment_for_record(record)
                existing.pop("selected_questions", None)
                is_blank = True
            else:
                is_blank = False
            self._apply_assessment_to_widgets(existing, blank_defaults_to_all_selected=is_blank)
            self.question_mode_dirty = False
            if self.current_question_id:
                apply_workflow_question_filter(self, self.current_question_id)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Discard Error", str(e))
            return False

    def on_student_combo_changed(self, new_index):
        if self._changing_student_combo or not self.student_records:
            return
        if new_index < 0 or new_index == self.current_student_index:
            return

        old_index = self.current_student_index
        if self.workflow_mode == QUESTION_CENTRIC:
            if self.question_mode_dirty and not self.save_current_question(show_success=False):
                self._changing_student_combo = True
                try:
                    self.student_combo.setCurrentIndex(old_index)
                finally:
                    self._changing_student_combo = False
                return
        elif self.student_mode_dirty and not self.save_assessment(show_success=False):
            self._changing_student_combo = True
            try:
                self.student_combo.setCurrentIndex(old_index)
            finally:
                self._changing_student_combo = False
            return

        self.current_student_index = new_index
        if self.workflow_mode == QUESTION_CENTRIC:
            if self.load_question_mode_student(new_index):
                self._write_grading_session_checkpoint()
        else:
            self.load_student_mode_student(new_index)

    def navigate_student(self, delta):
        if not self.student_records:
            return
        target = self.current_student_index + delta
        if target < 0 or target >= len(self.student_records):
            return

        if self.workflow_mode == QUESTION_CENTRIC:
            if self.question_mode_dirty and not self.save_current_question(show_success=False):
                return
        elif self.student_mode_dirty and not self.save_assessment(show_success=False):
            return

        self.current_student_index = target
        if self.workflow_mode == QUESTION_CENTRIC:
            if self.load_question_mode_student(target):
                self._write_grading_session_checkpoint()
        else:
            self.load_student_mode_student(target)

    def _move_student_after_save(self, delta):
        if not self.student_records:
            return
        target = self.current_student_index + delta
        if 0 <= target < len(self.student_records):
            self.current_student_index = target
            if self.workflow_mode == QUESTION_CENTRIC:
                if self.load_question_mode_student(target):
                    self._write_grading_session_checkpoint()
            else:
                self.load_student_mode_student(target)
        else:
            self.status_bar.show_temporary_message("Reached the end of the student list")

    def on_question_combo_changed(self, new_index):
        if self._changing_question_combo or self.workflow_mode != QUESTION_CENTRIC:
            return
        if new_index < 0:
            return
        requested = self.question_combo.itemData(new_index)
        if not requested or requested == self.current_question_id:
            return

        previous = self.current_question_id
        if self.question_mode_dirty and not self._confirm_dirty_navigation("change questions"):
            self._changing_question_combo = True
            try:
                previous_index = self.question_combo.findData(previous)
                if previous_index >= 0:
                    self.question_combo.setCurrentIndex(previous_index)
            finally:
                self._changing_question_combo = False
            return

        self.current_question_id = requested
        self.submission_controller.set_current_question(requested)
        self._notify_submission_context_changed()
        apply_workflow_question_filter(self, requested)
        self._update_question_navigation_buttons()
        self.update_question_progress_display()
        self._write_grading_session_checkpoint()

    def navigate_question(self, delta):
        if self.workflow_mode != QUESTION_CENTRIC or self.question_combo.count() == 0:
            return
        current_index = self.question_combo.findData(self.current_question_id)
        target_index = current_index + delta
        if target_index < 0 or target_index >= self.question_combo.count():
            return

        target_qid = self.question_combo.itemData(target_index)
        if self.question_mode_dirty and not self._confirm_dirty_navigation("change questions"):
            return

        self.current_question_id = target_qid
        self.submission_controller.set_current_question(target_qid)
        self._notify_submission_context_changed()
        self._changing_question_combo = True
        try:
            self.question_combo.setCurrentIndex(target_index)
        finally:
            self._changing_question_combo = False
        apply_workflow_question_filter(self, target_qid)

        if len(self.student_records) > 1 and self.current_student_index > 0:
            reply = QMessageBox.question(
                self,
                "Start New Question",
                f"Start {target_qid} from the first student?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.current_student_index = 0
                self.load_question_mode_student(0)

        self._update_question_navigation_buttons()
        self.update_question_progress_display()
        self._write_grading_session_checkpoint()

    def _update_student_navigation_buttons(self):
        count = len(self.student_records)
        valid = count > 0 and 0 <= self.current_student_index < count
        has_prev = valid and self.current_student_index > 0
        has_next = valid and self.current_student_index < count - 1
        if hasattr(self, "prev_student_btn"):
            self.prev_student_btn.setEnabled(has_prev)
        if hasattr(self, "next_student_btn"):
            self.next_student_btn.setEnabled(has_next)
        if hasattr(self, "save_next_student_btn"):
            self.save_next_student_btn.setEnabled(has_next)
        if hasattr(self, "save_next_assessment_btn"):
            self.save_next_assessment_btn.setEnabled(has_next)
        if hasattr(self, "student_position_label"):
            self.student_position_label.setText(
                f"{self.current_student_index + 1} of {count}" if valid else "No roster"
            )

    def _update_question_navigation_buttons(self):
        count = self.question_combo.count() if hasattr(self, "question_combo") else 0
        index = self.question_combo.findData(self.current_question_id) if count else -1
        self.prev_question_btn.setEnabled(index > 0)
        self.next_question_btn.setEnabled(0 <= index < count - 1)

    def update_question_progress_display(self):
        if self.workflow_mode != QUESTION_CENTRIC or not self.current_question_id:
            return

        if self.student_records:
            student_ids = [record.student_name or record.student_id for record in self.student_records]
            total_students = len(student_ids)
        else:
            name = self.student_name_edit.text().strip()
            student_ids = [safe_student_filename(name)] if name else []
            total_students = len(student_ids)

        if not self.assessments_dir:
            self.question_progress_label.setText(
                f"{self.current_question_id}: 0 / {total_students} graded"
            )
            total_criteria = len((self.rubric_data or {}).get("criteria", [])) * total_students
            self.overall_progress_label.setText(
                f"Overall progress: 0 / {total_criteria} criteria graded"
            )
            return

        progress = compute_question_progress(
            self.assessments_dir,
            self.rubric_data or {},
            self.current_question_id,
            student_ids=student_ids,
        )
        partial_suffix = (
            f" ({progress.partially_graded_students} partial)"
            if progress.partially_graded_students else ""
        )
        self.question_progress_label.setText(
            f"{self.current_question_id}: {progress.graded_students} / "
            f"{progress.total_students} graded{partial_suffix}"
        )

        overall = compute_overall_criteria_progress(
            self.assessments_dir,
            self.rubric_data or {},
            student_ids=student_ids,
        )
        self.overall_progress_label.setText(
            f"Overall progress: {overall.graded_criteria} / "
            f"{overall.total_criteria} criteria graded"
        )

    # ------------------------------------------------------------------
    # Existing analytics / autosave / form behavior
    # ------------------------------------------------------------------

    def show_analytics(self):
        from src.ui.dialogs.analytics import AnalyticsDialog
        analytics_data = collect_assessments(self)
        if analytics_data:
            dialog = AnalyticsDialog(self, analytics_data)
            dialog.exec_()
        else:
            QMessageBox.warning(
                self,
                "No Data Available",
                "No assessment data was found or selected. Please try again.",
            )

    def setup_auto_save(self):
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.auto_save_assessment)
        self.auto_save_timer.start(self.auto_save_interval)

    def auto_save_assessment(self):
        if not self.rubric_data or not self.criterion_widgets:
            return

        assessment_data = get_assessment_data(self, validate=False)
        if not assessment_data:
            return
        assessment_data = self._merge_current_submission_into_assessment(assessment_data)

        student_name = self.student_name_edit.text() or "unnamed_student"
        student_name = ''.join(c if c.isalnum() else '_' for c in student_name)
        timestamp = int(time.time())
        filename = f"autosave_{student_name}_{timestamp}.json"
        file_path = os.path.join(self.auto_save_dir, filename)

        try:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(assessment_data, file, indent=2, ensure_ascii=False)
            current_time = time.strftime("%H:%M:%S")
            self.status_bar.set_auto_save_status(f"Saved at {current_time}")
            self.status_bar.show_temporary_message("Assessment auto-saved")
            self.cleanup_auto_save_files()
        except Exception as e:
            self.status_bar.set_auto_save_status(f"Failed: {str(e)}", is_error=True)

    def cleanup_auto_save_files(self):
        try:
            student_name = self.student_name_edit.text() or "unnamed_student"
            student_name = ''.join(c if c.isalnum() else '_' for c in student_name)
            all_files = []
            for filename in os.listdir(self.auto_save_dir):
                if filename.startswith(f"autosave_{student_name}_") and filename.endswith(".json"):
                    file_path = os.path.join(self.auto_save_dir, filename)
                    all_files.append((file_path, os.path.getmtime(file_path)))
            all_files.sort(key=lambda x: x[1], reverse=True)
            for file_path, _ in all_files[5:]:
                os.remove(file_path)
        except Exception:
            pass

    def clear_form(self):
        if self.workflow_mode == QUESTION_CENTRIC:
            for widget in self._current_question_widgets():
                widget.reset()
            self.question_mode_dirty = True
            update_total_points(self)
            self.status_bar.set_status(f"Cleared {self.current_question_id} for current student")
            self.status_bar.show_temporary_message("Current question cleared")
            return

        self.student_name_edit.clear()
        self.assignment_name_edit.clear()
        for widget in self.criterion_widgets:
            widget.reset()
        if hasattr(self, 'question_checkboxes'):
            for checkbox in self.question_checkboxes.values():
                checkbox.setChecked(True)
        update_total_points(self)
        self.current_assessment_path = None
        self.student_mode_dirty = False
        self.submission_controller.deactivate_student()
        self.current_submission = None
        self._notify_submission_context_changed()
        self.status_bar.set_status("Form cleared")
        self.status_bar.show_temporary_message("Form has been cleared")

    # ------------------------------------------------------------------
    # Save/load assessment: old path preserved; question mode routes partial
    # ------------------------------------------------------------------

    def _build_complete_current_assessment(self):
        """Return a complete current-student snapshot in either workflow mode."""
        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to save.")
            return None
        # Saving is a persistence operation, not final-submission validation.
        # Both workflows must be able to save incomplete in-progress grading.
        assessment_data = get_assessment_data(self, validate=False)
        if not assessment_data:
            return None
        assessment_data = self._merge_current_submission_into_assessment(assessment_data)
        record = self._current_student_record()
        if record is not None:
            assessment_data["student_name"] = record.student_name
            assessment_data["student_id"] = record.student_id
        if self.workflow_mode == QUESTION_CENTRIC and record is not None:
            assessment_data = update_grading_progress_metadata(
                assessment_data, mode=QUESTION_CENTRIC,
                question_id=self.current_question_id, student_id=record.student_id,
                question_complete=None,
            )
        return assessment_data

    def _current_assessment_save_path(self):
        record = self._current_student_record()
        if record is not None:
            if not record.assessment_path and self.assessments_dir:
                record.assessment_path = assessment_path_for_student(record, self.assessments_dir)
            if record.assessment_path:
                return os.path.abspath(record.assessment_path)
        if self.current_assessment_path:
            return os.path.abspath(self.current_assessment_path)
        return None

    def _write_complete_assessment(self, file_path, assessment_data, show_success=True):
        if not file_path:
            return False
        if not str(file_path).lower().endswith('.json'):
            file_path = f"{file_path}.json"
        file_path = os.path.abspath(file_path)
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(assessment_data, file, indent=2, ensure_ascii=False)
            self.current_assessment_path = file_path
            record = self._current_student_record()
            if record is not None:
                record.assessment_path = file_path
            if self.workflow_mode == QUESTION_CENTRIC:
                self.question_mode_dirty = False
                self._write_grading_session_checkpoint()
            else:
                self.student_mode_dirty = False
            self.update_question_progress_display()
            self.status_bar.set_status(f"Saved to: {os.path.basename(file_path)}")
            self.status_bar.show_temporary_message("Assessment saved successfully")
            if show_success:
                QMessageBox.information(self, "Success", "Assessment saved successfully.")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save assessment: {str(e)}")
            return False

    def save_assessment(self, show_success=True):
        """Save the complete current student's assessment in either workflow mode."""
        assessment_data = self._build_complete_current_assessment()
        if assessment_data is None:
            return False
        target_path = self._current_assessment_save_path()
        if not target_path:
            return self.save_assessment_as(assessment_data=assessment_data, show_success=show_success)
        return self._write_complete_assessment(
            target_path, assessment_data, show_success=show_success
        )

    def save_assessment_as(self, assessment_data=None, show_success=True):
        """Save the complete current student's assessment to a chosen path."""
        if assessment_data is None:
            assessment_data = self._build_complete_current_assessment()
        if assessment_data is None:
            return False
        default_path = self._current_assessment_save_path() or ""
        if not default_path:
            student = self.student_name_edit.text()
            assignment = self.assignment_name_edit.text()
            if student and assignment:
                safe_student = ''.join(c if c.isalnum() else '_' for c in student)
                safe_assignment = ''.join(c if c.isalnum() else '_' for c in assignment)
                default_path = f"{safe_assignment}_{safe_student}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Assessment As", default_path,
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return False
        return self._write_complete_assessment(
            file_path, assessment_data, show_success=show_success
        )

    def load_assessment(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Assessment File",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                assessment_data = json.load(file)

            if not is_valid_assessment(assessment_data):
                QMessageBox.warning(
                    self,
                    "Invalid Assessment",
                    "The selected file does not contain a valid assessment.",
                )
                return

            rubric_path = assessment_data.get("rubric_path")
            if rubric_path and (not self.rubric_file_path or self.rubric_file_path != rubric_path):
                if os.path.exists(rubric_path):
                    reply = QMessageBox.question(
                        self,
                        "Load Rubric",
                        "This assessment was created with a different rubric. "
                        "Would you like to load the associated rubric?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if reply == QMessageBox.Yes:
                        self.load_rubric(rubric_path)
                else:
                    QMessageBox.warning(
                        self,
                        "Rubric Not Found",
                        "The original rubric file could not be found. Please load the correct rubric first.",
                    )

            if not self.criterion_widgets:
                QMessageBox.warning(self, "Warning", "Please load a rubric first.")
                return

            unmatched = self._apply_assessment_to_widgets(assessment_data)
            self.current_assessment_path = file_path
            self.student_mode_dirty = False

            # Saved submission metadata is optional and independent of scoring.
            # Configure the normal sibling evidence root, then prefer any exact
            # evidence_dir recorded in the assessment metadata.
            if not self.assessments_dir:
                self.submission_controller.set_assessments_dir(
                    os.path.dirname(os.path.abspath(file_path))
                )
            self._sync_submission_context(assessment_data, load_persisted=True)

            if self.workflow_mode == QUESTION_CENTRIC:
                self.assessments_dir = self.assessments_dir or os.path.dirname(os.path.abspath(file_path))
                self._set_assessment_workspace_path(self.assessments_dir)
                self._configure_submission_evidence_root()
                student_id = str(
                    assessment_data.get("student_id")
                    or os.path.splitext(os.path.basename(file_path))[0]
                )
                student_name = str(assessment_data.get("student_name") or student_id)
                matching = next(
                    (i for i, r in enumerate(self.student_records)
                     if r.student_id == student_id or r.student_name == student_name),
                    None,
                )
                if matching is None:
                    self.student_records.append(
                        StudentRecord(student_id, student_name, os.path.abspath(file_path))
                    )
                    self.current_student_index = len(self.student_records) - 1
                else:
                    self.current_student_index = matching
                    self.student_records[matching].assessment_path = os.path.abspath(file_path)
                self._populate_student_combo()
                self.question_mode_dirty = False
                self._sync_submission_context(assessment_data, load_persisted=True)
                if self.current_question_id:
                    apply_workflow_question_filter(self, self.current_question_id)
                self.update_question_progress_display()

            self.status_bar.set_status(f"Loaded from: {os.path.basename(file_path)}")
            self.status_bar.show_temporary_message("Assessment loaded successfully")
            update_total_points(self)

            if unmatched:
                QMessageBox.warning(
                    self,
                    "Assessment/Rubric Difference",
                    f"{unmatched} rubric criteria had no matching saved criterion and were left blank.",
                )
            else:
                QMessageBox.information(self, "Success", "Assessment loaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load assessment: {str(e)}")

    # ------------------------------------------------------------------
    # Existing export / close / ABET behavior
    # ------------------------------------------------------------------

    def export_to_pdf(self):
        export_to_pdf(self)

    def batch_export_assessments(self):
        batch_export_assessments(self)

    def _finalize_window_close(self):
        if self._workspace_popout_dialog is not None:
            self._reattach_grading_workspace(close_dialog=True)
        self._save_ui_preferences()
        for worker in list(self._submission_workers.values()):
            try:
                worker.cancel()
            except Exception:
                pass
        for worker in list(self._autograding_workers.values()):
            try:
                worker.cancel()
            except Exception:
                pass

    def closeEvent(self, event):
        if self.workflow_mode == QUESTION_CENTRIC and self.question_mode_dirty:
            reply = QMessageBox.question(
                self,
                "Save Before Closing",
                "The current question has unsaved changes. Save before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save and not self.save_current_question(show_success=False):
                event.ignore()
                return
            self._finalize_window_close()
            event.accept()
            return

        if self.workflow_mode == STUDENT_CENTRIC and self.student_mode_dirty:
            reply = QMessageBox.question(
                self,
                "Save Before Closing",
                "The current student's assessment has unsaved changes. Save before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save and not self.save_assessment(show_success=False):
                event.ignore()
                return
            self._finalize_window_close()
            event.accept()
            return

        if self.rubric_data and self.criterion_widgets:
            self.auto_save_assessment()
            if self.current_assessment_path is None:
                reply = QMessageBox.question(
                    self,
                    "Save Before Closing",
                    "There are unsaved changes. Would you like to save before closing?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    self.save_assessment()
                    self._finalize_window_close()
                    event.accept()
                elif reply == QMessageBox.Cancel:
                    event.ignore()
                else:
                    self._finalize_window_close()
                    event.accept()
            else:
                self._finalize_window_close()
                event.accept()
        else:
            self._finalize_window_close()
            event.accept()

    def show_abet_mapping(self):
        if not self.rubric_data:
            QMessageBox.warning(
                self, "No Rubric Loaded",
                "Please load a rubric first before creating ABET mappings.",
            )
            return
        try:
            profile = None
            try:
                from src.core.outcome_profile import load_profile, load_default_profile
                pid = (
                    self.rubric_data.get("profile_id")
                    or self.rubric_data.get("outcome_profile", "")
                )
                profile = load_profile(pid) if pid else load_default_profile()
            except Exception:
                pass

            dialog = ABETMappingDialog(self.rubric_data, self, profile=profile)
            if dialog.exec_() == QDialog.Accepted:
                reply = QMessageBox.question(
                    self, "Save Rubric?",
                    "Mappings have been embedded into the rubric.\n"
                    "Would you like to save the rubric file now?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes and self.rubric_file_path:
                    from src.core.rubric import save_rubric
                    save_rubric(self.rubric_data, self.rubric_file_path)
                    self.status_bar.show_temporary_message(
                        "Rubric saved with embedded mappings"
                    )
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to open ABET mapping dialog:\n{str(e)}"
            )

    def show_abet_report(self):
        try:
            dialog = ABETReportDialog(self, rubric_data=self.rubric_data or {})
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to open ABET report dialog:\n{str(e)}"
            )

    def show_semester_abet_report(self):
        try:
            dialog = SemesterABETReportDialog(self)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to open Semester ABET Report dialog:\n{str(e)}"
            )

    def show_similarity_review(self):
        """Open the v2.3.0 deterministic Submission Similarity Review UI."""
        try:
            rubric = self.rubric_data or {}
            assignment_id = (
                rubric.get("assignment_id")
                or rubric.get("assessment_id")
                or ""
            )
            dialog = SimilarityReviewDialog(
                self,
                assignment_id=str(assignment_id),
                question_ids=self._submission_question_ids(),
                loaded_submissions=self.submission_controller.submissions,
                submissions_dir=(
                    self.submissions_dir
                    or self.submission_controller.submissions_dir
                    or ""
                ),
                assessments_dir=self.assessments_dir or "",
            )
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open Submission Similarity Review:\n{str(e)}",
            )

    def show_master_abet_evidence_export(self):
        """Open the v2.2.1 master evidence export UI using current assignment context."""
        try:
            rubric = self.rubric_data or {}
            assignment_title = ""
            try:
                assignment_title = self.assignment_name_edit.text().strip()
            except Exception:
                assignment_title = ""
            if not assignment_title:
                assignment_title = str(rubric.get("title") or "")

            defaults = {
                "rubric_path": self.rubric_file_path or "",
                "assessments_dir": self.assessments_dir or "",
                "assignment_id": (
                    rubric.get("assignment_id")
                    or rubric.get("assessment_id")
                    or ""
                ),
                "assignment_title": assignment_title,
                "assignment_type": rubric.get("assignment_type") or "",
                "assignment_date": rubric.get("assignment_date") or "",
                "course_code": rubric.get("course_code") or "",
                "course_name": rubric.get("course_name") or "",
                "semester": rubric.get("semester") or "",
                "section": rubric.get("section") or "",
            }
            dialog = MasterEvidenceExportDialog(
                self,
                assignment_defaults=defaults,
            )
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open Master ABET Evidence export dialog:\n{str(e)}",
            )

