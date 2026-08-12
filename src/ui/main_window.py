"""
Main window implementation for the Rubric Grading Tool.

v2.1 adds a question-centric manual grading workflow while preserving the
existing student-centric grading/scoring path.  ``workflow_mode`` is separate
from ``grading_config['grading_mode']``: the former controls navigation and
filtering; the latter still controls selected-vs-best-N scoring.
"""

import json
import os
import tempfile
import time

from src.ui.dialogs.abet_dialogs import (
    ABETMappingDialog, ABETReportDialog, SemesterABETReportDialog,
)

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea,
    QLineEdit, QMessageBox, QGroupBox,
    QFrame, QSplitter, QDialog, QComboBox,
)
from PyQt5.QtCore import Qt, QTimer
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

from src.ui.widgets.header import HeaderWidget
from src.ui.widgets.status_bar import StatusBarWidget
from src.ui.widgets.card import CardWidget

from src.utils.layout import (
    apply_workflow_question_filter,
    setup_question_selection,
    show_all_criteria,
)
from src.utils.styles import COLORS
from src.utils.pdf import export_to_pdf, batch_export_assessments

from src.analytics.data_processor import collect_assessments


STUDENT_CENTRIC = "student_centric"
QUESTION_CENTRIC = "question_centric"


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
        self._loading_question_student = False
        self._changing_workflow_mode = False
        self._changing_question_combo = False
        self._changing_student_combo = False

        self.student_name = ""
        self.assignment_name = ""
        self.rubric_file_path = None
        self.current_assessment_path = None
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

        self.setWindowTitle("Rubric Grading Tool")
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)

        self.init_ui()
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
        main_layout.setContentsMargins(16, 16, 16, 16)

        self.header = HeaderWidget()
        main_layout.addWidget(self.header)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet(f"background-color: {COLORS['divider'].name()};")
        main_layout.addWidget(divider)

        # ------------------------- top toolbar -------------------------
        toolbar_container = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(0, 8, 0, 8)

        rubric_group = QWidget()
        rubric_layout = QHBoxLayout(rubric_group)
        rubric_layout.setContentsMargins(0, 0, 0, 0)
        rubric_layout.setSpacing(8)

        self.load_btn = QPushButton("Load Rubric")
        self.load_btn.setIcon(qta.icon('fa5s.folder-open'))
        self.load_btn.clicked.connect(self.load_rubric)
        rubric_layout.addWidget(self.load_btn)
        toolbar_layout.addWidget(rubric_group)
        toolbar_layout.addStretch()

        info_widget = QWidget()
        info_layout = QHBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(16)

        student_container = QWidget()
        student_layout = QVBoxLayout(student_container)
        student_layout.setContentsMargins(0, 0, 0, 0)
        student_layout.setSpacing(4)
        student_label = QLabel("Student")
        student_label.setStyleSheet("color: #757575; font-size: 12px;")
        student_layout.addWidget(student_label)
        self.student_name_edit = QLineEdit()
        self.student_name_edit.setPlaceholderText("Enter student name")
        student_layout.addWidget(self.student_name_edit)
        info_layout.addWidget(student_container)

        assignment_container = QWidget()
        assignment_layout = QVBoxLayout(assignment_container)
        assignment_layout.setContentsMargins(0, 0, 0, 0)
        assignment_layout.setSpacing(4)
        assignment_label = QLabel("Assignment")
        assignment_label.setStyleSheet("color: #757575; font-size: 12px;")
        assignment_layout.addWidget(assignment_label)
        self.assignment_name_edit = QLineEdit()
        self.assignment_name_edit.setPlaceholderText("Enter assignment name")
        assignment_layout.addWidget(self.assignment_name_edit)
        info_layout.addWidget(assignment_container)
        toolbar_layout.addWidget(info_widget)
        toolbar_layout.addStretch()

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.analytics_btn = QPushButton("Analytics")
        self.analytics_btn.setIcon(qta.icon('fa5s.chart-bar'))
        self.analytics_btn.clicked.connect(self.show_analytics)
        actions_layout.addWidget(self.analytics_btn)

        self.abet_mapping_btn = QPushButton("ABET Mapping")
        self.abet_mapping_btn.setIcon(qta.icon('fa5s.clipboard-check'))
        self.abet_mapping_btn.clicked.connect(self.show_abet_mapping)
        self.abet_mapping_btn.setEnabled(False)
        self.abet_mapping_btn.setToolTip("Map rubric criteria to ABET student outcomes")
        actions_layout.addWidget(self.abet_mapping_btn)

        self.abet_report_btn = QPushButton("ABET Report")
        self.abet_report_btn.setIcon(qta.icon('fa5s.file-contract'))
        self.abet_report_btn.clicked.connect(self.show_abet_report)
        self.abet_report_btn.setToolTip("Generate ABET assessment report for one assignment")
        actions_layout.addWidget(self.abet_report_btn)

        self.semester_abet_btn = QPushButton("Semester Report")
        self.semester_abet_btn.setIcon(qta.icon('fa5s.calendar-alt'))
        self.semester_abet_btn.clicked.connect(self.show_semester_abet_report)
        self.semester_abet_btn.setToolTip("Generate semester-level ABET aggregation report")
        actions_layout.addWidget(self.semester_abet_btn)

        self.config_btn = QPushButton("Grading Config")
        self.config_btn.setIcon(qta.icon('fa5s.cog'))
        self.config_btn.clicked.connect(self.show_grading_config)
        self.config_btn.setEnabled(False)
        actions_layout.addWidget(self.config_btn)

        self.export_btn = QPushButton("Export to PDF")
        self.export_btn.setIcon(qta.icon('fa5s.file-export'))
        self.export_btn.clicked.connect(self.export_to_pdf)
        self.export_btn.setEnabled(False)
        actions_layout.addWidget(self.export_btn)

        toolbar_layout.addWidget(actions_widget)
        main_layout.addWidget(toolbar_container)

        self.status_label = QLabel("Please load a rubric to begin")
        self.status_label.setProperty("labelType", "heading")
        main_layout.addWidget(self.status_label)

        # Existing score-selection configuration card.
        self.config_card = CardWidget("Grading Configuration")
        config_layout = self.config_card.get_content_layout()
        self.config_info = QLabel()
        config_layout.addWidget(self.config_info)
        main_layout.addWidget(self.config_card)
        self.update_config_info()

        # -------------------- v2.1 workflow controls --------------------
        self.workflow_card = CardWidget("Manual Grading Workflow")
        workflow_layout = self.workflow_card.get_content_layout()

        workflow_top = QHBoxLayout()
        workflow_top.addWidget(QLabel("Workflow:"))
        self.workflow_mode_combo = QComboBox()
        self.workflow_mode_combo.addItem("Student-by-student", STUDENT_CENTRIC)
        self.workflow_mode_combo.addItem("Question-by-question", QUESTION_CENTRIC)
        workflow_top.addWidget(self.workflow_mode_combo)
        workflow_top.addStretch()
        workflow_layout.addLayout(workflow_top)

        self.question_mode_controls = QWidget()
        question_mode_layout = QVBoxLayout(self.question_mode_controls)
        question_mode_layout.setContentsMargins(0, 8, 0, 0)
        question_mode_layout.setSpacing(8)

        source_row = QHBoxLayout()
        self.load_assessment_folder_btn = QPushButton("Assessment Folder")
        self.load_assessment_folder_btn.setIcon(qta.icon('fa5s.folder'))
        self.load_assessment_folder_btn.clicked.connect(self.load_assessment_folder)
        source_row.addWidget(self.load_assessment_folder_btn)

        self.load_roster_btn = QPushButton("Load Roster CSV")
        self.load_roster_btn.setIcon(qta.icon('fa5s.users'))
        self.load_roster_btn.clicked.connect(self.load_roster)
        source_row.addWidget(self.load_roster_btn)

        self.assessment_folder_label = QLabel("No assessment folder selected")
        self.assessment_folder_label.setStyleSheet("color: #757575; font-size: 12px;")
        source_row.addWidget(self.assessment_folder_label)
        source_row.addStretch()
        question_mode_layout.addLayout(source_row)

        navigation_row = QHBoxLayout()
        navigation_row.addWidget(QLabel("Question:"))
        self.question_combo = QComboBox()
        self.question_combo.setMinimumWidth(100)
        navigation_row.addWidget(self.question_combo)

        self.prev_question_btn = QPushButton("Previous Question")
        self.prev_question_btn.clicked.connect(lambda: self.navigate_question(-1))
        navigation_row.addWidget(self.prev_question_btn)
        self.next_question_btn = QPushButton("Next Question")
        self.next_question_btn.clicked.connect(lambda: self.navigate_question(1))
        navigation_row.addWidget(self.next_question_btn)

        navigation_row.addSpacing(20)
        navigation_row.addWidget(QLabel("Student:"))
        self.student_combo = QComboBox()
        self.student_combo.setMinimumWidth(220)
        navigation_row.addWidget(self.student_combo)

        self.prev_student_btn = QPushButton("Previous Student")
        self.prev_student_btn.clicked.connect(lambda: self.navigate_student(-1))
        navigation_row.addWidget(self.prev_student_btn)
        self.next_student_btn = QPushButton("Next Student")
        self.next_student_btn.clicked.connect(lambda: self.navigate_student(1))
        navigation_row.addWidget(self.next_student_btn)
        navigation_row.addStretch()
        question_mode_layout.addLayout(navigation_row)

        progress_row = QHBoxLayout()
        self.question_progress_label = QLabel("Question progress: —")
        self.question_progress_label.setStyleSheet("font-weight: bold;")
        progress_row.addWidget(self.question_progress_label)
        progress_row.addSpacing(24)
        self.overall_progress_label = QLabel("Overall progress: —")
        progress_row.addWidget(self.overall_progress_label)
        progress_row.addStretch()
        question_mode_layout.addLayout(progress_row)

        question_actions = QHBoxLayout()
        question_actions.addStretch()
        self.save_question_btn = QPushButton("Save")
        self.save_question_btn.setIcon(qta.icon('fa5s.save'))
        self.save_question_btn.clicked.connect(
            lambda: self.save_current_question(show_success=True)
        )
        question_actions.addWidget(self.save_question_btn)

        self.save_next_student_btn = QPushButton("Save and Next Student")
        self.save_next_student_btn.clicked.connect(self.save_and_next_student)
        question_actions.addWidget(self.save_next_student_btn)

        self.mark_question_complete_btn = QPushButton("Mark Question Complete")
        self.mark_question_complete_btn.clicked.connect(self.mark_current_question_complete)
        question_actions.addWidget(self.mark_question_complete_btn)
        question_mode_layout.addLayout(question_actions)

        self.question_mode_controls.setVisible(False)
        workflow_layout.addWidget(self.question_mode_controls)
        main_layout.addWidget(self.workflow_card)

        self.workflow_mode_combo.currentIndexChanged.connect(self.on_workflow_mode_changed)
        self.question_combo.currentIndexChanged.connect(self.on_question_combo_changed)
        self.student_combo.currentIndexChanged.connect(self.on_student_combo_changed)

        # Existing selected/attempted-question controls remain available in both
        # workflows because question-centric navigation must not alter scoring.
        self.question_selection_group = QGroupBox("Questions Attempted by Student")
        self.question_selection_group.setStyleSheet("""
            QGroupBox {
                background-color: white;
                border-radius: 4px;
                margin-top: 16px;
            }
        """)
        self.question_selection_layout = QHBoxLayout()
        self.question_selection_group.setLayout(self.question_selection_layout)
        self.question_selection_group.setVisible(False)
        main_layout.addWidget(self.question_selection_group)

        # ------------------------- grading area -------------------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget#scrollContent {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #BDBDBD;
            }
        """)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("scrollContent")
        self.criteria_layout = QVBoxLayout(self.scroll_content)
        self.criteria_layout.setContentsMargins(16, 16, 16, 16)
        self.scroll_area.setWidget(self.scroll_content)

        self.question_summary_card = CardWidget("Question Scores Summary")
        self.question_summary_layout = self.question_summary_card.get_content_layout()

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(self.scroll_area)
        self.summary_container = QWidget()
        summary_layout = QVBoxLayout(self.summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.question_summary_card)
        self.main_splitter.addWidget(self.summary_container)
        self.main_splitter.setSizes([600, 200])
        main_layout.addWidget(self.main_splitter)

        # ------------------------- bottom controls -------------------------
        bottom_layout = QHBoxLayout()
        self.total_label = QLabel("Total: 0 / 0 points")
        self.total_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        bottom_layout.addWidget(self.total_label)
        bottom_layout.addStretch()

        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)

        batch_export_btn = QPushButton("Batch Export")
        batch_export_btn.setIcon(qta.icon('fa5s.file-export'))
        batch_export_btn.setToolTip("Export multiple assessments to a directory")
        batch_export_btn.clicked.connect(self.batch_export_assessments)
        button_layout.addWidget(batch_export_btn)

        clear_btn = QPushButton("Clear Form")
        clear_btn.setIcon(qta.icon('fa5s.eraser'))
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #757575;
                border: 1px solid #BDBDBD;
                padding-left: 10px;
            }
            QPushButton:hover { background-color: #F5F5F5; }
        """)
        clear_btn.clicked.connect(self.clear_form)
        button_layout.addWidget(clear_btn)

        self.save_assessment_btn = QPushButton("Save Assessment")
        self.save_assessment_btn.setIcon(qta.icon('fa5s.save'))
        self.save_assessment_btn.setToolTip("Save assessment to a file")
        self.save_assessment_btn.clicked.connect(self.save_assessment)
        button_layout.addWidget(self.save_assessment_btn)

        load_assessment_btn = QPushButton("Load Assessment")
        load_assessment_btn.setIcon(qta.icon('fa5s.file-upload'))
        load_assessment_btn.clicked.connect(self.load_assessment)
        button_layout.addWidget(load_assessment_btn)

        bottom_layout.addWidget(button_container)
        main_layout.addLayout(bottom_layout)

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

            self.export_btn.setEnabled(True)
            self.config_btn.setEnabled(True)
            self.abet_mapping_btn.setEnabled(True)
            self.status_bar.set_status(f"Loaded rubric: {os.path.basename(file_path)}")
            self.status_label.setText(f"Loaded rubric: {os.path.basename(file_path)}")
            self.analytics_btn.setEnabled(True)

            self.refresh_workflow_questions()
            self.apply_current_workflow_view()

            if show_config_on_load:
                self.show_grading_config()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load rubric: {str(e)}")

    def on_criterion_points_changed(self):
        update_total_points(self)
        if self.workflow_mode == QUESTION_CENTRIC and not self._loading_question_student:
            self.question_mode_dirty = True

    def on_criterion_content_changed(self):
        if self.workflow_mode == QUESTION_CENTRIC and not self._loading_question_student:
            self.question_mode_dirty = True

    def on_question_selection_changed(self):
        update_total_points(self)
        if self.workflow_mode == QUESTION_CENTRIC and not self._loading_question_student:
            self.question_mode_dirty = True

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
            info = (
                f"Grading Mode: Using best {config['questions_to_count']} of "
                f"{total_questions} questions for final score"
            )
        else:
            info = (
                f"Grading Mode: Counting only {config['questions_to_count']} selected questions"
            )

        if config["use_fixed_total"]:
            info += f"<br>Total possible: {config['fixed_total']} points"
        else:
            total = config['questions_to_count'] * config['points_per_question']
            info += (
                f"<br>{config['points_per_question']} points per question "
                f"(Total: {total} points)"
            )

        self.config_info.setText(info)
        self.config_info.setTextFormat(Qt.RichText)

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
            update_total_points(self)
            if self.workflow_mode == QUESTION_CENTRIC:
                self.question_mode_dirty = True

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

        if self.workflow_mode == QUESTION_CENTRIC and self.question_mode_dirty:
            if not self._confirm_dirty_navigation("switch grading workflows"):
                self._set_workflow_combo(self.workflow_mode)
                return

        self.workflow_mode = requested
        self.apply_current_workflow_view()

    def _set_workflow_combo(self, mode):
        self._changing_workflow_mode = True
        try:
            index = self.workflow_mode_combo.findData(mode)
            if index >= 0:
                self.workflow_mode_combo.setCurrentIndex(index)
        finally:
            self._changing_workflow_mode = False

    def apply_current_workflow_view(self):
        if self.workflow_mode == QUESTION_CENTRIC:
            self.question_mode_controls.setVisible(True)
            self.student_name_edit.setReadOnly(bool(self.student_records))
            if self.current_question_id is None:
                self.refresh_workflow_questions()
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
        else:
            self.question_mode_controls.setVisible(False)
            self.student_name_edit.setReadOnly(False)
            show_all_criteria(self)

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
            self.assessment_folder_label.setText(self.assessments_dir)
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
                QMessageBox.information(
                    self,
                    "No Existing Assessments",
                    "No student assessment JSON files were found. You can load a roster CSV "
                    "to create the student list for this folder.",
                )

            self.current_student_index = 0 if self.student_records else -1
            self._populate_student_combo()
            if self.workflow_mode == QUESTION_CENTRIC and self.student_records:
                self.load_question_mode_student(self.current_student_index)
            else:
                self.update_question_progress_display()
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
            else:
                self.update_question_progress_display()
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
                self.assessment_folder_label.setText(parent)
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
        self.assessment_folder_label.setText(self.assessments_dir)
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

            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as fh:
                json.dump(merged, fh, indent=2, ensure_ascii=False)

            self.current_assessment_path = target_path
            record.assessment_path = target_path
            self.question_mode_dirty = False
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
        if self._changing_student_combo or self.workflow_mode != QUESTION_CENTRIC:
            return
        if new_index < 0 or new_index == self.current_student_index:
            return

        old_index = self.current_student_index
        if self.question_mode_dirty and not self.save_current_question(show_success=False):
            self._changing_student_combo = True
            try:
                self.student_combo.setCurrentIndex(old_index)
            finally:
                self._changing_student_combo = False
            return

        self.current_student_index = new_index
        self.load_question_mode_student(new_index)

    def navigate_student(self, delta):
        if self.workflow_mode != QUESTION_CENTRIC or not self.student_records:
            return
        target = self.current_student_index + delta
        if target < 0 or target >= len(self.student_records):
            return

        if self.question_mode_dirty and not self.save_current_question(show_success=False):
            return
        self.current_student_index = target
        self.load_question_mode_student(target)

    def _move_student_after_save(self, delta):
        if not self.student_records:
            return
        target = self.current_student_index + delta
        if 0 <= target < len(self.student_records):
            self.current_student_index = target
            self.load_question_mode_student(target)
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
        apply_workflow_question_filter(self, requested)
        self._update_question_navigation_buttons()
        self.update_question_progress_display()

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

    def _update_student_navigation_buttons(self):
        count = len(self.student_records)
        self.prev_student_btn.setEnabled(count > 0 and self.current_student_index > 0)
        self.next_student_btn.setEnabled(
            count > 0 and 0 <= self.current_student_index < count - 1
        )
        self.save_next_student_btn.setEnabled(count > 0)

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
        self.status_bar.set_status("Form cleared")
        self.status_bar.show_temporary_message("Form has been cleared")

    # ------------------------------------------------------------------
    # Save/load assessment: old path preserved; question mode routes partial
    # ------------------------------------------------------------------

    def save_assessment(self):
        if self.workflow_mode == QUESTION_CENTRIC:
            self.save_current_question(show_success=True)
            return

        if not self.criterion_widgets:
            QMessageBox.warning(self, "Warning", "No rubric loaded to save.")
            return

        assessment_data = get_assessment_data(self)
        if not assessment_data:
            return

        default_path = ""
        if self.current_assessment_path:
            default_path = self.current_assessment_path
        else:
            student = self.student_name_edit.text()
            assignment = self.assignment_name_edit.text()
            if student and assignment:
                safe_student = ''.join(c if c.isalnum() else '_' for c in student)
                safe_assignment = ''.join(c if c.isalnum() else '_' for c in assignment)
                default_path = f"{safe_assignment}_{safe_student}.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Assessment",
            default_path,
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith('.json'):
            file_path += '.json'

        try:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(assessment_data, file, indent=2, ensure_ascii=False)
            self.current_assessment_path = file_path
            self.status_bar.set_status(f"Saved to: {os.path.basename(file_path)}")
            self.status_bar.show_temporary_message("Assessment saved successfully")
            QMessageBox.information(self, "Success", "Assessment saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save assessment: {str(e)}")

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

            if self.workflow_mode == QUESTION_CENTRIC:
                self.assessments_dir = self.assessments_dir or os.path.dirname(os.path.abspath(file_path))
                self.assessment_folder_label.setText(self.assessments_dir)
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
                    event.accept()
                elif reply == QMessageBox.Cancel:
                    event.ignore()
                else:
                    event.accept()
            else:
                event.accept()
        else:
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
