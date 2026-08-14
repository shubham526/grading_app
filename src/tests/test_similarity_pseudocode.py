import unittest

from src.similarity.models import PairSimilarity, QuestionSimilarity
from src.similarity.pseudocode import (
    DEFAULT_PSEUDOCODE_THRESHOLDS,
    compute_question_pseudocode_similarity,
    extract_pseudocode_blocks,
    normalize_pseudocode,
    pseudocode_flag_for_score,
    pseudocode_similarity,
    resolve_pseudocode_thresholds,
)


class TestPseudocodeExtraction(unittest.TestCase):
    def test_extracts_algorithmic_environment(self):
        text = r"""
Before.
\begin{algorithmic}
\For{$i = 1$ to $n$}
  \State total = total + A[i]
\EndFor
\end{algorithmic}
After.
"""
        self.assertEqual(
            extract_pseudocode_blocks(text),
            [
                r"""\For{$i = 1$ to $n$}
  \State total = total + A[i]
\EndFor"""
            ],
        )

    def test_prefers_nested_algorithmic_over_outer_algorithm(self):
        text = r"""
\begin{algorithm}
\caption{Find maximum}
\begin{algorithmic}
\For{$i = 1$ to $n$}
\State best = A[i]
\EndFor
\end{algorithmic}
\end{algorithm}
"""
        blocks = extract_pseudocode_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertIn(r"\For", blocks[0])
        self.assertNotIn(r"\caption", blocks[0])

    def test_extracts_verbatim_environment(self):
        text = r"""
\begin{verbatim}
while x < n
  x = x + 1
\end{verbatim}
"""
        self.assertEqual(
            extract_pseudocode_blocks(text),
            ["while x < n\n  x = x + 1"],
        )

    def test_extracts_algorithm_heading_until_blank_paragraph(self):
        text = """Reasoning before.

Algorithm:
for i = 1 to n
  if A[i] > best
    best = A[i]

This prose should not be part of the block.
"""
        blocks = extract_pseudocode_blocks(text)
        self.assertEqual(
            blocks,
            ["for i = 1 to n\n  if A[i] > best\n    best = A[i]"],
        )

    def test_extracts_pseudocode_heading_with_same_line_content(self):
        text = """Pseudocode: return x
"""
        self.assertEqual(extract_pseudocode_blocks(text), ["return x"])

    def test_returns_empty_when_no_explicit_pseudocode_region_exists(self):
        self.assertEqual(
            extract_pseudocode_blocks(
                "We prove the runtime by considering each edge exactly once."
            ),
            [],
        )


class TestPseudocodeNormalization(unittest.TestCase):
    def test_normalizes_variable_names_and_numbers(self):
        first = normalize_pseudocode(
            """
for i = 1 to n
if A[i] > max
max = A[i]
"""
        )
        second = normalize_pseudocode(
            """
for j = 1 to n
if B[j] > best
best = B[j]
"""
        )
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            [
                "for", "VAR", "=", "NUM", "to", "VAR",
                "if", "VAR", "[", "VAR", "]", ">", "VAR",
                "VAR", "=", "VAR", "[", "VAR", "]",
            ],
        )

    def test_removes_common_comment_forms(self):
        tokens = normalize_pseudocode(
            r"""
x = 1  // Java-style comment
y = 2  # shell/Python-style comment
z = 3  % LaTeX-style comment
\Comment{algorithmic comment}
return z
"""
        )
        self.assertNotIn("comment", tokens)
        self.assertEqual(
            tokens,
            [
                "VAR", "=", "NUM",
                "VAR", "=", "NUM",
                "VAR", "=", "NUM",
                "return", "VAR",
            ],
        )

    def test_preserves_control_flow_keywords_and_operators(self):
        tokens = normalize_pseudocode(
            "while x <= n do if x != 0 then return x else break"
        )
        for keyword in ["while", "do", "if", "then", "return", "else", "break"]:
            self.assertIn(keyword, tokens)
        self.assertIn("<=", tokens)
        self.assertIn("!=", tokens)

    def test_normalizes_algorithmic_commands(self):
        tokens = normalize_pseudocode(
            r"""
\For{i = 1 to n}
\If{A[i] > best}
\State best = A[i]
\EndIf
\EndFor
"""
        )
        self.assertIn("for", tokens)
        self.assertIn("if", tokens)
        self.assertIn("end", tokens)
        self.assertNotIn("State", tokens)
        self.assertNotIn("For", tokens)


