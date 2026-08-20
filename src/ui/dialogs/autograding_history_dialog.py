"""Immutable programming-autograding history dialog for v2.3.3."""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt
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

from src.autograding.service import AutogradingService
from src.autograding.storage import AutogradingRunReference
from .autograding_results_dialog import AutogradingResultsDialog


class AutogradingHistoryDialog(QDialog):
    def __init__(self, service: AutogradingService, assessment_id: str, student_id: str, *, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.assessment_id = str(assessment_id or "").strip()
        self.student_id = str(student_id or "").strip()
        if not self.assessment_id or not self.student_id:
            raise ValueError("assessment_id and student_id are required")
        self._references: List[AutogradingRunReference] = []
        self._build_ui()
        self.refresh_history()

    def _build_ui(self) -> None:
        self.setObjectName("autogradingHistoryDialog")
        self.setWindowTitle("Programming Autograding History")
        self.resize(1000, 560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        heading = QLabel("Programming Autograding History", self)
        heading.setProperty("labelType", "heading")
        outer.addWidget(heading)
        context = QLabel("Student: %s    Assessment: %s" % (self.student_id, self.assessment_id), self)
        context.setStyleSheet("color: #667085;")
        outer.addWidget(context)
        note = QLabel(
            "Every rerun is immutable evidence. A newer run never overwrites an earlier result.",
            self,
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        self.table = QTableWidget(0, 8, self)
        self.table.setObjectName("autogradingHistoryTable")
        self.table.setHorizontalHeaderLabels(
            ["Created", "Attempt", "Score", "Status", "Review", "Bundle", "Run ID", "Submission"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _index: self.view_selected())
        header = self.table.horizontalHeader()
        for col in (0, 1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col in (5, 6, 7):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.view_button = QPushButton("View Selected Run", self)
        self.view_button.clicked.connect(self.view_selected)
        footer.addWidget(self.view_button)
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.refresh_history)
        footer.addWidget(self.refresh_button)
        footer.addStretch(1)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

    def refresh_history(self) -> None:
        try:
            self._references = list(self.service.list_history(self.assessment_id, self.student_id))
        except Exception as exc:
            self._references = []
            QMessageBox.critical(self, "Autograding History", str(exc))
        self.table.setRowCount(len(self._references))
        for row, ref in enumerate(self._references):
            self.table.setItem(row, 0, QTableWidgetItem(ref.created_at))
            self.table.setItem(row, 1, QTableWidgetItem("—" if ref.attempt is None else str(ref.attempt)))
            if ref.final_score is None:
                score = "Review" if ref.requires_review else "—"
            else:
                score = "%g / %g" % (ref.final_score, ref.max_score or 0)
            self.table.setItem(row, 2, QTableWidgetItem(score))
            self.table.setItem(row, 3, QTableWidgetItem(ref.status))
            self.table.setItem(row, 4, QTableWidgetItem(ref.review_status))
            self.table.setItem(row, 5, QTableWidgetItem(ref.bundle_id))
            run_item = QTableWidgetItem(ref.run_id)
            run_item.setData(Qt.UserRole, ref.run_id)
            self.table.setItem(row, 6, run_item)
            self.table.setItem(row, 7, QTableWidgetItem(ref.submission_id))
        if self._references:
            self.table.selectRow(len(self._references) - 1)
        self._update_buttons()

    def selected_reference(self) -> Optional[AutogradingRunReference]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._references):
            return self._references[row]
        return None

    def _update_buttons(self) -> None:
        self.view_button.setEnabled(self.selected_reference() is not None)

    def view_selected(self) -> None:
        ref = self.selected_reference()
        if ref is None:
            return
        try:
            stored = self.service.load_run(self.assessment_id, self.student_id, ref.run_id)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to Load Autograding Run", str(exc))
            return
        AutogradingResultsDialog(stored, parent=self).exec_()


__all__ = ["AutogradingHistoryDialog"]
