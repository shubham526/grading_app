"""Dedicated programming-grading dashboard for v2.3.4.1 Commit 3.

The workspace owns presentation and user intent only.  MainWindow continues to
own shared assessment/roster state plus the v2.3.3 autograding service, worker,
and dialogs.  This boundary deliberately does not import Docker, persistence,
submission repositories, or scoring code.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ProgrammingGradingWorkspace(QWidget):
    """Roster-centric programming grading workspace.

    The widget receives plain row/detail dictionaries from MainWindow and emits
    semantic requests back to the application shell.  It never executes student
    code or mutates grading persistence directly.
    """

    configure_autograder_requested = pyqtSignal()
    import_submissions_requested = pyqtSignal()
    check_runtime_requested = pyqtSignal()
    grade_selected_requested = pyqtSignal()
    grade_all_requested = pyqtSignal()
    run_history_requested = pyqtSignal()
    view_results_requested = pyqtSignal()
    grade_again_requested = pyqtSignal()
    student_selected = pyqtSignal(str)

    _ROW_STUDENT_ID_ROLE = Qt.UserRole

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("programmingGradingWorkspace")
        self._updating_table = False
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel("Programming Grading", self)
        self.title_label.setObjectName("programmingWorkspaceTitle")
        self.title_label.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #111827;"
        )
        self.assessment_label = QLabel("No assessment loaded", self)
        self.assessment_label.setObjectName("programmingAssessmentLabel")
        self.assessment_label.setStyleSheet("font-size: 13px; color: #667085;")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.assessment_label)
        header.addLayout(title_box)
        header.addStretch(1)

        self.context_label = QLabel("Shared course state", self)
        self.context_label.setObjectName("programmingSharedStateLabel")
        self.context_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.context_label.setStyleSheet("font-size: 12px; color: #667085;")
        header.addWidget(self.context_label)
        root.addLayout(header)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.configure_button = self._action_button("Configure Autograder")
        self.import_button = self._action_button("Import Submissions")
        self.runtime_button = self._action_button("Check Runtime")
        self.grade_selected_button = self._action_button("Grade Selected")
        self.grade_all_button = self._action_button("Grade All")
        self.history_button = self._action_button("Run History")

        for button in (
            self.configure_button,
            self.import_button,
            self.runtime_button,
            self.grade_selected_button,
            self.grade_all_button,
            self.history_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.configure_button.clicked.connect(
            lambda _checked=False: self.configure_autograder_requested.emit()
        )
        self.import_button.clicked.connect(
            lambda _checked=False: self.import_submissions_requested.emit()
        )
        self.runtime_button.clicked.connect(
            lambda _checked=False: self.check_runtime_requested.emit()
        )
        self.grade_selected_button.clicked.connect(
            lambda _checked=False: self.grade_selected_requested.emit()
        )
        self.grade_all_button.clicked.connect(
            lambda _checked=False: self.grade_all_requested.emit()
        )
        self.history_button.clicked.connect(
            lambda _checked=False: self.run_history_requested.emit()
        )

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.bundle_status_label = self._status_label("Autograder: not configured")
        self.runtime_status_label = self._status_label("Runtime: not checked")
        status_row.addWidget(self.bundle_status_label)
        status_row.addWidget(self.runtime_status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setObjectName("programmingDashboardSplitter")
        splitter.setChildrenCollapsible(False)

        roster_panel = self._build_roster_panel()
        result_panel = self._build_result_panel()
        splitter.addWidget(roster_panel)
        splitter.addWidget(result_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([850, 520])
        root.addWidget(splitter, 1)

        self.dashboard_splitter = splitter
        self._update_action_state()

    def _action_button(self, text):
        button = QPushButton(text, self)
        button.setMinimumHeight(36)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return button

    def _status_label(self, text):
        label = QLabel(text, self)
        label.setFrameShape(QFrame.StyledPanel)
        label.setContentsMargins(8, 5, 8, 5)
        label.setStyleSheet("color: #475467; background: #F9FAFB;")
        return label

    def _build_roster_panel(self):
        panel = QFrame(self)
        panel.setObjectName("programmingRosterPanel")
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel("Students", panel)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.roster_summary_label = QLabel("No roster loaded", panel)
        self.roster_summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.roster_summary_label.setStyleSheet("color: #667085;")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.roster_summary_label)
        layout.addLayout(heading)

        table = QTableWidget(0, 5, panel)
        table.setObjectName("programmingStudentTable")
        table.setHorizontalHeaderLabels(
            ["Student", "Attempt", "Status", "Score", "Last Run"]
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.setShowGrid(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        table.currentCellChanged.connect(self._on_current_cell_changed)
        layout.addWidget(table, 1)

        self.student_table = table
        return panel

    def _build_result_panel(self):
        panel = QFrame(self)
        panel.setObjectName("programmingLatestResultPanel")
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title = QLabel("Latest Result", panel)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        self.selected_student_label = QLabel("Selected: —", panel)
        self.selected_student_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.selected_student_label)

        self.result_status_label = QLabel("Select a student to view autograding history.", panel)
        self.result_status_label.setWordWrap(True)
        self.result_status_label.setStyleSheet("color: #667085;")
        layout.addWidget(self.result_status_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.public_tests_value = self._add_metric(grid, 0, "Public tests")
        self.hidden_tests_value = self._add_metric(grid, 1, "Hidden tests")
        self.total_score_value = self._add_metric(grid, 2, "Total")
        self.attempt_value = self._add_metric(grid, 3, "Attempt")
        self.last_run_value = self._add_metric(grid, 4, "Last run")
        layout.addLayout(grid)

        self.test_summary_label = QLabel("—", panel)
        self.test_summary_label.setWordWrap(True)
        self.test_summary_label.setStyleSheet("color: #475467;")
        layout.addWidget(self.test_summary_label)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.view_results_button = QPushButton("View Results", panel)
        self.grade_again_button = QPushButton("Grade Again", panel)
        self.view_history_button = QPushButton("View History", panel)
        buttons.addWidget(self.view_results_button)
        buttons.addWidget(self.grade_again_button)
        buttons.addWidget(self.view_history_button)
        layout.addLayout(buttons)

        self.view_results_button.clicked.connect(
            lambda _checked=False: self.view_results_requested.emit()
        )
        self.grade_again_button.clicked.connect(
            lambda _checked=False: self.grade_again_requested.emit()
        )
        self.view_history_button.clicked.connect(
            lambda _checked=False: self.run_history_requested.emit()
        )

        return panel

    def _add_metric(self, grid, row, name):
        label = QLabel(name, self)
        label.setStyleSheet("color: #667085;")
        value = QLabel("—", self)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setStyleSheet("font-weight: 600;")
        grid.addWidget(label, row, 0)
        grid.addWidget(value, row, 1)
        return value

    def set_context(
        self,
        *,
        assessment_name=None,
        assessment_id=None,
        bundle_id=None,
        runtime_image=None,
    ):
        display_name = str(assessment_name or assessment_id or "").strip()
        if display_name:
            if assessment_id and str(assessment_id).strip() != display_name:
                text = "%s — %s" % (display_name, str(assessment_id).strip())
            else:
                text = display_name
            self.assessment_label.setText(text)
        else:
            self.assessment_label.setText("No assessment loaded")

        if bundle_id:
            self.bundle_status_label.setText("Autograder: %s" % str(bundle_id))
        else:
            self.bundle_status_label.setText("Autograder: not configured")

        if runtime_image:
            self.runtime_status_label.setToolTip(str(runtime_image))
        else:
            self.runtime_status_label.setToolTip("")

    def set_runtime_status(self, text, available=None):
        message = str(text or "Runtime: not checked")
        self.runtime_status_label.setText(message)
        if available is True:
            self.runtime_status_label.setStyleSheet(
                "color: #027A48; background: #ECFDF3;"
            )
        elif available is False:
            self.runtime_status_label.setStyleSheet(
                "color: #B42318; background: #FEF3F2;"
            )
        else:
            self.runtime_status_label.setStyleSheet(
                "color: #475467; background: #F9FAFB;"
            )

    def set_rows(self, rows, selected_student_id=None):
        rows = list(rows or ())
        preserve = str(selected_student_id or self.selected_student_id() or "").strip()
        self._updating_table = True
        try:
            self.student_table.setRowCount(len(rows))
            selected_row = -1
            for row_index, row in enumerate(rows):
                student_id = str(row.get("student_id") or "").strip()
                student_name = str(row.get("student_name") or student_id or "—")
                values = (
                    student_name,
                    str(row.get("attempt") or "—"),
                    str(row.get("status") or "Not graded"),
                    str(row.get("score") or "—"),
                    str(row.get("last_run") or "—"),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(self._ROW_STUDENT_ID_ROLE, student_id)
                        if student_id and student_id != student_name:
                            item.setToolTip(student_id)
                    self.student_table.setItem(row_index, column, item)
                if preserve and student_id == preserve:
                    selected_row = row_index

            if rows:
                if selected_row < 0:
                    selected_row = 0
                self.student_table.setCurrentCell(selected_row, 0)
                self.student_table.selectRow(selected_row)
            else:
                self.student_table.clearSelection()
        finally:
            self._updating_table = False

        if rows:
            self.roster_summary_label.setText("%d student(s)" % len(rows))
        else:
            self.roster_summary_label.setText("No roster loaded")
        self._update_action_state()

    def selected_student_id(self):
        row = self.student_table.currentRow()
        if row < 0:
            return None
        item = self.student_table.item(row, 0)
        if item is None:
            return None
        value = item.data(self._ROW_STUDENT_ID_ROLE)
        return str(value or "").strip() or None

    def selected_student_name(self):
        row = self.student_table.currentRow()
        if row < 0:
            return None
        item = self.student_table.item(row, 0)
        return None if item is None else str(item.text() or "").strip() or None

    def select_student(self, student_id):
        target = str(student_id or "").strip()
        if not target:
            return False
        for row in range(self.student_table.rowCount()):
            item = self.student_table.item(row, 0)
            if item is not None and str(item.data(self._ROW_STUDENT_ID_ROLE) or "").strip() == target:
                self.student_table.setCurrentCell(row, 0)
                self.student_table.selectRow(row)
                return True
        return False

    def set_latest_result(self, detail=None):
        detail = dict(detail or {})
        student_name = str(detail.get("student_name") or self.selected_student_name() or "—")
        self.selected_student_label.setText("Selected: %s" % student_name)

        has_run = bool(detail.get("has_run"))
        has_submission = bool(detail.get("has_submission"))
        if not has_run:
            if has_submission:
                self.result_status_label.setText("Active submission is ready but has not been graded yet.")
            elif student_name != "—":
                self.result_status_label.setText("No active programming submission for this student.")
            else:
                self.result_status_label.setText("Select a student to view autograding history.")
            self.public_tests_value.setText("—")
            self.hidden_tests_value.setText("—")
            self.total_score_value.setText("—")
            self.attempt_value.setText(str(detail.get("attempt") or "—"))
            self.last_run_value.setText("—")
            self.test_summary_label.setText("—")
        else:
            self.result_status_label.setText(str(detail.get("status") or "Completed"))
            self.public_tests_value.setText(str(detail.get("public_tests") or "—"))
            self.hidden_tests_value.setText(str(detail.get("hidden_tests") or "—"))
            self.total_score_value.setText(str(detail.get("score") or "—"))
            self.attempt_value.setText(str(detail.get("attempt") or "—"))
            self.last_run_value.setText(str(detail.get("last_run") or "—"))
            self.test_summary_label.setText(str(detail.get("test_summary") or "—"))

        self.view_results_button.setEnabled(has_run and not self._busy)
        self.view_history_button.setEnabled(has_run and not self._busy)
        self.grade_again_button.setEnabled(has_submission and not self._busy)
        self._update_action_state()

    def set_busy(self, busy):
        self._busy = bool(busy)
        self._update_action_state()

    def _update_action_state(self):
        selected = bool(self.selected_student_id())
        enabled = not self._busy
        self.configure_button.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.runtime_button.setEnabled(enabled)
        self.grade_all_button.setEnabled(enabled)
        self.grade_selected_button.setEnabled(enabled and selected)
        self.history_button.setEnabled(enabled and selected)

        if self._busy:
            self.view_results_button.setEnabled(False)
            self.grade_again_button.setEnabled(False)
            self.view_history_button.setEnabled(False)

    def _on_current_cell_changed(self, current_row, _current_column, _previous_row, _previous_column):
        if self._updating_table or current_row < 0:
            return
        student_id = self.selected_student_id()
        self._update_action_state()
        if student_id:
            self.student_selected.emit(student_id)


__all__ = ["ProgrammingGradingWorkspace"]
