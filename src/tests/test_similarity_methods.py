import tempfile
import unittest

from src.similarity.compare import (
    VALID_SIMILARITY_METHODS,
    compare_submissions,
    resolve_similarity_methods,
)
from src.similarity.export import render_similarity_report_html
from src.similarity.report import generate_similarity_report


def assessment(student_id, answer, *, file_hash=None):
    meta = {"student_id": student_id}
    if file_hash:
        meta["file_hashes"] = {"latex_sha256": file_hash}
    return {
        "student_id": student_id,
        "extracted_answers": {"Q1": answer},
        "submission_meta": meta,
    }


class TestSimilarityMethodSelection(unittest.TestCase):
    def test_default_methods_are_all_deterministic_methods(self):
        self.assertEqual(resolve_similarity_methods(), VALID_SIMILARITY_METHODS)

    def test_methods_are_deduplicated_in_requested_order(self):
        self.assertEqual(
            resolve_similarity_methods(
                ["ngram_jaccard", "exact_file_hash", "ngram_jaccard"]
            ),
            ("ngram_jaccard", "exact_file_hash"),
        )

    def test_empty_method_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_similarity_methods([])

    def test_unknown_method_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_similarity_methods(["embedding_similarity"])

    def test_exact_method_can_be_disabled(self):
        shared_hash = "a" * 64
        result = compare_submissions(
            assessment("alice", "alpha beta gamma", file_hash=shared_hash),
            assessment("bob", "different words here", file_hash=shared_hash),
            ["Q1"],
            methods=["normalized_text_hash"],
        )
        self.assertFalse(result.exact_file_match)
        self.assertNotIn("exact_file_hash", result.signals)
        self.assertEqual(result.flag_level, "none")

    def test_normalized_method_can_be_disabled(self):
        result = compare_submissions(
            assessment("alice", r"The runtime is \\Theta(n)."),
            assessment("bob", "the runtime is theta n"),
            ["Q1"],
            methods=["exact_file_hash"],
        )
        self.assertFalse(result.normalized_text_match)
        self.assertNotIn("normalized_text_hash", result.signals)
        self.assertEqual(result.flag_level, "none")

    def test_ngram_method_can_be_disabled(self):
        text_a = (
            "we maintain an invariant while processing every item and update "
            "the stored maximum after each comparison across the full sequence"
        )
        text_b = (
            "we maintain an invariant while processing every item and update "
            "the stored maximum after each comparison across the full array"
        )
        result = compare_submissions(
            assessment("alice", text_a),
            assessment("bob", text_b),
            ["Q1"],
            methods=["exact_file_hash"],
        )
        self.assertEqual(result.question_similarities, {})
        self.assertNotIn("ngram_jaccard", result.signals)
        self.assertEqual(result.overall_score, 0.0)

    def test_report_records_only_selected_methods(self):
        report = generate_similarity_report(
            {
                "alice": assessment("alice", "alpha beta gamma"),
                "bob": assessment("bob", "alpha beta delta"),
            },
            "PS3",
            ["Q1"],
            methods=["ngram_jaccard"],
        )
        self.assertEqual(report.methods, ["ngram_jaccard"])
        self.assertEqual(len(report.pairs), 1)
        self.assertFalse(report.pairs[0].exact_file_match)
        self.assertFalse(report.pairs[0].normalized_text_match)
        self.assertIn("ngram_jaccard", report.pairs[0].signals)


    def test_html_keeps_side_by_side_detail_when_ngram_is_disabled(self):
        submissions = {
            "alice": assessment("alice", r"The runtime is \Theta(n)."),
            "bob": assessment("bob", "the runtime is theta n"),
        }
        report = generate_similarity_report(
            submissions,
            "PS3",
            ["Q1"],
            methods=["normalized_text_hash"],
        )
        self.assertEqual(report.pairs[0].flag_level, "high")
        self.assertEqual(report.pairs[0].question_similarities, {})
        html = render_similarity_report_html(report, submissions=submissions)
        self.assertIn('class="answer-grid"', html)
        self.assertIn("N-gram overlap was not selected", html)

if __name__ == "__main__":
    unittest.main()
