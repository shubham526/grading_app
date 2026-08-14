import tempfile
import unittest
from pathlib import Path

from src.similarity.compare import (
    DEFAULT_THRESHOLDS,
    compare_submissions,
    compute_question_ngram_similarity,
)
from src.submissions.models import ParsedSubmission


def assessment(
    student_id,
    answers,
    *,
    files=None,
    file_hashes=None,
    raw_text="",
):
    return {
        "student_id": student_id,
        "raw_text": raw_text,
        "extracted_answers": dict(answers),
        "submission_meta": {
            "student_id": student_id,
            "files": dict(files or {}),
            "file_hashes": dict(file_hashes or {}),
        },
    }


class TestQuestionNgramSimilarity(unittest.TestCase):
    def test_compares_only_matching_question_ids(self):
        scores = compute_question_ngram_similarity(
            {
                "Q1": "alpha beta gamma delta epsilon zeta",
                "Q2": "this is the same localized answer text",
            },
            {
                "Q1": "entirely different words appear over here",
                "Q2": "this is the same localized answer text",
            },
            ["Q1", "Q2"],
        )
        self.assertEqual(set(scores), {"Q1", "Q2"})
        self.assertLess(scores["Q1"], scores["Q2"])
        self.assertEqual(scores["Q2"], 1.0)

    def test_missing_question_is_not_cross_compared(self):
        scores = compute_question_ngram_similarity(
            {"Q1": "same same same answer"},
            {"Q2": "same same same answer"},
            ["Q1", "Q2"],
        )
        self.assertEqual(scores, {})

    def test_invalid_n_is_rejected(self):
        with self.assertRaises(ValueError):
            compute_question_ngram_similarity({"Q1": "x"}, {"Q1": "x"}, ["Q1"], n=0)


class TestExactFileSimilarity(unittest.TestCase):
    def test_identical_same_type_source_files_flag_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "alice.tex"
            b = Path(tmp) / "bob.tex"
            a.write_text("identical bytes", encoding="utf-8")
            b.write_text("identical bytes", encoding="utf-8")

            result = compare_submissions(
                assessment("alice", {"Q1": "different text a"}, files={"latex": str(a)}),
                assessment("bob", {"Q1": "different text b"}, files={"latex": str(b)}),
                ["Q1"],
            )

        self.assertTrue(result.exact_file_match)
        self.assertEqual(result.flag_level, "exact")
        self.assertEqual(result.overall_score, 1.0)
        self.assertEqual(
            result.signals["exact_file_hash"]["details"]["matching_file_type"],
            "latex",
        )

    def test_stored_hashes_work_when_source_paths_are_unavailable(self):
        shared = "a" * 64
        result = compare_submissions(
            assessment(
                "alice",
                {"Q1": "alpha"},
                files={"latex": "/moved/alice.tex"},
                file_hashes={"latex_sha256": shared},
            ),
            assessment(
                "bob",
                {"Q1": "beta"},
                files={"latex": "/moved/bob.tex"},
                file_hashes={"latex_sha256": shared},
            ),
            ["Q1"],
        )
        self.assertTrue(result.exact_file_match)
        self.assertEqual(result.flag_level, "exact")

    def test_different_logical_file_types_do_not_exact_match(self):
        shared = "b" * 64
        result = compare_submissions(
            assessment(
                "alice",
                {"Q1": "alpha"},
                file_hashes={"latex_sha256": shared},
            ),
            assessment(
                "bob",
                {"Q1": "beta"},
                file_hashes={"pdf_sha256": shared},
            ),
            ["Q1"],
        )
        self.assertFalse(result.exact_file_match)

    def test_compiled_pdf_is_not_used_as_student_source_exact_match(self):
        shared = "c" * 64
        result = compare_submissions(
            assessment(
                "alice",
                {"Q1": "alpha"},
                file_hashes={"compiled_pdf_sha256": shared},
            ),
            assessment(
                "bob",
                {"Q1": "beta"},
                file_hashes={"compiled_pdf_sha256": shared},
            ),
            ["Q1"],
        )
        self.assertFalse(result.exact_file_match)


