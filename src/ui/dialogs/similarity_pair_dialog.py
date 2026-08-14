"""Pair-detail review dialog for deterministic and advanced similarity."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.similarity.highlight import find_shared_spans
from src.similarity.models import PairSimilarity


DISCLAIMER = (
    "Similarity scores are indicators for instructor review only. "
    "They do not determine whether academic misconduct occurred."
)


def _answers_from_submission(submission: Any) -> dict[str, str]:
    if submission is None:
        return {}
    if isinstance(submission, Mapping):
        raw = (
            submission.get("extracted_answers")
            or submission.get("answers_by_question")
            or {}
        )
    else:
        raw = getattr(submission, "answers_by_question", {}) or {}

    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value or "") for key, value in raw.items()}


class PairSimilarityDetailDialog(QDialog):
    """Inspect one student pair question-by-question."""

    def __init__(
        self,
        parent=None,
        *,
        pair: PairSimilarity,
        submissions: Mapping[str, Any] | None = None,
        question_ids: Sequence[str] | None = None,
    ):
        super().__init__(parent)
        self.pair = pair
        self.submissions = dict(submissions or {})
        self.question_ids = self._resolve_question_ids(question_ids)

        self.setWindowTitle(
            f"Pair Similarity Detail — {pair.student_a} ↔ {pair.student_b}"
        )
        self.setMinimumSize(820, 560)
        self.resize(1180, 780)
        self.setSizeGripEnabled(True)

        self._build_ui()

    def _resolve_question_ids(self, preferred: Sequence[str] | None) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in preferred or ():
            qid = str(value or "").strip()
            if qid and qid not in seen:
                seen.add(qid)
                ordered.append(qid)
        for qid in self.pair.question_similarities:
            if qid and qid not in seen:
                seen.add(qid)
                ordered.append(qid)
        if self.pair.most_similar_question and self.pair.most_similar_question not in seen:
            ordered.append(self.pair.most_similar_question)
        return ordered

    @staticmethod
    def _optional_score(value: float | None) -> str:
        return "—" if value is None else f"{float(value):.4f}"

    def _trend_count(self) -> int:
        signal = self.pair.signals.get("cross_assignment_trend")
        if not isinstance(signal, Mapping):
            return 0
        details = signal.get("details")
        if not isinstance(details, Mapping):
            return 0
        try:
            return int(details.get("count", len(details.get("assignments", []) or [])) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _provenance_lines(student_id: str, provenance: Mapping[str, Any]) -> list[str]:
        if not provenance:
            return [student_id, "  No submission provenance available."]
        lines = [
            student_id,
            f"  Source used: {provenance.get('source_used') or '—'}",
            f"  Authoritative source: {provenance.get('authoritative_source') or '—'}",
            f"  Text used for analysis: "
            f"{provenance.get('analysis_text_source') or provenance.get('assistive_text_source') or '—'}",
            f"  Assistive transcription: "
            f"{'Yes' if provenance.get('uses_assistive_transcription') else 'No'}",
        ]
        if provenance.get("uses_assistive_transcription"):
            lines.append(
                "  Note: advanced similarity used assistive machine transcription."
            )
        return lines

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(
            f"<b>{self.pair.student_a}</b> &nbsp; ↔ &nbsp; "
            f"<b>{self.pair.student_b}</b>"
        )
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)

        summary = QLabel(
            f"Flag: <b>{self.pair.flag_level}</b> &nbsp;&nbsp; "
            f"Overall: <b>{self.pair.overall_score:.4f}</b> &nbsp;&nbsp; "
            f"Most similar question: <b>{self.pair.most_similar_question or '—'}</b><br>"
            f"Exact file: <b>{'yes' if self.pair.exact_file_match else 'no'}</b> &nbsp;&nbsp; "
            f"Normalized match: <b>{'yes' if self.pair.normalized_text_match else 'no'}</b> &nbsp;&nbsp; "
            f"Embedding max: <b>{self._optional_score(self.pair.embedding_max_similarity)}</b> &nbsp;&nbsp; "
            f"Pseudocode max: <b>{self._optional_score(self.pair.pseudocode_max_similarity)}</b> &nbsp;&nbsp; "
            f"Cluster: <b>{', '.join(self.pair.cluster_ids) or '—'}</b> &nbsp;&nbsp; "
            f"Trend count: <b>{self._trend_count()}</b>"
        )
        summary.setTextFormat(Qt.RichText)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        disclaimer = QLabel(DISCLAIMER)
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "QLabel { border: 1px solid #98A2B3; border-radius: 6px; "
            "padding: 8px; background: #F9FAFB; }"
        )
        layout.addWidget(disclaimer)

        # The review body is a vertical splitter so the instructor can decide
        # how much space to devote to question evidence, pair signals, and
        # warnings.  The Close button remains outside the splitter and therefore
        # cannot be pushed off-screen by resizing the evidence panes.
        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setObjectName("pairDetailMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("pairDetailQuestionTabs")
        if self.question_ids:
            for question_id in self.question_ids:
                self.tabs.addTab(
                    self._build_question_tab(question_id),
                    question_id,
                )
        else:
            empty = QLabel(
                "No question-level answers are available for this pair. "
                "Review the pair-level signals below."
            )
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            self.tabs.addTab(empty, "Pair signals")
        self.main_splitter.addWidget(self.tabs)

        signal_frame = QFrame()
        signal_frame.setObjectName("pairSignalPane")
        signal_layout = QVBoxLayout(signal_frame)
        signal_layout.setContentsMargins(0, 0, 0, 0)
        signal_layout.setSpacing(6)
        signal_layout.addWidget(QLabel("<b>Pair signals</b>"))
        self.signal_text = QPlainTextEdit()
        self.signal_text.setObjectName("pairSignalText")
        self.signal_text.setReadOnly(True)
        self.signal_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.signal_text.setMinimumHeight(80)
        self.signal_text.setPlainText(self._signal_summary())
        signal_layout.addWidget(self.signal_text, 1)
        self.main_splitter.addWidget(signal_frame)

        warning_frame = QFrame()
        warning_frame.setObjectName("pairWarningPane")
        warning_layout = QVBoxLayout(warning_frame)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.setSpacing(6)
        warning_layout.addWidget(QLabel("<b>Warnings / notes</b>"))
        self.warning_list = QListWidget()
        self.warning_list.setObjectName("pairWarningList")
        self.warning_list.setMinimumHeight(65)
        self.warning_list.setWordWrap(True)
        if self.pair.notes:
            self.warning_list.addItems(self.pair.notes)
        else:
            self.warning_list.addItem("No pair warnings.")
        warning_layout.addWidget(self.warning_list, 1)
        self.main_splitter.addWidget(warning_frame)

        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setStretchFactor(2, 1)
        self.main_splitter.setSizes([520, 150, 90])
        layout.addWidget(self.main_splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _build_question_tab(self, question_id: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        question_result = self.pair.question_similarities.get(question_id)

        answers_a = _answers_from_submission(self.submissions.get(self.pair.student_a))
        answers_b = _answers_from_submission(self.submissions.get(self.pair.student_b))
        answer_a = answers_a.get(question_id, "")
        answer_b = answers_b.get(question_id, "")

        # Each question tab has its own vertical splitter.  Its upper pane owns
        # the question score + horizontally resizable answers; its lower pane
        # owns shared phrases.  This keeps the shared-phrase list from forcing
        # pair signals and warnings out of view.
        question_splitter = QSplitter(Qt.Vertical)
        question_splitter.setObjectName("pairQuestionVerticalSplitter")
        question_splitter.setChildrenCollapsible(False)
        question_splitter.setHandleWidth(8)

        answer_section = QFrame()
        answer_section.setObjectName("pairAnswerSection")
        answer_layout = QVBoxLayout(answer_section)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setSpacing(8)

        if question_result is not None:
            score_text = (
                f"N-gram Jaccard: <b>{question_result.ngram_jaccard:.4f}</b> &nbsp;&nbsp; "
                f"Deterministic question flag: <b>{question_result.flag_level}</b> &nbsp;&nbsp; "
                f"Shared shingles: <b>{question_result.shared_shingle_count}</b><br>"
                f"Embedding similarity: <b>{self._optional_score(question_result.embedding_cosine)}</b> "
                f"&nbsp;&nbsp; Pseudocode similarity: "
                f"<b>{self._optional_score(question_result.pseudocode_similarity)}</b> "
                f"&nbsp;&nbsp; Advanced flags: "
                f"<b>{', '.join(question_result.advanced_flags) or '—'}</b>"
            )
        else:
            score_text = (
                "No n-gram result for this question under the selected methods. "
                "The original answers are still shown for instructor review."
            )
        score_label = QLabel(score_text)
        score_label.setTextFormat(Qt.RichText)
        score_label.setWordWrap(True)
        answer_layout.addWidget(score_label)

        answer_splitter = QSplitter(Qt.Horizontal)
        answer_splitter.setObjectName("pairAnswerHorizontalSplitter")
        answer_splitter.setChildrenCollapsible(False)
        answer_splitter.setHandleWidth(8)
        answer_splitter.addWidget(self._answer_panel(self.pair.student_a, answer_a))
        answer_splitter.addWidget(self._answer_panel(self.pair.student_b, answer_b))
        answer_splitter.setStretchFactor(0, 1)
        answer_splitter.setStretchFactor(1, 1)
        answer_splitter.setSizes([1, 1])
        answer_layout.addWidget(answer_splitter, 1)
        question_splitter.addWidget(answer_section)

        shared_frame = QFrame()
        shared_frame.setObjectName("pairSharedPhrasePane")
        shared_layout = QVBoxLayout(shared_frame)
        shared_layout.setContentsMargins(0, 0, 0, 0)
        shared_layout.setSpacing(6)
        shared_layout.addWidget(QLabel("<b>Shared phrases</b>"))

        self_shared = (
            list(question_result.shared_spans or [])
            if question_result is not None
            else find_shared_spans(answer_a, answer_b)
        )
        shared_list = QListWidget()
        shared_list.setObjectName("pairSharedPhraseList")
        shared_list.setMinimumHeight(80)
        shared_list.setWordWrap(True)
        if self_shared:
            for span in self_shared:
                shared_list.addItem(
                    f"{span.get('text', '')}  "
                    f"(A: {span.get('count_a', 0)}, B: {span.get('count_b', 0)})"
                )
        else:
            shared_list.addItem("No shared phrase spans were identified.")
        shared_layout.addWidget(shared_list, 1)

        if question_result is not None and question_result.warnings:
            warning_label = QLabel(
                "Warnings: " + "; ".join(question_result.warnings)
            )
            warning_label.setWordWrap(True)
            shared_layout.addWidget(warning_label)

        question_splitter.addWidget(shared_frame)
        question_splitter.setStretchFactor(0, 4)
        question_splitter.setStretchFactor(1, 2)
        question_splitter.setSizes([360, 150])

        layout.addWidget(question_splitter, 1)
        return widget

    @staticmethod
    def _answer_panel(student_id: str, answer: str) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(f"<b>{student_id}</b>")
        layout.addWidget(label)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        text.setPlainText(answer or "[No extracted answer available for this question]")
        layout.addWidget(text, 1)
        return panel

    def _signal_summary(self) -> str:
        signals = self.pair.signals if isinstance(self.pair.signals, dict) else {}
        lines: list[str] = []

        exact = signals.get("exact_file_hash")
        exact_details = exact.get("details") if isinstance(exact, dict) else {}
        exact_details = exact_details if isinstance(exact_details, dict) else {}
        lines.extend(
            [
                "Exact file hash",
                f"  Match: {'Yes' if self.pair.exact_file_match else 'No'}",
            ]
        )
        if exact_details:
            file_type = exact_details.get("matching_file_type") or "—"
            digest = exact_details.get("hash") or "—"
            lines.append(f"  File type: {file_type}")
            lines.append(f"  SHA256: {digest}")

        lines.append("")
        normalized = signals.get("normalized_text_hash")
        normalized_details = (
            normalized.get("details") if isinstance(normalized, dict) else {}
        )
        normalized_details = (
            normalized_details if isinstance(normalized_details, dict) else {}
        )
        lines.extend(
            [
                "Normalized text hash",
                f"  Match: {'Yes' if self.pair.normalized_text_match else 'No'}",
            ]
        )
        matching_questions = normalized_details.get("matching_questions") or []
        if matching_questions:
            lines.append("  Matching questions: " + ", ".join(matching_questions))
        if normalized_details.get("assignment_level_fallback"):
            lines.append("  Assignment-level fallback: Yes")

        lines.append("")
        lines.append("N-gram overlap")
        ngram = signals.get("ngram_jaccard")
        if isinstance(ngram, dict) and ngram:
            for question_id, value in ngram.items():
                lines.append(f"  {question_id}: {float(value):.4f}")
        else:
            lines.append("  Not computed under the selected methods.")

        lines.append("")
        lines.append("Embedding similarity")
        embedding = signals.get("embedding_cosine")
        if isinstance(embedding, dict):
            lines.append(
                f"  Max: {self._optional_score(self.pair.embedding_max_similarity)}"
            )
            details = embedding.get("details")
            if isinstance(details, Mapping):
                if details.get("provider"):
                    lines.append(f"  Provider: {details.get('provider')}")
                if details.get("model"):
                    lines.append(f"  Model: {details.get('model')}")
        else:
            lines.append("  Not computed.")

        lines.append("")
        lines.append("Pseudocode structure similarity")
        pseudocode = signals.get("pseudocode_structure")
        if isinstance(pseudocode, dict):
            lines.append(
                f"  Max: {self._optional_score(self.pair.pseudocode_max_similarity)}"
            )
            details = pseudocode.get("details")
            if isinstance(details, Mapping) and details.get("method"):
                lines.append(f"  Method: {details.get('method')}")
        else:
            lines.append("  Not computed.")

        lines.append("")
        lines.append("Cluster / trend context")
        lines.append(f"  Clusters: {', '.join(self.pair.cluster_ids) or '—'}")
        lines.append(f"  Trend count: {self._trend_count()}")
        if self.pair.trend_flags:
            lines.append(f"  Trend flags: {', '.join(self.pair.trend_flags)}")

        lines.append("")
        lines.append("Submission provenance")
        provenance = (
            self.pair.submission_provenance
            if isinstance(self.pair.submission_provenance, dict)
            else {}
        )
        for index, student_id in enumerate((self.pair.student_a, self.pair.student_b)):
            if index:
                lines.append("")
            lines.extend(
                self._provenance_lines(
                    student_id,
                    provenance.get(student_id, {}),
                )
            )

        return "\n".join(lines)


__all__ = ["PairSimilarityDetailDialog"]
