import unittest

from src.similarity.shingles import jaccard_similarity, make_word_shingles, tokenize_for_similarity


class TestSimilarityTokenization(unittest.TestCase):
    def test_tokenization_normalizes_first(self):
        self.assertEqual(
            tokenize_for_similarity(r"The runtime is \Theta(n \log n)."),
            ["the", "runtime", "is", "theta", "n", "log", "n"],
        )

    def test_tokenization_keeps_simple_math_operators(self):
        self.assertEqual(tokenize_for_similarity(r"x \leq y + 1"), ["x", "<=", "y", "+", "1"])

    def test_empty_input_has_no_tokens(self):
        self.assertEqual(tokenize_for_similarity(""), [])


class TestWordShingles(unittest.TestCase):
    def test_default_generates_five_grams_for_long_answer(self):
        tokens = [f"t{i}" for i in range(12)]
        shingles = make_word_shingles(tokens)
        self.assertEqual(len(shingles), 8)
        self.assertIn(tuple(tokens[:5]), shingles)
        self.assertIn(tuple(tokens[-5:]), shingles)

    def test_short_answer_uses_trigrams(self):
        tokens = ["prove", "by", "induction", "on", "n", "now"]
        shingles = make_word_shingles(tokens, n=5)
        self.assertEqual(
            shingles,
            {
                ("prove", "by", "induction"),
                ("by", "induction", "on"),
                ("induction", "on", "n"),
                ("on", "n", "now"),
            },
        )

    def test_two_token_answer_uses_largest_possible_shingle(self):
        self.assertEqual(make_word_shingles(["base", "case"]), {("base", "case")})

    def test_empty_tokens_produce_empty_shingle_set(self):
        self.assertEqual(make_word_shingles([]), set())

    def test_nonpositive_n_is_rejected(self):
        with self.assertRaises(ValueError):
            make_word_shingles(["a", "b", "c"], n=0)


class TestJaccardSimilarity(unittest.TestCase):
    def test_identical_sets_are_one(self):
        a = {("a",), ("b",)}
        self.assertEqual(jaccard_similarity(a, set(a)), 1.0)

    def test_disjoint_sets_are_zero(self):
        self.assertEqual(jaccard_similarity({1, 2}, {3, 4}), 0.0)

    def test_known_jaccard_value(self):
        self.assertAlmostEqual(jaccard_similarity({1, 2, 3}, {2, 3, 4}), 0.5)

    def test_both_empty_is_zero(self):
        self.assertEqual(jaccard_similarity(set(), set()), 0.0)

    def test_one_empty_is_zero(self):
        self.assertEqual(jaccard_similarity({"x"}, set()), 0.0)


if __name__ == "__main__":
    unittest.main()
