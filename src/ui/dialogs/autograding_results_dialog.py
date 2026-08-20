"""Instructor results view for one immutable v2.3.3 autograding run."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from src.autograding.reporting import build_instructor_run_report
from src.autograding.storage import StoredAutogradingRun


class AutogradingResultsDialog(QDialog):
    def __init__(self, stored_run: StoredAutogradingRun, *, parent=None) -> None:
        super().__init__(parent)
        if not isinstance(stored_run, StoredAutogradingRun):
            raise TypeError("stored_run must be StoredAutogradingRun")
        self.stored_run = stored_run
        self.report = build_instructor_run_report(stored_run)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        self.setObjectName("autogradingResultsDialog")
        self.setWindowTitle("Programming Autograding Results")
        self.resize(1050, 720)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        self.title_label = QLabel("Programming Autograding Results", self)
        self.title_label.setProperty("labelType", "heading")
        outer.addWidget(self.title_label)
        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        outer.addWidget(self.summary_label)
        self.provenance_label = QLabel(self)
        self.provenance_label.setWordWrap(True)
        self.provenance_label.setStyleSheet("color: #667085;")
        outer.addWidget(self.provenance_label)

        self.table = QTableWidget(0, 7, self)
        self.table.setObjectName("autogradingResultsTable")
        self.table.setHorizontalHeaderLabels(
            ["Test", "Visibility", "Status", "Points", "Runtime", "Message", "Test ID"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        header = self.table.horizontalHeader()
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        self.detail = QTextEdit(self)
        self.detail.setObjectName("autogradingTestDetail")
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(150)
        outer.addWidget(self.detail)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

    def _populate(self) -> None:
        run = self.stored_run.run
        summary = run.score_summary
        if summary is None:
            score_text = "Score: unavailable"
        elif summary.final_score is None:
            score_text = "Score: requires review / %s" % ("%g" % summary.max_score)
        else:
            score_text = "Score: %g / %g" % (summary.final_score, summary.max_score)
        review = " — REVIEW REQUIRED: %s" % (run.review_reason or "instructor review required") if run.requires_review else ""
        self.summary_label.setText(
            "%s    Status: %s    Attempt: %s%s"
            % (score_text, run.status, run.attempt or "—", review)
        )
        env = self.stored_run.pytest_result.backend_record.environment
        self.provenance_label.setText(
            "Student: %s · Run: %s · Bundle: %s · Runtime: %s · Image digest: %s"
            % (
                run.student_id,
                run.run_id,
                run.provenance.bundle_id,
                env.environment_id,
                env.container_image_digest or "—",
            )
        )

        tests = list(run.test_results)
        self.table.setRowCount(len(tests))
        for row, item in enumerate(tests):
            name = item.display_name or item.test_id
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(item.visibility))
            self.table.setItem(row, 2, QTableWidgetItem(item.status))
            points = "—"
            if item.points_possible is not None:
                awarded = "?" if item.points_awarded is None else "%g" % item.points_awarded
                points = "%s / %g" % (awarded, item.points_possible)
            self.table.setItem(row, 3, QTableWidgetItem(points))
            runtime = "—" if item.duration_ms is None else "%d ms" % item.duration_ms
            self.table.setItem(row, 4, QTableWidgetItem(runtime))
            self.table.setItem(row, 5, QTableWidgetItem(item.message or ""))
            id_item = QTableWidgetItem(item.test_id)
            id_item.setData(Qt.UserRole, item.test_id)
            self.table.setItem(row, 6, id_item)
        if tests:
            self.table.selectRow(0)
        else:
            self.detail.setPlainText("No structured test results were stored.")

    def _show_selected_detail(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.detail.clear()
            return
        row = rows[0].row()
        tests = self.stored_run.run.test_results
        if not (0 <= row < len(tests)):
            self.detail.clear()
            return
        item = tests[row]
        lines = [
            "Test ID: %s" % item.test_id,
            "Visibility: %s" % item.visibility,
            "Status: %s" % item.status,
        ]
        if item.message:
            lines.extend(["", "Message:", item.message])
        if item.stdout:
            lines.extend(["", "Captured stdout:", item.stdout])
        if item.stderr:
            lines.extend(["", "Captured stderr:", item.stderr])
        if item.traceback:
            lines.extend(["", "Traceback:", item.traceback])
        self.detail.setPlainText("\n".join(lines))


__all__ = ["AutogradingResultsDialog"]