class TestNormalizedTextSimilarity(unittest.TestCase):
    def test_formatting_differences_produce_normalized_match(self):
        a = assessment(
            "alice",
            {"Q1": r"The runtime is \Theta(n \log n)."},
        )
        b = assessment(
            "bob",
            {"Q1": "the runtime is theta n log n"},
        )
        result = compare_submissions(a, b, ["Q1"])

        self.assertTrue(result.normalized_text_match)
        self.assertGreaterEqual(result.overall_score, 1.0)
        self.assertIn(result.flag_level, {"high", "exact"})
        self.assertEqual(
            result.signals["normalized_text_hash"]["details"]["matching_questions"],
            ["Q1"],
        )

    def test_raw_text_fallback_only_when_question_answers_unavailable(self):
        a = assessment("alice", {}, raw_text=r"\author{Alice} Actual proof text.")
        b = assessment("bob", {}, raw_text="actual proof text")
        result = compare_submissions(a, b, ["Q1"])

        self.assertTrue(result.normalized_text_match)
        self.assertEqual(result.flag_level, "high")
        self.assertIsNone(result.most_similar_question)
        self.assertTrue(
            result.signals["normalized_text_hash"]["details"]["assignment_level_fallback"]
        )

    def test_empty_text_does_not_count_as_normalized_match(self):
        result = compare_submissions(
            assessment("alice", {"Q1": ""}),
            assessment("bob", {"Q1": ""}),
            ["Q1"],
        )
        self.assertFalse(result.normalized_text_match)


class TestNgramFlagging(unittest.TestCase):
    def test_high_overlap_is_flagged_high_for_long_answers(self):
        base = (
            "we maintain an invariant that the prefix has already been processed "
            "and the maximum value stored is correct after every iteration because "
            "each new element is compared against the current maximum before continuing "
            "to the next position in the input sequence"
        )
        altered = (
            "we maintain an invariant that the prefix has already been processed "
            "and the maximum value stored is correct after every iteration because "
            "each new element is compared against the current maximum before continuing "
            "to the next position in the array sequence"
        )
        result = compare_submissions(
            assessment("alice", {"Q1": base}),
            assessment("bob", {"Q1": altered}),
            ["Q1"],
        )
        self.assertGreaterEqual(result.question_similarities["Q1"].ngram_jaccard, 0.80)
        self.assertEqual(result.flag_level, "high")
        self.assertFalse(result.normalized_text_match)

    def test_low_overlap_is_not_flagged(self):
        a = (
            "the algorithm scans every element and maintains the largest value "
            "encountered so far while moving from left to right through the array"
        )
        b = (
            "dynamic programming stores optimal subproblem values in a table "
            "and later reconstructs a solution by following predecessor choices"
        )
        result = compare_submissions(
            assessment("alice", {"Q1": a}),
            assessment("bob", {"Q1": b}),
            ["Q1"],
        )
        self.assertEqual(result.flag_level, "none")
        self.assertLess(result.overall_score, DEFAULT_THRESHOLDS["ngram_low"])

    def test_configured_thresholds_are_applied(self):
        a = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
        )
        b = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen different words appear at the end"
        )
        result = compare_submissions(
            assessment("alice", {"Q1": a}),
            assessment("bob", {"Q1": b}),
            ["Q1"],
            thresholds={
                "ngram_low": 0.20,
                "ngram_medium": 0.30,
                "ngram_high": 0.40,
                "ngram_exact": 0.99,
            },
        )
        self.assertIn(result.flag_level, {"medium", "high"})

    def test_invalid_threshold_order_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_submissions(
                assessment("alice", {"Q1": "a b c"}),
                assessment("bob", {"Q1": "a b c"}),
                ["Q1"],
                thresholds={
                    "ngram_low": 0.8,
                    "ngram_medium": 0.6,
                    "ngram_high": 0.9,
                    "ngram_exact": 0.95,
                },
            )

    def test_unknown_threshold_key_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_submissions(
                assessment("alice", {"Q1": "a b c"}),
                assessment("bob", {"Q1": "a b c"}),
                ["Q1"],
                thresholds={"mystery": 0.5},
            )


