"""Canonical submission import dialog with v2.3.4.2 LaTeX-project UX.

The dialog owns preview, mapping, explicit ambiguous-root selection, and commit
intent. Slow discovery, hashing, safe ZIP preflight, copying, compilation, and
parsing remain delegated to :class:`SubmissionImportWorker` and backend services.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.submissions import (
    ImportCandidate,
    SubmissionImporter,
    SubmissionRepository,
)
from src.submissions.domain import (
    VALIDATION_STATUS_DUPLICATE,
    VALIDATION_STATUS_READY,
)
from src.submissions.latex_project import (
    LATEX_PROJECT_ROOT_METADATA_KEY,
    apply_latex_project_preview_validation,
    candidate_latex_project_preview,
    latex_project_root_selection_required,
    set_candidate_latex_project_root,
)
from src.ui.dialogs.latex_project_root_dialog import (
    LatexProjectRootSelectionDialog,
)
from src.ui.dialogs.latex_project_diagnostics_dialog import (
    ACTION_RESELECT_ROOT,
    ACTION_RETRY,
    LatexProjectDiagnosticsDialog,
)
from src.ui.workers.submission_import_worker import (
    SubmissionImportOperation,
    SubmissionImportWorker,
)


class SubmissionImportDialog(QDialog):
    """Preview, map, and commit canonical local-file submissions."""

    imports_committed = pyqtSignal(object)
    evidence_recovered = pyqtSignal(object, object)

    def __init__(
        self,
        repository: SubmissionRepository,
        assessment_id: str,
        roster: Sequence[Any],
        *,
        question_ids: Optional[Sequence[str]] = None,
        evidence_dir: Optional[str] = None,
        thread_pool: Optional[QThreadPool] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(repository, SubmissionRepository):
            raise TypeError("repository must be SubmissionRepository")
        assessment_id = str(assessment_id or "").strip()
        if not assessment_id:
            raise ValueError("assessment_id is required")

        self.repository = repository
        self.assessment_id = assessment_id
        self.roster = list(roster)
        self.question_ids = tuple(str(value) for value in (question_ids or ()))
        self.evidence_dir = str(evidence_dir) if evidence_dir else None
        self.thread_pool = thread_pool or QThreadPool.globalInstance()

        self.importer = SubmissionImporter(
            repository,
            assessment_id=assessment_id,
            roster=self.roster,
        )
        self._raw_candidates: List[ImportCandidate] = []
        self._candidates: List[ImportCandidate] = []
        self._workers: Dict[str, SubmissionImportWorker] = {}
        self._latex_project_root_overrides: Dict[str, str] = {}
        self._rebuilding = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("submissionImportDialog")
        self.setWindowTitle("Import Submissions")
        self.setModal(True)
        self.resize(1080, 620)
        self.setMinimumSize(820, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        title = QLabel("Import Submissions", self)
        title.setProperty("labelType", "heading")
        outer.addWidget(title)

        description = QLabel(
            "Select local files or a submission folder. The app will hash the original "
            "files, conservatively match them to the loaded roster, detect duplicate "
            "attempts, and preview every import before anything is committed. LaTeX "
            "project ZIPs are safely inspected; if multiple complete root documents "
            "exist, you will choose the correct root before import.",
            self,
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #667085;")
        outer.addWidget(description)

        source_row = QHBoxLayout()
        self.add_files_button = QPushButton("Add Files…", self)
        self.add_files_button.setObjectName("importSubmissionFilesButton")
        self.add_files_button.clicked.connect(self._choose_files)
        source_row.addWidget(self.add_files_button)

        self.add_folder_button = QPushButton("Add Folder…", self)
        self.add_folder_button.setObjectName("importSubmissionFolderButton")
        self.add_folder_button.clicked.connect(self._choose_folder)
        source_row.addWidget(self.add_folder_button)

        self.clear_button = QPushButton("Clear", self)
        self.clear_button.setObjectName("clearSubmissionImportButton")
        self.clear_button.clicked.connect(self.clear_candidates)
        source_row.addWidget(self.clear_button)
        source_row.addStretch(1)
        outer.addLayout(source_row)

        self.table = QTableWidget(0, 6, self)
        self.table.setObjectName("submissionImportTable")
        self.table.setHorizontalHeaderLabels(
            ["Import", "File(s)", "Student", "Attempt", "Status", "Details"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # QTableWidgetItem check-state changes do not automatically refresh the
        # dialog's derived selection count/button state.  Listen explicitly so
        # a user can opt into importing an exact duplicate after preview.
        self.table.itemChanged.connect(self._selection_changed)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        self.status_label = QLabel("No submissions selected.", self)
        self.status_label.setObjectName("submissionImportStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #667085;")
        outer.addWidget(self.status_label)

        footer = QHBoxLayout()
        self.import_button = QPushButton("Import Selected", self)
        self.import_button.setObjectName("commitSubmissionImportButton")
        self.import_button.setProperty("buttonRole", "primary")
        self.import_button.clicked.connect(self._commit_selected)
        self.import_button.setEnabled(False)
        footer.addWidget(self.import_button)
        footer.addStretch(1)

        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        outer.addLayout(footer)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @property
    def candidates(self) -> List[ImportCandidate]:
        return list(self._candidates)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Submission Files",
            "",
            "Submission Files (*.tex *.pdf *.py *.zip *.docx *.txt);;All Files (*)",
        )
        if paths:
            self.discover_files(paths)

    def _choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Submission Folder",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if directory:
            self.discover_directory(directory)

    def discover_files(self, paths: Sequence[str]) -> Optional[str]:
        if not paths:
            return None
        return self._start_worker(
            SubmissionImportOperation.DISCOVER_FILES,
            parameters={"file_paths": list(paths)},
        )

    def discover_directory(self, directory: str) -> Optional[str]:
        if not str(directory or "").strip():
            return None
        return self._start_worker(
            SubmissionImportOperation.DISCOVER_DIRECTORY,
            parameters={
                "directory": str(directory),
                "include_student_subdirectories": True,
            },
        )

    def clear_candidates(self) -> None:
        if self._workers:
            QMessageBox.information(
                self,
                "Import In Progress",
                "Wait for the current import operation to finish before clearing the preview.",
            )
            return
        self._raw_candidates = []
        self._candidates = []
        self._latex_project_root_overrides = {}
        self._populate_table()

    # ------------------------------------------------------------------
    # Mapping / table presentation
    # ------------------------------------------------------------------

    def _student_display(self, record: Any) -> str:
        student_id = str(getattr(record, "student_id", "") or "").strip()
        student_name = str(getattr(record, "student_name", "") or "").strip()
        if student_name and student_id and student_name != student_id:
            return f"{student_name} ({student_id})"
        return student_name or student_id

    def _prepare_candidates(
        self,
        raw_candidates: Sequence[ImportCandidate],
        *,
        student_overrides: Optional[Mapping[str, str]] = None,
    ) -> List[ImportCandidate]:
        prepared = self.importer.prepare_candidates(
            raw_candidates,
            student_overrides=student_overrides,
        )
        for candidate in prepared:
            selected_root = self._latex_project_root_overrides.get(
                candidate.candidate_id
            )
            if selected_root:
                try:
                    set_candidate_latex_project_root(candidate, selected_root)
                except ValueError:
                    self._latex_project_root_overrides.pop(
                        candidate.candidate_id, None
                    )
            apply_latex_project_preview_validation(candidate)
        return prepared

    def _populate_table(self) -> None:
        self._rebuilding = True
        try:
            self.table.setRowCount(len(self._candidates))
            for row, candidate in enumerate(self._candidates):
                select_item = QTableWidgetItem("")
                select_item.setData(Qt.UserRole, candidate.candidate_id)
                selectable = candidate.validation_status in {
                    VALIDATION_STATUS_READY,
                    VALIDATION_STATUS_DUPLICATE,
                }
                select_item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                    if selectable
                    else Qt.ItemIsSelectable
                )
                select_item.setCheckState(
                    Qt.Checked
                    if candidate.validation_status == VALIDATION_STATUS_READY
                    else Qt.Unchecked
                )
                self.table.setItem(row, 0, select_item)

                filenames = ", ".join(
                    item.original_filename for item in candidate.files
                ) or "—"
                file_item = QTableWidgetItem(filenames)
                file_item.setToolTip("\n".join(item.source_path for item in candidate.files))
                self.table.setItem(row, 1, file_item)

                combo = QComboBox(self.table)
                combo.setObjectName(f"submissionStudentMap_{row}")
                combo.addItem("— Select student —", "")
                for record in self.roster:
                    student_id = str(getattr(record, "student_id", "") or "").strip()
                    if not student_id:
                        continue
                    combo.addItem(self._student_display(record), student_id)
                target_id = str(candidate.proposed_student_id or "")
                if target_id:
                    for index in range(combo.count()):
                        if str(combo.itemData(index) or "") == target_id:
                            combo.setCurrentIndex(index)
                            break
                combo.currentIndexChanged.connect(self._mapping_changed)
                self.table.setCellWidget(row, 2, combo)

                attempt = "—" if candidate.proposed_attempt is None else str(candidate.proposed_attempt)
                self.table.setItem(row, 3, QTableWidgetItem(attempt))
                self.table.setItem(
                    row,
                    4,
                    QTableWidgetItem(self._friendly_status(candidate)),
                )
                details_item = QTableWidgetItem(self._candidate_details(candidate))
                details_item.setToolTip(self._candidate_details(candidate, multiline=True))
                self.table.setItem(row, 5, details_item)
        finally:
            self._rebuilding = False
        self._update_summary()

    def _friendly_status(self, candidate: ImportCandidate) -> str:
        if latex_project_root_selection_required(candidate):
            return "Choose project root"
        status = candidate.validation_status
        mapping = {
            "ready": "Ready",
            "duplicate": "Exact duplicate",
            "needs_mapping": "Needs student mapping",
            "invalid": "Invalid",
            "unsupported": "Unsupported",
            "error": "Error",
            "pending": "Pending",
        }
        return mapping.get(status, status.replace("_", " ").title())

    def _candidate_details(self, candidate: ImportCandidate, *, multiline: bool = False) -> str:
        values: List[str] = []
        preview = candidate_latex_project_preview(candidate)
        if preview is not None:
            selected_root = str(
                candidate.metadata.get(LATEX_PROJECT_ROOT_METADATA_KEY) or ""
            ).strip()
            if selected_root:
                values.append("LaTeX project root: %s" % selected_root)
            elif preview.requires_root_selection:
                values.append(
                    "Choose LaTeX root: %s"
                    % ", ".join(preview.candidate_paths)
                )
            elif preview.error_message:
                values.append("LaTeX project: %s" % preview.error_message)
        duplicate = candidate.metadata.get("duplicate_status")
        if duplicate and duplicate not in {"none", "not_checked"}:
            values.append(str(duplicate).replace("_", " "))
        values.extend(str(value) for value in candidate.warnings)
        values.extend(str(value) for value in candidate.errors)
        separator = "\n" if multiline else "; "
        return separator.join(dict.fromkeys(values)) if values else "—"

    def _mapping_changed(self) -> None:
        if self._rebuilding or not self._raw_candidates:
            return
        overrides: Dict[str, str] = {}
        for row, candidate in enumerate(self._candidates):
            combo = self.table.cellWidget(row, 2)
            if isinstance(combo, QComboBox):
                student_id = str(combo.currentData() or "").strip()
                if student_id:
                    overrides[candidate.candidate_id] = student_id
        try:
            self._candidates = self._prepare_candidates(
                self._raw_candidates,
                student_overrides=overrides,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Student Mapping Error", str(exc))
            return
        self._populate_table()

    def _selection_changed(self, item: QTableWidgetItem) -> None:
        """Refresh selection-dependent UI after an Import checkbox toggle."""
        if self._rebuilding or self._workers:
            return
        if item is None or item.column() != 0:
            return
        self._update_summary()

    def _selected_candidates(self) -> List[ImportCandidate]:
        selected: List[ImportCandidate] = []
        by_id = {item.candidate_id: item for item in self._candidates}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            candidate_id = str(item.data(Qt.UserRole) or "")
            candidate = by_id.get(candidate_id)
            if candidate is not None:
                selected.append(candidate)
        return selected

    def _update_summary(self) -> None:
        ready = sum(
            item.validation_status == VALIDATION_STATUS_READY
            for item in self._candidates
        )
        duplicates = sum(
            item.validation_status == VALIDATION_STATUS_DUPLICATE
            for item in self._candidates
        )
        unresolved = len(self._candidates) - ready - duplicates
        roots_needed = sum(
            latex_project_root_selection_required(item)
            for item in self._candidates
        )
        selected = len(self._selected_candidates()) if self._candidates else 0
        if not self._candidates:
            text = "No submissions selected."
        else:
            text = (
                f"{len(self._candidates)} candidate(s): {ready} ready, "
                f"{duplicates} exact duplicate(s), {unresolved} needing attention. "
                f"{roots_needed} LaTeX project root choice(s) pending. "
                f"{selected} selected for import."
            )
        self.status_label.setText(text)
        self.import_button.setEnabled(bool(selected) and not self._workers)
        self.clear_button.setEnabled(not self._workers)

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def _resolve_latex_project_roots(
        self,
        selected: Sequence[ImportCandidate],
    ) -> bool:
        for candidate in selected:
            if not latex_project_root_selection_required(candidate):
                continue
            preview = candidate_latex_project_preview(candidate)
            if preview is None:
                continue
            student_label = str(candidate.proposed_student_id or "").strip()
            archive_name = preview.archive_name or ", ".join(
                item.original_filename for item in candidate.files
            )
            dialog = LatexProjectRootSelectionDialog(
                preview.candidate_paths,
                archive_name=archive_name,
                student_label=student_label,
                preferred_hints=preview.metadata.get(
                    "preferred_name_hints", []
                ),
                parent=self,
            )
            if dialog.exec_() != QDialog.Accepted or not dialog.selected_root:
                self.status_label.setText(
                    "Import cancelled before commit; LaTeX project root selection "
                    "was not completed."
                )
                return False
            selected_root = str(dialog.selected_root)
            self._latex_project_root_overrides[candidate.candidate_id] = (
                selected_root
            )
            set_candidate_latex_project_root(candidate, selected_root)
        self._populate_table()
        return True

    def _commit_selected(self) -> None:
        selected = self._selected_candidates()
        if not selected:
            QMessageBox.information(self, "Nothing Selected", "Select at least one ready submission.")
            return

        if not self._resolve_latex_project_roots(selected):
            return

        force_ids: Set[str] = {
            item.candidate_id
            for item in selected
            if item.validation_status == VALIDATION_STATUS_DUPLICATE
        }
        if force_ids:
            answer = QMessageBox.question(
                self,
                "Import Exact Duplicate?",
                "One or more selected rows are exact duplicates of evidence already stored. "
                "Importing them will create new attempts with identical bytes. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self._start_worker(
            SubmissionImportOperation.COMMIT,
            parameters={
                "candidates": selected,
                "force_duplicate_ids": sorted(force_ids),
                "make_active": True,
                "question_ids": list(self.question_ids),
                "evidence_dir": self.evidence_dir,
                "compile_pdf": True,
            },
        )

    def _start_latex_project_recovery(
        self,
        student_id: str,
        diagnostic: Mapping[str, Any],
        *,
        root_relative_path: Optional[str] = None,
    ) -> None:
        root = str(
            root_relative_path
            or diagnostic.get("root_relative_path")
            or ""
        ).strip() or None
        self._start_worker(
            SubmissionImportOperation.RECOVER_LATEX_PROJECT,
            parameters={
                "student_id": student_id,
                "root_relative_path": root,
                "question_ids": list(self.question_ids),
                "evidence_dir": self.evidence_dir,
            },
        )

    def _show_latex_project_diagnostic(
        self,
        student_id: str,
        diagnostic: Mapping[str, Any],
    ) -> None:
        dialog = LatexProjectDiagnosticsDialog(
            diagnostic,
            student_id=student_id,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        if dialog.selected_action == ACTION_RETRY:
            self._start_latex_project_recovery(student_id, diagnostic)
            return
        if dialog.selected_action != ACTION_RESELECT_ROOT:
            return

        candidates = [
            str(value)
            for value in (diagnostic.get("candidate_paths") or [])
            if str(value).strip()
        ]
        if len(candidates) < 2:
            QMessageBox.information(
                self,
                "Root Selection",
                "No alternative LaTeX root candidates are available.",
            )
            return
        root_dialog = LatexProjectRootSelectionDialog(
            candidates,
            archive_name="Persisted canonical LaTeX project",
            student_label=student_id,
            parent=self,
        )
        if root_dialog.exec_() != QDialog.Accepted or not root_dialog.selected_root:
            return
        self._start_latex_project_recovery(
            student_id,
            diagnostic,
            root_relative_path=str(root_dialog.selected_root),
        )

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _start_worker(
        self,
        operation: SubmissionImportOperation,
        *,
        parameters: Mapping[str, Any],
    ) -> str:
        worker = SubmissionImportWorker(
            self.repository,
            self.assessment_id,
            self.roster,
            operation,
            parameters=parameters,
        )
        request_id = worker.request_id
        self._workers[request_id] = worker
        worker.signals.started.connect(self._worker_started)
        worker.signals.progress.connect(self._worker_progress)
        worker.signals.completed.connect(self._worker_completed)
        worker.signals.failed.connect(self._worker_failed)
        worker.signals.cancelled.connect(self._worker_cancelled)
        worker.signals.finished.connect(self._worker_finished)
        self._set_busy(True, "Preparing submission import…")
        self.thread_pool.start(worker)
        return request_id

    def _set_busy(self, busy: bool, message: Optional[str] = None) -> None:
        busy = bool(busy)
        self.add_files_button.setEnabled(not busy)
        self.add_folder_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        if message:
            self.status_label.setText(message)
        self._update_summary() if not busy else self.import_button.setEnabled(False)

    def _worker_started(self, request_id: str, operation: str) -> None:
        if request_id in self._workers:
            self._set_busy(True, "Working…")

    def _worker_progress(self, request_id: str, operation: str, message: str) -> None:
        if request_id in self._workers:
            self.status_label.setText(str(message))

    def _worker_completed(self, request_id: str, operation: str, payload: Any) -> None:
        if request_id not in self._workers:
            return
        if operation == SubmissionImportOperation.RECOVER_LATEX_PROJECT.value:
            if not isinstance(payload, dict):
                QMessageBox.warning(
                    self,
                    "LaTeX Recovery",
                    "Recovery completed without a result payload.",
                )
                return
            student_id = str(payload.get("student_id") or "").strip()
            parsed_by_student = dict(payload.get("parsed_by_student", {}) or {})
            parsed = parsed_by_student.get(student_id)
            submission = payload.get("submission")
            if parsed is not None and submission is not None:
                self.evidence_recovered.emit(submission, parsed)
                QMessageBox.information(
                    self,
                    "LaTeX Recovery Complete",
                    "The canonical project re-verified successfully and its grading PDF was regenerated.",
                )
                return
            diagnostics = dict(payload.get("latex_project_diagnostics", {}) or {})
            diagnostic = diagnostics.get(student_id)
            if diagnostic is not None:
                self._show_latex_project_diagnostic(student_id, diagnostic)
            return

        if operation in {
            SubmissionImportOperation.DISCOVER_FILES.value,
            SubmissionImportOperation.DISCOVER_DIRECTORY.value,
        }:
            raw = payload.get("raw_candidates", []) if isinstance(payload, dict) else []
            prepared = payload.get("candidates", []) if isinstance(payload, dict) else []
            # A later discovery adds to the current preview rather than replacing
            # it. Candidate IDs are opaque and unique, so re-preparation safely
            # handles duplicate bytes in the combined batch.
            self._raw_candidates.extend(raw)
            self._candidates = self._prepare_candidates(self._raw_candidates)
            self._populate_table()
            if not prepared and not raw:
                self.status_label.setText("No supported files were found in that selection.")
            return

        if operation == SubmissionImportOperation.COMMIT.value:
            if not isinstance(payload, dict):
                QMessageBox.warning(self, "Import Result", "Import completed without a result payload.")
                return
            result = payload.get("commit_result")
            imported_count = int(getattr(getattr(result, "batch", None), "imported_count", 0) or 0)
            error_count = int(getattr(getattr(result, "batch", None), "error_count", 0) or 0)
            if imported_count:
                self.imports_committed.emit(payload)
            # Re-evaluate the same preview against the updated repository so
            # successfully imported rows become exact duplicates and are no
            # longer selected by default.
            self._candidates = self._prepare_candidates(self._raw_candidates)
            self._populate_table()
            parse_errors = dict(payload.get("parse_errors", {}) or {})
            unresolved_roots = dict(
                payload.get("root_resolution_required", {}) or {}
            )
            latex_diagnostics = dict(
                payload.get("latex_project_diagnostics", {}) or {}
            )
            if error_count or parse_errors or unresolved_roots or latex_diagnostics:
                errors = getattr(result, "errors", {}) or {}
                details: List[str] = []
                details.extend(str(value) for value in errors.values())
                details.extend(
                    "Grading evidence for %s: %s" % (student_id, message)
                    for student_id, message in sorted(parse_errors.items())
                )
                details.extend(
                    "LaTeX project root still unresolved for %s" % student_id
                    for student_id in sorted(unresolved_roots)
                )
                details.extend(
                    "LaTeX project for %s: %s"
                    % (
                        student_id,
                        str(diagnostic.get("error_message") or diagnostic.get("status") or "attention required"),
                    )
                    for student_id, diagnostic in sorted(latex_diagnostics.items())
                )
                QMessageBox.warning(
                    self,
                    "Import Completed with Attention Needed",
                    f"Imported {imported_count} submission(s); {error_count} canonical "
                    "import(s) failed.\n\n" + "\n".join(details),
                )
                for student_id, diagnostic in sorted(latex_diagnostics.items()):
                    self._show_latex_project_diagnostic(student_id, diagnostic)
            else:
                QMessageBox.information(
                    self,
                    "Import Complete",
                    f"Imported {imported_count} submission(s). Original evidence is "
                    "stored canonically and supported Written grading evidence was prepared.",
                )

    def _worker_failed(
        self,
        request_id: str,
        operation: str,
        error_type: str,
        error_message: str,
    ) -> None:
        if request_id not in self._workers:
            return
        QMessageBox.critical(
            self,
            "Submission Import Error",
            f"{error_type}: {error_message}",
        )

    def _worker_cancelled(self, request_id: str, operation: str) -> None:
        if request_id in self._workers:
            self.status_label.setText("Import operation cancelled.")

    def _worker_finished(self, request_id: str, operation: str) -> None:
        self._workers.pop(request_id, None)
        if not self._workers:
            self._set_busy(False)

    def reject(self) -> None:
        for worker in list(self._workers.values()):
            worker.cancel()
        super().reject()


__all__ = ["SubmissionImportDialog"]
