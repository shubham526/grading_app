import json
from pathlib import Path
import tempfile
import unittest

from src.similarity.models import PairSimilarity, QuestionSimilarity, SimilarityReport
from src.similarity.trends import (
    DEFAULT_TREND_MIN_ASSIGNMENT_COUNT,
    DEFAULT_TREND_MIN_FLAG_LEVEL,
    TRENDS_REVIEW_WARNING,
    analyze_similarity_trends,
    load_similarity_reports,
    similarity_report_from_dict,
)


def make_pair(
    a,
    b,
    *,
    score,
    flag,
    question=None,
    question_flag=None,
    exact=False,
    normalized=False,
    signals=None,
):
    question_similarities = {}
    if question is not None:
        question_similarities[question] = QuestionSimilarity(
            question_id=question,
            ngram_jaccard=score,
            flag_level=question_flag or flag,
        )

    return PairSimilarity(
        student_a=a,
        student_b=b,
        overall_score=score,
        flag_level=flag,
        most_similar_question=question,
        exact_file_match=exact,
        normalized_text_match=normalized,
        question_similarities=question_similarities,
        signals=dict(signals or {}),
    )


def make_report(assignment_id, pairs):
    students = sorted(
        {
            student
            for pair in pairs
            for student in (pair.student_a, pair.student_b)
        }
    )
    return SimilarityReport(
        assignment_id=assignment_id,
        generated_at="2026-08-14T12:00:00Z",
        methods=["exact_file_hash", "normalized_text_hash", "ngram_jaccard"],
        students=students,
        pairs=list(pairs),
        thresholds={
            "ngram_low": 0.50,
            "ngram_medium": 0.65,
            "ngram_high": 0.80,
            "ngram_exact": 0.95,
        },
    )


class TestTrendDefaults(unittest.TestCase):
    def test_defaults_match_design_intent(self):
        self.assertEqual(DEFAULT_TREND_MIN_FLAG_LEVEL, "high")
        self.assertEqual(DEFAULT_TREND_MIN_ASSIGNMENT_COUNT, 2)
        self.assertEqual(
            TRENDS_REVIEW_WARNING,
            "trends_are_not_misconduct_evidence",
        )


class TestTrendAnalysis(unittest.TestCase):
    def test_detects_repeated_high_similarity_pair(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.91, flag="high", question="Q1")],
            ),
            make_report(
                "PS2",
                [make_pair("alice", "bob", score=0.96, flag="exact", question="Q2")],
            ),
        ]

        trends = analyze_similarity_trends(reports)

        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0]["student_a"], "alice")
        self.assertEqual(trends[0]["student_b"], "bob")
        self.assertEqual(trends[0]["assignments"], ["PS1", "PS2"])
        self.assertEqual(trends[0]["count"], 2)
        self.assertEqual(trends[0]["max_similarity"], 0.96)

    def test_reversed_pair_order_is_canonicalized(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.91, flag="high", question="Q1")],
            ),
            make_report(
                "PS2",
                [make_pair("bob", "alice", score=0.92, flag="high", question="Q2")],
            ),
        ]

        trend = analyze_similarity_trends(reports)[0]
        self.assertEqual((trend["student_a"], trend["student_b"]), ("alice", "bob"))

    def test_preserves_questions_by_assignment(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.91, flag="high", question="Q1")],
            ),
            make_report(
                "PS2",
                [make_pair("alice", "bob", score=0.93, flag="high", question="Q3")],
            ),
        ]

        trend = analyze_similarity_trends(reports)[0]

        self.assertEqual(
            trend["questions"],
            {
                "PS1": ["Q1"],
                "PS2": ["Q3"],
            },
        )

    def test_aggregates_signal_names_across_assignments(self):
        reports = [
            make_report(
                "PS1",
                [
                    make_pair(
                        "alice",
                        "bob",
                        score=1.0,
                        flag="exact",
                        exact=True,
                        signals={
                            "exact_file_hash": {
                                "method": "exact_file_hash",
                                "score": 1.0,
                            }
                        },
                    )
                ],
            ),
            make_report(
                "PS2",
                [
                    make_pair(
                        "alice",
                        "bob",
                        score=0.95,
                        flag="high",
                        question="Q2",
                        signals={
                            "embedding_cosine": {
                                "Q2": 0.95,
                            }
                        },
                    )
                ],
            ),
        ]

        trend = analyze_similarity_trends(reports)[0]
        self.assertEqual(
            trend["signals"],
            ["embedding_cosine", "exact_file_hash", "ngram_jaccard"],
        )

    def test_low_or_medium_pairs_do_not_count_at_default_threshold(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.70, flag="medium", question="Q1")],
            ),
            make_report(
                "PS2",
                [make_pair("alice", "bob", score=0.75, flag="medium", question="Q2")],
            ),
        ]
        self.assertEqual(analyze_similarity_trends(reports), [])

    def test_one_off_similarity_is_not_a_trend_by_default(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.91, flag="high", question="Q1")],
            ),
            make_report(
                "PS2",
                [make_pair("alice", "carol", score=0.92, flag="high", question="Q1")],
            ),
        ]

        self.assertEqual(analyze_similarity_trends(reports), [])

    def test_one_off_similarity_can_be_requested_explicitly(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.91, flag="high", question="Q1")],
            )
        ]

        trends = analyze_similarity_trends(
            reports,
            min_assignment_count=1,
        )

        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0]["count"], 1)

    def test_medium_threshold_can_be_requested(self):
        reports = [
            make_report(
                "PS1",
                [make_pair("alice", "bob", score=0.70, flag="medium", question="Q1")],
            ),
            make_report(
                "PS2",
                [make_pair("alice", "bob", score=0.72, flag="medium", question="Q2")],
            ),
        ]

        trends = analyze_similarity_trends(
            reports,
            min_flag_level="medium",
        )
        self.assertEqual(len(trends), 1)

    def test_trends_sort_by_count_then_max_similarity_then_pair(self):
        reports = [
            make_report(
                "PS1",
                [
                    make_pair("alice", "bob", score=0.90, flag="high"),
                    make_pair("carol", "dana", score=0.99, flag="exact"),
                ],
            ),
            make_report(
                "PS2",
                [
                    make_pair("alice", "bob", score=0.91, flag="high"),
                    make_pair("carol", "dana", score=0.97, flag="exact"),
                ],
            ),
            make_report(
                "PS3",
                [make_pair("alice", "bob", score=0.92, flag="high")],
            ),
        ]

        trends = analyze_similarity_trends(reports)
        self.assertEqual(
            [(item["student_a"], item["student_b"]) for item in trends],
            [("alice", "bob"), ("carol", "dana")],
        )

    def test_duplicate_assignment_ids_are_rejected(self):
        reports = [
            make_report("PS1", []),
            make_report("PS1", []),
        ]
        with self.assertRaises(ValueError):
            analyze_similarity_trends(reports)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze_similarity_trends([], min_flag_level="severe")
        with self.assertRaises(ValueError):
            analyze_similarity_trends([], min_assignment_count=0)


