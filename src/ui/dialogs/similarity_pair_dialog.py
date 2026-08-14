"""Pair-detail review dialog for deterministic submission similarity."""

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
    QScrollArea,
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
            f"Most similar question: <b>{self.pair.most_similar_question or '—'}</b> &nbsp;&nbsp; "
            f"Exact file: <b>{'yes' if self.pair.exact_file_match else 'no'}</b> &nbsp;&nbsp; "
            f"Normalized match: <b>{'yes' if self.pair.normalized_text_match else 'no'}</b>"
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

        self.tabs = QTabWidget()
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
        layout.addWidget(self.tabs, 1)

        signal_frame = QFrame()
        signal_layout = QVBoxLayout(signal_frame)
        signal_layout.setContentsMargins(0, 0, 0, 0)
        signal_layout.addWidget(QLabel("<b>Pair signals</b>"))
        self.signal_text = QPlainTextEdit()
        self.signal_text.setReadOnly(True)
        self.signal_text.setMaximumHeight(130)
        self.signal_text.setPlainText(self._signal_summary())
        signal_layout.addWidget(self.signal_text)
        layout.addWidget(signal_frame)

        warnings = QLabel("<b>Warnings / notes</b>")
        layout.addWidget(warnings)
        self.warning_list = QListWidget()
        self.warning_list.setMaximumHeight(100)
        if self.pair.notes:
            self.warning_list.addItems(self.pair.notes)
        else:
            self.warning_list.addItem("No pair warnings.")
        layout.addWidget(self.warning_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _build_question_tab(self, question_id: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        question_result = self.pair.question_similarities.get(question_id)
        if question_result is not None:
            score_text = (
                f"N-gram Jaccard: <b>{question_result.ngram_jaccard:.4f}</b> &nbsp;&nbsp; "
                f"Question flag: <b>{question_result.flag_level}</b> &nbsp;&nbsp; "
                f"Shared shingles: <b>{question_result.shared_shingle_count}</b>"
            )
        else:
            score_text = (
                "No n-gram result for this question under the selected methods. "
                "The original answers are still shown for instructor review."
            )
        score_label = QLabel(score_text)
        score_label.setTextFormat(Qt.RichText)
        score_label.setWordWrap(True)
        layout.addWidget(score_label)

        answers_a = _answers_from_submission(self.submissions.get(self.pair.student_a))
        answers_b = _answers_from_submission(self.submissions.get(self.pair.student_b))
        answer_a = answers_a.get(question_id, "")
        answer_b = answers_b.get(question_id, "")

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._answer_panel(self.pair.student_a, answer_a))
        splitter.addWidget(self._answer_panel(self.pair.student_b, answer_b))
        splitter.setSizes([1, 1])
        layout.addWidget(splitter, 1)

        shared_label = QLabel("<b>Shared phrases</b>")
        layout.addWidget(shared_label)
        self_shared = (
            list(question_result.shared_spans or [])
            if question_result is not None
            else find_shared_spans(answer_a, answer_b)
        )
        shared_list = QListWidget()
        shared_list.setMaximumHeight(150)
        if self_shared:
            for span in self_shared:
                shared_list.addItem(
                    f"{span.get('text', '')}  "
                    f"(A: {span.get('count_a', 0)}, B: {span.get('count_b', 0)})"
                )
        else:
            shared_list.addItem("No shared phrase spans were identified.")
        layout.addWidget(shared_list)

        if question_result is not None and question_result.warnings:
            warning_label = QLabel(
                "Warnings: " + "; ".join(question_result.warnings)
            )
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)

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
        lines = [
            f"exact_file_match: {self.pair.exact_file_match}",
            f"normalized_text_match: {self.pair.normalized_text_match}",
        ]
        ngram = self.pair.signals.get("ngram_jaccard") if isinstance(self.pair.signals, dict) else None
        if isinstance(ngram, dict):
            for question_id, value in ngram.items():
                lines.append(f"ngram_jaccard[{question_id}]: {float(value):.4f}")
        exact = self.pair.signals.get("exact_file_hash") if isinstance(self.pair.signals, dict) else None
        if isinstance(exact, dict):
            details = exact.get("details") or {}
            lines.append(
                "exact_file_hash: "
                f"type={details.get('matching_file_type', '')}, hash={details.get('hash', '')}"
            )
        normalized = self.pair.signals.get("normalized_text_hash") if isinstance(self.pair.signals, dict) else None
        if isinstance(normalized, dict):
            details = normalized.get("details") or {}
            lines.append(
                "normalized_text_hash: matching_questions="
                + ", ".join(details.get("matching_questions") or [])
            )
        return "\n".join(lines)


__all__ = ["PairSimilarityDetailDialog"]
