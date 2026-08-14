import math
import unittest

from src.similarity.advanced_report import (
    ASSISTIVE_TRANSCRIPTION_REVIEW_WARNING,
    CROSS_ASSIGNMENT_TREND_FLAG,
    EMBEDDING_REVIEW_WARNING,
    generate_advanced_similarity_report,
    submission_similarity_provenance,
)
from src.similarity.mock_embedding_provider import MockEmbeddingProvider
from src.similarity.pseudocode import PSEUDOCODE_REVIEW_WARNING
from src.similarity.report import generate_similarity_report
from src.similarity.trends import (
    TRENDS_REVIEW_WARNING,
    analyze_similarity_trends,
    similarity_report_from_dict,
)


def assessment(student_id, answers, **meta_overrides):
    meta = {
        "student_id": student_id,
        "source_used": "latex",
        "submission_mode": "latex",
        "accommodation_mode": False,
        "authoritative_source": "latex",
        "assistive_text_source": None,
        "warnings": [],
    }
    meta.update(meta_overrides)
    return {
        "student_id": student_id,
        "criteria": [],
        "submission_meta": meta,
        "extracted_answers": dict(answers),
    }


def base_report(submissions, assignment_id="PS1", question_ids=("Q1",), methods=("ngram_jaccard",)):
    return generate_similarity_report(
        submissions,
        assignment_id,
        list(question_ids),
        methods=list(methods),
    )


class TestAdvancedEmbeddingIntegration(unittest.TestCase):
    def test_embedding_augments_base_report_without_mutating_it(self):
        answer_a = " ".join(f"alpha{i}" for i in range(40))
        answer_b = " ".join(f"beta{i}" for i in range(40))
        submissions = {
            "alice": assessment("alice", {"Q1": answer_a}),
            "bob": assessment("bob", {"Q1": answer_b}),
        }
        base = base_report(submissions)
        before = base.to_dict()

        cosine = 0.95
        provider = MockEmbeddingProvider(
            vectors={
                answer_a: [1.0, 0.0],
                answer_b: [cosine, math.sqrt(1.0 - cosine * cosine)],
            }
        )
        advanced = generate_advanced_similarity_report(
            base,
            submissions,
            ["Q1"],
            embedding_provider=provider,
            include_pseudocode=False,
            include_clustering=False,
            embedding_cache_enabled=False,
        )

        self.assertEqual(base.to_dict(), before)
        pair = advanced.pairs[0]
        question = pair.question_similarities["Q1"]
        self.assertAlmostEqual(pair.embedding_max_similarity, cosine)
        self.assertAlmostEqual(question.embedding_cosine, cosine)
        self.assertEqual(question.flag_level, "none")  # deterministic n-gram remains separate
        self.assertIn("embedding_high", question.advanced_flags)
        self.assertEqual(pair.flag_level, "high")
        self.assertAlmostEqual(pair.overall_score, cosine)
        self.assertEqual(pair.most_similar_question, "Q1")
        self.assertIn("embedding_cosine", pair.signals)
        self.assertIn("high_semantic_similarity_low_textual_overlap", pair.notes)
        self.assertIn(EMBEDDING_REVIEW_WARNING, advanced.warnings)
        self.assertEqual(advanced.advanced_methods, ["embedding_cosine"])
        self.assertTrue(advanced.embedding_config["enabled"])
        self.assertEqual(advanced.embedding_config["provider"], "mock")
        self.assertEqual(advanced.embedding_config["model"], "mock-embedding")

    def test_embedding_is_cleanly_disabled_without_provider(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "answer one"}),
            "bob": assessment("bob", {"Q1": "answer two"}),
        }
        base = base_report(submissions)
        advanced = generate_advanced_similarity_report(
            base,
            submissions,
            ["Q1"],
            embedding_provider=None,
            include_pseudocode=False,
            include_clustering=False,
        )

        self.assertFalse(advanced.embedding_config["enabled"])
        self.assertNotIn("embedding_cosine", advanced.advanced_methods)
        self.assertIsNone(advanced.pairs[0].embedding_max_similarity)
        self.assertNotIn("embedding_cosine", advanced.pairs[0].signals)

    def test_advanced_threshold_override_is_applied(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "alpha response"}),
            "bob": assessment("bob", {"Q1": "beta response"}),
        }
        provider = MockEmbeddingProvider(
            vectors={
                "alpha response": [1.0, 0.0],
                "beta response": [0.90, math.sqrt(1.0 - 0.90**2)],
            }
        )
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            embedding_provider=provider,
            include_pseudocode=False,
            include_clustering=False,
            thresholds={
                "embedding_medium": 0.80,
                "embedding_high": 0.89,
                "embedding_exact": 0.99,
            },
            embedding_cache_enabled=False,
        )
        self.assertEqual(advanced.pairs[0].flag_level, "high")
        self.assertEqual(advanced.thresholds["embedding_high"], 0.89)

    def test_unknown_advanced_threshold_is_rejected(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "a"}),
            "bob": assessment("bob", {"Q1": "b"}),
        }
        with self.assertRaises(ValueError):
            generate_advanced_similarity_report(
                base_report(submissions),
                submissions,
                ["Q1"],
                include_pseudocode=False,
                include_clustering=False,
                thresholds={"mystery_threshold": 0.5},
            )


