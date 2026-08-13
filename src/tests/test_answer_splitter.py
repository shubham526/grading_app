"""Tests for conservative question-level answer splitting."""

import os
import sys
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.splitter import (
    FULL_SUBMISSION,
    normalize_heading_question_id,
    split_answers_by_question,
)


class TestQuestionHeadingNormalization(unittest.TestCase):

    def test_matches_v21_canonical_examples(self):
        cases = {
            "Question 1": "Q1",
            "Problem 2": "Q2",
            "q3a": "Q3A",
            "Q4(b)": "Q4B",
            "P5(a)": "Q5A",
            "Q10": "Q10",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_heading_question_id(raw), expected)


class TestAnswerSplitting(unittest.TestCase):

    def test_plain_question_headings(self):
        text = "Question 1\nFirst answer\n\nQuestion 2\nSecond answer"
        answers, warnings = split_answers_by_question(text, ["Q1", "Q2"])
        self.assertEqual(answers, {"Q1": "First answer", "Q2": "Second answer"})
        self.assertEqual(warnings, [])

    def test_problem_and_subpart_headings(self):
        text = "Problem 1(a)\nA\nQ1(b)\nB\nP2\nC"
        answers, warnings = split_answers_by_question(text, ["Q1A", "Q1B", "Q2"])
        self.assertEqual(answers["Q1A"], "A")
        self.assertEqual(answers["Q1B"], "B")
        self.assertEqual(answers["Q2"], "C")
        self.assertEqual(warnings, [])

    def test_latex_section_headings(self):
        text = r"""\section*{Question 1}
$T(n)=n$
\subsection{Q2}
Proof text
"""
        answers, warnings = split_answers_by_question(text, ["Q1", "Q2"])
        self.assertEqual(answers["Q1"], "$T(n)=n$")
        self.assertEqual(answers["Q2"], "Proof text")
        self.assertEqual(warnings, [])

    def test_inline_question_reference_is_not_a_heading(self):
        text = "Question 1 is used in this explanation.\nMore prose."
        answers, warnings = split_answers_by_question(text, ["Q1"])
        self.assertEqual(answers, {FULL_SUBMISSION: text})
        self.assertIn("could_not_split_by_question", warnings)
        self.assertIn("missing_answer_for_Q1", warnings)

    def test_no_heading_returns_full_submission_once(self):
        text = "A proof with no explicit heading."
        answers, warnings = split_answers_by_question(text, ["Q1", "Q2"])
        self.assertEqual(answers, {FULL_SUBMISSION: text})
        self.assertNotIn("Q1", answers)
        self.assertNotIn("Q2", answers)
        self.assertIn("could_not_split_by_question", warnings)

    def test_requested_missing_question_is_not_invented(self):
        answers, warnings = split_answers_by_question("Q1\nAnswer", ["Q1", "Q2"])
        self.assertEqual(answers, {"Q1": "Answer"})
        self.assertIn("missing_answer_for_Q2", warnings)

    def test_duplicate_heading_preserves_both_sections(self):
        answers, warnings = split_answers_by_question("Q1\nA\nQ1\nB", ["Q1"])
        self.assertEqual(answers["Q1"], "A\n\nB")
        self.assertIn("duplicate_heading_for_Q1", warnings)

    def test_bare_numbered_headings_match_requested_questions(self):
        text = "1.\nFirst answer\n\n2)\nSecond answer"
        answers, warnings = split_answers_by_question(text, ["Q1", "Q2"])
        self.assertEqual(answers, {"Q1": "First answer", "Q2": "Second answer"})
        self.assertEqual(warnings, [])

    def test_bare_numbered_subparts_match_requested_questions(self):
        text = "1(a)\nPart A\n\n1(b).\nPart B"
        answers, warnings = split_answers_by_question(text, ["Q1A", "Q1B"])
        self.assertEqual(answers, {"Q1A": "Part A", "Q1B": "Part B"})
        self.assertEqual(warnings, [])

    def test_bare_numbered_headings_require_requested_question_context(self):
        text = "1.\nA numbered line with no rubric context."
        answers, warnings = split_answers_by_question(text)
        self.assertEqual(answers, {FULL_SUBMISSION: text})
        self.assertIn("could_not_split_by_question", warnings)

    def test_explicit_headings_disable_bare_numeric_fallback(self):
        text = "Question 1\nFirst answer\n1.\nA numbered list item"
        answers, warnings = split_answers_by_question(text, ["Q1"])
        self.assertEqual(answers, {"Q1": "First answer\n1.\nA numbered list item"})
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