class TestPseudocodeSimilarity(unittest.TestCase):
    def test_renamed_variables_score_exact_structural_match(self):
        left = """
for i = 1 to n
if A[i] > max
max = A[i]
"""
        right = """
for j = 1 to m
if B[j] > best
best = B[j]
"""
        self.assertAlmostEqual(pseudocode_similarity(left, right), 1.0)

    def test_unrelated_structures_score_low(self):
        left = """
for i = 1 to n
if A[i] > best
best = A[i]
"""
        right = """
while queue != empty
x = pop(queue)
return x
"""
        self.assertLess(pseudocode_similarity(left, right), 0.30)

    def test_empty_code_scores_zero(self):
        self.assertEqual(pseudocode_similarity("", "for i = 1 to n"), 0.0)

    def test_question_level_comparison_uses_same_question_ids(self):
        answers_a = {
            "Q1": """Algorithm:
for i = 1 to n
  total = total + A[i]
""",
            "Q2": "ordinary prose only",
        }
        answers_b = {
            "Q1": """Pseudocode:
for j = 1 to m
  sum = sum + B[j]
""",
            "Q2": """Algorithm:
return x
""",
        }

        result = compute_question_pseudocode_similarity(
            answers_a,
            answers_b,
            ["Q1", "Q2"],
        )
        self.assertEqual(list(result), ["Q1"])
        self.assertAlmostEqual(result["Q1"], 1.0)

    def test_multiple_blocks_use_best_block_pair(self):
        answers_a = {
            "Q1": r"""
\begin{verbatim}
while x < n
  x = x + 1
\end{verbatim}

\begin{algorithmic}
\For{$i = 1$ to $n$}
\State total = total + A[i]
\EndFor
\end{algorithmic}
"""
        }
        answers_b = {
            "Q1": r"""
\begin{algorithmic}
\For{$j = 1$ to $m$}
\State sum = sum + B[j]
\EndFor
\end{algorithmic}
"""
        }
        result = compute_question_pseudocode_similarity(
            answers_a,
            answers_b,
            ["Q1"],
        )
        self.assertAlmostEqual(result["Q1"], 1.0)


class TestPseudocodeThresholds(unittest.TestCase):
    def test_thresholds_follow_design_defaults(self):
        self.assertEqual(
            DEFAULT_PSEUDOCODE_THRESHOLDS,
            {
                "pseudocode_medium": 0.65,
                "pseudocode_high": 0.80,
                "pseudocode_exact": 0.95,
            },
        )
        self.assertEqual(pseudocode_flag_for_score(0.64), "none")
        self.assertEqual(pseudocode_flag_for_score(0.65), "medium")
        self.assertEqual(pseudocode_flag_for_score(0.80), "high")
        self.assertEqual(pseudocode_flag_for_score(0.95), "exact")

    def test_threshold_order_and_keys_are_validated(self):
        with self.assertRaises(ValueError):
            resolve_pseudocode_thresholds(
                {
                    "pseudocode_medium": 0.90,
                    "pseudocode_high": 0.80,
                }
            )
        with self.assertRaises(ValueError):
            resolve_pseudocode_thresholds({"unknown": 0.5})


class TestPseudocodeModelExtensions(unittest.TestCase):
    def test_question_and_pair_models_serialize_optional_pseudocode_fields(self):
        question = QuestionSimilarity(
            question_id="Q1",
            pseudocode_similarity=0.87,
        )
        pair = PairSimilarity(
            student_a="alice",
            student_b="bob",
            question_similarities={"Q1": question},
            pseudocode_max_similarity=0.87,
        )

        question_payload = question.to_dict()
        pair_payload = pair.to_dict()

        self.assertEqual(question_payload["pseudocode_similarity"], 0.87)
        self.assertEqual(pair_payload["pseudocode_max_similarity"], 0.87)
        self.assertEqual(
            pair_payload["question_similarities"]["Q1"]["pseudocode_similarity"],
            0.87,
        )

    def test_pseudocode_model_scores_must_be_in_range(self):
        with self.assertRaises(ValueError):
            QuestionSimilarity(
                question_id="Q1",
                pseudocode_similarity=1.01,
            )
        with self.assertRaises(ValueError):
            PairSimilarity(
                student_a="alice",
                student_b="bob",
                pseudocode_max_similarity=-0.01,
            )


if __name__ == "__main__":
    unittest.main()
