import json
import math
import tempfile
import unittest
from pathlib import Path

from src.similarity.embedding_provider import EmbeddingProvider
from src.similarity.embeddings import (
    cosine_similarity,
    embedding_cache_key,
    get_embeddings,
    load_cached_embedding,
    save_cached_embedding,
)
from src.similarity.mock_embedding_provider import MockEmbeddingProvider


class CountingMockEmbeddingProvider(MockEmbeddingProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return super().embed_texts(texts)


class BadCountProvider(EmbeddingProvider):
    def provider_name(self):
        return "bad-count"

    def model_name(self):
        return "bad-count-model"

    def embed_texts(self, texts):
        return []


class TestMockEmbeddingProvider(unittest.TestCase):
    def test_provider_identity_is_stable(self):
        provider = MockEmbeddingProvider()
        self.assertEqual(provider.provider_name(), "mock")
        self.assertEqual(provider.model_name(), "mock-embedding")

    def test_hash_embeddings_are_deterministic_across_instances(self):
        first = MockEmbeddingProvider(dimension=16)
        second = MockEmbeddingProvider(dimension=16)
        self.assertEqual(
            first.embed_texts(["same answer"]),
            second.embed_texts(["same answer"]),
        )

    def test_hash_embedding_has_requested_dimension_and_unit_norm(self):
        provider = MockEmbeddingProvider(dimension=24)
        vector = provider.embed_texts(["answer"])[0]
        self.assertEqual(len(vector), 24)
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in vector)),
            1.0,
            places=12,
        )

    def test_custom_vectors_override_hash_embedding(self):
        provider = MockEmbeddingProvider(
            vectors={"alice": [1.0, 0.0], "bob": [0.5, 0.5]}
        )
        self.assertEqual(provider.embed_texts(["alice"]), [[1.0, 0.0]])
        self.assertEqual(provider.embed_texts(["bob"]), [[0.5, 0.5]])

    def test_mock_rejects_non_string_inputs(self):
        provider = MockEmbeddingProvider()
        with self.assertRaises(TypeError):
            provider.embed_texts([123])

    def test_mock_requires_positive_dimension(self):
        with self.assertRaises(ValueError):
            MockEmbeddingProvider(dimension=0)


class TestCosineSimilarity(unittest.TestCase):
    def test_identical_vectors_score_one(self):
        self.assertAlmostEqual(cosine_similarity([1, 2, 3], [1, 2, 3]), 1.0)

    def test_orthogonal_vectors_score_zero(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_negative_cosine_is_clamped_to_zero(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [-1, 0]), 0.0)

    def test_empty_and_zero_norm_vectors_score_zero(self):
        self.assertEqual(cosine_similarity([], []), 0.0)
        self.assertEqual(cosine_similarity([0, 0], [1, 1]), 0.0)

    def test_dimension_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1, 2], [1, 2, 3])

    def test_non_finite_vectors_are_rejected(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1.0, float("nan")], [1.0, 2.0])


