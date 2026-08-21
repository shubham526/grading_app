"""Instructor-facing diagnostics and recovery actions for LaTeX projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


ACTION_NONE = "none"
ACTION_RETRY = "retry"
ACTION_RESELECT_ROOT = "reselect_root"


class LatexProjectDiagnosticsDialog(QDialog):
    """Show structured compilation/integrity details and safe recovery actions."""

    def __init__(
        self,
        diagnostic: Mapping[str, Any],
        *,
        student_id: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.diagnostic = dict(diagnostic or {})
        self.student_id = str(student_id or "").strip() or None
        self.selected_action = ACTION_NONE
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("LaTeX Project Diagnostics")
        self.setModal(True)
        self.resize(720, 520)

        outer = QVBoxLayout(self)
        title = QLabel("LaTeX project needs attention", self)
        title.setProperty("labelType", "heading")
        outer.addWidget(title)

        if self.student_id:
            student = QLabel("Student: %s" % self.student_id, self)
            student.setStyleSheet("color: #667085;")
            outer.addWidget(student)

        form = QFormLayout()
        status = str(self.diagnostic.get("status") or "unknown")
        root = str(self.diagnostic.get("root_relative_path") or "Not resolved")
        compiler = str(self.diagnostic.get("compiler") or "Not available")
        code = str(self.diagnostic.get("error_code") or "Not available")
        form.addRow("Status:", QLabel(status, self))
        form.addRow("Root:", QLabel(root, self))
        form.addRow("Compiler:", QLabel(compiler, self))
        form.addRow("Reason code:", QLabel(code, self))
        outer.addLayout(form)

        message = str(self.diagnostic.get("error_message") or "No additional details were reported.")
        details = QTextEdit(self)
        details.setReadOnly(True)
        details.setPlainText(message)
        details.setMinimumHeight(120)
        outer.addWidget(details)

        warnings = [str(v) for v in (self.diagnostic.get("warnings") or [])]
        if warnings:
            warning_label = QLabel("Warnings: " + "; ".join(warnings), self)
            warning_label.setWordWrap(True)
            warning_label.setStyleSheet("color: #9a6700;")
            outer.addWidget(warning_label)

        action_row = QHBoxLayout()
        self.log_button = QPushButton("View Compilation Log", self)
        self.log_button.clicked.connect(self._view_log)
        self.log_button.setEnabled(bool(self.diagnostic.get("compilation_log_path")))
        action_row.addWidget(self.log_button)

        self.project_button = QPushButton("Open Source Project", self)
        self.project_button.clicked.connect(self._open_project)
        self.project_button.setEnabled(bool(self.diagnostic.get("source_project_dir")))
        action_row.addWidget(self.project_button)
        action_row.addStretch(1)
        outer.addLayout(action_row)

        recovery_row = QHBoxLayout()
        self.retry_button = QPushButton("Retry Compilation", self)
        self.retry_button.setProperty("buttonRole", "primary")
        self.retry_button.clicked.connect(self._retry)
        self.retry_button.setEnabled(bool(self.diagnostic.get("recoverable", False)))
        recovery_row.addWidget(self.retry_button)

        candidates = [str(v) for v in (self.diagnostic.get("candidate_paths") or [])]
        self.reselect_button = QPushButton("Choose Different Root", self)
        self.reselect_button.clicked.connect(self._reselect)
        self.reselect_button.setEnabled(
            bool(self.diagnostic.get("recoverable", False)) and len(candidates) > 1
        )
        recovery_row.addWidget(self.reselect_button)
        recovery_row.addStretch(1)
        outer.addLayout(recovery_row)

        if not bool(self.diagnostic.get("recoverable", False)):
            blocked = QLabel(
                "Recovery is blocked because the canonical project did not pass integrity verification.",
                self,
            )
            blocked.setWordWrap(True)
            blocked.setStyleSheet("color: #b42318;")
            outer.addWidget(blocked)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _view_log(self) -> None:
        value = str(self.diagnostic.get("compilation_log_path") or "").strip()
        if not value:
            return
        path = Path(value)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "Compilation Log", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("LaTeX Compilation Log")
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        editor = QTextEdit(dialog)
        editor.setReadOnly(True)
        editor.setPlainText(text)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()

    def _open_project(self) -> None:
        value = str(self.diagnostic.get("source_project_dir") or "").strip()
        if not value:
            return
        path = Path(value)
        if not path.exists():
            QMessageBox.warning(self, "Source Project", "The extracted project directory is missing.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _retry(self) -> None:
        self.selected_action = ACTION_RETRY
        self.accept()

    def _reselect(self) -> None:
        self.selected_action = ACTION_RESELECT_ROOT
        self.accept()


__all__ = [
    "ACTION_NONE",
    "ACTION_RESELECT_ROOT",
    "ACTION_RETRY",
    "LatexProjectDiagnosticsDialog",
]
