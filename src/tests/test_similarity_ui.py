import os
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN_WINDOW = ROOT / "src" / "ui" / "main_window.py"
DIALOG = ROOT / "src" / "ui" / "dialogs" / "similarity_dialog.py"
PAIR_DIALOG = ROOT / "src" / "ui" / "dialogs" / "similarity_pair_dialog.py"


class TestSimilarityUiWiringWithoutQt(unittest.TestCase):
    def test_main_window_adds_tools_similarity_action(self):
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn('self.tools_menu_button.setText("Tools")', source)
        self.assertIn('"Submission Similarity Review"', source)
        self.assertIn("self.show_similarity_review", source)
        self.assertIn("SimilarityReviewDialog", source)

    def test_main_window_passes_current_v22_submission_context(self):
        source = MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("loaded_submissions=self.submission_controller.submissions", source)
        self.assertIn("question_ids=self._submission_question_ids()", source)
        self.assertIn("assessments_dir=self.assessments_dir", source)
        self.assertIn("self.submission_controller.submissions_dir", source)

    def test_dialog_refreshes_question_selector_from_discovered_source(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn("self._refresh_question_options(source.question_ids)", source)
        self.assertIn("source_question_ids = list(self.initial_question_ids) or None", source)
        self.assertIn("self.question_combo.addItem(qid, qid)", source)

    def test_dialog_uses_shared_backend_instead_of_reimplementing_similarity(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn("collect_similarity_source", source)
        self.assertIn("generate_similarity_report", source)
        self.assertIn("export_similarity_report", source)
        self.assertNotIn("hashlib", source)
        self.assertNotIn("jaccard_similarity", source)

    def test_pair_detail_uses_shared_span_helper(self):
        source = PAIR_DIALOG.read_text(encoding="utf-8")
        self.assertIn("find_shared_spans", source)
        self.assertIn("Shared phrases", source)
        self.assertIn("academic misconduct", source)

    def test_pair_detail_uses_nested_resizable_splitters(self):
        source = PAIR_DIALOG.read_text(encoding="utf-8")
        self.assertIn('setObjectName("pairDetailMainSplitter")', source)
        self.assertIn('setObjectName("pairQuestionVerticalSplitter")', source)
        self.assertIn('setObjectName("pairAnswerHorizontalSplitter")', source)
        self.assertNotIn("self.signal_text.setMaximumHeight", source)
        self.assertNotIn("self.warning_list.setMaximumHeight", source)
        self.assertNotIn("shared_list.setMaximumHeight", source)

    def test_dialog_wires_advanced_similarity_backend(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn("generate_advanced_similarity_report", source)
        self.assertIn("analyze_similarity_trends", source)
        self.assertIn("load_similarity_reports", source)
        self.assertIn("SentenceTransformerEmbeddingProvider", source)
        self.assertIn('"Embedding similarity"', source)
        self.assertIn('"Pseudocode structure similarity"', source)
        self.assertIn('"Clustering"', source)
        self.assertIn('"Trends across assignments"', source)

    def test_dialog_has_pairs_clusters_and_trends_tabs(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn('self.result_tabs.addTab(pairs_tab, "Pairs")', source)
        self.assertIn('self.result_tabs.addTab(clusters_tab, "Clusters")', source)
        self.assertIn('self.result_tabs.addTab(trends_tab, "Trends")', source)
        self.assertIn("SimilarityClusterDetailDialog", source)

    def test_pair_detail_displays_advanced_signals_and_provenance(self):
        source = PAIR_DIALOG.read_text(encoding="utf-8")
        self.assertIn("Embedding similarity", source)
        self.assertIn("Pseudocode structure similarity", source)
        self.assertIn("Submission provenance", source)
        self.assertIn("Assistive transcription", source)

    def test_pair_signal_summary_is_instructor_readable(self):
        source = PAIR_DIALOG.read_text(encoding="utf-8")
        self.assertIn('"Exact file hash"', source)
        self.assertIn('"Normalized text hash"', source)
        self.assertIn('"N-gram overlap"', source)
        self.assertIn('"  SHA256: ', source)


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QSplitter

    from src.similarity.mock_embedding_provider import MockEmbeddingProvider
    from src.similarity.models import PairSimilarity, QuestionSimilarity
    from src.ui.dialogs.similarity_dialog import SimilarityReviewDialog
    from src.ui.dialogs.similarity_pair_dialog import PairSimilarityDetailDialog

    QT_AVAILABLE = True
except Exception:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PyQt5 is not available")
class TestSimilarityReviewDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _submission(student_id, answer):
        return {
            "student_id": student_id,
            "extracted_answers": {"Q1": answer},
            "submission_meta": {"student_id": student_id},
        }

    def _dialog(self):
        text_a = (
            "we maintain an invariant over each processed prefix and update the "
            "stored maximum after examining every element of the input sequence"
        )
        text_b = (
            "we maintain an invariant over each processed prefix and update the "
            "stored maximum after examining every element of the input array"
        )
        return SimilarityReviewDialog(
            assignment_id="PS3",
            question_ids=["Q1", "Q2"],
            loaded_submissions={
                "alice": self._submission("alice", text_a),
                "bob": self._submission("bob", text_b),
            },
        )

    def _advanced_dialog(self):
        dialog = self._dialog()
        vectors = {
            dialog.loaded_submissions["alice"]["extracted_answers"]["Q1"]: [1.0, 0.0],
            dialog.loaded_submissions["bob"]["extracted_answers"]["Q1"]: [1.0, 0.0],
        }
        dialog.embedding_provider_factory = lambda: MockEmbeddingProvider(vectors=vectors)
        dialog.embedding_available = True
        dialog.embedding_check.setEnabled(True)
        dialog.embedding_status_label.setText("Test embedding provider available.")
        return dialog

    @staticmethod
    def _write_assessment(path, student_id, q1, q2):
        payload = {
            "student_id": student_id,
            "criteria": [
                {"id": "C1", "question_id": "Q1", "points_awarded": 1},
                {"id": "C2", "question_id": "Q2", "points_awarded": 1},
            ],
            "submission_meta": {
                "student_id": student_id,
                "source_used": "latex",
                "files": {},
                "file_hashes": {},
                "warnings": [],
            },
            "extracted_answers": {
                "Q1": q1,
                "Q2": q2,
            },
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    def test_assessment_folder_run_populates_discovered_question_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(
                Path(tmp) / "alice.json",
                "alice",
                "alice q1 unique response",
                "shared q2 response with enough words for comparison",
            )
            self._write_assessment(
                Path(tmp) / "bob.json",
                "bob",
                "bob q1 different response",
                "shared q2 response with enough words for comparison",
            )

            dialog = SimilarityReviewDialog(
                assignment_id="SIM1",
                question_ids=None,
            )
            dialog.source_radios["assessment_folder"].setChecked(True)
            dialog.source_path_edit.setText(tmp)
            dialog._remember_source_path()
            dialog.run_review()

            self.assertEqual(
                [dialog.question_combo.itemText(i) for i in range(dialog.question_combo.count())],
                ["All available questions", "Q1", "Q2"],
            )
            self.assertEqual(dialog.source_result.question_ids, ["Q1", "Q2"])
            dialog.close()

    def test_single_question_rerun_filters_report_without_shrinking_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_assessment(
                Path(tmp) / "alice.json",
                "alice",
                "alice q1 unique response",
                "shared q2 response with enough words for comparison",
            )
            self._write_assessment(
                Path(tmp) / "bob.json",
                "bob",
                "bob q1 different response",
                "shared q2 response with enough words for comparison",
            )

            dialog = SimilarityReviewDialog(
                assignment_id="SIM1",
                question_ids=None,
            )
            dialog.source_radios["assessment_folder"].setChecked(True)
            dialog.source_path_edit.setText(tmp)
            dialog._remember_source_path()

            # First run discovers and populates Q1/Q2.
            dialog.run_review()
            q2_index = dialog.question_combo.findData("Q2")
            self.assertGreaterEqual(q2_index, 0)

            # Second run is Q2-only, but the source/selector must still retain
            # all available questions for a later Q1 or All rerun.
            dialog.question_combo.setCurrentIndex(q2_index)
            dialog.run_review()

            self.assertEqual(dialog.source_result.question_ids, ["Q1", "Q2"])
            self.assertEqual(
                [dialog.question_combo.itemText(i) for i in range(dialog.question_combo.count())],
                ["All available questions", "Q1", "Q2"],
            )
            self.assertEqual(dialog.question_combo.currentData(), "Q2")
            self.assertEqual(
                list(dialog.report.pairs[0].question_similarities),
                ["Q2"],
            )
            dialog.close()

    def test_dialog_is_resizable_and_defaults_to_loaded_source(self):
        dialog = self._dialog()
        self.assertTrue(dialog.isSizeGripEnabled())
        self.assertEqual(dialog.selected_source_type(), "loaded")
        self.assertEqual(dialog.assignment_id_edit.text(), "PS3")
        self.assertEqual(dialog.question_combo.count(), 3)
        self.assertTrue(all(box.isChecked() for box in dialog.method_checks.values()))
        dialog.close()

    def test_run_review_populates_pair_table(self):
        dialog = self._dialog()
        dialog.run_review()
        self.assertIsNotNone(dialog.report)
        self.assertEqual(len(dialog.report.pairs), 1)
        self.assertEqual(dialog.results_table.rowCount(), 1)
        self.assertIsNotNone(dialog.selected_pair())
        dialog.close()

    def test_method_checkboxes_control_report_methods(self):
        dialog = self._dialog()
        dialog.method_checks["exact_file_hash"].setChecked(False)
        dialog.method_checks["normalized_text_hash"].setChecked(False)
        dialog.run_review()
        self.assertEqual(dialog.report.methods, ["ngram_jaccard"])
        dialog.close()

    def test_export_helper_writes_json_csv_matrix_and_html(self):
        dialog = self._dialog()
        dialog.run_review()
        with tempfile.TemporaryDirectory() as tmp:
            results = dialog._export_to_directory(tmp)
            self.assertTrue(results["json"].is_file())
            self.assertTrue(results["csv"].is_file())
            self.assertTrue(results["matrix_csv"].is_file())
            self.assertTrue(results["html"].is_file())
            self.assertTrue(dialog.last_html_path.is_file())
        dialog.close()

    def test_advanced_method_controls_exist_and_default_off(self):
        dialog = self._advanced_dialog()
        self.assertFalse(dialog.embedding_check.isChecked())
        self.assertFalse(dialog.pseudocode_check.isChecked())
        self.assertFalse(dialog.clustering_check.isChecked())
        self.assertFalse(dialog.trends_check.isChecked())
        self.assertEqual(dialog.result_tabs.count(), 3)
        self.assertEqual(
            [dialog.result_tabs.tabText(i) for i in range(dialog.result_tabs.count())],
            ["Pairs", "Clusters", "Trends"],
        )
        dialog.close()

    def test_embedding_review_populates_advanced_pair_column(self):
        dialog = self._advanced_dialog()
        dialog.embedding_check.setChecked(True)
        dialog.run_review()

        self.assertIn("embedding_cosine", dialog.report.advanced_methods)
        self.assertEqual(dialog.report.pairs[0].embedding_max_similarity, 1.0)
        self.assertEqual(dialog.results_table.item(0, 7).text(), "1.0000")
        dialog.close()

    def test_clustering_populates_cluster_tab(self):
        dialog = self._advanced_dialog()
        dialog.embedding_check.setChecked(True)
        dialog.clustering_check.setChecked(True)
        dialog.run_review()

        self.assertEqual(len(dialog.report.clusters), 1)
        self.assertEqual(dialog.clusters_table.rowCount(), 1)
        self.assertEqual(dialog.clusters_table.item(0, 0).text(), "C1")
        self.assertIsNotNone(dialog.selected_cluster())
        dialog.close()

    def test_export_helper_writes_cluster_and_trend_csv(self):
        dialog = self._advanced_dialog()
        dialog.embedding_check.setChecked(True)
        dialog.clustering_check.setChecked(True)
        dialog.run_review()
        with tempfile.TemporaryDirectory() as tmp:
            results = dialog._export_to_directory(tmp)
            self.assertTrue(results["clusters_csv"].is_file())
            self.assertTrue(results["trends_csv"].is_file())
        dialog.close()

    def test_pair_detail_shows_question_tabs(self):
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            overall_score=0.9,
            flag_level="high",
            most_similar_question="Q1",
            question_similarities={
                "Q1": QuestionSimilarity(
                    question_id="Q1",
                    ngram_jaccard=0.9,
                    shared_shingle_count=4,
                    total_shingle_count=5,
                    shared_spans=[
                        {"text": "we prove by induction", "count_a": 1, "count_b": 1}
                    ],
                    flag_level="high",
                )
            },
            signals={"ngram_jaccard": {"Q1": 0.9}},
        )
        detail = PairSimilarityDetailDialog(
            pair=pair,
            submissions={
                "alice": self._submission("alice", "answer a"),
                "bob": self._submission("bob", "answer b"),
            },
            question_ids=["Q1"],
        )
        self.assertEqual(detail.tabs.count(), 1)
        self.assertEqual(detail.tabs.tabText(0), "Q1")
        self.assertTrue(detail.isSizeGripEnabled())

        main_splitter = detail.findChild(QSplitter, "pairDetailMainSplitter")
        self.assertIsNotNone(main_splitter)
        self.assertEqual(main_splitter.orientation(), Qt.Vertical)
        self.assertEqual(main_splitter.count(), 3)

        question_splitter = detail.findChild(QSplitter, "pairQuestionVerticalSplitter")
        self.assertIsNotNone(question_splitter)
        self.assertEqual(question_splitter.orientation(), Qt.Vertical)
        self.assertEqual(question_splitter.count(), 2)

        answer_splitter = detail.findChild(QSplitter, "pairAnswerHorizontalSplitter")
        self.assertIsNotNone(answer_splitter)
        self.assertEqual(answer_splitter.orientation(), Qt.Horizontal)
        self.assertEqual(answer_splitter.count(), 2)

        self.assertGreater(detail.signal_text.maximumHeight(), 1000000)
        self.assertGreater(detail.warning_list.maximumHeight(), 1000000)
        detail.close()

    def test_pair_detail_formats_signals_as_readable_sections(self):
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            overall_score=1.0,
            flag_level="exact",
            most_similar_question="Q1",
            exact_file_match=True,
            normalized_text_match=True,
            question_similarities={
                "Q1": QuestionSimilarity(
                    question_id="Q1",
                    ngram_jaccard=1.0,
                    shared_shingle_count=10,
                    total_shingle_count=10,
                    flag_level="exact",
                )
            },
            signals={
                "exact_file_hash": {
                    "method": "exact_file_hash",
                    "score": 1.0,
                    "details": {
                        "matching_file_type": "latex",
                        "hash": "abc123",
                    },
                },
                "normalized_text_hash": {
                    "method": "normalized_text_hash",
                    "score": 1.0,
                    "details": {"matching_questions": ["Q1"]},
                },
                "ngram_jaccard": {"Q1": 1.0},
            },
        )
        detail = PairSimilarityDetailDialog(
            pair=pair,
            submissions={
                "alice": self._submission("alice", "answer a"),
                "bob": self._submission("bob", "answer b"),
            },
            question_ids=["Q1"],
        )
        summary = detail.signal_text.toPlainText()
        self.assertIn("Exact file hash", summary)
        self.assertIn("Match: Yes", summary)
        self.assertIn("File type: latex", summary)
        self.assertIn("SHA256: abc123", summary)
        self.assertIn("Normalized text hash", summary)
        self.assertIn("Matching questions: Q1", summary)
        self.assertIn("N-gram overlap", summary)
        self.assertIn("Q1: 1.0000", summary)
        detail.close()

    def test_pair_detail_formats_advanced_signals_and_provenance(self):
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            overall_score=0.95,
            flag_level="high",
            most_similar_question="Q1",
            question_similarities={
                "Q1": QuestionSimilarity(
                    question_id="Q1",
                    ngram_jaccard=0.20,
                    flag_level="none",
                    embedding_cosine=0.95,
                    pseudocode_similarity=0.84,
                    advanced_flags=["embedding_high", "pseudocode_high"],
                )
            },
            embedding_max_similarity=0.95,
            pseudocode_max_similarity=0.84,
            cluster_ids=["C1"],
            trend_flags=["cross_assignment_trend"],
            signals={
                "embedding_cosine": {
                    "method": "embedding_cosine",
                    "score": 0.95,
                    "details": {
                        "provider": "mock",
                        "model": "mock-embedding",
                        "count": 2,
                    },
                },
                "pseudocode_structure": {
                    "method": "pseudocode_structure",
                    "score": 0.84,
                    "details": {"method": "normalized_token_3gram_jaccard"},
                },
                "cross_assignment_trend": {
                    "method": "cross_assignment_trend",
                    "score": 0.97,
                    "details": {
                        "count": 2,
                        "assignments": ["PS2", "PS3"],
                    },
                },
            },
            submission_provenance={
                "alice": {
                    "source_used": "latex",
                    "authoritative_source": "latex",
                    "analysis_text_source": "latex",
                    "uses_assistive_transcription": False,
                },
                "bob": {
                    "source_used": "pdf",
                    "authoritative_source": "original_pdf",
                    "analysis_text_source": "machine_transcription",
                    "uses_assistive_transcription": True,
                },
            },
        )
        detail = PairSimilarityDetailDialog(
            pair=pair,
            submissions={
                "alice": self._submission("alice", "answer a"),
                "bob": self._submission("bob", "answer b"),
            },
            question_ids=["Q1"],
        )
        summary = detail.signal_text.toPlainText()
        self.assertIn("Embedding similarity", summary)
        self.assertIn("Max: 0.9500", summary)
        self.assertIn("Pseudocode structure similarity", summary)
        self.assertIn("Max: 0.8400", summary)
        self.assertIn("Clusters: C1", summary)
        self.assertIn("Trend count: 2", summary)
        self.assertIn("Submission provenance", summary)
        self.assertIn("machine_transcription", summary)
        self.assertIn("Assistive transcription: Yes", summary)
        detail.close()


if __name__ == "__main__":
    unittest.main()
