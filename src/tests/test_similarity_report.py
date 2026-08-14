import math
import re
import unittest

from src.similarity.compare import DEFAULT_THRESHOLDS
from src.similarity.models import FLAG_RANK
from src.similarity.report import DEFAULT_METHODS, generate_similarity_report
from src.submissions.models import ParsedSubmission


def assessment(student_id, answers, *, warnings=None, file_hashes=None):
    return {
        "student_id": student_id,
        "extracted_answers": dict(answers),
        "submission_meta": {
            "student_id": student_id,
            "file_hashes": dict(file_hashes or {}),
            "warnings": list(warnings or []),
        },
    }


def long_text(prefix):
    return (
        f"{prefix} the algorithm maintains an invariant over every processed "
        "prefix and updates the stored state after examining each next element "
        "while preserving correctness throughout the complete sequence of steps"
    )


class TestSimilarityReportGeneration(unittest.TestCase):
    def test_report_compares_all_unique_pairs(self):
        submissions = {
            "alice": assessment("alice", {"Q1": long_text("alice")}),
            "bob": assessment("bob", {"Q1": long_text("bob")}),
            "carol": assessment("carol", {"Q1": long_text("carol")}),
            "dana": assessment("dana", {"Q1": long_text("dana")}),
        }

        report = generate_similarity_report(
            submissions,
            "PS3",
            ["Q1"],
        )

        self.assertEqual(len(report.students), 4)
        self.assertEqual(len(report.pairs), math.comb(4, 2))

        pair_ids = {
            frozenset((pair.student_a, pair.student_b))
            for pair in report.pairs
        }
        self.assertEqual(len(pair_ids), 6)

    def test_report_student_order_is_deterministic(self):
        submissions = {
            "zoe": assessment("zoe", {"Q1": "z answer"}),
            "alice": assessment("alice", {"Q1": "a answer"}),
            "mike": assessment("mike", {"Q1": "m answer"}),
        }
        report = generate_similarity_report(submissions, "PS3", ["Q1"])
        self.assertEqual(report.students, ["alice", "mike", "zoe"])

    def test_report_sorts_highest_flags_first(self):
        shared_exact_hash = "a" * 64
        long_high_a = (
            "we prove the loop invariant by showing initialization maintenance "
            "and termination then conclude the algorithm returns the correct "
            "maximum element after processing every entry in the input array"
        )
        long_high_b = (
            "we prove the loop invariant by showing initialization maintenance "
            "and termination then conclude the algorithm returns the correct "
            "maximum element after processing every entry in the input sequence"
        )

        submissions = {
            "alice": assessment(
                "alice",
                {"Q1": "brief unrelated alpha"},
                file_hashes={"latex_sha256": shared_exact_hash},
            ),
            "bob": assessment(
                "bob",
                {"Q1": "brief unrelated beta"},
                file_hashes={"latex_sha256": shared_exact_hash},
            ),
            "carol": assessment("carol", {"Q1": long_high_a}),
            "dana": assessment("dana", {"Q1": long_high_b}),
        }

        report = generate_similarity_report(submissions, "PS3", ["Q1"])

        ranks = [FLAG_RANK[pair.flag_level] for pair in report.pairs]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        self.assertEqual(report.pairs[0].flag_level, "exact")
        self.assertEqual(
            {report.pairs[0].student_a, report.pairs[0].student_b},
            {"alice", "bob"},
        )

    def test_score_breaks_ties_within_same_flag(self):
        base = (
            "we maintain the invariant while processing each element and update "
            "the best value whenever the new candidate improves the current state "
            "before continuing to the following position in the sequence"
        )
        close = (
            "we maintain the invariant while processing each element and update "
            "the best value whenever the new candidate improves the current state "
            "before continuing to the following position in the array"
        )
        farther = (
            "we maintain the invariant while processing each element and update "
            "the best value whenever the new candidate changes the state before "
            "continuing through a different part of the array"
        )

        submissions = {
            "alice": assessment("alice", {"Q1": base}),
            "bob": assessment("bob", {"Q1": close}),
            "carol": assessment("carol", {"Q1": farther}),
        }

        report = generate_similarity_report(
            submissions,
            "PS3",
            ["Q1"],
            thresholds={
                "ngram_low": 0.20,
                "ngram_medium": 0.30,
                "ngram_high": 0.40,
                "ngram_exact": 0.99,
            },
        )

        high_pairs = [p for p in report.pairs if p.flag_level == "high"]
        if len(high_pairs) >= 2:
            self.assertGreaterEqual(
                high_pairs[0].overall_score,
                high_pairs[1].overall_score,
            )

    def test_most_similar_question_is_preserved(self):
        shared_q2 = (
            "dynamic programming stores the best solution for each prefix and "
            "combines previously computed states to avoid repeated recursive work "
            "before returning the final optimal value for the complete instance"
        )
        submissions = {
            "alice": assessment(
                "alice",
                {
                    "Q1": "an unrelated discussion about heaps and priority queues",
                    "Q2": shared_q2,
                },
            ),
            "bob": assessment(
                "bob",
                {
                    "Q1": "a different argument involving graph traversal",
                    "Q2": shared_q2 + " ",
                },
            ),
        }

        report = generate_similarity_report(submissions, "PS3", ["Q1", "Q2"])
        self.assertEqual(len(report.pairs), 1)
        self.assertEqual(report.pairs[0].most_similar_question, "Q2")

    def test_thresholds_are_resolved_and_stored(self):
        report = generate_similarity_report(
            {
                "alice": assessment("alice", {"Q1": long_text("a")}),
                "bob": assessment("bob", {"Q1": long_text("b")}),
            },
            "PS3",
            ["Q1"],
            thresholds={"ngram_high": 0.75},
        )
        expected = dict(DEFAULT_THRESHOLDS)
        expected["ngram_high"] = 0.75
        self.assertEqual(report.thresholds, expected)

    def test_invalid_thresholds_fail_even_with_no_pairs(self):
        with self.assertRaises(ValueError):
            generate_similarity_report(
                {},
                "PS3",
                ["Q1"],
                thresholds={
                    "ngram_low": 0.90,
                    "ngram_medium": 0.60,
                    "ngram_high": 0.80,
                    "ngram_exact": 0.95,
                },
            )

    def test_submission_warnings_are_preserved(self):
        report = generate_similarity_report(
            {
                "alice": assessment(
                    "alice",
                    {"Q1": "answer"},
                    warnings=["pdf_text_fallback_used"],
                ),
                "bob": assessment("bob", {"Q1": "different"}),
            },
            "PS3",
            ["Q1"],
        )
        self.assertIn(
            "submission_warning:alice:pdf_text_fallback_used",
            report.warnings,
        )

    def test_pair_warnings_are_preserved_at_report_level(self):
        # Repeated trigram content creates n-gram identity without normalized
        # identity, triggering the short-answer confidence warning.
        report = generate_similarity_report(
            {
                "alice": assessment(
                    "alice",
                    {"Q1": "alpha beta gamma alpha beta gamma"},
                ),
                "bob": assessment(
                    "bob",
                    {"Q1": "alpha beta gamma alpha beta gamma alpha beta gamma"},
                ),
            },
            "PS3",
            ["Q1"],
        )
        self.assertTrue(
            any(
                warning.endswith(":short_answer_high_similarity")
                for warning in report.warnings
            )
        )

    def test_comparison_failure_becomes_warning_and_other_pairs_continue(self):
        submissions = {
            "bad": {
                # Intentionally missing student_id.
                "extracted_answers": {"Q1": "bad submission"},
            },
            "alice": assessment("alice", {"Q1": long_text("alice")}),
            "bob": assessment("bob", {"Q1": long_text("bob")}),
        }

        report = generate_similarity_report(submissions, "PS3", ["Q1"])

        # alice/bob remains comparable even though pairs involving "bad" fail.
        self.assertTrue(
            any(
                {pair.student_a, pair.student_b} == {"alice", "bob"}
                for pair in report.pairs
            )
        )
        self.assertTrue(
            any(warning.startswith("comparison_failed:") for warning in report.warnings)
        )

    def test_empty_report_is_valid(self):
        report = generate_similarity_report({}, "PS3", ["Q1"])
        self.assertEqual(report.pairs, [])
        self.assertEqual(report.students, [])
        self.assertEqual(report.warnings, [])

    def test_single_student_report_has_no_pairs(self):
        report = generate_similarity_report(
            {"alice": assessment("alice", {"Q1": "answer"})},
            "PS3",
            ["Q1"],
        )
        self.assertEqual(report.students, ["alice"])
        self.assertEqual(report.pairs, [])

    def test_duplicate_question_ids_are_deduplicated(self):
        report = generate_similarity_report(
            {
                "alice": assessment("alice", {"Q1": long_text("same")}),
                "bob": assessment("bob", {"Q1": long_text("same")}),
            },
            "PS3",
            ["Q1", "Q1", "", "Q1"],
        )
        self.assertEqual(
            list(report.pairs[0].question_similarities),
            ["Q1"],
        )

    def test_methods_match_v230_deterministic_scope(self):
        report = generate_similarity_report({}, "PS3", [])
        self.assertEqual(report.methods, DEFAULT_METHODS)
        self.assertEqual(
            report.methods,
            [
                "exact_file_hash",
                "normalized_text_hash",
                "ngram_jaccard",
            ],
        )

    def test_report_type_and_assignment_id(self):
        report = generate_similarity_report({}, "PS3", [])
        self.assertEqual(report.report_type, "submission_similarity")
        self.assertEqual(report.assignment_id, "PS3")

    def test_generated_at_is_utc_iso_timestamp(self):
        report = generate_similarity_report({}, "PS3", [])
        self.assertRegex(
            report.generated_at,
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

    def test_blank_assignment_id_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_similarity_report({}, "   ", [])

    def test_non_mapping_submissions_are_rejected(self):
        with self.assertRaises(TypeError):
            generate_similarity_report([], "PS3", [])


class TestParsedSubmissionWarnings(unittest.TestCase):
    def test_parsed_submission_warning_is_carried_to_report(self):
        parsed = ParsedSubmission(
            student_id="alice",
            raw_text="",
            answers_by_question={"Q1": "answer"},
            files={},
            warnings=["typed_pdf_text_extraction_used"],
        )
        report = generate_similarity_report(
            {
                "alice": parsed,
                "bob": assessment("bob", {"Q1": "other answer"}),
            },
            "PS3",
            ["Q1"],
        )
        self.assertIn(
            "submission_warning:alice:typed_pdf_text_extraction_used",
            report.warnings,
        )


if __name__ == "__main__":
    unittest.main()
