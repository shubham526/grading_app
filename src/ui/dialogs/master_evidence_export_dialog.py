"""Master ABET Evidence export dialog for v2.2.1.

The dialog is intentionally a thin Qt front end over
``src.tools.master_evidence_export``.  It does not implement scoring,
selected/counted semantics, semester aggregation, or export formatting itself.
Those behaviors remain owned by the backend shared with the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.tools.master_evidence_export import (
    MasterEvidenceBuildResult,
    VALID_EVIDENCE_POLICIES,
    collect_master_evidence_for_assignment,
    collect_master_evidence_for_semester,
    export_master_evidence,
)


DEFAULT_EXPORT_FORMATS = ("csv", "xlsx", "json")


def _read_json_object(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        with source.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} not found: {source}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def _course_meta_from_config(config: Mapping[str, Any]) -> dict:
    return {
        "semester": str(config.get("semester") or ""),
        "course_code": str(config.get("course_code") or ""),
        "course_name": str(config.get("course_name") or ""),
        "section": str(config.get("section") or ""),
    }


class MasterEvidenceWarningsDialog(QDialog):
    """Compact table view for non-fatal master-evidence warnings."""

    COLUMNS = (
        ("code", "Code"),
        ("assignment_id", "Assignment"),
        ("student_id", "Student"),
        ("criterion_id", "Criterion"),
        ("assessment_file", "Assessment File"),
        ("message", "Message"),
    )

    def __init__(self, warnings: Sequence[Mapping[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Master ABET Evidence Warnings")
        self.setMinimumSize(900, 420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        summary = QLabel(
            f"{len(warnings)} warning(s). These warnings do not necessarily mean the "
            "export failed; missing optional metadata is intentionally tolerated.",
            self,
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #667085;")
        outer.addWidget(summary)

        self.table = QTableWidget(len(warnings), len(self.COLUMNS), self)
        self.table.setObjectName("masterEvidenceWarningsTable")
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        for row_index, warning in enumerate(warnings):
            for column_index, (key, _) in enumerate(self.COLUMNS):
                item = QTableWidgetItem(str(warning.get(key) or ""))
                item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
                self.table.setItem(row_index, column_index, item)

        header = self.table.horizontalHeader()
        for column in range(len(self.COLUMNS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, 1)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        outer.addLayout(close_row)


class MasterEvidenceExportDialog(QDialog):
    """UI entry point for assignment- and semester-level master evidence export."""

    def __init__(
        self,
        parent=None,
        *,
        assignment_defaults: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(parent)
        self.assignment_defaults = dict(assignment_defaults or {})
        self._last_paths: Dict[str, Optional[str]] = {}
        self._last_warnings: List[dict] = []
        self._last_output_dir = ""
        self._build_ui()
        self._apply_assignment_defaults()
        self._update_mode_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("masterEvidenceExportDialog")
        self.setWindowTitle("Export Master ABET Evidence")
        # Keep the dialog usable on laptop displays.  The body scrolls while
        # Close/Export stay pinned at the bottom, and the user may resize the
        # window in either direction.
        self.setMinimumSize(720, 520)
        self.resize(980, 720)
        self.setSizeGripEnabled(True)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("masterEvidenceBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QScrollArea.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        body = QWidget(self.body_scroll)
        body.setObjectName("masterEvidenceBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(8, 6, 8, 8)
        content.setSpacing(14)

        title = QLabel("Export Master ABET Evidence", body)
        title.setObjectName("masterEvidenceDialogTitle")
        title.setProperty("labelType", "heading")
        content.addWidget(title)

        description = QLabel(
            "Create an auditable row-level evidence sheet without changing grading or ABET "
            "scoring. One row represents one student × assignment × rubric criterion.",
            body,
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #667085;")
        content.addWidget(description)

        mode_group = QGroupBox("Mode", body)
        mode_layout = QHBoxLayout(mode_group)
        self.semester_mode_radio = QRadioButton("Semester config", mode_group)
        self.assignment_mode_radio = QRadioButton("Single assignment", mode_group)
        self.semester_mode_radio.setObjectName("masterEvidenceSemesterMode")
        self.assignment_mode_radio.setObjectName("masterEvidenceAssignmentMode")
        self.semester_mode_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.semester_mode_radio)
        self.mode_group.addButton(self.assignment_mode_radio)
        mode_layout.addWidget(self.semester_mode_radio)
        mode_layout.addWidget(self.assignment_mode_radio)
        mode_layout.addStretch(1)
        content.addWidget(mode_group)

        self.semester_group = QGroupBox("Semester source", body)
        semester_form = QFormLayout(self.semester_group)
        self.semester_config_edit = QLineEdit(self.semester_group)
        self.semester_config_edit.setObjectName("masterEvidenceSemesterConfig")
        self.semester_config_edit.setPlaceholderText("semester.json")
        self.semester_config_edit.setClearButtonEnabled(True)
        semester_form.addRow(
            "Semester config",
            self._path_picker_row(
                self.semester_config_edit,
                "Choose File",
                self._choose_semester_config,
            ),
        )
        content.addWidget(self.semester_group)

        self.assignment_group = QGroupBox("Single-assignment source", body)
        assignment_form = QFormLayout(self.assignment_group)
        assignment_form.setHorizontalSpacing(16)
        assignment_form.setVerticalSpacing(8)

        self.rubric_edit = QLineEdit(self.assignment_group)
        self.rubric_edit.setObjectName("masterEvidenceRubricFile")
        self.rubric_edit.setPlaceholderText("rubric.json")
        self.rubric_edit.setClearButtonEnabled(True)
        assignment_form.addRow(
            "Rubric file",
            self._path_picker_row(self.rubric_edit, "Choose File", self._choose_rubric),
        )

        self.assessments_dir_edit = QLineEdit(self.assignment_group)
        self.assessments_dir_edit.setObjectName("masterEvidenceAssessmentsDir")
        self.assessments_dir_edit.setPlaceholderText("Folder containing saved assessment JSON files")
        self.assessments_dir_edit.setClearButtonEnabled(True)
        assignment_form.addRow(
            "Assessments folder",
            self._path_picker_row(
                self.assessments_dir_edit,
                "Choose Folder",
                self._choose_assessments_dir,
            ),
        )

        self.assignment_id_edit = QLineEdit(self.assignment_group)
        self.assignment_id_edit.setObjectName("masterEvidenceAssignmentId")
        assignment_form.addRow("Assignment ID", self.assignment_id_edit)

        self.assignment_title_edit = QLineEdit(self.assignment_group)
        self.assignment_title_edit.setObjectName("masterEvidenceAssignmentTitle")
        assignment_form.addRow("Assignment title", self.assignment_title_edit)

        self.assignment_type_edit = QLineEdit(self.assignment_group)
        self.assignment_type_edit.setObjectName("masterEvidenceAssignmentType")
        self.assignment_type_edit.setPlaceholderText("problem_set, exam, project, …")
        assignment_form.addRow("Assignment type", self.assignment_type_edit)

        self.assignment_date_edit = QLineEdit(self.assignment_group)
        self.assignment_date_edit.setObjectName("masterEvidenceAssignmentDate")
        self.assignment_date_edit.setPlaceholderText("YYYY-MM-DD")
        assignment_form.addRow("Assignment date", self.assignment_date_edit)

        self.course_code_edit = QLineEdit(self.assignment_group)
        self.course_code_edit.setObjectName("masterEvidenceCourseCode")
        assignment_form.addRow("Course code", self.course_code_edit)

        self.course_name_edit = QLineEdit(self.assignment_group)
        self.course_name_edit.setObjectName("masterEvidenceCourseName")
        assignment_form.addRow("Course name", self.course_name_edit)

        self.semester_edit = QLineEdit(self.assignment_group)
        self.semester_edit.setObjectName("masterEvidenceSemester")
        assignment_form.addRow("Semester", self.semester_edit)

        self.section_edit = QLineEdit(self.assignment_group)
        self.section_edit.setObjectName("masterEvidenceSection")
        assignment_form.addRow("Section", self.section_edit)
        content.addWidget(self.assignment_group)

        output_group = QGroupBox("Export", body)
        output_layout = QVBoxLayout(output_group)
        output_form = QFormLayout()
        self.output_dir_edit = QLineEdit(output_group)
        self.output_dir_edit.setObjectName("masterEvidenceOutputDir")
        self.output_dir_edit.setPlaceholderText("Folder for master_abet_evidence.*")
        self.output_dir_edit.setClearButtonEnabled(True)
        output_form.addRow(
            "Output directory",
            self._path_picker_row(
                self.output_dir_edit,
                "Choose Folder",
                self._choose_output_dir,
            ),
        )
        output_layout.addLayout(output_form)

        formats_row = QHBoxLayout()
        formats_label = QLabel("Formats", output_group)
        self.csv_checkbox = QCheckBox("CSV", output_group)
        self.xlsx_checkbox = QCheckBox("XLSX", output_group)
        self.json_checkbox = QCheckBox("JSON", output_group)
        self.csv_checkbox.setObjectName("masterEvidenceFormatCsv")
        self.xlsx_checkbox.setObjectName("masterEvidenceFormatXlsx")
        self.json_checkbox.setObjectName("masterEvidenceFormatJson")
        self.csv_checkbox.setChecked(True)
        self.xlsx_checkbox.setChecked(True)
        self.json_checkbox.setChecked(True)
        formats_row.addWidget(formats_label)
        formats_row.addSpacing(12)
        formats_row.addWidget(self.csv_checkbox)
        formats_row.addWidget(self.xlsx_checkbox)
        formats_row.addWidget(self.json_checkbox)
        formats_row.addStretch(1)
        output_layout.addLayout(formats_row)

        policy_form = QFormLayout()
        self.evidence_policy_combo = QComboBox(output_group)
        self.evidence_policy_combo.setObjectName("masterEvidencePolicy")
        ordered_policies = ["counted_only", "selected_only", "all"]
        for policy in ordered_policies:
            if policy in VALID_EVIDENCE_POLICIES:
                self.evidence_policy_combo.addItem(policy)
        policy_form.addRow("Evidence policy", self.evidence_policy_combo)

        self.include_excluded_checkbox = QCheckBox(
            "Include rows excluded by the selected evidence policy",
            output_group,
        )
        self.include_excluded_checkbox.setObjectName("masterEvidenceIncludeExcluded")
        policy_form.addRow("", self.include_excluded_checkbox)
        output_layout.addLayout(policy_form)
        content.addWidget(output_group)

        note = QLabel(
            "Missing optional metadata is exported as blank values and reported as warnings. "
            "The export uses final saved assessment scores and does not modify existing reports.",
            body,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #98A2B3; font-size: 11px;")
        content.addWidget(note)

        self.result_group = QGroupBox("Result", body)
        self.result_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        result_layout = QVBoxLayout(self.result_group)

        # Keep the existing QLabel API used by tests, but put it in its own
        # scrollable viewport so long file paths can always be inspected.
        self.result_scroll = QScrollArea(self.result_group)
        self.result_scroll.setObjectName("masterEvidenceResultScroll")
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setMinimumHeight(130)
        self.result_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.result_label = QLabel("", self.result_scroll)
        self.result_label.setObjectName("masterEvidenceResultSummary")
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.result_label.setContentsMargins(8, 6, 8, 6)
        self.result_scroll.setWidget(self.result_label)
        result_layout.addWidget(self.result_scroll, 1)

        result_buttons = QHBoxLayout()
        self.open_folder_button = QPushButton("Open Folder", self.result_group)
        self.open_folder_button.setObjectName("masterEvidenceOpenFolder")
        self.open_folder_button.clicked.connect(self._open_output_folder)
        self.view_warnings_button = QPushButton("View Warnings", self.result_group)
        self.view_warnings_button.setObjectName("masterEvidenceViewWarnings")
        self.view_warnings_button.clicked.connect(self._view_warnings)
        result_buttons.addWidget(self.open_folder_button)
        result_buttons.addWidget(self.view_warnings_button)
        result_buttons.addStretch(1)
        result_layout.addLayout(result_buttons)
        self.result_group.setVisible(False)
        content.addWidget(self.result_group, 1)

        self.body_scroll.setWidget(body)
        outer.addWidget(self.body_scroll, 1)

        # Footer actions stay visible even when the single-assignment form is
        # taller than the available screen.
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        self.export_button = QPushButton("Export", self)
        self.export_button.setObjectName("masterEvidenceExportButton")
        self.export_button.setProperty("buttonRole", "primary")
        self.export_button.clicked.connect(self._on_export_clicked)
        action_row.addWidget(self.close_button)
        action_row.addWidget(self.export_button)
        outer.addLayout(action_row)

        self.semester_mode_radio.toggled.connect(self._update_mode_ui)
        self.assignment_mode_radio.toggled.connect(self._update_mode_ui)

    def _path_picker_row(self, edit: QLineEdit, label: str, callback) -> QWidget:
        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(edit, 1)
        button = QPushButton(label, host)
        button.clicked.connect(callback)
        row.addWidget(button)
        return host

    def _apply_assignment_defaults(self) -> None:
        values = self.assignment_defaults
        mapping = (
            (self.rubric_edit, "rubric_path"),
            (self.assessments_dir_edit, "assessments_dir"),
            (self.assignment_id_edit, "assignment_id"),
            (self.assignment_title_edit, "assignment_title"),
            (self.assignment_type_edit, "assignment_type"),
            (self.assignment_date_edit, "assignment_date"),
            (self.course_code_edit, "course_code"),
            (self.course_name_edit, "course_name"),
            (self.semester_edit, "semester"),
            (self.section_edit, "section"),
        )
        for edit, key in mapping:
            value = values.get(key)
            if value is not None:
                edit.setText(str(value))

    # ------------------------------------------------------------------
    # Mode / values
    # ------------------------------------------------------------------

    def _update_mode_ui(self) -> None:
        semester_mode = self.semester_mode_radio.isChecked()
        self.semester_group.setVisible(semester_mode)
        self.assignment_group.setVisible(not semester_mode)

    def selected_formats(self) -> List[str]:
        selected: List[str] = []
        if self.csv_checkbox.isChecked():
            selected.append("csv")
        if self.xlsx_checkbox.isChecked():
            selected.append("xlsx")
        if self.json_checkbox.isChecked():
            selected.append("json")
        return selected

    def assignment_meta(self) -> dict:
        return {
            "assignment_id": self.assignment_id_edit.text().strip(),
            "assignment_title": self.assignment_title_edit.text().strip(),
            "assignment_type": self.assignment_type_edit.text().strip(),
            "assignment_date": self.assignment_date_edit.text().strip(),
        }

    def course_meta(self) -> dict:
        return {
            "semester": self.semester_edit.text().strip(),
            "course_code": self.course_code_edit.text().strip(),
            "course_name": self.course_name_edit.text().strip(),
            "section": self.section_edit.text().strip(),
        }

    def validation_error(self) -> str:
        if not self.selected_formats():
            return "Select at least one export format."

        output_dir = self.output_dir_edit.text().strip()
        if not output_dir:
            return "Choose an output directory."

        if self.semester_mode_radio.isChecked():
            config = self.semester_config_edit.text().strip()
            if not config:
                return "Choose a semester config JSON file."
            if not Path(config).expanduser().is_file():
                return f"Semester config file not found: {config}"
            return ""

        rubric = self.rubric_edit.text().strip()
        assessments = self.assessments_dir_edit.text().strip()
        if not rubric:
            return "Choose a rubric JSON file."
        if not Path(rubric).expanduser().is_file():
            return f"Rubric file not found: {rubric}"
        if not assessments:
            return "Choose an assessments folder."
        if not Path(assessments).expanduser().is_dir():
            return f"Assessments folder not found: {assessments}"
        return ""

    # ------------------------------------------------------------------
    # Export execution
    # ------------------------------------------------------------------

    def perform_export(self) -> dict:
        """Run the selected export synchronously and return a testable result dict."""

        error = self.validation_error()
        if error:
            raise ValueError(error)

        policy = self.evidence_policy_combo.currentText().strip() or "counted_only"
        include_excluded = self.include_excluded_checkbox.isChecked()
        output_dir = str(Path(self.output_dir_edit.text().strip()).expanduser())

        if self.semester_mode_radio.isChecked():
            config_path = Path(self.semester_config_edit.text().strip()).expanduser().resolve()
            config = _read_json_object(str(config_path), "semester config")
            result = collect_master_evidence_for_semester(
                config,
                evidence_policy=policy,
                include_excluded=include_excluded,
                base_dir=str(config_path.parent),
            )
            course_meta = _course_meta_from_config(config)
        else:
            rubric_path = Path(self.rubric_edit.text().strip()).expanduser().resolve()
            rubric = _read_json_object(str(rubric_path), "rubric")
            if not isinstance(rubric.get("criteria"), list):
                raise ValueError("Rubric must contain a criteria list.")

            assessments_dir = Path(
                self.assessments_dir_edit.text().strip()
            ).expanduser().resolve()
            result = collect_master_evidence_for_assignment(
                rubric,
                str(assessments_dir),
                self.assignment_meta(),
                self.course_meta(),
                evidence_policy=policy,
                include_excluded=include_excluded,
            )
            course_meta = self.course_meta()

        if not isinstance(result, MasterEvidenceBuildResult):
            # Keep the UI tolerant of a compatible backend-like object in tests,
            # while still requiring rows/warnings attributes.
            rows = list(getattr(result, "rows", []) or [])
            warnings = list(getattr(result, "warnings", []) or [])
        else:
            rows = result.rows
            warnings = result.warnings

        paths = export_master_evidence(
            rows,
            output_dir,
            formats=self.selected_formats(),
            warnings=warnings,
            course_meta=course_meta,
            evidence_policy=policy,
        )
        return {
            "paths": paths,
            "warnings": list(warnings),
            "rows": list(rows),
            "output_dir": str(Path(output_dir).resolve()),
        }

    def _on_export_clicked(self) -> None:
        error = self.validation_error()
        if error:
            QMessageBox.warning(self, "Cannot Export", error)
            return

        self.export_button.setEnabled(False)
        self.export_button.setText("Exporting…")
        QApplication.processEvents()
        try:
            result = self.perform_export()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Master Evidence Export Failed",
                str(exc),
            )
            return
        finally:
            self.export_button.setEnabled(True)
            self.export_button.setText("Export")

        self._show_export_result(result)

    def _show_export_result(self, result: Mapping[str, Any]) -> None:
        self._last_paths = dict(result.get("paths") or {})
        self._last_warnings = [dict(w) for w in (result.get("warnings") or [])]
        self._last_output_dir = str(result.get("output_dir") or self.output_dir_edit.text()).strip()

        lines = ["Master evidence export complete.", ""]
        preferred = (("csv", "CSV"), ("xlsx", "XLSX"), ("json", "JSON"), ("warnings_csv", "Warnings CSV"))
        for key, label in preferred:
            if key not in self._last_paths:
                continue
            path = self._last_paths.get(key)
            if path:
                lines.append(f"✓ {label}: {path}")
            else:
                lines.append(f"— {label}: unavailable (optional dependency not installed)")
        lines.append("")
        lines.append(f"Warnings: {len(self._last_warnings)}")

        self.result_label.setText("\n".join(lines))
        self.view_warnings_button.setEnabled(bool(self._last_warnings))
        self.open_folder_button.setEnabled(bool(self._last_output_dir))
        self.result_group.setVisible(True)

    # ------------------------------------------------------------------
    # File/folder actions
    # ------------------------------------------------------------------

    def _choose_semester_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Semester Config",
            self.semester_config_edit.text().strip() or "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.semester_config_edit.setText(path)

    def _choose_rubric(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Rubric",
            self.rubric_edit.text().strip() or "",
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.rubric_edit.setText(path)

    def _choose_assessments_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose Assessments Folder",
            self.assessments_dir_edit.text().strip() or "",
        )
        if path:
            self.assessments_dir_edit.setText(path)

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose Output Directory",
            self.output_dir_edit.text().strip() or "",
        )
        if path:
            self.output_dir_edit.setText(path)

    def _open_output_folder(self) -> None:
        if not self._last_output_dir:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_output_dir))

    def _view_warnings(self) -> None:
        if not self._last_warnings:
            return
        dialog = MasterEvidenceWarningsDialog(self._last_warnings, self)
        dialog.exec_()


__all__ = [
    "DEFAULT_EXPORT_FORMATS",
    "MasterEvidenceExportDialog",
    "MasterEvidenceWarningsDialog",
]
