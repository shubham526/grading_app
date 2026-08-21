"""Instructor root-selection dialog for ambiguous LaTeX project ZIPs."""

from __future__ import annotations

from typing import Optional, Sequence

from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)


class LatexProjectRootSelectionDialog(QDialog):
    """Require an explicit root choice when project discovery is ambiguous."""

    def __init__(
        self,
        candidate_paths: Sequence[str],
        *,
        archive_name: str = "",
        student_label: str = "",
        preferred_hints: Optional[Sequence[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        paths = tuple(
            str(value).strip()
            for value in candidate_paths
            if str(value).strip()
        )
        if len(paths) < 2:
            raise ValueError("root selection requires at least two candidate paths")
        if len(set(paths)) != len(paths):
            raise ValueError("candidate_paths must be unique")

        self._candidate_paths = paths
        self._selected_root: Optional[str] = None
        self._buttons = QButtonGroup(self)
        self._buttons.setExclusive(True)

        self.setObjectName("latexProjectRootSelectionDialog")
        self.setWindowTitle("Select LaTeX Project Root")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Multiple LaTeX entry points found", self)
        title.setProperty("labelType", "heading")
        layout.addWidget(title)

        context = []
        if archive_name:
            context.append("Archive: %s" % archive_name)
        if student_label:
            context.append("Student: %s" % student_label)
        if context:
            context_label = QLabel("\n".join(context), self)
            context_label.setStyleSheet("color: #667085;")
            layout.addWidget(context_label)

        explanation = QLabel(
            "The project contains more than one complete LaTeX document. "
            "Choose the file that represents the student's submitted solution. "
            "The app will not guess.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        hints = {
            str(value).strip().casefold()
            for value in (preferred_hints or ())
            if str(value).strip()
        }
        for index, path in enumerate(paths):
            label = path
            if path.casefold() in hints:
                label += "  (preferred-name hint)"
            button = QRadioButton(label, self)
            button.setObjectName("latexProjectRootOption_%d" % index)
            button.setProperty("rootRelativePath", path)
            self._buttons.addButton(button, index)
            layout.addWidget(button)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Use Selected File")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    @property
    def selected_root(self) -> Optional[str]:
        return self._selected_root

    def accept(self) -> None:
        button = self._buttons.checkedButton()
        if button is None:
            QMessageBox.information(
                self,
                "Select a Root File",
                "Choose one LaTeX entry point before continuing.",
            )
            return
        selected = str(button.property("rootRelativePath") or "").strip()
        if selected not in self._candidate_paths:
            QMessageBox.critical(
                self,
                "Invalid Root Selection",
                "The selected root is no longer available in this project preview.",
            )
            return
        self._selected_root = selected
        super().accept()


__all__ = ["LatexProjectRootSelectionDialog"]