class TestAdvancedPseudocodeIntegration(unittest.TestCase):
    def test_pseudocode_signal_is_added_separately_from_text_overlap(self):
        answer_a = """Algorithm:\nfor i = 1 to n\nif A[i] > best\nbest = A[i]\n"""
        answer_b = """Pseudocode:\nfor j = 1 to m\nif B[j] > maximum\nmaximum = B[j]\n"""
        submissions = {
            "alice": assessment("alice", {"Q1": answer_a}),
            "bob": assessment("bob", {"Q1": answer_b}),
        }
        base = base_report(submissions, methods=("exact_file_hash",))
        advanced = generate_advanced_similarity_report(
            base,
            submissions,
            ["Q1"],
            embedding_provider=None,
            include_pseudocode=True,
            include_clustering=False,
        )

        pair = advanced.pairs[0]
        question = pair.question_similarities["Q1"]
        self.assertAlmostEqual(pair.pseudocode_max_similarity, 1.0)
        self.assertAlmostEqual(question.pseudocode_similarity, 1.0)
        self.assertEqual(question.flag_level, "none")
        self.assertIn("pseudocode_exact", question.advanced_flags)
        self.assertEqual(pair.flag_level, "exact")
        self.assertEqual(pair.overall_score, 1.0)
        self.assertIn("pseudocode_structure", pair.signals)
        self.assertIn(PSEUDOCODE_REVIEW_WARNING, pair.notes)
        self.assertIn(PSEUDOCODE_REVIEW_WARNING, advanced.warnings)
        self.assertEqual(advanced.pseudocode_config["method"], "normalized_token_3gram_jaccard")

    def test_no_pseudocode_block_does_not_create_signal(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "ordinary explanation"}),
            "bob": assessment("bob", {"Q1": "another explanation"}),
        }
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            include_pseudocode=True,
            include_clustering=False,
        )
        self.assertIsNone(advanced.pairs[0].pseudocode_max_similarity)
        self.assertNotIn("pseudocode_structure", advanced.pairs[0].signals)


