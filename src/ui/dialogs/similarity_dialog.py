"""Interactive v2.3.0 Submission Similarity Review dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.similarity import (
    DEFAULT_THRESHOLDS,
    DISCLAIMER,
    SOURCE_ASSESSMENT_FOLDER,
    SOURCE_LOADED,
    SOURCE_SUBMISSIONS_FOLDER,
    collect_similarity_source,
    export_similarity_report,
    generate_similarity_report,
)
from src.similarity.models import FLAG_RANK, PairSimilarity
from src.ui.dialogs.similarity_pair_dialog import PairSimilarityDetailDialog


SOURCE_LABELS = {
    SOURCE_LOADED: "Use loaded submissions",
    SOURCE_SUBMISSIONS_FOLDER: "Choose submissions folder",
    SOURCE_ASSESSMENT_FOLDER: "Choose assessment folder",
}

METHOD_LABELS = {
    "exact_file_hash": "Exact file hash",
    "normalized_text_hash": "Normalized text hash",
    "ngram_jaccard": "N-gram overlap",
}


class NumericTableWidgetItem(QTableWidgetItem):
    """Sortable numeric table item while retaining a formatted display string."""

    def __init__(self, value: float, digits: int = 4):
        self.numeric_value = float(value)
        super().__init__(f"{self.numeric_value:.{digits}f}")

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class FlagTableWidgetItem(QTableWidgetItem):
    """Sort flag levels by review severity rather than alphabetically."""

    def __init__(self, flag_level: str):
        self.flag_level = str(flag_level)
        super().__init__(self.flag_level)

    def __lt__(self, other):
        if isinstance(other, FlagTableWidgetItem):
            return FLAG_RANK.get(self.flag_level, -1) < FLAG_RANK.get(other.flag_level, -1)
        return super().__lt__(other)


class SimilarityWarningsDialog(QDialog):
    def __init__(self, parent=None, warnings: Sequence[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Similarity Review Warnings")
        self.setMinimumSize(620, 360)
        self.resize(820, 520)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "These warnings describe missing/partial source evidence or comparison "
            "conditions. They are not misconduct determinations."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        values = list(warnings or [])
        text.setPlainText("\n".join(values) if values else "No warnings.")
        layout.addWidget(text, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)


class SimilarityReviewDialog(QDialog):
    """Configure, run, inspect, and export deterministic similarity review."""

    RESULT_COLUMNS = [
        "Student A",
        "Student B",
        "Flag",
        "Overall",
        "Most Similar Q",
        "Exact File",
        "Normalized Match",
    ]

    def __init__(
        self,
        parent=None,
        *,
        assignment_id: str = "",
        question_ids: Sequence[str] | None = None,
        loaded_submissions: Mapping[str, Any] | None = None,
        submissions_dir: str | None = None,
        assessments_dir: str | None = None,
    ):
        super().__init__(parent)
        self.initial_question_ids = self._clean_question_ids(question_ids)
        self.loaded_submissions = dict(loaded_submissions or {})
        self.default_submissions_dir = str(submissions_dir or "")
        self.default_assessments_dir = str(assessments_dir or "")
        self._source_paths = {
            SOURCE_SUBMISSIONS_FOLDER: self.default_submissions_dir,
            SOURCE_ASSESSMENT_FOLDER: self.default_assessments_dir,
        }
        self._active_path_source = None

        self.source_result = None
        self.report = None
        self.last_export_results = None
        self.last_html_path: Path | None = None

        self.setWindowTitle("Submission Similarity Review")
        self.setMinimumSize(900, 620)
        self.resize(1220, 860)
        self.setSizeGripEnabled(True)

        self._build_ui(str(assignment_id or ""))
        self._choose_initial_source()
        self._update_source_controls()
        self._update_action_state()

    @staticmethod
    def _clean_question_ids(question_ids: Sequence[str] | None) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in question_ids or ():
            qid = str(raw or "").strip()
            if qid and qid not in seen:
                seen.add(qid)
                ordered.append(qid)
        return ordered

    def _build_ui(self, assignment_id: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("<b>Submission Similarity Review</b>")
        title.setStyleSheet("font-size: 17px;")
        root.addWidget(title)

        disclaimer = QLabel(DISCLAIMER)
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "QLabel { border: 1px solid #667085; border-radius: 6px; "
            "padding: 9px; background: #F9FAFB; }"
        )
        root.addWidget(disclaimer)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setChildrenCollapsible(False)
        root.addWidget(self.main_splitter, 1)

        config_widget = QWidget()
        config_layout = QHBoxLayout(config_widget)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(10)

        source_group = QGroupBox("Submission source")
        source_layout = QVBoxLayout(source_group)
        self.source_button_group = QButtonGroup(self)
        self.source_radios = {}
        for index, source_type in enumerate(
            (SOURCE_LOADED, SOURCE_SUBMISSIONS_FOLDER, SOURCE_ASSESSMENT_FOLDER)
        ):
            radio = QRadioButton(SOURCE_LABELS[source_type])
            self.source_button_group.addButton(radio, index)
            self.source_radios[source_type] = radio
            radio.toggled.connect(
                lambda checked, st=source_type: self._on_source_selected(st) if checked else None
            )
            source_layout.addWidget(radio)

        self.loaded_count_label = QLabel(
            f"Loaded submissions available: {len(self.loaded_submissions)}"
        )
        self.loaded_count_label.setWordWrap(True)
        source_layout.addWidget(self.loaded_count_label)

        path_row = QHBoxLayout()
        self.source_path_label = QLabel("Folder:")
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Choose a folder")
        self.source_browse_btn = QPushButton("Browse…")
        self.source_browse_btn.clicked.connect(self._browse_source_folder)
        self.source_path_edit.editingFinished.connect(self._remember_source_path)
        path_row.addWidget(self.source_path_label)
        path_row.addWidget(self.source_path_edit, 1)
        path_row.addWidget(self.source_browse_btn)
        source_layout.addLayout(path_row)
        source_layout.addStretch(1)
        config_layout.addWidget(source_group, 2)

        assignment_group = QGroupBox("Assignment / questions")
        assignment_form = QFormLayout(assignment_group)
        self.assignment_id_edit = QLineEdit(assignment_id)
        self.assignment_id_edit.setPlaceholderText("e.g., PS3")
        assignment_form.addRow("Assignment ID:", self.assignment_id_edit)

        self.question_combo = QComboBox()
        self.question_combo.addItem("All questions", None)
        for qid in self.initial_question_ids:
            self.question_combo.addItem(qid, qid)
        if not self.initial_question_ids:
            self.question_combo.setItemText(0, "All available questions")
        assignment_form.addRow("Questions:", self.question_combo)
        config_layout.addWidget(assignment_group, 1)

        methods_group = QGroupBox("Methods")
        methods_layout = QVBoxLayout(methods_group)
        self.method_checks = {}
        for method in ("exact_file_hash", "normalized_text_hash", "ngram_jaccard"):
            checkbox = QCheckBox(METHOD_LABELS[method])
            checkbox.setChecked(True)
            self.method_checks[method] = checkbox
            methods_layout.addWidget(checkbox)
        self.method_checks["ngram_jaccard"].toggled.connect(
            lambda checked: self.thresholds_group.setEnabled(bool(checked))
            if hasattr(self, "thresholds_group") else None
        )
        methods_layout.addStretch(1)
        config_layout.addWidget(methods_group, 1)

        self.thresholds_group = QGroupBox("N-gram thresholds")
        thresholds_form = QFormLayout(self.thresholds_group)
        self.threshold_spins = {}
        for key, label in (
            ("ngram_low", "Low:"),
            ("ngram_medium", "Medium:"),
            ("ngram_high", "High:"),
            ("ngram_exact", "Exact:"),
        ):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.05)
            spin.setValue(DEFAULT_THRESHOLDS[key])
            self.threshold_spins[key] = spin
            thresholds_form.addRow(label, spin)
        config_layout.addWidget(self.thresholds_group, 1)

        self.main_splitter.addWidget(config_widget)

        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(6)

        self.result_summary = QLabel(
            "Choose a source and run the similarity review."
        )
        self.result_summary.setWordWrap(True)
        result_layout.addWidget(self.result_summary)

        self.results_table = QTableWidget(0, len(self.RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(self.RESULT_COLUMNS)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.verticalHeader().setVisible(False)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.results_table.itemSelectionChanged.connect(self._update_action_state)
        self.results_table.itemDoubleClicked.connect(lambda _item: self.view_selected_pair())
        result_layout.addWidget(self.results_table, 1)

        self.main_splitter.addWidget(result_widget)
        self.main_splitter.setSizes([260, 520])

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run Similarity Review")
        self.run_btn.clicked.connect(self.run_review)
        actions.addWidget(self.run_btn)

        self.view_pair_btn = QPushButton("View Selected Pair")
        self.view_pair_btn.clicked.connect(self.view_selected_pair)
        actions.addWidget(self.view_pair_btn)

        self.warnings_btn = QPushButton("View Warnings")
        self.warnings_btn.clicked.connect(self.view_warnings)
        actions.addWidget(self.warnings_btn)

        actions.addStretch(1)

        self.export_btn = QPushButton("Export Report…")
        self.export_btn.clicked.connect(self.export_report)
        actions.addWidget(self.export_btn)

        self.open_html_btn = QPushButton("Open HTML")
        self.open_html_btn.clicked.connect(self.open_html_report)
        actions.addWidget(self.open_html_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        root.addLayout(actions)

    def _choose_initial_source(self):
        if len(self.loaded_submissions) >= 2:
            self.source_radios[SOURCE_LOADED].setChecked(True)
        elif self.default_assessments_dir:
            self.source_radios[SOURCE_ASSESSMENT_FOLDER].setChecked(True)
        elif self.default_submissions_dir:
            self.source_radios[SOURCE_SUBMISSIONS_FOLDER].setChecked(True)
        else:
            self.source_radios[SOURCE_LOADED].setChecked(True)

    def selected_source_type(self) -> str:
        for source_type, radio in self.source_radios.items():
            if radio.isChecked():
                return source_type
        return SOURCE_LOADED

    def _on_source_selected(self, source_type: str):
        if self._active_path_source in self._source_paths:
            self._source_paths[self._active_path_source] = self.source_path_edit.text().strip()
        self._active_path_source = source_type
        if source_type in self._source_paths:
            self.source_path_edit.setText(self._source_paths.get(source_type, ""))
        self._update_source_controls()

    def _remember_source_path(self):
        source_type = self.selected_source_type()
        if source_type in self._source_paths:
            self._source_paths[source_type] = self.source_path_edit.text().strip()

    def _update_source_controls(self):
        source_type = self.selected_source_type()
        use_path = source_type != SOURCE_LOADED
        self.source_path_label.setVisible(use_path)
        self.source_path_edit.setVisible(use_path)
        self.source_browse_btn.setVisible(use_path)

        if source_type == SOURCE_SUBMISSIONS_FOLDER:
            self.source_path_label.setText("Submissions folder:")
        elif source_type == SOURCE_ASSESSMENT_FOLDER:
            self.source_path_label.setText("Assessment folder:")
        self._update_action_state()

    def _browse_source_folder(self):
        source_type = self.selected_source_type()
        title = (
            "Choose submissions folder"
            if source_type == SOURCE_SUBMISSIONS_FOLDER
            else "Choose assessment folder"
        )
        start = self.source_path_edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, title, start)
        if directory:
            self.source_path_edit.setText(directory)
            self._remember_source_path()

    def selected_methods(self) -> list[str]:
        return [
            method
            for method, checkbox in self.method_checks.items()
            if checkbox.isChecked()
        ]

    def selected_thresholds(self) -> dict[str, float]:
        return {
            key: spin.value()
            for key, spin in self.threshold_spins.items()
        }

    def requested_question_ids(self) -> list[str]:
        selected = self.question_combo.currentData()
        if selected:
            return [str(selected)]
        return list(self.initial_question_ids)

    def _collect_source(self):
        source_type = self.selected_source_type()
        question_ids = self.requested_question_ids()
        if source_type == SOURCE_LOADED:
            return collect_similarity_source(
                SOURCE_LOADED,
                loaded_submissions=self.loaded_submissions,
                question_ids=question_ids,
            )

        path = self.source_path_edit.text().strip()
        if not path:
            raise ValueError("Choose a source folder before running the review.")
        return collect_similarity_source(
            source_type,
            path=path,
            question_ids=question_ids,
        )

    def run_review(self):
        assignment_id = self.assignment_id_edit.text().strip()
        if not assignment_id:
            QMessageBox.warning(
                self,
                "Assignment ID required",
                "Enter a stable assignment ID before running similarity review.",
            )
            return

        methods = self.selected_methods()
        if not methods:
            QMessageBox.warning(
                self,
                "Select a method",
                "Select at least one deterministic similarity method.",
            )
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            source = self._collect_source()
            if len(source.submissions) < 2:
                self.source_result = source
                self.report = None
                self._populate_results([])
                self.result_summary.setText(
                    f"{len(source.submissions)} usable submission(s). "
                    "At least two are required for pairwise similarity review."
                )
                self._update_action_state()
                QMessageBox.warning(
                    self,
                    "Not enough submissions",
                    "At least two usable student submissions are required.",
                )
                return

            question_ids = source.question_ids
            selected = self.question_combo.currentData()
            if selected:
                question_ids = [str(selected)]

            report = generate_similarity_report(
                source.submissions,
                assignment_id,
                question_ids,
                thresholds=self.selected_thresholds(),
                methods=methods,
            )

            for warning in reversed(source.warnings):
                if warning not in report.warnings:
                    report.warnings.insert(0, warning)

            if "ngram_jaccard" in methods and not question_ids:
                warning = "no_question_ids_available_for_ngram"
                if warning not in report.warnings:
                    report.warnings.append(warning)

            self.source_result = source
            self.report = report
            self.last_export_results = None
            self.last_html_path = None
            self._populate_results(report.pairs)

            flagged = sum(1 for pair in report.pairs if pair.flag_level != "none")
            self.result_summary.setText(
                f"{len(report.students)} students · {len(report.pairs)} unique pairs · "
                f"{flagged} flagged for review · {len(report.warnings)} warning(s). "
                "Double-click a pair for question-level detail."
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Similarity review failed",
                f"Could not complete the similarity review:\n{exc}",
            )
        finally:
            QApplication.restoreOverrideCursor()
            self._update_action_state()

    def _populate_results(self, pairs: Sequence[PairSimilarity]):
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)
        for pair in pairs:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            student_a = QTableWidgetItem(pair.student_a)
            student_a.setData(Qt.UserRole, pair)
            self.results_table.setItem(row, 0, student_a)
            self.results_table.setItem(row, 1, QTableWidgetItem(pair.student_b))
            self.results_table.setItem(row, 2, FlagTableWidgetItem(pair.flag_level))
            self.results_table.setItem(row, 3, NumericTableWidgetItem(pair.overall_score))
            self.results_table.setItem(
                row,
                4,
                QTableWidgetItem(pair.most_similar_question or ""),
            )
            self.results_table.setItem(
                row,
                5,
                QTableWidgetItem("yes" if pair.exact_file_match else "no"),
            )
            self.results_table.setItem(
                row,
                6,
                QTableWidgetItem("yes" if pair.normalized_text_match else "no"),
            )

            if pair.flag_level in {"exact", "high"}:
                font = student_a.font()
                font.setBold(True)
                for column in range(len(self.RESULT_COLUMNS)):
                    item = self.results_table.item(row, column)
                    if item is not None:
                        item.setFont(font)

        # Keep the backend's severity-then-score ordering initially. The user
        # can still click any sortable column header afterward.
        self.results_table.setSortingEnabled(True)
        if self.results_table.rowCount():
            self.results_table.selectRow(0)

    def selected_pair(self) -> PairSimilarity | None:
        row = self.results_table.currentRow()
        if row < 0:
            return None
        item = self.results_table.item(row, 0)
        if item is None:
            return None
        pair = item.data(Qt.UserRole)
        return pair if isinstance(pair, PairSimilarity) else None

    def view_selected_pair(self):
        pair = self.selected_pair()
        if pair is None or self.source_result is None:
            return

        question_ids = list(self.source_result.question_ids)
        selected = self.question_combo.currentData()
        if selected:
            question_ids = [str(selected)]

        dialog = PairSimilarityDetailDialog(
            self,
            pair=pair,
            submissions=self.source_result.submissions,
            question_ids=question_ids,
        )
        dialog.exec_()

    def view_warnings(self):
        warnings = self.report.warnings if self.report is not None else (
            self.source_result.warnings if self.source_result is not None else []
        )
        dialog = SimilarityWarningsDialog(self, warnings=warnings)
        dialog.exec_()

    def export_report(self):
        if self.report is None or self.source_result is None:
            return
        start = self.source_path_edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose similarity report output folder",
            start,
        )
        if not directory:
            return
        try:
            results = self._export_to_directory(directory)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export failed",
                f"Could not export similarity report:\n{exc}",
            )
            return

        written = [path.name for path in results.values() if path is not None]
        self.result_summary.setText(
            self.result_summary.text()
            + "\nExported: "
            + ", ".join(written)
        )
        QMessageBox.information(
            self,
            "Similarity report exported",
            "Export complete.\n\n" + "\n".join(written),
        )
        self._update_action_state()

    def _export_to_directory(self, directory: str):
        if self.report is None or self.source_result is None:
            raise ValueError("Run a similarity review before exporting.")
        results = export_similarity_report(
            self.report,
            directory,
            formats=("json", "csv", "html"),
            include_matrix=True,
            submissions=self.source_result.submissions,
        )
        self.last_export_results = results
        html_path = results.get("html")
        self.last_html_path = Path(html_path) if html_path is not None else None
        return results

    def open_html_report(self):
        if self.last_html_path is None or not self.last_html_path.is_file():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_html_path)))

    def _update_action_state(self):
        has_report = self.report is not None
        self.export_btn.setEnabled(has_report)
        self.warnings_btn.setEnabled(
            bool(
                (self.report is not None and self.report.warnings)
                or (self.source_result is not None and self.source_result.warnings)
            )
        )
        self.view_pair_btn.setEnabled(self.selected_pair() is not None)
        self.open_html_btn.setEnabled(
            self.last_html_path is not None and self.last_html_path.is_file()
        )


__all__ = [
    "SimilarityReviewDialog",
    "SimilarityWarningsDialog",
    "NumericTableWidgetItem",
    "FlagTableWidgetItem",
]
