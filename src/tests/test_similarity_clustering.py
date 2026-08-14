import unittest

from src.similarity.clustering import (
    DEFAULT_CLUSTER_MIN_FLAG_LEVEL,
    build_similarity_graph,
    find_similarity_clusters,
)
from src.similarity.models import PairSimilarity, QuestionSimilarity


def make_pair(
    a,
    b,
    *,
    score,
    flag,
    question=None,
    question_flag="none",
    exact=False,
    normalized=False,
    signals=None,
):
    question_similarities = {}
    if question is not None:
        question_similarities[question] = QuestionSimilarity(
            question_id=question,
            ngram_jaccard=score,
            flag_level=question_flag,
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


class TestSimilarityGraph(unittest.TestCase):
    def test_default_minimum_is_high(self):
        self.assertEqual(DEFAULT_CLUSTER_MIN_FLAG_LEVEL, "high")

    def test_builds_undirected_graph_and_keeps_isolated_students(self):
        pairs = [
            make_pair("alice", "bob", score=0.91, flag="high"),
            make_pair("alice", "carol", score=0.60, flag="low"),
            make_pair("bob", "carol", score=0.62, flag="low"),
        ]

        graph = build_similarity_graph(pairs)

        self.assertEqual(graph["alice"], {"bob"})
        self.assertEqual(graph["bob"], {"alice"})
        self.assertEqual(graph["carol"], set())

    def test_ignores_edges_below_requested_flag_level(self):
        pairs = [
            make_pair("alice", "bob", score=0.99, flag="exact"),
            make_pair("bob", "carol", score=0.84, flag="high"),
            make_pair("carol", "dana", score=0.70, flag="medium"),
        ]

        graph = build_similarity_graph(pairs, min_flag_level="exact")

        self.assertEqual(graph["alice"], {"bob"})
        self.assertEqual(graph["bob"], {"alice"})
        self.assertEqual(graph["carol"], set())
        self.assertEqual(graph["dana"], set())

    def test_invalid_minimum_flag_level_is_rejected(self):
        with self.assertRaises(ValueError):
            build_similarity_graph([], min_flag_level="severe")

    def test_non_pair_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            build_similarity_graph([{"student_a": "alice"}])


class TestSimilarityClusters(unittest.TestCase):
    def test_finds_connected_components(self):
        pairs = [
            make_pair("alice", "bob", score=0.91, flag="high", question="Q1", question_flag="high"),
            make_pair("bob", "chen", score=0.89, flag="high", question="Q2", question_flag="high"),
            make_pair("alice", "chen", score=0.20, flag="none", question="Q3"),
            make_pair("dana", "elias", score=1.00, flag="exact", exact=True),
            make_pair("frank", "grace", score=0.60, flag="low"),
        ]

        clusters = find_similarity_clusters(pairs)

        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["cluster_id"], "C1")
        self.assertEqual(clusters[0]["students"], ["alice", "bob", "chen"])
        self.assertEqual(clusters[0]["size"], 3)

        self.assertEqual(clusters[1]["cluster_id"], "C2")
        self.assertEqual(clusters[1]["students"], ["dana", "elias"])
        self.assertEqual(clusters[1]["size"], 2)

    def test_singletons_are_not_returned_as_clusters(self):
        pairs = [
            make_pair("alice", "bob", score=0.50, flag="low"),
            make_pair("alice", "carol", score=0.40, flag="none"),
            make_pair("bob", "carol", score=0.45, flag="none"),
        ]
        self.assertEqual(find_similarity_clusters(pairs), [])

    def test_cluster_metadata_reports_max_similarity_questions_and_signals(self):
        pairs = [
            make_pair(
                "alice",
                "bob",
                score=0.91,
                flag="high",
                question="Q1",
                question_flag="high",
            ),
            make_pair(
                "bob",
                "chen",
                score=0.97,
                flag="exact",
                question="Q2",
                question_flag="exact",
                signals={"pseudocode_structure": {"Q2": 0.97}},
            ),
            make_pair(
                "alice",
                "chen",
                score=1.00,
                flag="high",
                question="Q3",
                normalized=True,
                signals={
                    "normalized_text_hash": {
                        "details": {
                            "matching_questions": ["Q3"],
                            "assignment_level_fallback": False,
                        }
                    }
                },
            ),
        ]

        cluster = find_similarity_clusters(pairs)[0]

        self.assertEqual(cluster["max_similarity"], 1.0)
        self.assertEqual(cluster["questions"], ["Q1", "Q2", "Q3"])
        self.assertEqual(
            cluster["signals"],
            [
                "ngram_jaccard",
                "normalized_text_hash",
                "pseudocode_structure",
            ],
        )

    def test_exact_file_signal_is_reported_without_question(self):
        pairs = [
            make_pair(
                "alice",
                "bob",
                score=1.0,
                flag="exact",
                exact=True,
            )
        ]

        cluster = find_similarity_clusters(pairs)[0]
        self.assertEqual(cluster["questions"], [])
        self.assertEqual(cluster["signals"], ["exact_file_hash"])

    def test_medium_clusters_can_be_requested(self):
        pairs = [
            make_pair(
                "alice",
                "bob",
                score=0.70,
                flag="medium",
                question="Q4",
                question_flag="medium",
            )
        ]

        self.assertEqual(find_similarity_clusters(pairs), [])
        medium = find_similarity_clusters(pairs, min_flag_level="medium")
        self.assertEqual(len(medium), 1)
        self.assertEqual(medium[0]["questions"], ["Q4"])

    def test_cluster_ids_are_deterministic_independent_of_pair_input_order(self):
        pairs = [
            make_pair("dana", "elias", score=0.95, flag="exact"),
            make_pair("alice", "bob", score=0.90, flag="high"),
            make_pair("bob", "chen", score=0.88, flag="high"),
        ]

        forward = find_similarity_clusters(pairs)
        reverse = find_similarity_clusters(list(reversed(pairs)))

        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0]["students"], ["alice", "bob", "chen"])
        self.assertEqual(forward[0]["cluster_id"], "C1")
        self.assertEqual(forward[1]["students"], ["dana", "elias"])
        self.assertEqual(forward[1]["cluster_id"], "C2")

    def test_same_size_clusters_sort_by_max_similarity_then_student_names(self):
        pairs = [
            make_pair("alice", "bob", score=0.90, flag="high"),
            make_pair("carol", "dana", score=0.97, flag="exact"),
            make_pair("erin", "frank", score=0.90, flag="high"),
        ]

        clusters = find_similarity_clusters(pairs)

        self.assertEqual(clusters[0]["students"], ["carol", "dana"])
        self.assertEqual(clusters[1]["students"], ["alice", "bob"])
        self.assertEqual(clusters[2]["students"], ["erin", "frank"])


class TestClusterModelExtension(unittest.TestCase):
    def test_pair_cluster_ids_serialize_and_deduplicate(self):
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            cluster_ids=["C2", "C2", "", " C1 "],
        )
        self.assertEqual(pair.cluster_ids, ["C2", "C1"])
        self.assertEqual(pair.to_dict()["cluster_ids"], ["C2", "C1"])


if __name__ == "__main__":
    unittest.main()
