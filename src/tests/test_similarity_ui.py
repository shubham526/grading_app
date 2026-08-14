import os
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


if __name__ == "__main__":
    unittest.main()