class TestShortAnswerHandling(unittest.TestCase):
    def test_short_ngram_exact_is_downgraded_and_warned(self):
        # Not normalized-identical, but the short-answer shingle set is identical
        # after repeated duplicate shingles collapse to a set.
        a = "alpha beta gamma alpha beta gamma"
        b = "alpha beta gamma alpha beta gamma alpha beta gamma"
        result = compare_submissions(
            assessment("alice", {"Q1": a}),
            assessment("bob", {"Q1": b}),
            ["Q1"],
        )

        question = result.question_similarities["Q1"]
        self.assertEqual(question.ngram_jaccard, 1.0)
        self.assertEqual(question.flag_level, "high")
        self.assertIn("short_answer_high_similarity", question.warnings)
        self.assertIn("short_answer_high_similarity", result.notes)

    def test_exact_file_match_is_never_downgraded_for_short_answer(self):
        shared = "d" * 64
        result = compare_submissions(
            assessment(
                "alice",
                {"Q1": "yes"},
                file_hashes={"latex_sha256": shared},
            ),
            assessment(
                "bob",
                {"Q1": "yes"},
                file_hashes={"latex_sha256": shared},
            ),
            ["Q1"],
        )
        self.assertEqual(result.flag_level, "exact")
        self.assertTrue(result.exact_file_match)

    def test_normalized_short_answer_match_remains_at_least_high(self):
        result = compare_submissions(
            assessment("alice", {"Q1": r"\Theta(n)"}),
            assessment("bob", {"Q1": "theta n"}),
            ["Q1"],
        )
        self.assertTrue(result.normalized_text_match)
        self.assertIn(result.flag_level, {"high", "exact"})


class TestPairMetadata(unittest.TestCase):
    def test_most_similar_question_is_selected(self):
        long_same = (
            "this question contains a long identical explanation of the algorithm "
            "including the invariant proof runtime argument and final conclusion "
            "with enough tokens to avoid the short answer confidence rule"
        )
        result = compare_submissions(
            assessment(
                "alice",
                {
                    "Q1": "alpha beta gamma delta epsilon zeta eta theta iota kappa",
                    "Q2": long_same,
                },
            ),
            assessment(
                "bob",
                {
                    "Q1": "completely unrelated discussion using other words entirely",
                    "Q2": long_same + " ",
                },
            ),
            ["Q1", "Q2"],
        )
        self.assertEqual(result.most_similar_question, "Q2")

    def test_missing_requested_question_adds_note_but_does_not_cross_compare(self):
        result = compare_submissions(
            assessment("alice", {"Q1": "same words here"}),
            assessment("bob", {"Q2": "same words here"}),
            ["Q1", "Q2"],
        )
        self.assertIn("missing_comparable_question:Q1", result.notes)
        self.assertIn("missing_comparable_question:Q2", result.notes)
        self.assertEqual(result.question_similarities, {})

    def test_no_comparable_text_is_not_a_failure(self):
        result = compare_submissions(
            assessment("alice", {}),
            assessment("bob", {}),
            ["Q1"],
        )
        self.assertEqual(result.flag_level, "none")
        self.assertEqual(result.overall_score, 0.0)
        self.assertIn("no_comparable_text", result.notes)

    def test_same_student_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_submissions(
                assessment("alice", {"Q1": "a"}),
                assessment("alice", {"Q1": "b"}),
                ["Q1"],
            )

    def test_parsed_submission_objects_are_supported(self):
        a = ParsedSubmission(
            student_id="alice",
            raw_text="",
            answers_by_question={"Q1": "a sufficiently distinctive answer"},
            files={},
        )
        b = ParsedSubmission(
            student_id="bob",
            raw_text="",
            answers_by_question={"Q1": "a sufficiently distinctive answer"},
            files={},
        )
        result = compare_submissions(a, b, ["Q1"])
        self.assertEqual(result.student_a, "alice")
        self.assertEqual(result.student_b, "bob")
        self.assertTrue(result.normalized_text_match)

    def test_duplicate_question_ids_are_processed_once(self):
        result = compare_submissions(
            assessment("alice", {"Q1": "one two three four"}),
            assessment("bob", {"Q1": "one two three four"}),
            ["Q1", "Q1"],
        )
        self.assertEqual(list(result.question_similarities), ["Q1"])


if __name__ == "__main__":
    unittest.main()
