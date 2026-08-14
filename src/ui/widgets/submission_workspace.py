"""Submission-first evidence viewer used by the Commit-5 grading workspace.

The main grading layout intentionally follows a Gradescope-like model: the
student's rendered submission stays visible on the left while rubric controls
remain visible on the right.  Machine-readable artifacts (LaTeX source,
extracted answer text, selectable PDF text, or VLM transcription) are retained
for provenance and later LLM grading, but are opened on demand instead of
permanently consuming half of the grading workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import json

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFontDatabase
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.submissions.reference_solution import ReferenceSolution
from src.submissions.models import (
    SUBMISSION_MODE_LATEX,
    SUBMISSION_MODE_PDF_ACCOMMODATION,
    ParsedSubmission,
)
from src.ui.widgets.pdf_viewer import PdfDocumentViewer


class EvidenceTextDialog(QDialog):
    """Read-only viewer for source, extracted answer text, or transcription."""

    def __init__(
        self,
        title: str,
        text: str,
        *,
        notice: str = "",
        fixed_font=False,
        open_path: Optional[str] = None,
        open_label: str = "Open Full Solution",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 700)
        self.setMinimumSize(650, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading = QLabel(title, self)
        heading.setObjectName("evidenceTextDialogTitle")
        layout.addWidget(heading)

        self.notice_label = QLabel(notice, self)
        self.notice_label.setObjectName("evidenceTextDialogNotice")
        self.notice_label.setWordWrap(True)
        self.notice_label.setVisible(bool(notice))
        layout.addWidget(self.notice_label)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(str(text or ""))
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap if fixed_font else QPlainTextEdit.WidgetWidth)
        if fixed_font:
            self.text_edit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        layout.addWidget(self.text_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        if open_path:
            open_button = buttons.addButton(str(open_label), QDialogButtonBox.ActionRole)
            open_button.clicked.connect(
                lambda _checked=False, p=str(open_path): QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(Path(p).expanduser().resolve()))
                )
            )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet(
            """
            QLabel#evidenceTextDialogTitle {
                color: #1F2937;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#evidenceTextDialogNotice {
                color: #667085;
                background: #F9FAFB;
                border: 1px solid #E6E9EF;
                border-radius: 6px;
                padding: 8px 10px;
            }
            QPlainTextEdit {
                color: #1F2937;
                background: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 6px;
                padding: 10px;
                selection-background-color: #DCE4FF;
            }
            """
        )


class SubmissionWorkspace(QFrame):
    """Rendered submission viewer with on-demand machine-readable evidence.

    Manual grading should primarily use the rendered/canonical visual evidence.
    Parsed text and VLM transcription remain available because they are useful
    for navigation today and will become inputs to later LLM-assisted grading.
    """

    open_source_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal(str)
    generate_transcription_requested = pyqtSignal(str)
    focus_requested = pyqtSignal(bool)
    popout_workspace_requested = pyqtSignal()

    def __init__(self, parent=None, *, allow_focus=True, allow_popout=True):
        super().__init__(parent)
        self.setObjectName("submissionWorkspace")
        self._submission: Optional[ParsedSubmission] = None
        self._reference_solution: Optional[ReferenceSolution] = None
        self._question_id: Optional[str] = None
        self._busy = False
        self._focus_mode = False
        self._allow_focus = bool(allow_focus)
        self._allow_popout = bool(allow_popout)
        self._text_dialogs = []
        self._build_ui()
        self.clear_submission()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("submissionWorkspaceHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 7, 10, 7)
        header_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(7)
        title = QLabel("Student Submission", header)
        title.setObjectName("submissionWorkspaceTitle")
        title_row.addWidget(title)

        self.status_badge = QLabel("No submission", header)
        self.status_badge.setObjectName("submissionWorkspaceStatus")
        title_row.addWidget(self.status_badge)
        title_row.addStretch(1)
        header_layout.addLayout(title_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.view_answer_button = QPushButton("Student Response", header)
        self.view_answer_button.setToolTip(
            "View the machine-readable response extracted for this student's current question"
        )
        self.view_answer_button.setProperty("workspaceAction", "secondary")
        self.view_answer_button.clicked.connect(self.show_extracted_answer)
        # Public alias with terminology that does not imply a correct answer.
        self.student_response_button = self.view_answer_button
        action_row.addWidget(self.view_answer_button)

        self.reference_solution_button = QPushButton("Reference Solution", header)
        self.reference_solution_button.setToolTip(
            "View the instructor-provided reference solution for the current question"
        )
        self.reference_solution_button.setProperty("workspaceAction", "secondary")
        self.reference_solution_button.clicked.connect(self.show_reference_solution)
        action_row.addWidget(self.reference_solution_button)

        self.view_machine_text_button = QPushButton("Source", header)
        self.view_machine_text_button.setProperty("workspaceAction", "secondary")
        self.view_machine_text_button.clicked.connect(self.show_machine_readable_text)
        action_row.addWidget(self.view_machine_text_button)

        self.open_source_button = QPushButton("Open", header)
        self.open_source_button.setProperty("workspaceAction", "secondary")
        self.open_source_button.clicked.connect(self._emit_open_source)
        action_row.addWidget(self.open_source_button)

        self.generate_transcription_button = QPushButton("Transcribe Scan", header)
        self.generate_transcription_button.setProperty("workspaceAction", "primary")
        self.generate_transcription_button.clicked.connect(self._emit_generate_transcription)
        action_row.addWidget(self.generate_transcription_button)

        self.transcription_details_button = QPushButton("View Details", header)
        self.transcription_details_button.setProperty("workspaceAction", "secondary")
        self.transcription_details_button.setToolTip("Show why scan transcription failed")
        self.transcription_details_button.clicked.connect(self.show_transcription_details)
        action_row.addWidget(self.transcription_details_button)

        self.refresh_button = QPushButton("Refresh", header)
        self.refresh_button.setProperty("workspaceAction", "secondary")
        self.refresh_button.clicked.connect(self._emit_refresh)
        action_row.addWidget(self.refresh_button)

        action_row.addStretch(1)

        self.focus_button = QPushButton("Focus", header)
        self.focus_button.setProperty("workspaceAction", "secondary")
        self.focus_button.setToolTip("Temporarily maximize the submission viewer")
        self.focus_button.clicked.connect(self._toggle_focus)
        self.focus_button.setVisible(self._allow_focus)
        action_row.addWidget(self.focus_button)

        self.popout_button = QPushButton("Pop Out Workspace", header)
        self.popout_button.setProperty("workspaceAction", "secondary")
        self.popout_button.setToolTip("Open the submission and grading panes together in a separate window")
        self.popout_button.clicked.connect(self._emit_popout_workspace)
        self.popout_button.setVisible(self._allow_popout)
        action_row.addWidget(self.popout_button)

        header_layout.addLayout(action_row)
        outer.addWidget(header)

        self.busy_label = QLabel("", self)
        self.busy_label.setObjectName("submissionWorkspaceBusy")
        self.busy_label.setContentsMargins(10, 6, 10, 6)
        self.busy_label.setVisible(False)
        outer.addWidget(self.busy_label)

        # The permanent body is intentionally document-only.  Source,
        # extracted answer text, and transcription are opened on demand.
        self.pdf_viewer = PdfDocumentViewer(self)
        outer.addWidget(self.pdf_viewer, 1)

        self.empty_state = QLabel(
            "No submission loaded for this student.\n"
            "Load submissions or prepare PDF evidence to begin grading.",
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
            """
        )

    # ------------------------------------------------------------------
    # Public API used by MainWindow
    # ------------------------------------------------------------------

    @property
    def submission(self):
        return self._submission

    @property
    def question_id(self):
        return self._question_id

    @property
    def focus_mode(self):
        return self._focus_mode

    @property
    def reference_solution(self):
        return self._reference_solution

    def set_reference_solution(self, reference_solution):
        if reference_solution is not None and not isinstance(reference_solution, ReferenceSolution):
            raise TypeError("reference_solution must be a ReferenceSolution or None")
        self._reference_solution = reference_solution
        if hasattr(self, "reference_solution_button"):
            self.reference_solution_button.setEnabled(
                reference_solution is not None and not self._busy and self._submission is not None
            )
            self.reference_solution_button.setToolTip(
                "View the instructor-provided reference solution for the current question"
                if reference_solution is not None
                else "No reference solution has been loaded for this assignment"
            )

    def set_submission(self, parsed_submission):
        if parsed_submission is None:
            self.clear_submission(keep_question=True)
            return

        self._submission = parsed_submission
        self.empty_state.setVisible(False)
        self.pdf_viewer.setVisible(True)
        self._configure_document_view(parsed_submission)
        self._update_actions_and_status(parsed_submission)
        # clear_submission() intentionally disables all evidence actions while no
        # submission is active.  Re-enabling a real submission must therefore
        # also restore the action state; otherwise buttons can remain disabled
        # even though the status badge says the submission is ready.
        self.set_busy(False)

    def set_question(self, question_id):
        self._question_id = str(question_id).strip() if question_id else None

    def clear_submission(self, *, keep_question=False):
        self._submission = None
        if not keep_question:
            self._question_id = None
        self.pdf_viewer.clear_document()
        self.pdf_viewer.setVisible(False)
        self.empty_state.setVisible(True)
        self.status_badge.setText("No submission")
        self.status_badge.setStyleSheet("")
        for button in (
            self.view_answer_button,
            self.reference_solution_button,
            self.view_machine_text_button,
            self.open_source_button,
            self.generate_transcription_button,
            self.transcription_details_button,
            self.refresh_button,
        ):
            button.setVisible(False)
        self.focus_button.setEnabled(False)
        self.popout_button.setEnabled(False)
        self.set_busy(False)

    def set_busy(self, busy, message="Preparing submission evidence…"):
        self._busy = bool(busy)
        self.busy_label.setText(str(message or "Preparing submission evidence…"))
        self.busy_label.setVisible(self._busy)
        for button in (
            self.view_answer_button,
            self.reference_solution_button,
            self.view_machine_text_button,
            self.open_source_button,
            self.generate_transcription_button,
            self.transcription_details_button,
            self.refresh_button,
            self.focus_button,
            self.popout_button,
        ):
            button.setEnabled(not self._busy and self._submission is not None)
        self.reference_solution_button.setEnabled(
            not self._busy and self._submission is not None and self._reference_solution is not None
        )

    # ------------------------------------------------------------------
    # On-demand machine-readable evidence
    # ------------------------------------------------------------------

    def show_extracted_answer(self):
        """Show the student's machine-readable response for the current question."""
        parsed = self._submission
        if parsed is None:
            return
        answer, title, notice = self._answer_for_current_context(parsed)
        self._show_text_dialog(title, answer, notice=notice)

    def show_reference_solution(self):
        solution = self._reference_solution
        if solution is None:
            self._show_text_dialog(
                "Reference Solution",
                "No reference solution has been loaded for this assignment.",
                notice="Use Load Reference Solution in the main toolbar. LaTeX is recommended.",
            )
            return

        question = self._question_id
        if question:
            text = solution.answers_by_question.get(question)
            title = f"Reference Solution — {question}"
            if text is None:
                text = "No question-specific reference solution was extracted for this question."
        else:
            text = solution.raw_text or "No machine-readable reference solution text is available."
            title = "Reference Solution"

        source_label = "canonical LaTeX" if solution.source_type == "latex" else "instructor PDF"
        notice = (
            f"Instructor-provided expected solution derived from {source_label}. "
            "This is separate from the student's response and does not automatically change the grade."
        )
        self._show_text_dialog(
            title,
            text,
            notice=notice,
            fixed_font=solution.source_type == "latex",
            open_path=solution.display_pdf_path or solution.canonical_source_path,
            open_label="Open Full Solution",
        )

    def show_transcription_details(self):
        parsed = self._submission
        if parsed is None:
            return
        transcription = self._transcription_metadata(parsed)
        if not transcription:
            return
        summary = self._transcription_failure_summary(transcription)
        diagnostic = json.dumps(transcription, indent=2, sort_keys=True, ensure_ascii=False)
        self._show_text_dialog(
            "Transcription Details",
            diagnostic,
            notice=summary,
            fixed_font=True,
        )

    def show_machine_readable_text(self):
        parsed = self._submission
        if parsed is None:
            return

        mode = getattr(parsed, "submission_mode", SUBMISSION_MODE_LATEX)
        if mode != SUBMISSION_MODE_PDF_ACCOMMODATION and not getattr(parsed, "accommodation_mode", False):
            self._show_text_dialog(
                "Canonical LaTeX Source",
                self._read_latex_source(parsed),
                notice=(
                    "The .tex file is canonical and is the preferred machine-readable "
                    "representation for future automated grading."
                ),
                fixed_font=True,
            )
            return

        extraction = self._extraction_metadata(parsed)
        if extraction.get("selectable_text"):
            self._show_text_dialog(
                "Extracted PDF Text",
                str(getattr(parsed, "raw_text", "") or ""),
                notice=(
                    "Extracted deterministically from the PDF text layer with PyMuPDF. "
                    "The original submitted PDF remains authoritative."
                ),
            )
            return

        transcription = self._transcription_metadata(parsed)
        if str(transcription.get("status") or "") == "successful":
            self._show_text_dialog(
                "Assistive Scan Transcription",
                self._page_aligned_transcription(parsed),
                notice=(
                    "AI-generated transcription for machine readability. The original "
                    "submitted PDF is authoritative; verify transcription-sensitive details "
                    "before relying on it."
                ),
            )

    def _show_text_dialog(
        self,
        title,
        text,
        *,
        notice="",
        fixed_font=False,
        open_path=None,
        open_label="Open Full Solution",
    ):
        dialog = EvidenceTextDialog(
            title,
            str(text or "No text is available."),
            notice=notice,
            fixed_font=fixed_font,
            open_path=open_path,
            open_label=open_label,
            parent=self.window(),
        )
        self._text_dialogs.append(dialog)

        def _cleanup(_result):
            if dialog in self._text_dialogs:
                self._text_dialogs.remove(dialog)

        dialog.finished.connect(_cleanup)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _answer_for_current_context(self, parsed):
        answers = getattr(parsed, "answers_by_question", {})
        answers = answers if isinstance(answers, dict) else {}
        if self._question_id:
            answer = answers.get(self._question_id)
            title = f"Student Response — {self._question_id}"
            if answer is None:
                return (
                    "No machine-readable student response is available for this question.",
                    title,
                    "Use the rendered submission as the grading source.",
                )
            return (
                str(answer),
                title,
                "Question-specific text derived from this student's submission. Use the rendered submission as authoritative visual evidence.",
            )

        raw_text = str(getattr(parsed, "raw_text", "") or "")
        if raw_text:
            return (
                raw_text,
                "Student Response",
                "No single question is selected; showing available machine-readable student text.",
            )
        if answers:
            joined = "\n\n".join(f"{qid}\n{text}" for qid, text in answers.items())
            return joined, "Student Response", "Showing all extracted student-response sections."
        return "No machine-readable student response is available.", "Student Response", ""

    # ------------------------------------------------------------------
    # Focus / pop-out viewing
    # ------------------------------------------------------------------

    def set_focus_mode(self, enabled):
        self._focus_mode = bool(enabled)
        self.focus_button.setText("Exit Focus" if self._focus_mode else "Focus")
        self.focus_button.setToolTip(
            "Return to the grading workspace"
            if self._focus_mode
            else "Temporarily maximize the submission viewer"
        )

    def _toggle_focus(self):
        if not self._allow_focus or self._submission is None:
            return
        self.focus_requested.emit(not self._focus_mode)

    def show_popout(self):
        """Request pop-out of the complete submission + grading workspace.

        The MainWindow owns the grading widgets, so it must perform the actual
        reparenting. Keeping this method as a compatibility wrapper means any
        older callers still get the new whole-workspace behavior.
        """
        self._emit_popout_workspace()

    def _emit_popout_workspace(self):
        if self._allow_popout and self._submission is not None:
            self.popout_workspace_requested.emit()

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
            self.pdf_viewer.clear_document("Original PDF is unavailable.")
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
            "Compiled PDF is unavailable. Use Source / Student Response while the source remains persisted."
        )

    def _update_actions_and_status(self, parsed):
        mode = getattr(parsed, "submission_mode", SUBMISSION_MODE_LATEX)
        is_pdf = mode == SUBMISSION_MODE_PDF_ACCOMMODATION or getattr(parsed, "accommodation_mode", False)

        self.view_answer_button.setVisible(True)
        self.reference_solution_button.setVisible(True)
        self.reference_solution_button.setEnabled(self._reference_solution is not None)
        self.transcription_details_button.setVisible(False)
        self.open_source_button.setVisible(True)
        self.refresh_button.setVisible(True)
        self.focus_button.setEnabled(True)
        self.popout_button.setEnabled(True)

        if not is_pdf:
            self.status_badge.setText("LaTeX submission ready")
            self._set_status_state("ready" if self.pdf_viewer.has_document else "warning")
            self.view_machine_text_button.setText("Source")
            self.view_machine_text_button.setVisible(True)
            self.open_source_button.setText("Open .tex")
            self.generate_transcription_button.setVisible(False)
            self.refresh_button.setText("Refresh")
            return

        self.open_source_button.setText("Open Original PDF")
        extraction = self._extraction_metadata(parsed)
        transcription = self._transcription_metadata(parsed)
        trans_status = str(transcription.get("status") or "not_requested")

        if extraction.get("selectable_text"):
            self.status_badge.setText("PDF text extracted")
            self._set_status_state("ready")
            self.view_machine_text_button.setText("PDF Text")
            self.view_machine_text_button.setVisible(True)
            self.generate_transcription_button.setVisible(False)
            self.refresh_button.setText("Refresh Text")
            return

        # Scan-like PDF.  Only here is VLM transcription relevant.
        if trans_status == "successful":
            cache = transcription.get("cache") if isinstance(transcription.get("cache"), dict) else {}
            cached = cache.get("status") == "hit"
            self.status_badge.setText("Scan transcription ready · cached" if cached else "Scan transcription ready")
            self._set_status_state("warning")
            self.view_machine_text_button.setText("Transcription")
            self.view_machine_text_button.setVisible(True)
            self.generate_transcription_button.setVisible(False)
            self.refresh_button.setText("Refresh AI Text")
        else:
            self.view_machine_text_button.setVisible(False)
            failed = trans_status not in {"not_requested", ""}
            if failed:
                summary = self._transcription_failure_summary(transcription, short=True)
                self.status_badge.setText(summary)
                self._set_status_state("error")
                self.transcription_details_button.setVisible(True)
            else:
                self.status_badge.setText("Scanned PDF · transcription needed")
                self._set_status_state("warning")
            self.generate_transcription_button.setText(
                "Retry Transcription" if failed else "Transcribe Scan"
            )
            self.generate_transcription_button.setVisible(True)
            self.refresh_button.setVisible(False)

    @staticmethod
    def _transcription_failure_summary(transcription, *, short=False):
        preflight = transcription.get("preflight") if isinstance(transcription, dict) else {}
        preflight = preflight if isinstance(preflight, dict) else {}
        code = str(preflight.get("error_code") or "")
        message = str(preflight.get("error_message") or "").strip()
        if not code:
            pages = transcription.get("pages", []) if isinstance(transcription, dict) else []
            if isinstance(pages, list):
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    code = str(page.get("warning") or page.get("status") or "")
                    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
                    message = str(metadata.get("error_message") or "").strip()
                    if code:
                        break

        labels = {
            "model_load_timeout": "model loading timed out",
            "model_load_failure": "model could not be loaded",
            "connection_timeout": "Ollama connection timed out",
            "ollama_unavailable": "Ollama is unavailable",
            "model_not_installed": "configured model is not installed",
            "model_not_vision_capable": "configured model is not vision-capable",
            "inference_timeout": "transcription inference timed out",
            "generation_limit": "generation limit reached",
            "empty_output": "model returned no transcription",
            "degenerate_repetition": "model output was unusably repetitive",
            "inference_failure": "transcription inference failed",
        }
        human = labels.get(code, code.replace("_", " ") if code else "transcription failed")
        if short:
            return f"Transcription failed · {human}"
        extra = ""
        if code in {"model_load_timeout", "model_load_failure"}:
            extra = " The GPU may be busy or may not have enough free memory for the configured model."
        detail = f"Transcription failed: {human}."
        if message:
            detail += f" {message}"
        return detail + extra + " The original submitted PDF remains authoritative and fully gradable."

    @staticmethod
    def _extraction_metadata(parsed):
        metadata = getattr(parsed, "metadata", {})
        if not isinstance(metadata, dict):
            return {}
        extraction = metadata.get("extraction", {})
        return extraction if isinstance(extraction, dict) else {}

    @staticmethod
    def _transcription_metadata(parsed):
        value = getattr(parsed, "transcription_metadata", {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_latex_source(parsed):
        files = getattr(parsed, "files", {})
        latex_path = files.get("latex") if isinstance(files, dict) else None
        if not latex_path:
            return "Canonical LaTeX source path is unavailable."
        path = Path(str(latex_path)).expanduser()
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return f"Could not read LaTeX source: {exc}"
        except OSError as exc:
            return f"Could not read LaTeX source: {exc}"

    @staticmethod
    def _page_aligned_transcription(parsed):
        pages = getattr(parsed, "page_transcriptions", [])
        if not isinstance(pages, list):
            return ""
        chunks = []
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                continue
            text = str(page.get("text") or "").strip()
            if not text:
                continue
            page_number = page.get("page_number") or index
            chunks.append(f"--- Page {page_number} ---\n{text}")
        return "\n\n".join(chunks)

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
    # Signals
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


__all__ = ["EvidenceTextDialog", "SubmissionWorkspace"]
