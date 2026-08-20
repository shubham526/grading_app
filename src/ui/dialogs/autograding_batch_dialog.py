"""Batch programming-autograding progress dialog for v2.3.3 Commit 9."""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional

from PyQt5.QtCore import QThreadPool, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.autograding.service import (
    GRADE_STATUS_CANCELLED,
    GRADE_STATUS_COMPLETED,
    GRADE_STATUS_ERROR,
    GRADE_STATUS_PENDING,
    GRADE_STATUS_REVIEW,
    GRADE_STATUS_RUNNING,
    AutogradingBatchResult,
    AutogradingService,
)
from src.ui.workers.autograding_worker import AutogradingOperation, AutogradingWorker
from .autograding_results_dialog import AutogradingResultsDialog


class AutogradingBatchDialog(QDialog):
    batch_completed = pyqtSignal(object)

    def __init__(
        self,
        service: AutogradingService,
        assessment_id: str,
        bundle_id: str,
        student_ids: Iterable[str],
        *,
        student_labels: Optional[Mapping[str, str]] = None,
        image: Optional[str] = None,
        thread_pool: Optional[QThreadPool] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.assessment_id = str(assessment_id or "").strip()
        self.bundle_id = str(bundle_id or "").strip()
        self.student_ids = [str(item).strip() for item in student_ids if str(item).strip()]
        self.student_labels = dict(student_labels or {})
        self.image = image
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self.worker = None
        self.result: Optional[AutogradingBatchResult] = None
        self._result_by_student = {}
        self._row_by_student: Dict[str, int] = {}
        self._build_ui()
        self._populate_students()

    def _build_ui(self) -> None:
        self.setObjectName("autogradingBatchDialog")
        self.setWindowTitle("Programming Autograding — Batch")
        self.resize(920, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        heading = QLabel("Grade All Active Programming Submissions", self)
        heading.setProperty("labelType", "heading")
        outer.addWidget(heading)
        self.context = QLabel(
            "Assessment: %s · Bundle: %s · %d student(s)"
            % (self.assessment_id, self.bundle_id, len(self.student_ids)),
            self,
        )
        self.context.setStyleSheet("color: #667085;")
        outer.addWidget(self.context)
        note = QLabel(
            "Cancel is cooperative: the current Docker run is allowed to finish/timeout and clean up; "
            "remaining students are then marked Cancelled.",
            self,
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, max(1, len(self.student_ids)))
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.table = QTableWidget(0, 5, self)
        self.table.setObjectName("autogradingBatchTable")
        self.table.setHorizontalHeaderLabels(["Student", "Student ID", "Status", "Score", "Message"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.start_button = QPushButton("Start Batch Grading", self)
        self.start_button.setProperty("buttonRole", "primary")
        self.start_button.clicked.connect(self.start_batch)
        footer.addWidget(self.start_button)
        self.cancel_button = QPushButton("Cancel After Current Student", self)
        self.cancel_button.clicked.connect(self.cancel_batch)
        self.cancel_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        self.view_button = QPushButton("View Selected Result", self)
        self.view_button.clicked.connect(self.view_selected)
        self.view_button.setEnabled(False)
        footer.addWidget(self.view_button)
        footer.addStretch(1)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        outer.addLayout(footer)
        self.table.itemSelectionChanged.connect(self._update_view_button)

    def _populate_students(self) -> None:
        self.table.setRowCount(len(self.student_ids))
        for row, student_id in enumerate(self.student_ids):
            self._row_by_student[student_id] = row
            self.table.setItem(row, 0, QTableWidgetItem(self.student_labels.get(student_id, student_id)))
            self.table.setItem(row, 1, QTableWidgetItem(student_id))
            self.table.setItem(row, 2, QTableWidgetItem(GRADE_STATUS_PENDING))
            self.table.setItem(row, 3, QTableWidgetItem("—"))
            self.table.setItem(row, 4, QTableWidgetItem(""))

    def start_batch(self) -> None:
        if self.worker is not None:
            return
        if not self.student_ids:
            QMessageBox.information(self, "Batch Autograding", "No eligible active programming submissions were found.")
            return
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.close_button.setEnabled(False)
        worker = AutogradingWorker(
            self.service,
            AutogradingOperation.GRADE_BATCH,
            parameters={
                "assessment_id": self.assessment_id,
                "student_ids": list(self.student_ids),
                "bundle_id": self.bundle_id,
                "image": self.image,
                "metadata": {"ui_operation": "batch"},
            },
        )
        self.worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.finished.connect(self._on_finished)
        self.thread_pool.start(worker)

    def cancel_batch(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)

    def _on_progress(self, _request_id, index, total, student_id, status) -> None:
        self.progress.setMaximum(max(1, int(total)))
        if status != GRADE_STATUS_RUNNING:
            self.progress.setValue(min(int(index), int(total)))
        row = self._row_by_student.get(str(student_id))
        if row is not None:
            self.table.setItem(row, 2, QTableWidgetItem(str(status)))

    def _on_completed(self, _request_id, _operation, payload) -> None:
        if not isinstance(payload, AutogradingBatchResult):
            return
        self.result = payload
        for item in payload.results:
            row = self._row_by_student.get(item.student_id)
            if row is None:
                continue
            self.table.setItem(row, 2, QTableWidgetItem(item.status))
            if item.grade_result is not None:
                self._result_by_student[item.student_id] = item.grade_result
                if item.grade_result.final_score is None:
                    score = "Review"
                else:
                    score = "%g / %g" % (item.grade_result.final_score, item.grade_result.max_score)
                message = item.grade_result.scoring_result.score_summary.review_reason or ""
            else:
                score = "—"
                message = item.error_message or ("Cancelled" if item.status == GRADE_STATUS_CANCELLED else "")
            self.table.setItem(row, 3, QTableWidgetItem(score))
            self.table.setItem(row, 4, QTableWidgetItem(message))
        self.progress.setValue(self.progress.maximum())
        self.batch_completed.emit(payload)
        self._update_view_button()

    def _on_failed(self, _request_id, _operation, error_type, error_message) -> None:
        QMessageBox.critical(self, "Batch Autograding Failed", "%s: %s" % (error_type, error_message))

    def _on_finished(self, _request_id, _operation) -> None:
        self.worker = None
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)
        if self.result is None:
            self.start_button.setEnabled(True)

    def _selected_student_id(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 1)
        return None if item is None else item.text().strip() or None

    def _update_view_button(self) -> None:
        sid = self._selected_student_id()
        self.view_button.setEnabled(bool(sid and sid in self._result_by_student))

    def view_selected(self) -> None:
        sid = self._selected_student_id()
        result = self._result_by_student.get(sid or "")
        if result is None:
            return
        AutogradingResultsDialog(result.stored_run, parent=self).exec_()

    def reject(self) -> None:
        if self.worker is not None:
            QMessageBox.information(
                self,
                "Batch Autograding Running",
                "Cancel the batch first. The current Docker run must finish/timeout and clean up before this dialog can close.",
            )
            return
        super().reject()


__all__ = ["AutogradingBatchDialog"]