class TestAdvancedClusteringIntegration(unittest.TestCase):
    def test_clusters_are_generated_after_advanced_pair_flags(self):
        answers = {
            "alice": "alice semantically same but lexically unique answer sequence one",
            "bob": "bob semantically same while wording differs answer sequence two",
            "chen": "chen equivalent reasoning with completely different terms three",
        }
        submissions = {
            student: assessment(student, {"Q1": text})
            for student, text in answers.items()
        }
        provider = MockEmbeddingProvider(
            vectors={text: [1.0, 0.0] for text in answers.values()}
        )
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            embedding_provider=provider,
            include_pseudocode=False,
            include_clustering=True,
            embedding_cache_enabled=False,
        )

        self.assertEqual(len(advanced.clusters), 1)
        cluster = advanced.clusters[0]
        self.assertEqual(cluster["cluster_id"], "C1")
        self.assertEqual(cluster["students"], ["alice", "bob", "chen"])
        self.assertEqual(cluster["signals"], ["embedding_cosine"])
        self.assertEqual(cluster["questions"], ["Q1"])
        self.assertTrue(all(pair.cluster_ids == ["C1"] for pair in advanced.pairs))
        self.assertIn("clustering", advanced.advanced_methods)

    def test_clustering_can_be_disabled(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "a"}),
            "bob": assessment("bob", {"Q1": "b"}),
        }
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            include_pseudocode=False,
            include_clustering=False,
        )
        self.assertEqual(advanced.clusters, [])
        self.assertNotIn("clustering", advanced.advanced_methods)


class TestAdvancedTrendIntegration(unittest.TestCase):
    def test_current_assignment_trend_updates_flag_but_not_current_score(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "unique alice"}),
            "bob": assessment("bob", {"Q1": "unique bob"}),
        }
        base = base_report(submissions)
        self.assertEqual(base.pairs[0].overall_score, 0.0)

        trend = {
            "student_a": "bob",
            "student_b": "alice",
            "assignments": ["PS0", "PS1"],
            "count": 2,
            "max_similarity": 0.97,
            "questions": {"PS0": ["Q2"], "PS1": ["Q1"]},
            "signals": ["embedding_cosine"],
        }
        advanced = generate_advanced_similarity_report(
            base,
            submissions,
            ["Q1"],
            include_pseudocode=False,
            include_clustering=False,
            trend_records=[trend],
        )

        pair = advanced.pairs[0]
        self.assertEqual(pair.flag_level, "high")
        self.assertEqual(pair.overall_score, 0.0)
        self.assertIn(CROSS_ASSIGNMENT_TREND_FLAG, pair.trend_flags)
        self.assertIn("cross_assignment_trend", pair.signals)
        self.assertIn(TRENDS_REVIEW_WARNING, pair.notes)
        self.assertIn(TRENDS_REVIEW_WARNING, advanced.warnings)
        self.assertEqual(advanced.trends[0]["student_a"], "alice")
        self.assertEqual(advanced.trends[0]["student_b"], "bob")
        self.assertIn("cross_assignment_trends", advanced.advanced_methods)

    def test_historical_trend_not_containing_current_assignment_does_not_modify_pair(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "unique alice"}),
            "bob": assessment("bob", {"Q1": "unique bob"}),
        }
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            include_pseudocode=False,
            include_clustering=False,
            trend_records=[
                {
                    "student_a": "alice",
                    "student_b": "bob",
                    "assignments": ["PS0", "PSX"],
                    "count": 2,
                    "max_similarity": 0.98,
                }
            ],
        )
        self.assertEqual(advanced.pairs[0].trend_flags, [])
        self.assertNotIn("cross_assignment_trend", advanced.pairs[0].signals)


