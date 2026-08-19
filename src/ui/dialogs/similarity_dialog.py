"""Interactive v2.3.1 Submission Similarity Review dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.similarity import (
    DEFAULT_EMBEDDING_THRESHOLDS,
    DEFAULT_PSEUDOCODE_THRESHOLDS,
    DEFAULT_SENTENCE_TRANSFORMER_MODEL,
    DEFAULT_THRESHOLDS,
    DISCLAIMER,
    SOURCE_ASSESSMENT_FOLDER,
    SOURCE_LOADED,
    SOURCE_SUBMISSIONS_FOLDER,
    SentenceTransformerEmbeddingProvider,
    analyze_similarity_trends,
    collect_similarity_source,
    export_similarity_report,
    generate_advanced_similarity_report,
    generate_similarity_report,
    load_similarity_reports,
    sentence_transformers_available,
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


class SimilarityClusterDetailDialog(QDialog):
    """Show the pairwise review edges inside one similarity cluster."""

    COLUMNS = [
        "Student A",
        "Student B",
        "Flag",
        "Overall",
        "Most Similar Q",
        "Embedding Max",
        "Pseudocode Max",
    ]

    def __init__(
        self,
        parent=None,
        *,
        cluster: Mapping[str, Any],
        pairs: Sequence[PairSimilarity],
        submissions: Mapping[str, Any],
        question_ids: Sequence[str],
    ):
        super().__init__(parent)
        self.cluster = dict(cluster or {})
        self.submissions = dict(submissions or {})
        self.question_ids = list(question_ids or [])
        students = {
            str(student)
            for student in self.cluster.get("students", [])
            if str(student).strip()
        }
        self.pairs = [
            pair
            for pair in pairs
            if pair.student_a in students and pair.student_b in students
        ]
        self.pairs.sort(
            key=lambda pair: (
                -FLAG_RANK.get(pair.flag_level, -1),
                -float(pair.overall_score),
                pair.student_a,
                pair.student_b,
            )
        )

        cluster_id = str(self.cluster.get("cluster_id") or "Cluster")
        self.setWindowTitle(f"Similarity Cluster — {cluster_id}")
        self.setMinimumSize(760, 420)
        self.resize(980, 580)
        self.setSizeGripEnabled(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        students = ", ".join(str(s) for s in self.cluster.get("students", []))
        summary = QLabel(
            f"<b>{self.cluster.get('cluster_id', 'Cluster')}</b> &nbsp;&nbsp; "
            f"Size: <b>{self.cluster.get('size', len(self.cluster.get('students', [])))}</b>"
            f"<br>Students: {students}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        note = QLabel(
            "This table shows pairwise review results among students in the cluster. "
            "Cluster membership is a review aid, not a misconduct determination."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(lambda _item: self.view_selected_pair())
        layout.addWidget(self.table, 1)

        for pair in self.pairs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            first = QTableWidgetItem(pair.student_a)
            first.setData(Qt.UserRole, pair)
            self.table.setItem(row, 0, first)
            self.table.setItem(row, 1, QTableWidgetItem(pair.student_b))
            self.table.setItem(row, 2, FlagTableWidgetItem(pair.flag_level))
            self.table.setItem(row, 3, NumericTableWidgetItem(pair.overall_score))
            self.table.setItem(row, 4, QTableWidgetItem(pair.most_similar_question or ""))
            self.table.setItem(
                row,
                5,
                QTableWidgetItem(
                    "—"
                    if pair.embedding_max_similarity is None
                    else f"{pair.embedding_max_similarity:.4f}"
                ),
            )
            self.table.setItem(
                row,
                6,
                QTableWidgetItem(
                    "—"
                    if pair.pseudocode_max_similarity is None
                    else f"{pair.pseudocode_max_similarity:.4f}"
                ),
            )

        if self.table.rowCount():
            self.table.selectRow(0)

        row = QHBoxLayout()
        self.view_pair_btn = QPushButton("View Selected Pair")
        self.view_pair_btn.clicked.connect(self.view_selected_pair)
        self.view_pair_btn.setEnabled(bool(self.pairs))
        row.addWidget(self.view_pair_btn)
        row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)

    def selected_pair(self) -> PairSimilarity | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        pair = item.data(Qt.UserRole)
        return pair if isinstance(pair, PairSimilarity) else None

    def selected_cluster(self) -> dict[str, Any] | None:
        row = self.clusters_table.currentRow()
        if row < 0:
            return None
        item = self.clusters_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return dict(value) if isinstance(value, Mapping) else None

    def selected_trend(self) -> dict[str, Any] | None:
        row = self.trends_table.currentRow()
        if row < 0:
            return None
        item = self.trends_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return dict(value) if isinstance(value, Mapping) else None

    def view_selected_cluster(self):
        cluster = self.selected_cluster()
        if cluster is None or self.report is None or self.source_result is None:
            return
        question_ids = list(self.source_result.question_ids)
        selected = self.question_combo.currentData()
        if selected:
            question_ids = [str(selected)]
        SimilarityClusterDetailDialog(
            self,
            cluster=cluster,
            pairs=self.report.pairs,
            submissions=self.source_result.submissions,
            question_ids=question_ids,
        ).exec_()

    def view_selected_trend_pair(self):
        trend = self.selected_trend()
        if trend is None or self.report is None:
            return
        target = tuple(
            sorted(
                (
                    str(trend.get("student_a") or ""),
                    str(trend.get("student_b") or ""),
                )
            )
        )
        for row in range(self.results_table.rowCount()):
            pair = self.results_table.item(row, 0).data(Qt.UserRole)
            if (
                isinstance(pair, PairSimilarity)
                and tuple(sorted((pair.student_a, pair.student_b))) == target
            ):
                self.results_table.selectRow(row)
                self.result_tabs.setCurrentIndex(0)
                self.view_selected_pair()
                return

    def view_selected_pair(self):
        pair = self.selected_pair()
        if pair is None:
            return
        PairSimilarityDetailDialog(
            self,
            pair=pair,
            submissions=self.submissions,
            question_ids=self.question_ids,
        ).exec_()


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
        "Embedding Max",
        "Pseudocode Max",
        "Cluster",
        "Trend Count",
    ]

    CLUSTER_COLUMNS = [
        "Cluster ID",
        "Size",
        "Students",
        "Max Similarity",
        "Questions",
        "Signals",
    ]

    TREND_COLUMNS = [
        "Student A",
        "Student B",
        "Assignments Flagged",
        "Max Similarity",
        "Questions",
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
        embedding_provider_factory: Callable[[], Any] | None = None,
        embedding_available: bool | None = None,
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

        self.embedding_provider_factory = (
            embedding_provider_factory
            if embedding_provider_factory is not None
            else lambda: SentenceTransformerEmbeddingProvider(
                model_name=self.embedding_model_edit.text().strip()
                if hasattr(self, "embedding_model_edit")
                else DEFAULT_SENTENCE_TRANSFORMER_MODEL
            )
        )
        self.embedding_available = (
            bool(embedding_available)
            if embedding_available is not None
            else (
                embedding_provider_factory is not None
                or sentence_transformers_available()
            )
        )

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

    def _set_question_options(
        self,
        question_ids: Sequence[str] | None,
        *,
        preserve_selection: bool = True,
    ):
        """Populate the question selector from the currently available source.

        The first entry always means "compare all available questions".  When a
        source exposes concrete question IDs, they are added as individually
        selectable entries.  A previous single-question selection is preserved
        only when it still exists in the refreshed source.
        """

        qids = self._clean_question_ids(question_ids)
        previous = self.question_combo.currentData() if preserve_selection else None

        self.question_combo.blockSignals(True)
        try:
            self.question_combo.clear()
            all_label = (
                "All questions"
                if self.initial_question_ids
                else "All available questions"
            )
            self.question_combo.addItem(all_label, None)
            for qid in qids:
                self.question_combo.addItem(qid, qid)

            if previous and previous in qids:
                index = self.question_combo.findData(previous)
                self.question_combo.setCurrentIndex(index if index >= 0 else 0)
            else:
                self.question_combo.setCurrentIndex(0)
        finally:
            self.question_combo.blockSignals(False)

    def _reset_question_options(self):
        """Reset the selector when the submission source/path changes."""
        self._set_question_options(
            self.initial_question_ids,
            preserve_selection=False,
        )

    def _refresh_question_options(self, question_ids: Sequence[str] | None):
        """Refresh the selector after the source has discovered its questions."""
        self._set_question_options(question_ids, preserve_selection=True)

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
        self.main_splitter.setObjectName("similarityMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(10)
        self.main_splitter.setOpaqueResize(True)
        root.addWidget(self.main_splitter, 1)

        config_widget = QWidget()
        config_widget.setObjectName("similarityConfigWidget")
        config_outer = QVBoxLayout(config_widget)
        config_outer.setContentsMargins(0, 0, 0, 0)
        config_outer.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

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
                lambda checked, st=source_type: self._on_source_selected(st)
                if checked
                else None
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
        top_row.addWidget(source_group, 3)

        assignment_group = QGroupBox("Assignment / questions")
        assignment_form = QFormLayout(assignment_group)
        self.assignment_id_edit = QLineEdit(assignment_id)
        self.assignment_id_edit.setPlaceholderText("e.g., PS3")
        assignment_form.addRow("Assignment ID:", self.assignment_id_edit)

        self.question_combo = QComboBox()
        self._set_question_options(
            self.initial_question_ids,
            preserve_selection=False,
        )
        assignment_form.addRow("Questions:", self.question_combo)
        top_row.addWidget(assignment_group, 2)

        methods_group = QGroupBox("Deterministic methods")
        methods_layout = QVBoxLayout(methods_group)
        self.method_checks = {}
        for method in ("exact_file_hash", "normalized_text_hash", "ngram_jaccard"):
            checkbox = QCheckBox(METHOD_LABELS[method])
            checkbox.setChecked(True)
            self.method_checks[method] = checkbox
            methods_layout.addWidget(checkbox)
        methods_layout.addStretch(1)
        top_row.addWidget(methods_group, 2)

        config_outer.addLayout(top_row)

        advanced_row = QHBoxLayout()
        advanced_row.setSpacing(10)

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
        self.method_checks["ngram_jaccard"].toggled.connect(
            self.thresholds_group.setEnabled
        )
        advanced_row.addWidget(self.thresholds_group, 1)

        advanced_methods_group = QGroupBox("Advanced methods")
        advanced_methods_layout = QVBoxLayout(advanced_methods_group)
        self.advanced_checks = {}

        self.embedding_check = QCheckBox("Embedding similarity")
        self.embedding_check.setObjectName("embeddingSimilarityCheck")
        self.embedding_check.setChecked(False)
        self.embedding_check.setEnabled(self.embedding_available)
        self.advanced_checks["embedding_cosine"] = self.embedding_check
        advanced_methods_layout.addWidget(self.embedding_check)

        self.embedding_status_label = QLabel()
        self.embedding_status_label.setWordWrap(True)
        if self.embedding_available:
            self.embedding_status_label.setText(
                "Local SentenceTransformers provider available."
            )
        else:
            self.embedding_status_label.setText(
                "Embedding provider not configured. Install sentence-transformers "
                "to enable local semantic similarity."
            )
        advanced_methods_layout.addWidget(self.embedding_status_label)

        self.pseudocode_check = QCheckBox("Pseudocode structure similarity")
        self.pseudocode_check.setObjectName("pseudocodeSimilarityCheck")
        self.pseudocode_check.setChecked(False)
        self.advanced_checks["pseudocode_structure"] = self.pseudocode_check
        advanced_methods_layout.addWidget(self.pseudocode_check)

        self.clustering_check = QCheckBox("Clustering")
        self.clustering_check.setObjectName("similarityClusteringCheck")
        self.clustering_check.setChecked(False)
        self.advanced_checks["clustering"] = self.clustering_check
        advanced_methods_layout.addWidget(self.clustering_check)

        self.trends_check = QCheckBox("Trends across assignments")
        self.trends_check.setObjectName("similarityTrendsCheck")
        self.trends_check.setChecked(False)
        self.advanced_checks["cross_assignment_trends"] = self.trends_check
        advanced_methods_layout.addWidget(self.trends_check)
        advanced_methods_layout.addStretch(1)
        advanced_row.addWidget(advanced_methods_group, 2)

        advanced_settings_group = QGroupBox("Advanced settings")
        advanced_settings = QFormLayout(advanced_settings_group)

        self.embedding_model_edit = QLineEdit(DEFAULT_SENTENCE_TRANSFORMER_MODEL)
        self.embedding_model_edit.setObjectName("embeddingModelEdit")
        self.embedding_model_edit.setToolTip(
            "Local SentenceTransformers model. The default is "
            "Alibaba-NLP/gte-modernbert-base."
        )
        self.embedding_model_edit.setEnabled(self.embedding_available)
        advanced_settings.addRow("Embedding model:", self.embedding_model_edit)

        self.embedding_threshold_spins = {}
        for key, label in (
            ("embedding_medium", "Embedding medium:"),
            ("embedding_high", "Embedding high:"),
            ("embedding_exact", "Embedding exact:"),
        ):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.01)
            spin.setValue(DEFAULT_EMBEDDING_THRESHOLDS[key])
            self.embedding_threshold_spins[key] = spin
            advanced_settings.addRow(label, spin)

        self.pseudocode_threshold_spins = {}
        for key, label in (
            ("pseudocode_medium", "Pseudocode medium:"),
            ("pseudocode_high", "Pseudocode high:"),
            ("pseudocode_exact", "Pseudocode exact:"),
        ):
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.05)
            spin.setValue(DEFAULT_PSEUDOCODE_THRESHOLDS[key])
            self.pseudocode_threshold_spins[key] = spin
            advanced_settings.addRow(label, spin)

        self.cluster_min_combo = QComboBox()
        self.cluster_min_combo.addItems(["medium", "high", "exact"])
        self.cluster_min_combo.setCurrentText("high")
        advanced_settings.addRow("Cluster minimum:", self.cluster_min_combo)

        self.trend_min_combo = QComboBox()
        self.trend_min_combo.addItems(["medium", "high", "exact"])
        self.trend_min_combo.setCurrentText("high")
        advanced_settings.addRow("Trend minimum:", self.trend_min_combo)

        self.trend_min_assignments_spin = QSpinBox()
        self.trend_min_assignments_spin.setRange(1, 99)
        self.trend_min_assignments_spin.setValue(2)
        advanced_settings.addRow(
            "Trend min assignments:",
            self.trend_min_assignments_spin,
        )
        advanced_row.addWidget(advanced_settings_group, 2)

        trend_group = QGroupBox("Previous similarity reports")
        trend_layout = QVBoxLayout(trend_group)
        trend_note = QLabel(
            "Used only when Trends across assignments is enabled. Choose a folder "
            "containing prior similarity_report.json files."
        )
        trend_note.setWordWrap(True)
        trend_layout.addWidget(trend_note)
        trend_path_row = QHBoxLayout()
        self.trend_folder_edit = QLineEdit()
        self.trend_folder_edit.setObjectName("trendReportsFolderEdit")
        self.trend_folder_edit.setPlaceholderText(
            "Folder containing prior similarity reports"
        )
        self.trend_browse_btn = QPushButton("Browse…")
        self.trend_browse_btn.clicked.connect(self._browse_trend_folder)
        trend_path_row.addWidget(self.trend_folder_edit, 1)
        trend_path_row.addWidget(self.trend_browse_btn)
        trend_layout.addLayout(trend_path_row)
        advanced_row.addWidget(trend_group, 2)

        self.embedding_check.toggled.connect(self._update_advanced_controls)
        self.pseudocode_check.toggled.connect(self._update_advanced_controls)
        self.clustering_check.toggled.connect(self._update_advanced_controls)
        self.trends_check.toggled.connect(self._update_advanced_controls)

        config_outer.addLayout(advanced_row)

        # The configuration form is intentionally taller than many laptop
        # viewports once every advanced option is visible.  Put it in its own
        # scroll area so its size hint cannot pin the splitter and squeeze the
        # results table down to a few pixels.
        self.config_scroll = QScrollArea()
        self.config_scroll.setObjectName("similarityConfigScroll")
        self.config_scroll.setWidgetResizable(True)
        self.config_scroll.setFrameShape(QScrollArea.NoFrame)
        self.config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.config_scroll.setMinimumHeight(180)
        self.config_scroll.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.config_scroll.setWidget(config_widget)
        self.main_splitter.addWidget(self.config_scroll)

        result_widget = QWidget()
        result_widget.setObjectName("similarityResultsWidget")
        result_widget.setMinimumHeight(220)
        result_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(6)

        self.result_summary = QLabel(
            "Choose a source and run the similarity review."
        )
        self.result_summary.setWordWrap(True)
        result_layout.addWidget(self.result_summary)

        self.result_tabs = QTabWidget()
        self.result_tabs.setObjectName("similarityResultTabs")
        self.result_tabs.setMinimumHeight(170)
        self.result_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        pairs_tab = QWidget()
        pairs_layout = QVBoxLayout(pairs_tab)
        pairs_layout.setContentsMargins(0, 0, 0, 0)
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
        self.results_table.itemDoubleClicked.connect(
            lambda _item: self.view_selected_pair()
        )
        pairs_layout.addWidget(self.results_table, 1)
        self.result_tabs.addTab(pairs_tab, "Pairs")

        clusters_tab = QWidget()
        clusters_layout = QVBoxLayout(clusters_tab)
        clusters_layout.setContentsMargins(0, 0, 0, 0)
        self.clusters_table = QTableWidget(0, len(self.CLUSTER_COLUMNS))
        self.clusters_table.setHorizontalHeaderLabels(self.CLUSTER_COLUMNS)
        self.clusters_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.clusters_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.clusters_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.clusters_table.verticalHeader().setVisible(False)
        self.clusters_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.clusters_table.horizontalHeader().setStretchLastSection(True)
        self.clusters_table.itemSelectionChanged.connect(self._update_action_state)
        self.clusters_table.itemDoubleClicked.connect(
            lambda _item: self.view_selected_cluster()
        )
        clusters_layout.addWidget(self.clusters_table, 1)
        self.result_tabs.addTab(clusters_tab, "Clusters")

        trends_tab = QWidget()
        trends_layout = QVBoxLayout(trends_tab)
        trends_layout.setContentsMargins(0, 0, 0, 0)
        self.trends_table = QTableWidget(0, len(self.TREND_COLUMNS))
        self.trends_table.setHorizontalHeaderLabels(self.TREND_COLUMNS)
        self.trends_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trends_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trends_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trends_table.verticalHeader().setVisible(False)
        self.trends_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.trends_table.horizontalHeader().setStretchLastSection(True)
        self.trends_table.itemSelectionChanged.connect(self._update_action_state)
        self.trends_table.itemDoubleClicked.connect(
            lambda _item: self.view_selected_trend_pair()
        )
        trends_layout.addWidget(self.trends_table, 1)
        self.result_tabs.addTab(trends_tab, "Trends")

        result_layout.addWidget(self.result_tabs, 1)

        self.main_splitter.addWidget(result_widget)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 3)
        # Prefer the review results over the settings form on first open.  The
        # settings remain fully reachable by scrolling or dragging the divider.
        self.main_splitter.setSizes([310, 520])

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run Similarity Review")
        self.run_btn.clicked.connect(self.run_review)
        actions.addWidget(self.run_btn)

        self.view_pair_btn = QPushButton("View Selected Pair")
        self.view_pair_btn.clicked.connect(self.view_selected_pair)
        actions.addWidget(self.view_pair_btn)

        self.view_cluster_btn = QPushButton("View Selected Cluster")
        self.view_cluster_btn.clicked.connect(self.view_selected_cluster)
        actions.addWidget(self.view_cluster_btn)

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

        self._update_advanced_controls()

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
        self._reset_question_options()
        self._update_source_controls()

    def _remember_source_path(self):
        source_type = self.selected_source_type()
        if source_type in self._source_paths:
            new_path = self.source_path_edit.text().strip()
            old_path = self._source_paths.get(source_type, "")
            self._source_paths[source_type] = new_path
            if new_path != old_path:
                self._reset_question_options()

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

    def _browse_trend_folder(self):
        start = self.trend_folder_edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose previous similarity reports folder",
            start,
        )
        if directory:
            self.trend_folder_edit.setText(directory)

    def _update_advanced_controls(self):
        embedding_enabled = self.embedding_check.isChecked() and self.embedding_available
        for spin in self.embedding_threshold_spins.values():
            spin.setEnabled(embedding_enabled)
        self.embedding_model_edit.setEnabled(self.embedding_available)

        pseudocode_enabled = self.pseudocode_check.isChecked()
        for spin in self.pseudocode_threshold_spins.values():
            spin.setEnabled(pseudocode_enabled)

        self.cluster_min_combo.setEnabled(self.clustering_check.isChecked())
        trends_enabled = self.trends_check.isChecked()
        self.trend_folder_edit.setEnabled(trends_enabled)
        self.trend_browse_btn.setEnabled(trends_enabled)
        self.trend_min_combo.setEnabled(trends_enabled)
        self.trend_min_assignments_spin.setEnabled(trends_enabled)

    def selected_advanced_thresholds(self) -> dict[str, float]:
        values: dict[str, float] = {}
        if self.embedding_check.isChecked():
            values.update(
                {
                    key: spin.value()
                    for key, spin in self.embedding_threshold_spins.items()
                }
            )
        if self.pseudocode_check.isChecked():
            values.update(
                {
                    key: spin.value()
                    for key, spin in self.pseudocode_threshold_spins.items()
                }
            )
        return values

    def _create_embedding_provider(self):
        if not self.embedding_check.isChecked():
            return None
        if not self.embedding_available:
            raise ValueError(
                "Embedding similarity is unavailable because the local "
                "SentenceTransformers provider is not configured."
            )
        model_name = self.embedding_model_edit.text().strip()
        if not model_name:
            raise ValueError("Enter a SentenceTransformers model name.")
        if self.embedding_provider_factory is not None:
            provider = self.embedding_provider_factory()
        else:
            provider = SentenceTransformerEmbeddingProvider(model_name=model_name)

        # A test/injected factory may ignore the line-edit model. Production
        # uses the configured SentenceTransformer provider.
        return provider

    @staticmethod
    def _trend_count_for_pair(pair: PairSimilarity) -> int:
        signal = pair.signals.get("cross_assignment_trend")
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
    def _trend_questions_text(record: Mapping[str, Any]) -> str:
        questions = record.get("questions", {})
        if not isinstance(questions, Mapping):
            return str(questions or "")
        chunks = []
        for assignment in sorted(questions):
            raw = questions[assignment]
            if isinstance(raw, (list, tuple, set)):
                value = ", ".join(str(qid) for qid in raw)
            else:
                value = str(raw or "")
            chunks.append(f"{assignment}: {value}")
        return "; ".join(chunks)

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

        # Always collect the complete source question set. A single-question UI
        # selection is applied only when generating the report. Otherwise a
        # Q3-only rerun would shrink the source itself to Q3 and remove Q1/Q2/Q4
        # from the selector.
        source_question_ids = list(self.initial_question_ids) or None

        if source_type == SOURCE_LOADED:
            return collect_similarity_source(
                SOURCE_LOADED,
                loaded_submissions=self.loaded_submissions,
                question_ids=source_question_ids,
            )

        path = self.source_path_edit.text().strip()
        if not path:
            raise ValueError("Choose a source folder before running the review.")
        return collect_similarity_source(
            source_type,
            path=path,
            question_ids=source_question_ids,
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

        if self.trends_check.isChecked() and not self.trend_folder_edit.text().strip():
            QMessageBox.warning(
                self,
                "Previous reports folder required",
                "Choose a folder containing previous similarity_report.json files "
                "before enabling cross-assignment trends.",
            )
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            source = self._collect_source()
            self._refresh_question_options(source.question_ids)

            if len(source.submissions) < 2:
                self.source_result = source
                self.report = None
                self._populate_results([])
                self._populate_clusters([])
                self._populate_trends([])
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

            question_ids = list(source.question_ids)
            selected = self.question_combo.currentData()
            if selected:
                question_ids = [str(selected)]

            base_report = generate_similarity_report(
                source.submissions,
                assignment_id,
                question_ids,
                thresholds=self.selected_thresholds(),
                methods=methods,
            )

            embedding_provider = self._create_embedding_provider()
            use_advanced_report = any(
                (
                    embedding_provider is not None,
                    self.pseudocode_check.isChecked(),
                    self.clustering_check.isChecked(),
                    self.trends_check.isChecked(),
                )
            )

            if use_advanced_report:
                # First pass computes current-assignment advanced pair signals.
                # If trends are enabled, the resulting current report is added
                # to the historical reports before the second (cache-backed)
                # pass attaches trend annotations.
                report = generate_advanced_similarity_report(
                    base_report,
                    source.submissions,
                    question_ids,
                    embedding_provider=embedding_provider,
                    include_pseudocode=self.pseudocode_check.isChecked(),
                    include_clustering=self.clustering_check.isChecked(),
                    thresholds=self.selected_advanced_thresholds(),
                    cluster_min_flag_level=self.cluster_min_combo.currentText(),
                )

                if self.trends_check.isChecked():
                    historical = load_similarity_reports(
                        self.trend_folder_edit.text().strip()
                    )
                    historical = [
                        item
                        for item in historical
                        if item.assignment_id != assignment_id
                    ]
                    trend_records = analyze_similarity_trends(
                        [*historical, report],
                        min_flag_level=self.trend_min_combo.currentText(),
                        min_assignment_count=self.trend_min_assignments_spin.value(),
                    )
                    report = generate_advanced_similarity_report(
                        base_report,
                        source.submissions,
                        question_ids,
                        embedding_provider=embedding_provider,
                        include_pseudocode=self.pseudocode_check.isChecked(),
                        include_clustering=self.clustering_check.isChecked(),
                        thresholds=self.selected_advanced_thresholds(),
                        cluster_min_flag_level=self.cluster_min_combo.currentText(),
                        trend_records=trend_records,
                        trend_flag_level=self.trend_min_combo.currentText(),
                    )
            else:
                report = base_report

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
            self._populate_clusters(report.clusters)
            self._populate_trends(report.trends)

            flagged = sum(1 for pair in report.pairs if pair.flag_level != "none")
            advanced_names = ", ".join(report.advanced_methods) if report.advanced_methods else "none"
            self.result_summary.setText(
                f"{len(report.students)} students · {len(report.pairs)} unique pairs · "
                f"{flagged} flagged for review · {len(report.clusters)} cluster(s) · "
                f"{len(report.trends)} trend(s) · {len(report.warnings)} warning(s). "
                f"Advanced methods: {advanced_names}. "
                "Double-click a pair, cluster, or trend for more detail."
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
            self.results_table.setItem(
                row,
                7,
                QTableWidgetItem(
                    "—"
                    if pair.embedding_max_similarity is None
                    else f"{pair.embedding_max_similarity:.4f}"
                ),
            )
            self.results_table.setItem(
                row,
                8,
                QTableWidgetItem(
                    "—"
                    if pair.pseudocode_max_similarity is None
                    else f"{pair.pseudocode_max_similarity:.4f}"
                ),
            )
            self.results_table.setItem(
                row,
                9,
                QTableWidgetItem(", ".join(pair.cluster_ids)),
            )
            self.results_table.setItem(
                row,
                10,
                QTableWidgetItem(str(self._trend_count_for_pair(pair))),
            )

            if pair.flag_level in {"exact", "high"}:
                font = student_a.font()
                font.setBold(True)
                for column in range(len(self.RESULT_COLUMNS)):
                    item = self.results_table.item(row, column)
                    if item is not None:
                        item.setFont(font)

        self.results_table.setSortingEnabled(True)
        if self.results_table.rowCount():
            self.results_table.selectRow(0)

    def _populate_clusters(self, clusters: Sequence[Mapping[str, Any]]):
        self.clusters_table.setRowCount(0)
        for cluster in clusters:
            row = self.clusters_table.rowCount()
            self.clusters_table.insertRow(row)
            first = QTableWidgetItem(str(cluster.get("cluster_id") or ""))
            first.setData(Qt.UserRole, dict(cluster))
            self.clusters_table.setItem(row, 0, first)
            self.clusters_table.setItem(row, 1, QTableWidgetItem(str(cluster.get("size", ""))))
            self.clusters_table.setItem(
                row,
                2,
                QTableWidgetItem(", ".join(str(s) for s in cluster.get("students", []))),
            )
            self.clusters_table.setItem(
                row,
                3,
                NumericTableWidgetItem(float(cluster.get("max_similarity", 0.0) or 0.0)),
            )
            self.clusters_table.setItem(
                row,
                4,
                QTableWidgetItem(", ".join(str(q) for q in cluster.get("questions", []))),
            )
            self.clusters_table.setItem(
                row,
                5,
                QTableWidgetItem(", ".join(str(s) for s in cluster.get("signals", []))),
            )
        if self.clusters_table.rowCount():
            self.clusters_table.selectRow(0)

    def _populate_trends(self, trends: Sequence[Mapping[str, Any]]):
        self.trends_table.setRowCount(0)
        for trend in trends:
            row = self.trends_table.rowCount()
            self.trends_table.insertRow(row)
            first = QTableWidgetItem(str(trend.get("student_a") or ""))
            first.setData(Qt.UserRole, dict(trend))
            self.trends_table.setItem(row, 0, first)
            self.trends_table.setItem(
                row,
                1,
                QTableWidgetItem(str(trend.get("student_b") or "")),
            )
            self.trends_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    ", ".join(str(a) for a in trend.get("assignments", []))
                ),
            )
            self.trends_table.setItem(
                row,
                3,
                NumericTableWidgetItem(float(trend.get("max_similarity", 0.0) or 0.0)),
            )
            self.trends_table.setItem(
                row,
                4,
                QTableWidgetItem(self._trend_questions_text(trend)),
            )
        if self.trends_table.rowCount():
            self.trends_table.selectRow(0)

    def selected_pair(self) -> PairSimilarity | None:
        row = self.results_table.currentRow()
        if row < 0:
            return None
        item = self.results_table.item(row, 0)
        if item is None:
            return None
        pair = item.data(Qt.UserRole)
        return pair if isinstance(pair, PairSimilarity) else None

    def selected_cluster(self) -> dict[str, Any] | None:
        row = self.clusters_table.currentRow()
        if row < 0:
            return None
        item = self.clusters_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return dict(value) if isinstance(value, Mapping) else None

    def selected_trend(self) -> dict[str, Any] | None:
        row = self.trends_table.currentRow()
        if row < 0:
            return None
        item = self.trends_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return dict(value) if isinstance(value, Mapping) else None

    def view_selected_cluster(self):
        cluster = self.selected_cluster()
        if cluster is None or self.report is None or self.source_result is None:
            return
        question_ids = list(self.source_result.question_ids)
        selected = self.question_combo.currentData()
        if selected:
            question_ids = [str(selected)]
        SimilarityClusterDetailDialog(
            self,
            cluster=cluster,
            pairs=self.report.pairs,
            submissions=self.source_result.submissions,
            question_ids=question_ids,
        ).exec_()

    def view_selected_trend_pair(self):
        trend = self.selected_trend()
        if trend is None or self.report is None:
            return
        target = tuple(
            sorted(
                (
                    str(trend.get("student_a") or ""),
                    str(trend.get("student_b") or ""),
                )
            )
        )
        for row in range(self.results_table.rowCount()):
            pair = self.results_table.item(row, 0).data(Qt.UserRole)
            if (
                isinstance(pair, PairSimilarity)
                and tuple(sorted((pair.student_a, pair.student_b))) == target
            ):
                self.results_table.selectRow(row)
                self.result_tabs.setCurrentIndex(0)
                self.view_selected_pair()
                return

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
        self.view_cluster_btn.setEnabled(self.selected_cluster() is not None)
        self.open_html_btn.setEnabled(
            self.last_html_path is not None and self.last_html_path.is_file()
        )


__all__ = [
    "SimilarityReviewDialog",
    "SimilarityWarningsDialog",
    "SimilarityClusterDetailDialog",
    "NumericTableWidgetItem",
    "FlagTableWidgetItem",
]
