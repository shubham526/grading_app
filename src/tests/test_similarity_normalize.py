import unittest

from src.similarity.normalize import normalize_for_similarity


class TestSimilarityNormalization(unittest.TestCase):
    def test_lowercases_text(self):
        self.assertEqual(normalize_for_similarity("Proof BY Induction"), "proof by induction")

    def test_unicode_is_nfkc_normalized(self):
        self.assertEqual(normalize_for_similarity("Ａ１"), "a1")

    def test_repeated_whitespace_is_collapsed(self):
        self.assertEqual(normalize_for_similarity("one \n\t two       three"), "one two three")

    def test_latex_comments_are_removed(self):
        text = "answer one % template comment\nanswer two"
        self.assertEqual(normalize_for_similarity(text), "answer one answer two")

    def test_escaped_percent_is_preserved(self):
        self.assertEqual(normalize_for_similarity(r"success is 90\%"), "success is 90%")

    def test_latex_preamble_and_document_commands_are_removed(self):
        text = r"""
        \documentclass{article}
        \usepackage{amsmath}
        \title{Problem Set 1}
        \author{Alice Example}
        \date{2026-09-01}
        \begin{document}
        \maketitle
        Actual solution text.
        \end{document}
        """
        self.assertEqual(normalize_for_similarity(text), "actual solution text")

    def test_template_placeholders_are_removed(self):
        text = """
        Name: Alice Example
        Student ID: 123456
        Date: 2026-09-01
        Write your solution here.
        Maintain the largest value seen so far.
        """
        self.assertEqual(
            normalize_for_similarity(text),
            "maintain the largest value seen so far",
        )

    def test_template_word_inside_real_prose_is_not_removed(self):
        text = "The variable name remains unchanged in the invariant."
        self.assertEqual(
            normalize_for_similarity(text),
            "the variable name remains unchanged in the invariant",
        )

    def test_simple_theta_normalization(self):
        self.assertEqual(normalize_for_similarity(r"\Theta(n \log n)"), "theta n log n")

    def test_big_o_power_normalization(self):
        self.assertEqual(normalize_for_similarity(r"O(n^2)"), "o n 2")

    def test_comparison_operator_normalization(self):
        self.assertEqual(
            normalize_for_similarity(r"x \leq y and z \geq y"),
            "x <= y and z >= y",
        )

    def test_formatting_wrapper_preserves_content(self):
        self.assertEqual(
            normalize_for_similarity(r"\textbf{Important} \mathrm{OPT}"),
            "important opt",
        )

    def test_remaining_math_command_name_is_preserved(self):
        self.assertEqual(normalize_for_similarity(r"\sum_{i=1}^{n} i"), "sum i=1 n i")

    def test_empty_and_none_normalize_to_empty(self):
        self.assertEqual(normalize_for_similarity(""), "")
        self.assertEqual(normalize_for_similarity(None), "")


if __name__ == "__main__":
    unittest.main()