class TestAdvancedProvenance(unittest.TestCase):
    def test_preserves_typed_pdf_vs_assistive_transcription_provenance(self):
        typed = assessment(
            "alice",
            {"Q1": "typed pdf answer"},
            source_used="pdf",
            submission_mode="pdf_accommodation",
            accommodation_mode=True,
            authoritative_source="original_pdf",
            assistive_text_source="pdf_selectable_text",
        )
        handwritten = assessment(
            "bob",
            {"Q1": "transcribed handwritten answer"},
            source_used="pdf",
            submission_mode="pdf_accommodation",
            accommodation_mode=True,
            authoritative_source="original_pdf",
            assistive_text_source="machine_transcription",
            transcription={"provider": "ollama", "model": "vision-model", "page_count": 2},
        )
        submissions = {"alice": typed, "bob": handwritten}
        provider = MockEmbeddingProvider(
            vectors={
                "typed pdf answer": [1.0, 0.0],
                "transcribed handwritten answer": [1.0, 0.0],
            }
        )
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            embedding_provider=provider,
            include_pseudocode=False,
            include_clustering=False,
            embedding_cache_enabled=False,
        )

        alice = advanced.submission_provenance["alice"]
        bob = advanced.submission_provenance["bob"]
        self.assertEqual(alice["authoritative_source"], "original_pdf")
        self.assertEqual(alice["analysis_text_source"], "pdf_selectable_text")
        self.assertFalse(alice["uses_assistive_transcription"])
        self.assertEqual(bob["authoritative_source"], "original_pdf")
        self.assertEqual(bob["analysis_text_source"], "machine_transcription")
        self.assertTrue(bob["uses_assistive_transcription"])
        self.assertEqual(bob["transcription"]["provider"], "ollama")

        pair = advanced.pairs[0]
        self.assertEqual(pair.submission_provenance["bob"]["analysis_text_source"], "machine_transcription")
        self.assertIn(
            f"{ASSISTIVE_TRANSCRIPTION_REVIEW_WARNING}:bob",
            pair.notes,
        )

    def test_provenance_helper_handles_latex_assessment(self):
        provenance = submission_similarity_provenance(
            assessment("alice", {"Q1": "answer"})
        )
        self.assertEqual(provenance["source_used"], "latex")
        self.assertEqual(provenance["authoritative_source"], "latex")
        self.assertEqual(provenance["analysis_text_source"], "latex")
        self.assertFalse(provenance["uses_assistive_transcription"])

    def test_missing_submission_for_base_report_student_is_warned(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "a"}),
            "bob": assessment("bob", {"Q1": "b"}),
        }
        base = base_report(submissions)
        advanced = generate_advanced_similarity_report(
            base,
            {"alice": submissions["alice"]},
            ["Q1"],
            include_pseudocode=False,
            include_clustering=False,
        )
        self.assertIn("advanced_submission_missing:bob", advanced.warnings)


class TestAdvancedSchemaAndTrendRoundTrip(unittest.TestCase):
    def test_advanced_report_round_trip_preserves_new_fields(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "first answer"}),
            "bob": assessment("bob", {"Q1": "second answer"}),
        }
        provider = MockEmbeddingProvider(
            vectors={
                "first answer": [1.0, 0.0],
                "second answer": [1.0, 0.0],
            }
        )
        advanced = generate_advanced_similarity_report(
            base_report(submissions),
            submissions,
            ["Q1"],
            embedding_provider=provider,
            include_pseudocode=False,
            include_clustering=True,
            embedding_cache_enabled=False,
        )

        restored = similarity_report_from_dict(advanced.to_dict())
        self.assertEqual(restored.advanced_methods, advanced.advanced_methods)
        self.assertEqual(restored.clusters, advanced.clusters)
        self.assertEqual(restored.embedding_config, advanced.embedding_config)
        self.assertEqual(restored.submission_provenance, advanced.submission_provenance)
        self.assertEqual(
            restored.pairs[0].submission_provenance,
            advanced.pairs[0].submission_provenance,
        )

    def test_trends_from_advanced_reports_attribute_embedding_not_ngram(self):
        submissions = {
            "alice": assessment("alice", {"Q1": "first unique answer"}),
            "bob": assessment("bob", {"Q1": "second unique answer"}),
        }
        provider = MockEmbeddingProvider(
            vectors={
                "first unique answer": [1.0, 0.0],
                "second unique answer": [1.0, 0.0],
            }
        )
        reports = []
        for assignment_id in ["PS1", "PS2"]:
            reports.append(
                generate_advanced_similarity_report(
                    base_report(submissions, assignment_id=assignment_id),
                    submissions,
                    ["Q1"],
                    embedding_provider=provider,
                    include_pseudocode=False,
                    include_clustering=False,
                    embedding_cache_enabled=False,
                )
            )

        trends = analyze_similarity_trends(reports)
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0]["signals"], ["embedding_cosine"])
        self.assertEqual(trends[0]["questions"], {"PS1": ["Q1"], "PS2": ["Q1"]})


if __name__ == "__main__":
    unittest.main()
