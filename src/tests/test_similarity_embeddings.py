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


if __name__ == "__main__":
    unittest.main()