class TestEmbeddingCache(unittest.TestCase):
    def test_cache_key_is_deterministic(self):
        key = embedding_cache_key("answer", "mock", "mock-embedding")
        self.assertEqual(
            key,
            embedding_cache_key("answer", "mock", "mock-embedding"),
        )
        self.assertEqual(len(key), 64)

    def test_cache_key_changes_with_text_provider_or_model(self):
        base = embedding_cache_key("answer", "mock", "m1")
        self.assertNotEqual(base, embedding_cache_key("different", "mock", "m1"))
        self.assertNotEqual(base, embedding_cache_key("answer", "other", "m1"))
        self.assertNotEqual(base, embedding_cache_key("answer", "mock", "m2"))

    def test_cache_round_trip_preserves_metadata_and_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_cached_embedding(
                "alice answer",
                "mock",
                "mock-embedding",
                [0.1, 0.2, 0.3],
                cache_dir=tmp,
            )
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["provider"], "mock")
            self.assertEqual(payload["model"], "mock-embedding")
            self.assertEqual(payload["embedding"], [0.1, 0.2, 0.3])
            self.assertEqual(
                load_cached_embedding(
                    "alice answer",
                    "mock",
                    "mock-embedding",
                    cache_dir=tmp,
                ),
                [0.1, 0.2, 0.3],
            )

    def test_corrupt_cache_is_treated_as_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / (
                embedding_cache_key("answer", "mock", "mock-embedding") + ".json"
            )
            path.write_text("{not-json", encoding="utf-8")
            self.assertIsNone(
                load_cached_embedding(
                    "answer",
                    "mock",
                    "mock-embedding",
                    cache_dir=tmp,
                )
            )

    def test_get_embeddings_batches_only_unique_cache_misses(self):
        provider = CountingMockEmbeddingProvider(
            {
                "alice": [1.0, 0.0],
                "bob": [0.0, 1.0],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = get_embeddings(
                ["alice", "bob", "alice"],
                provider,
                cache_enabled=True,
                cache_dir=tmp,
            )

            self.assertEqual(result, [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
            self.assertEqual(provider.calls, [["alice", "bob"]])

            second = get_embeddings(
                ["bob", "alice"],
                provider,
                cache_enabled=True,
                cache_dir=tmp,
            )
            self.assertEqual(second, [[0.0, 1.0], [1.0, 0.0]])
            self.assertEqual(
                provider.calls,
                [["alice", "bob"]],
                "second call should be fully served from cache",
            )

    def test_cache_disabled_still_deduplicates_within_one_batch(self):
        provider = CountingMockEmbeddingProvider(
            {
                "alice": [1.0, 0.0],
                "bob": [0.0, 1.0],
            }
        )
        result = get_embeddings(
            ["alice", "alice", "bob"],
            provider,
            cache_enabled=False,
        )
        self.assertEqual(result[0], result[1])
        self.assertEqual(provider.calls, [["alice", "bob"]])

    def test_provider_vector_count_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            get_embeddings(
                ["alice"],
                BadCountProvider(),
                cache_enabled=False,
            )

    def test_empty_input_does_not_call_provider(self):
        provider = CountingMockEmbeddingProvider()
        self.assertEqual(get_embeddings([], provider), [])
        self.assertEqual(provider.calls, [])


class FakeSentenceTransformerModel:
    def __init__(self, vectors=None):
        self.vectors = vectors or {}
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), dict(kwargs)))
        return [self.vectors.get(text, [1.0, 0.0, 0.0]) for text in texts]


class TestSentenceTransformerEmbeddingProvider(unittest.TestCase):
    def test_default_model_and_provider_identity(self):
        from src.similarity.sentence_transformer_provider import (
            DEFAULT_SENTENCE_TRANSFORMER_MODEL,
            SentenceTransformerEmbeddingProvider,
        )

        provider = SentenceTransformerEmbeddingProvider(
            model=FakeSentenceTransformerModel()
        )
        self.assertEqual(provider.provider_name(), "sentence_transformers")
        self.assertEqual(provider.model_name(), DEFAULT_SENTENCE_TRANSFORMER_MODEL)
        self.assertEqual(
            DEFAULT_SENTENCE_TRANSFORMER_MODEL,
            "Alibaba-NLP/gte-modernbert-base",
        )

    def test_provider_uses_normalized_batched_local_encode(self):
        from src.similarity.sentence_transformer_provider import (
            SentenceTransformerEmbeddingProvider,
        )

        model = FakeSentenceTransformerModel(
            vectors={
                "alice": [1.0, 0.0],
                "bob": [0.0, 1.0],
            }
        )
        provider = SentenceTransformerEmbeddingProvider(
            model=model,
            batch_size=7,
            show_progress_bar=False,
        )
        self.assertEqual(
            provider.embed_texts(["alice", "bob"]),
            [[1.0, 0.0], [0.0, 1.0]],
        )
        texts, kwargs = model.calls[0]
        self.assertEqual(texts, ["alice", "bob"])
        self.assertEqual(kwargs["batch_size"], 7)
        self.assertFalse(kwargs["show_progress_bar"])
        self.assertTrue(kwargs["convert_to_numpy"])
        self.assertTrue(kwargs["normalize_embeddings"])

    def test_model_factory_receives_safe_sentence_transformer_options(self):
        from src.similarity.sentence_transformer_provider import (
            SentenceTransformerEmbeddingProvider,
        )

        captured = {}

        def factory(model_name, **kwargs):
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs
            return FakeSentenceTransformerModel()

        provider = SentenceTransformerEmbeddingProvider(
            model_name="custom/model",
            device="cpu",
            model_cache_dir="~/models",
            local_files_only=True,
            revision="abc123",
            model_factory=factory,
        )
        provider.embed_texts(["answer"])

        self.assertEqual(captured["model_name"], "custom/model")
        self.assertEqual(captured["kwargs"]["device"], "cpu")
        self.assertTrue(captured["kwargs"]["local_files_only"])
        self.assertFalse(captured["kwargs"]["trust_remote_code"])
        self.assertEqual(captured["kwargs"]["revision"], "abc123")
        self.assertTrue(captured["kwargs"]["cache_folder"].endswith("models"))

    def test_provider_is_lazy_until_first_embedding_request(self):
        from src.similarity.sentence_transformer_provider import (
            SentenceTransformerEmbeddingProvider,
        )

        calls = []

        def factory(model_name, **kwargs):
            calls.append(model_name)
            return FakeSentenceTransformerModel()

        provider = SentenceTransformerEmbeddingProvider(model_factory=factory)
        self.assertEqual(calls, [])
        provider.embed_texts(["one"])
        self.assertEqual(calls, [provider.model_name()])
        provider.embed_texts(["two"])
        self.assertEqual(
            calls,
            [provider.model_name()],
            "the loaded model should be reused",
        )

    def test_provider_rejects_invalid_model_output(self):
        from src.similarity.sentence_transformer_provider import (
            SentenceTransformerEmbeddingProvider,
        )

        class BadModel:
            def encode(self, texts, **kwargs):
                return [[1.0, 0.0], [1.0]]

        provider = SentenceTransformerEmbeddingProvider(model=BadModel())
        with self.assertRaises(ValueError):
            provider.embed_texts(["a", "b"])

    def test_optional_dependency_failure_is_clear(self):
        from unittest.mock import patch

        from src.similarity.sentence_transformer_provider import (
            SentenceTransformerEmbeddingProvider,
            SentenceTransformerUnavailableError,
        )

        provider = SentenceTransformerEmbeddingProvider()
        with patch(
            "src.similarity.sentence_transformer_provider.importlib.import_module",
            side_effect=ModuleNotFoundError("sentence_transformers"),
        ):
            with self.assertRaisesRegex(
                SentenceTransformerUnavailableError,
                "sentence-transformers",
            ):
                provider.embed_texts(["answer"])


class TestQuestionEmbeddingSimilarity(unittest.TestCase):
    def test_thresholds_follow_design_defaults(self):
        from src.similarity.embeddings import (
            DEFAULT_EMBEDDING_THRESHOLDS,
            embedding_flag_for_score,
        )

        self.assertEqual(
            DEFAULT_EMBEDDING_THRESHOLDS,
            {
                "embedding_medium": 0.88,
                "embedding_high": 0.93,
                "embedding_exact": 0.98,
            },
        )
        self.assertEqual(embedding_flag_for_score(0.87), "none")
        self.assertEqual(embedding_flag_for_score(0.88), "medium")
        self.assertEqual(embedding_flag_for_score(0.93), "high")
        self.assertEqual(embedding_flag_for_score(0.98), "exact")

    def test_threshold_order_is_validated(self):
        from src.similarity.embeddings import resolve_embedding_thresholds

        with self.assertRaises(ValueError):
            resolve_embedding_thresholds(
                {
                    "embedding_medium": 0.95,
                    "embedding_high": 0.90,
                }
            )
        with self.assertRaises(ValueError):
            resolve_embedding_thresholds({"unknown": 0.9})

    def test_same_questions_only_and_all_student_pairs(self):
        from src.similarity.embeddings import compute_question_embedding_similarity

        answers = {
            "alice": {"Q1": "a1", "Q2": "a2"},
            "bob": {"Q1": "b1", "Q2": "b2"},
            "carol": {"Q1": "c1", "Q2": "c2"},
        }
        provider = MockEmbeddingProvider(
            vectors={
                "a1": [1.0, 0.0],
                "b1": [1.0, 0.0],
                "c1": [0.0, 1.0],
                "a2": [0.0, 1.0],
                "b2": [0.0, 1.0],
                "c2": [1.0, 0.0],
            }
        )
        result = compute_question_embedding_similarity(
            answers,
            ["Q1", "Q2"],
            provider,
            cache_enabled=False,
        )

        self.assertEqual(
            list(result),
            [("alice", "bob"), ("alice", "carol"), ("bob", "carol")],
        )
        self.assertAlmostEqual(result[("alice", "bob")]["Q1"], 1.0)
        self.assertAlmostEqual(result[("alice", "bob")]["Q2"], 1.0)
        self.assertAlmostEqual(result[("alice", "carol")]["Q1"], 0.0)
        self.assertAlmostEqual(result[("alice", "carol")]["Q2"], 0.0)

    def test_missing_or_blank_question_is_omitted(self):
        from src.similarity.embeddings import compute_question_embedding_similarity

        answers = {
            "alice": {"Q1": "answer", "Q2": "   "},
            "bob": {"Q1": "same", "Q2": "something"},
        }
        provider = MockEmbeddingProvider(
            vectors={"answer": [1.0, 0.0], "same": [1.0, 0.0]}
        )
        result = compute_question_embedding_similarity(
            answers,
            ["Q1", "Q2"],
            provider,
            cache_enabled=False,
        )
        self.assertEqual(set(result[("alice", "bob")]), {"Q1"})

    def test_question_embeddings_are_batched_once_before_pairwise_scoring(self):
        from src.similarity.embeddings import compute_question_embedding_similarity

        provider = CountingMockEmbeddingProvider()
        answers = {
            "alice": {"Q1": "alice q1", "Q2": "alice q2"},
            "bob": {"Q1": "bob q1", "Q2": "bob q2"},
            "carol": {"Q1": "carol q1", "Q2": "carol q2"},
        }
        compute_question_embedding_similarity(
            answers,
            ["Q1", "Q2"],
            provider,
            cache_enabled=False,
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(provider.calls[0]), 6)

    def test_high_semantic_low_text_warning(self):
        from src.similarity.embeddings import embedding_review_warnings

        long_a = " ".join(f"alpha{i}" for i in range(35))
        long_b = " ".join(f"beta{i}" for i in range(35))
        warnings = embedding_review_warnings(
            long_a,
            long_b,
            0.95,
            ngram_score=0.10,
        )
        self.assertIn("high_semantic_similarity_low_textual_overlap", warnings)
        self.assertNotIn("short_answer_embedding_unreliable", warnings)

    def test_high_semantic_short_answer_warning(self):
        from src.similarity.embeddings import embedding_review_warnings

        warnings = embedding_review_warnings(
            "short answer",
            "another short answer",
            0.95,
            ngram_score=0.80,
        )
        self.assertEqual(warnings, ["short_answer_embedding_unreliable"])

    def test_medium_embedding_does_not_emit_high_similarity_warnings(self):
        from src.similarity.embeddings import embedding_review_warnings

        self.assertEqual(
            embedding_review_warnings(
                "short",
                "short",
                0.90,
                ngram_score=0.10,
            ),
            [],
        )


class TestEmbeddingModelExtensions(unittest.TestCase):
    def test_question_and_pair_models_serialize_optional_embedding_fields(self):
        from src.similarity.models import PairSimilarity, QuestionSimilarity

        question = QuestionSimilarity(
            question_id="Q2",
            embedding_cosine=0.94,
            advanced_flags=["semantic_high"],
        )
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            question_similarities={"Q2": question},
            embedding_max_similarity=0.94,
        )
        payload = pair.to_dict()
        self.assertEqual(payload["embedding_max_similarity"], 0.94)
        self.assertEqual(
            payload["question_similarities"]["Q2"]["embedding_cosine"],
            0.94,
        )
        self.assertEqual(
            payload["question_similarities"]["Q2"]["advanced_flags"],
            ["semantic_high"],
        )


if __name__ == "__main__":
    unittest.main()