class TestTrendReportLoading(unittest.TestCase):
    def test_similarity_report_round_trip_from_dict(self):
        report = make_report(
            "PS1",
            [
                make_pair(
                    "alice",
                    "bob",
                    score=0.91,
                    flag="high",
                    question="Q1",
                )
            ],
        )

        loaded = similarity_report_from_dict(report.to_dict())

        self.assertIsInstance(loaded, SimilarityReport)
        self.assertEqual(loaded.assignment_id, "PS1")
        self.assertEqual(len(loaded.pairs), 1)
        self.assertIsInstance(
            loaded.pairs[0].question_similarities["Q1"],
            QuestionSimilarity,
        )

    def test_loads_nested_similarity_report_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for assignment, score in [("PS2", 0.93), ("PS1", 0.91)]:
                folder = root / assignment
                folder.mkdir(parents=True)
                report = make_report(
                    assignment,
                    [
                        make_pair(
                            "alice",
                            "bob",
                            score=score,
                            flag="high",
                            question="Q1",
                        )
                    ],
                )
                (folder / "similarity_report.json").write_text(
                    json.dumps(report.to_dict()),
                    encoding="utf-8",
                )

            reports = load_similarity_reports(root)
            self.assertEqual(
                [report.assignment_id for report in reports],
                ["PS1", "PS2"],
            )

    def test_duplicate_assignment_ids_in_folder_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder_name in ["copy1", "copy2"]:
                folder = root / folder_name
                folder.mkdir(parents=True)
                report = make_report("PS1", [])
                (folder / "similarity_report.json").write_text(
                    json.dumps(report.to_dict()),
                    encoding="utf-8",
                )

            with self.assertRaises(ValueError):
                load_similarity_reports(root)

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "PS1"
            folder.mkdir(parents=True)
            (folder / "similarity_report.json").write_text(
                "{not valid json",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_similarity_reports(root)

    def test_missing_folder_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with self.assertRaises(FileNotFoundError):
                load_similarity_reports(missing)


class TestTrendModelExtension(unittest.TestCase):
    def test_pair_trend_flags_serialize_and_deduplicate(self):
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            trend_flags=["repeated_high_similarity", "", "repeated_high_similarity", " PS1_PS2 "],
        )
        self.assertEqual(
            pair.trend_flags,
            ["repeated_high_similarity", "PS1_PS2"],
        )
        self.assertEqual(
            pair.to_dict()["trend_flags"],
            ["repeated_high_similarity", "PS1_PS2"],
        )


if __name__ == "__main__":
    unittest.main()
