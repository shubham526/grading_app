"""Read-only answer/source/transcription panel for submission evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.submissions.models import (
    SUBMISSION_MODE_LATEX,
    SUBMISSION_MODE_PDF_ACCOMMODATION,
    ParsedSubmission,
)


class SubmissionTextPanel(QFrame):
    """Show current-question text and the relevant source/assistive text.

    The panel never edits canonical evidence.  It deliberately keeps provenance
    visible so derived PDF text or machine transcription cannot be mistaken for
    the authoritative submitted artifact.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("submissionTextPanel")
        self._submission: Optional[ParsedSubmission] = None
        self._question_id: Optional[str] = None
        self._secondary_kind = "none"
        self._build_ui()
        self.clear_submission()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("submissionTextHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)

        self.title_label = QLabel("Answer / Source", header)
        self.title_label.setObjectName("submissionTextTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)

        self.provenance_label = QLabel("", header)
        self.provenance_label.setObjectName("submissionProvenanceBadge")
        self.provenance_label.setVisible(False)
        header_layout.addWidget(self.provenance_label)
        layout.addWidget(header)

        self.context_label = QLabel("No submission loaded.", self)
        self.context_label.setObjectName("submissionContextLabel")
        self.context_label.setWordWrap(True)
        self.context_label.setContentsMargins(10, 7, 10, 7)
        layout.addWidget(self.context_label)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("submissionTextTabs")
        self.tabs.setDocumentMode(True)

        answer_container = QWidget(self.tabs)
        answer_layout = QVBoxLayout(answer_container)
        answer_layout.setContentsMargins(8, 8, 8, 8)
        answer_layout.setSpacing(6)
        self.answer_notice = QLabel("", answer_container)
        self.answer_notice.setObjectName("submissionAnswerNotice")
        self.answer_notice.setWordWrap(True)
        self.answer_notice.setVisible(False)
        answer_layout.addWidget(self.answer_notice)
        self.answer_edit = QPlainTextEdit(answer_container)
        self.answer_edit.setObjectName("submissionAnswerText")
        self.answer_edit.setReadOnly(True)
        self.answer_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        answer_layout.addWidget(self.answer_edit, 1)
        self.answer_tab_index = self.tabs.addTab(answer_container, "Answer")

        secondary_container = QWidget(self.tabs)
        secondary_layout = QVBoxLayout(secondary_container)
        secondary_layout.setContentsMargins(8, 8, 8, 8)
        secondary_layout.setSpacing(6)
        self.secondary_notice = QLabel("", secondary_container)
        self.secondary_notice.setObjectName("submissionSecondaryNotice")
        self.secondary_notice.setWordWrap(True)
        secondary_layout.addWidget(self.secondary_notice)
        self.secondary_edit = QPlainTextEdit(secondary_container)
        self.secondary_edit.setObjectName("submissionSecondaryText")
        self.secondary_edit.setReadOnly(True)
        self.secondary_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        secondary_layout.addWidget(self.secondary_edit, 1)
        self.secondary_tab_index = self.tabs.addTab(secondary_container, "Source")

        layout.addWidget(self.tabs, 1)

        self.setStyleSheet(
            """
            QFrame#submissionTextPanel {
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 8px;
            }
            QWidget#submissionTextHeader {
                background: #FFFFFF;
                border: none;
                border-bottom: 1px solid #E6E9EF;
            }
            QLabel#submissionTextTitle {
                color: #1F2937;
                font-weight: 600;
            }
            QLabel#submissionProvenanceBadge {
                color: #475467;
                background-color: #F2F4F7;
                border: 1px solid #E6E9EF;
                border-radius: 9px;
                padding: 2px 7px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#submissionContextLabel {
                color: #667085;
                background-color: #F9FAFB;
                border-bottom: 1px solid #E6E9EF;
            }
            QLabel#submissionAnswerNotice,
            QLabel#submissionSecondaryNotice {
                color: #667085;
                background-color: #F9FAFB;
                border: 1px solid #E6E9EF;
                border-radius: 5px;
                padding: 6px 8px;
            }
            QTabWidget#submissionTextTabs::pane {
                border: none;
                background: #FFFFFF;
            }
            QTabBar::tab {
                color: #667085;
                background: #F9FAFB;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 7px 12px;
            }
            QTabBar::tab:selected {
                color: #304DAF;
                background: #FFFFFF;
                border-bottom: 2px solid #3B5CCC;
                font-weight: 600;
            }
            QPlainTextEdit#submissionAnswerText,
            QPlainTextEdit#submissionSecondaryText {
                color: #1F2937;
                background-color: #FFFFFF;
                border: 1px solid #E6E9EF;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #DCE4FF;
            }
            """
        )

    # ------------------------------------------------------------------
    # Public API used by SubmissionWorkspace / MainWindow
    # ------------------------------------------------------------------

    @property
    def submission(self):
        return self._submission

    @property
    def question_id(self):
        return self._question_id

    @property
    def secondary_kind(self):
        return self._secondary_kind

    def set_submission(self, parsed_submission):
        """Display one ``ParsedSubmission`` or clear on ``None``."""
        if parsed_submission is None:
            self.clear_submission()
            return
        self._submission = parsed_submission
        self._configure_for_submission()
        self._refresh_answer()

    def set_question(self, question_id):
        normalized = str(question_id).strip() if question_id else None
        if normalized == self._question_id:
            return
        self._question_id = normalized
        self._refresh_answer()

    def clear_submission(self):
        self._submission = None
        self._question_id = None
        self._secondary_kind = "none"
        self.title_label.setText("Answer / Source")
        self.context_label.setText("No submission loaded.")
        self.provenance_label.setVisible(False)
        self.answer_notice.setVisible(False)
        self.answer_notice.clear()
        self.answer_edit.clear()
        self.secondary_notice.setText("No source text is available.")
        self.secondary_edit.clear()
        self.tabs.setTabText(self.answer_tab_index, "Answer")
        self.tabs.setTabText(self.secondary_tab_index, "Source")
        self.tabs.setTabEnabled(self.secondary_tab_index, False)

    def answer_text(self):
        return self.answer_edit.toPlainText()

    def secondary_text(self):
        return self.secondary_edit.toPlainText()

    # ------------------------------------------------------------------
    # Mode configuration
    # ------------------------------------------------------------------

    def _configure_for_submission(self):
        parsed = self._submission
        mode = getattr(parsed, "submission_mode", SUBMISSION_MODE_LATEX)
        self.tabs.setTabEnabled(self.secondary_tab_index, True)

        if mode == SUBMISSION_MODE_PDF_ACCOMMODATION or getattr(parsed, "accommodation_mode", False):
            self._configure_pdf_accommodation(parsed)
        else:
            self._configure_latex(parsed)

    def _configure_latex(self, parsed):
        self.title_label.setText("Current answer / LaTeX source")
        self.context_label.setText(
            "The .tex file is canonical. The compiled PDF is a rendered view for grading."
        )
        self.provenance_label.setText("LaTeX canonical")
        self.provenance_label.setVisible(True)
        self.tabs.setTabText(self.secondary_tab_index, "LaTeX Source")
        self._secondary_kind = "latex_source"
        self.secondary_notice.setText("Canonical submitted LaTeX source · read-only")
        self.secondary_edit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.secondary_edit.setPlainText(self._read_latex_source(parsed))

    def _configure_pdf_accommodation(self, parsed):
        self.title_label.setText("Current answer / Assistive text")
        self.context_label.setText(
            "The original submitted PDF is authoritative. Text shown here is assistive and should be verified against the original."
        )
        self.provenance_label.setText("Original PDF authoritative")
        self.provenance_label.setVisible(True)

        assistive_source = ""
        metadata = getattr(parsed, "metadata", {})
        if isinstance(metadata, dict):
            assistive_source = str(metadata.get("assistive_text_source") or "")

        if assistive_source == "pdf_selectable_text":
            self._secondary_kind = "pdf_selectable_text"
            self.tabs.setTabText(self.secondary_tab_index, "Extracted Text")
            self.secondary_notice.setText("Selectable PDF text · assistive, non-authoritative")
            self.secondary_edit.setFont(self.font())
            text = str(getattr(parsed, "raw_text", "") or "")
            self.secondary_edit.setPlainText(text or "No selectable PDF text is available.")
            return

        transcription = getattr(parsed, "transcription_metadata", {})
        if not isinstance(transcription, dict):
            transcription = {}
        self._secondary_kind = "transcription"
        self.tabs.setTabText(self.secondary_tab_index, "Full Transcription")
        self.secondary_edit.setFont(self.font())

        status = str(transcription.get("status") or "not_requested")
        model = transcription.get("model")
        cache = transcription.get("cache") if isinstance(transcription.get("cache"), dict) else {}
        cache_status = cache.get("status") if isinstance(cache, dict) else None
        parts = ["Assistive only"]
        if model:
            parts.append(str(model))
        if cache_status == "hit":
            parts.append("cached")
        parts.append(f"status: {status}")
        self.secondary_notice.setText(" · ".join(parts))

        full_text = self._page_aligned_transcription(parsed)
        if not full_text:
            full_text = self._transcription_empty_message(status)
        self.secondary_edit.setPlainText(full_text)

    # ------------------------------------------------------------------
    # Answer selection
    # ------------------------------------------------------------------

    def _refresh_answer(self):
        parsed = self._submission
        if parsed is None:
            return

        self.answer_notice.setVisible(False)
        self.answer_notice.clear()
        question_id = self._question_id
        answers = getattr(parsed, "answers_by_question", {})
        answers = answers if isinstance(answers, dict) else {}

        if question_id:
            self.tabs.setTabText(self.answer_tab_index, question_id)
            answer = None
            getter = getattr(parsed, "get_answer", None)
            if callable(getter):
                answer = getter(question_id)
            else:
                answer = answers.get(question_id)
            if answer is None:
                self.answer_edit.clear()
                self.answer_notice.setText(
                    f"No extracted answer is available for {question_id}. Use the document pane as the grading source."
                )
                self.answer_notice.setVisible(True)
            else:
                self.answer_edit.setPlainText(str(answer))
            return

        self.tabs.setTabText(self.answer_tab_index, "Submission Text")
        # Student-centric mode may not have one active question. Present the
        # parser's raw/extracted text without inventing a question mapping.
        raw_text = str(getattr(parsed, "raw_text", "") or "")
        if raw_text:
            self.answer_edit.setPlainText(raw_text)
            self.answer_notice.setText(
                "Student-centric view: showing available submission text. Select a question for question-specific extraction."
            )
            self.answer_notice.setVisible(True)
        elif answers:
            pieces = []
            for key, value in answers.items():
                pieces.append(f"{key}\n{value}")
            self.answer_edit.setPlainText("\n\n".join(pieces))
            self.answer_notice.setText("Student-centric view: showing all extracted answer sections.")
            self.answer_notice.setVisible(True)
        else:
            self.answer_edit.clear()
            self.answer_notice.setText("No extracted submission text is available.")
            self.answer_notice.setVisible(True)

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

    @staticmethod
    def _transcription_empty_message(status):
        mapping = {
            "not_requested": "Transcription not generated.",
            "unavailable": "GPU/Ollama transcription is unavailable.",
            "model_load_failure": "The configured transcription model is unavailable.",
            "inference_failure": "Transcription failed during inference.",
            "empty_output": "The transcription model returned no usable text.",
            "generation_limit": "Transcription stopped at the generation limit and was not accepted as complete.",
            "degenerate_repetition": "Transcription output was rejected because of degenerate repetition.",
            "failed": "Transcription failed.",
            "partial": "Only part of the submission was transcribed; partial text is not used as a complete answer.",
        }
        return mapping.get(str(status), "No usable assistive transcription is available.")
