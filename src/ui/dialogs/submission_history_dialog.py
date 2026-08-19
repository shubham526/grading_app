"""Canonical submission-attempt history dialog for v2.3.2 Commit 7."""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.submissions import Submission
from src.ui.submission_controller import SubmissionController


class SubmissionHistoryDialog(QDialog):
    """View canonical attempts and make one historical attempt active."""

    submission_activated = pyqtSignal(object)

    def __init__(
        self,
        controller: SubmissionController,
        student_id: str,
        assessment_id: str,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(controller, SubmissionController):
            raise TypeError("controller must be SubmissionController")
        self.controller = controller
        self.student_id = self.controller.canonical_student_id(student_id)
        self.assessment_id = str(assessment_id or "").strip()
        if not self.assessment_id:
            raise ValueError("assessment_id is required")
        self._history: List[Submission] = []
        self._build_ui()
        self.refresh_history()

    def _build_ui(self) -> None:
        self.setObjectName("submissionHistoryDialog")
        self.setWindowTitle("Submission History")
        self.setModal(True)
        self.resize(980, 520)
        self.setMinimumSize(760, 420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        title = QLabel("Submission History", self)
        title.setProperty("labelType", "heading")
        outer.addWidget(title)

        self.context_label = QLabel(
            f"Student: {self.student_id}    Assessment: {self.assessment_id}",
            self,
        )
        self.context_label.setStyleSheet("color: #667085;")
        outer.addWidget(self.context_label)

        note = QLabel(
            "Canonical originals are immutable. Making an older attempt active changes only "
            "the active-attempt pointer; no historical files are deleted or overwritten.",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #667085;")
        outer.addWidget(note)

        self.table = QTableWidget(0, 7, self)
        self.table.setObjectName("submissionHistoryTable")
        self.table.setHorizontalHeaderLabels(
            ["Active", "Attempt", "Source", "Submitted", "Imported", "Artifacts", "SHA-256"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        header = self.table.horizontalHeader()
        for column in (0, 1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.make_active_button = QPushButton("Make Selected Active", self)
        self.make_active_button.setObjectName("makeSubmissionAttemptActiveButton")
        self.make_active_button.setProperty("buttonRole", "primary")
        self.make_active_button.clicked.connect(self.make_selected_active)
        self.make_active_button.setEnabled(False)
        footer.addWidget(self.make_active_button)
        footer.addStretch(1)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        outer.addLayout(footer)

    def refresh_history(self) -> List[Submission]:
        try:
            self._history = self.controller.submission_history_for_student(
                self.student_id,
                assessment_id=self.assessment_id,
            )
        except Exception as exc:
            self._history = []
            QMessageBox.warning(self, "Submission History", str(exc))

        self.table.setRowCount(len(self._history))
        for row, submission in enumerate(self._history):
            active_item = QTableWidgetItem("Yes" if submission.is_active_attempt else "")
            active_item.setData(Qt.UserRole, submission.submission_id)
            self.table.setItem(row, 0, active_item)
            self.table.setItem(
                row,
                1,
                QTableWidgetItem("—" if submission.attempt is None else str(submission.attempt)),
            )
            self.table.setItem(row, 2, QTableWidgetItem(submission.source_system))
            self.table.setItem(row, 3, QTableWidgetItem(submission.submitted_at or "—"))
            self.table.setItem(row, 4, QTableWidgetItem(submission.imported_at or "—"))

            artifacts = ", ".join(
                f"{item.original_filename} [{item.artifact_type}]"
                for item in submission.artifacts
            ) or "—"
            artifact_item = QTableWidgetItem(artifacts)
            artifact_item.setToolTip("\n".join(
                f"{item.artifact_id}: {item.original_filename}"
                for item in submission.artifacts
            ))
            self.table.setItem(row, 5, artifact_item)

            hashes = ", ".join(item.sha256[:12] + "…" for item in submission.artifacts) or "—"
            hash_item = QTableWidgetItem(hashes)
            hash_item.setToolTip("\n".join(
                f"{item.original_filename}: {item.sha256}"
                for item in submission.artifacts
            ))
            self.table.setItem(row, 6, hash_item)

        if self._history:
            active_row = next(
                (index for index, item in enumerate(self._history) if item.is_active_attempt),
                0,
            )
            self.table.selectRow(active_row)
        self._update_buttons()
        return list(self._history)

    def selected_submission(self) -> Optional[Submission]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._history):
            return self._history[row]
        return None

    def _update_buttons(self) -> None:
        selected = self.selected_submission()
        self.make_active_button.setEnabled(
            selected is not None and not selected.is_active_attempt
        )

    def make_selected_active(self) -> None:
        selected = self.selected_submission()
        if selected is None or selected.is_active_attempt:
            return

        answer = QMessageBox.question(
            self,
            "Change Active Attempt?",
            f"Make attempt {selected.attempt or '—'} active for {self.student_id}?\n\n"
            "The existing active attempt will remain in history.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.setEnabled(False)
        try:
            parsed = self.controller.activate_submission(
                self.student_id,
                selected.submission_id,
                assessment_id=self.assessment_id,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Unable to Activate Submission",
                str(exc),
            )
            return
        finally:
            self.setEnabled(True)

        self.refresh_history()
        self.submission_activated.emit(parsed)


__all__ = ["SubmissionHistoryDialog"]
