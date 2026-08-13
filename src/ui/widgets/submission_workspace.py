"""Resizable two-pane submission evidence workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.submissions.models import (
    SUBMISSION_MODE_LATEX,
    SUBMISSION_MODE_PDF_ACCOMMODATION,
    ParsedSubmission,
)
from src.ui.widgets.pdf_viewer import PdfDocumentViewer
from src.ui.widgets.submission_text_panel import SubmissionTextPanel


class SubmissionWorkspace(QFrame):
    """Document + answer/source workspace shared by LaTeX and accommodations.

    The widget is intentionally presentation-only.  Parsing, persistence, and
    model inference remain in the submission backend/controller/worker layers.
    """

    open_source_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal(str)
    generate_transcription_requested = pyqtSignal(str)
    focus_requested = pyqtSignal(bool)

    def __init__(self, parent=None, *, allow_focus=True, allow_popout=True):
        super().__init__(parent)
        self.setObjectName("submissionWorkspace")
        self._submission: Optional[ParsedSubmission] = None
        self._question_id: Optional[str] = None
        self._busy = False
        self._focus_mode = False
        self._allow_focus = bool(allow_focus)
        self._allow_popout = bool(allow_popout)
        self._last_splitter_sizes = [600, 500]
        self._popout_dialog = None
        self._popout_workspace = None
        self._build_ui()
        self.clear_submission()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("submissionWorkspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)

        title = QLabel("Submission Evidence", header)
        title.setObjectName("submissionWorkspaceTitle")
        header_layout.addWidget(title)

        self.status_badge = QLabel("No submission", header)
        self.status_badge.setObjectName("submissionWorkspaceStatus")
        header_layout.addWidget(self.status_badge)
        header_layout.addStretch(1)

        self.open_source_button = QPushButton("Open Source", header)
        self.open_source_button.setProperty("workspaceAction", "secondary")
        self.open_source_button.clicked.connect(self._emit_open_source)
        header_layout.addWidget(self.open_source_button)

        self.generate_transcription_button = QPushButton("Generate Transcription", header)
        self.generate_transcription_button.setProperty("workspaceAction", "primary")
        self.generate_transcription_button.clicked.connect(self._emit_generate_transcription)
        header_layout.addWidget(self.generate_transcription_button)

        self.refresh_button = QPushButton("Refresh", header)
        self.refresh_button.setProperty("workspaceAction", "secondary")
        self.refresh_button.clicked.connect(self._emit_refresh)
        header_layout.addWidget(self.refresh_button)

        self.focus_button = QPushButton("Focus", header)
        self.focus_button.setProperty("workspaceAction", "secondary")
        self.focus_button.setToolTip("Temporarily give the submission most of the main window")
        self.focus_button.clicked.connect(self._toggle_focus)
        self.focus_button.setVisible(self._allow_focus)
        header_layout.addWidget(self.focus_button)

        self.popout_button = QPushButton("Pop Out", header)
        self.popout_button.setProperty("workspaceAction", "secondary")
        self.popout_button.setToolTip("Open the submission in a separate resizable window")
        self.popout_button.clicked.connect(self.show_popout)
        self.popout_button.setVisible(self._allow_popout)
        header_layout.addWidget(self.popout_button)

        self.toggle_document_button = QToolButton(header)
        self.toggle_document_button.setText("◀")
        self.toggle_document_button.setToolTip("Collapse/restore document pane")
        self.toggle_document_button.clicked.connect(self.toggle_document_panel)
        header_layout.addWidget(self.toggle_document_button)

        self.toggle_text_button = QToolButton(header)
        self.toggle_text_button.setText("▶")
        self.toggle_text_button.setToolTip("Collapse/restore text pane")
        self.toggle_text_button.clicked.connect(self.toggle_text_panel)
        header_layout.addWidget(self.toggle_text_button)

        outer.addWidget(header)

        self.busy_label = QLabel("", self)
        self.busy_label.setObjectName("submissionWorkspaceBusy")
        self.busy_label.setContentsMargins(10, 6, 10, 6)
        self.busy_label.setVisible(False)
        outer.addWidget(self.busy_label)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setObjectName("submissionEvidenceSplitter")
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(6)

        self.pdf_viewer = PdfDocumentViewer(self.splitter)
        self.text_panel = SubmissionTextPanel(self.splitter)
        self.splitter.addWidget(self.pdf_viewer)
        self.splitter.addWidget(self.text_panel)
        self.splitter.setStretchFactor(0, 6)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setSizes(self._last_splitter_sizes)
        self.splitter.splitterMoved.connect(self._remember_splitter_sizes)
        outer.addWidget(self.splitter, 1)

        self.empty_state = QLabel(
            "No submission loaded for this student.\nLoad or prepare submission evidence to use this workspace.",
            self,
        )
        self.empty_state.setObjectName("submissionWorkspaceEmpty")
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setWordWrap(True)
        outer.addWidget(self.empty_state, 1)

        self.setStyleSheet(
            """
            QFrame#submissionWorkspace {
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 8px;
            }
            QWidget#submissionWorkspaceHeader {
                background: #FFFFFF;
                border: none;
                border-bottom: 1px solid #E6E9EF;
            }
            QLabel#submissionWorkspaceTitle {
                color: #1F2937;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#submissionWorkspaceStatus {
                color: #475467;
                background-color: #F2F4F7;
                border: 1px solid #E6E9EF;
                border-radius: 9px;
                padding: 2px 7px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#submissionWorkspaceBusy {
                color: #304DAF;
                background-color: #EEF2FF;
                border-bottom: 1px solid #DCE4FF;
            }
            QLabel#submissionWorkspaceEmpty {
                color: #667085;
                background-color: #F9FAFB;
                padding: 32px;
            }
            QPushButton[workspaceAction="primary"] {
                color: #FFFFFF;
                background-color: #3B5CCC;
                border: 1px solid #3B5CCC;
                border-radius: 5px;
                padding: 5px 9px;
                font-weight: 600;
            }
            QPushButton[workspaceAction="primary"]:hover {
                background-color: #304DAF;
                border-color: #304DAF;
            }
            QPushButton[workspaceAction="secondary"] {
                color: #475467;
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 5px;
                padding: 5px 9px;
            }
            QPushButton[workspaceAction="secondary"]:hover {
                color: #1F2937;
                background-color: #F9FAFB;
                border-color: #C8CFDA;
            }
            QPushButton:disabled {
                color: #98A2B3;
                background-color: #EEF1F5;
                border-color: #E6E9EF;
            }
            QToolButton {
                color: #667085;
                background: transparent;
                border: 1px solid #D9DEE7;
                border-radius: 5px;
                padding: 4px 7px;
            }
            QToolButton:hover {
                color: #1F2937;
                background-color: #F9FAFB;
            }
            QSplitter#submissionEvidenceSplitter::handle {
                background-color: #E6E9EF;
            }
            QSplitter#submissionEvidenceSplitter::handle:hover {
                background-color: #C8CFDA;
            }
            """
        )

    # ------------------------------------------------------------------
    # Public API expected by MainWindow Batch A hooks
    # ------------------------------------------------------------------

    @property
    def submission(self):
        return self._submission

    @property
    def question_id(self):
        return self._question_id

    def set_submission(self, parsed_submission):
        if parsed_submission is None:
            self.clear_submission(keep_question=True)
            return

        self._submission = parsed_submission
        self.empty_state.setVisible(False)
        self.splitter.setVisible(True)
        self.text_panel.set_submission(parsed_submission)
        self.text_panel.set_question(self._question_id)
        self._configure_document_view(parsed_submission)
        self._update_actions_and_status(parsed_submission)
        if self._popout_workspace is not None:
            self._popout_workspace.set_submission(parsed_submission)
            self._popout_workspace.set_question(self._question_id)

    def set_question(self, question_id):
        self._question_id = str(question_id).strip() if question_id else None
        self.text_panel.set_question(self._question_id)
        if self._popout_workspace is not None:
            self._popout_workspace.set_question(self._question_id)

    def clear_submission(self, *, keep_question=False):
        self._submission = None
        if not keep_question:
            self._question_id = None
        self.pdf_viewer.clear_document()
        self.text_panel.clear_submission()
        if keep_question:
            self.text_panel.set_question(self._question_id)
        self.splitter.setVisible(False)
        self.empty_state.setVisible(True)
        self.status_badge.setText("No submission")
        self.status_badge.setStyleSheet("")
        self.open_source_button.setVisible(False)
        self.generate_transcription_button.setVisible(False)
        self.refresh_button.setVisible(False)
        self.focus_button.setEnabled(False)
        self.popout_button.setEnabled(False)
        if self._popout_workspace is not None:
            self._popout_workspace.clear_submission(keep_question=keep_question)
        self.set_busy(False)

    def set_busy(self, busy, message="Preparing submission evidence…"):
        self._busy = bool(busy)
        self.busy_label.setText(str(message or "Preparing submission evidence…"))
        self.busy_label.setVisible(self._busy)
        for button in (
            self.open_source_button,
            self.generate_transcription_button,
            self.refresh_button,
            self.focus_button,
            self.popout_button,
        ):
            button.setEnabled(not self._busy and self._submission is not None)
        if self._popout_workspace is not None:
            self._popout_workspace.set_busy(self._busy, message)

    def splitter_sizes(self):
        return list(self.splitter.sizes())

    def set_splitter_sizes(self, sizes):
        values = [max(0, int(value)) for value in list(sizes or [])[:2]]
        if len(values) == 2 and any(values):
            self._last_splitter_sizes = values[:]
            self.splitter.setSizes(values)

    def collapse_document_panel(self):
        self._store_nonzero_sizes()
        sizes = self.splitter.sizes()
        total = max(1, sum(sizes))
        self.splitter.setSizes([0, total])
        self._update_collapse_buttons()

    def restore_document_panel(self):
        self._restore_splitter_sizes()

    def collapse_text_panel(self):
        self._store_nonzero_sizes()
        sizes = self.splitter.sizes()
        total = max(1, sum(sizes))
        self.splitter.setSizes([total, 0])
        self._update_collapse_buttons()

    def restore_text_panel(self):
        self._restore_splitter_sizes()

    def toggle_document_panel(self):
        sizes = self.splitter.sizes()
        if len(sizes) >= 2 and sizes[0] <= 1:
            self.restore_document_panel()
        else:
            self.collapse_document_panel()

    def toggle_text_panel(self):
        sizes = self.splitter.sizes()
        if len(sizes) >= 2 and sizes[1] <= 1:
            self.restore_text_panel()
        else:
            self.collapse_text_panel()

    # ------------------------------------------------------------------
    # Focus / pop-out viewing
    # ------------------------------------------------------------------

    @property
    def focus_mode(self):
        return self._focus_mode

    def set_focus_mode(self, enabled):
        self._focus_mode = bool(enabled)
        self.focus_button.setText("Exit Focus" if self._focus_mode else "Focus")
        self.focus_button.setToolTip(
            "Return to grading workspace"
            if self._focus_mode
            else "Temporarily give the submission most of the main window"
        )

    def _toggle_focus(self):
        if not self._allow_focus or self._submission is None:
            return
        self.focus_requested.emit(not self._focus_mode)

    def show_popout(self):
        """Show the same evidence in a separate, non-destructive viewer window."""
        if not self._allow_popout or self._submission is None:
            return

        if self._popout_dialog is not None:
            self._popout_dialog.show()
            self._popout_dialog.raise_()
            self._popout_dialog.activateWindow()
            return

        dialog = QDialog(self.window())
        dialog.setWindowTitle("Submission Evidence")
        dialog.resize(1400, 900)
        dialog.setMinimumSize(900, 600)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)

        workspace = SubmissionWorkspace(
            dialog,
            allow_focus=False,
            allow_popout=False,
        )
        workspace.open_source_requested.connect(self.open_source_requested.emit)
        workspace.refresh_requested.connect(self.refresh_requested.emit)
        workspace.generate_transcription_requested.connect(
            self.generate_transcription_requested.emit
        )
        workspace.set_submission(self._submission)
        workspace.set_question(self._question_id)
        workspace.set_busy(self._busy)
        layout.addWidget(workspace)

        self._popout_dialog = dialog
        self._popout_workspace = workspace

        def _clear_popout():
            self._popout_dialog = None
            self._popout_workspace = None

        dialog.finished.connect(lambda _result: _clear_popout())
        dialog.show()

    # ------------------------------------------------------------------
    # Submission-specific presentation
    # ------------------------------------------------------------------

    def _configure_document_view(self, parsed):
        mode = getattr(parsed, "submission_mode", SUBMISSION_MODE_LATEX)
        files = getattr(parsed, "files", {})
        files = files if isinstance(files, dict) else {}

        if mode == SUBMISSION_MODE_PDF_ACCOMMODATION or getattr(parsed, "accommodation_mode", False):
            pdf_path = files.get("pdf")
            if pdf_path and Path(str(pdf_path)).exists():
                self.pdf_viewer.set_document(
                    pdf_path,
                    title="Original submitted PDF",
                    authoritative=True,
                )
                return
            page_paths = list(getattr(parsed, "page_image_paths", []) or [])
            if page_paths:
                self.pdf_viewer.set_page_images(
                    page_paths,
                    title="Rendered pages (derived)",
                    authoritative=False,
                )
                return
            self.pdf_viewer.clear_document("Original PDF is unavailable. Grading text remains visible if present.")
            return

        compiled_pdf = files.get("compiled_pdf")
        if not compiled_pdf:
            metadata = getattr(parsed, "metadata", {})
            compilation = metadata.get("compilation", {}) if isinstance(metadata, dict) else {}
            if isinstance(compilation, dict):
                compiled_pdf = compilation.get("pdf_path")

        if compiled_pdf and Path(str(compiled_pdf)).exists():
            self.pdf_viewer.set_document(
                compiled_pdf,
                title="Compiled submission PDF",
                authoritative=False,
            )
            return

        reference_pdf = files.get("pdf")
        if reference_pdf and Path(str(reference_pdf)).exists():
            self.pdf_viewer.set_document(
                reference_pdf,
                title="Student reference PDF",
                authoritative=False,
            )
            return

        self.pdf_viewer.clear_document(
            "Compiled PDF is unavailable. The canonical LaTeX source and extracted answer remain available."
        )

    def _update_actions_and_status(self, parsed):
        mode = getattr(parsed, "submission_mode", SUBMISSION_MODE_LATEX)
        files = getattr(parsed, "files", {})
        files = files if isinstance(files, dict) else {}
        self.open_source_button.setVisible(True)
        self.refresh_button.setVisible(True)
        self.focus_button.setEnabled(True)
        self.popout_button.setEnabled(True)

        if mode == SUBMISSION_MODE_PDF_ACCOMMODATION or getattr(parsed, "accommodation_mode", False):
            self.open_source_button.setText("Open Original PDF")
            transcription = getattr(parsed, "transcription_metadata", {})
            transcription = transcription if isinstance(transcription, dict) else {}
            status = str(transcription.get("status") or "not_requested")
            cache = transcription.get("cache") if isinstance(transcription.get("cache"), dict) else {}
            cached = cache.get("status") == "hit"

            if status == "successful":
                self.status_badge.setText("Transcription ready · cached" if cached else "Transcription ready")
                self._set_status_state("ready")
                self.generate_transcription_button.setVisible(False)
            else:
                self.status_badge.setText("Original PDF ready · transcription unavailable" if status not in {"not_requested", ""} else "Original PDF ready")
                self._set_status_state("warning" if status not in {"not_requested", ""} else "neutral")
                self.generate_transcription_button.setText(
                    "Retry Transcription" if status not in {"not_requested", ""} else "Generate Transcription"
                )
                self.generate_transcription_button.setVisible(True)
            return

        self.open_source_button.setText("Open LaTeX Source")
        self.generate_transcription_button.setVisible(False)
        if self.pdf_viewer.has_document:
            self.status_badge.setText("LaTeX submission ready")
            self._set_status_state("ready")
        else:
            self.status_badge.setText("LaTeX source ready · PDF unavailable")
            self._set_status_state("warning")

    def _set_status_state(self, state):
        palette = {
            "ready": ("#2E7D5B", "#EEF7F2", "#D4EADF"),
            "warning": ("#A66B16", "#FFF8EA", "#F0DFC0"),
            "error": ("#B94A48", "#FDF1F1", "#EECFCF"),
            "neutral": ("#475467", "#F2F4F7", "#E6E9EF"),
        }
        fg, bg, border = palette.get(state, palette["neutral"])
        self.status_badge.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border: 1px solid {border}; "
            "border-radius: 9px; padding: 2px 7px; font-size: 11px; font-weight: 600;"
        )

    # ------------------------------------------------------------------
    # Signals / splitters
    # ------------------------------------------------------------------

    def _active_student_id(self):
        return str(getattr(self._submission, "student_id", "") or "")

    def _emit_open_source(self):
        if self._submission is None:
            return
        files = getattr(self._submission, "files", {})
        files = files if isinstance(files, dict) else {}
        if getattr(self._submission, "accommodation_mode", False):
            path = files.get("pdf")
        else:
            path = files.get("latex") or files.get("compiled_pdf") or files.get("pdf")
        if path:
            self.open_source_requested.emit(str(path))

    def _emit_refresh(self):
        student_id = self._active_student_id()
        if student_id:
            self.refresh_requested.emit(student_id)

    def _emit_generate_transcription(self):
        student_id = self._active_student_id()
        if student_id:
            self.generate_transcription_requested.emit(student_id)

    def _remember_splitter_sizes(self, _pos, _index):
        sizes = self.splitter.sizes()
        if len(sizes) >= 2 and sizes[0] > 8 and sizes[1] > 8:
            self._last_splitter_sizes = sizes[:2]
        self._update_collapse_buttons()

    def _store_nonzero_sizes(self):
        sizes = self.splitter.sizes()
        if len(sizes) >= 2 and sizes[0] > 8 and sizes[1] > 8:
            self._last_splitter_sizes = sizes[:2]

    def _restore_splitter_sizes(self):
        sizes = self._last_splitter_sizes
        if len(sizes) != 2 or not all(value > 0 for value in sizes):
            sizes = [600, 500]
        self.splitter.setSizes(sizes)
        self._update_collapse_buttons()

    def _update_collapse_buttons(self):
        sizes = self.splitter.sizes()
        if len(sizes) < 2:
            return
        self.toggle_document_button.setText("▶" if sizes[0] <= 1 else "◀")
        self.toggle_text_button.setText("◀" if sizes[1] <= 1 else "▶")
