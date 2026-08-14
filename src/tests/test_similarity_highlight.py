import unittest

from src.similarity.compare import compare_submissions
from src.similarity.highlight import find_shared_spans, render_side_by_side_html


def assessment(student_id, answers):
    return {
        "student_id": student_id,
        "extracted_answers": dict(answers),
        "submission_meta": {"student_id": student_id},
    }


class TestSharedSpanExtraction(unittest.TestCase):
    def test_finds_shared_five_word_phrases(self):
        a = (
            "we prove by induction on n and then derive the final recurrence "
            "using the established hypothesis"
        )
        b = (
            "first we prove by induction on n before simplifying the recurrence "
            "with a separate argument"
        )
        spans = find_shared_spans(a, b, n=5)
        texts = {span["text"] for span in spans}
        self.assertIn("we prove by induction on", texts)
        self.assertIn("prove by induction on n", texts)

    def test_short_answers_use_shared_trigrams(self):
        spans = find_shared_spans(
            "alpha beta gamma delta",
            "zero alpha beta gamma",
            n=5,
        )
        self.assertIn(
            "alpha beta gamma",
            {span["text"] for span in spans},
        )

    def test_counts_repeated_phrases(self):
        spans = find_shared_spans(
            "alpha beta gamma alpha beta gamma",
            "alpha beta gamma alpha beta gamma alpha beta gamma",
            n=5,
        )
        target = next(
            span for span in spans
            if span["text"] == "alpha beta gamma"
        )
        self.assertEqual(target["count_a"], 2)
        self.assertEqual(target["count_b"], 3)

    def test_no_overlap_returns_empty(self):
        self.assertEqual(
            find_shared_spans(
                "alpha beta gamma delta epsilon",
                "one two three four five",
            ),
            [],
        )

    def test_empty_input_returns_empty(self):
        self.assertEqual(find_shared_spans("", "answer"), [])
        self.assertEqual(find_shared_spans("answer", ""), [])

    def test_max_spans_is_respected(self):
        a = " ".join(f"token{i}" for i in range(30))
        spans = find_shared_spans(a, a, max_spans=3)
        self.assertEqual(len(spans), 3)

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            find_shared_spans("a", "b", n=0)
        with self.assertRaises(ValueError):
            find_shared_spans("a", "b", max_spans=-1)

    def test_compare_populates_shared_spans(self):
        a = (
            "we maintain the invariant while processing each element and update "
            "the current maximum before continuing through the sequence"
        )
        b = (
            "we maintain the invariant while processing each element and update "
            "the current maximum before moving to another sequence position"
        )
        result = compare_submissions(
            assessment("alice", {"Q1": a}),
            assessment("bob", {"Q1": b}),
            ["Q1"],
        )
        self.assertTrue(result.question_similarities["Q1"].shared_spans)


class TestSideBySideHtml(unittest.TestCase):
    def test_contains_both_students_and_answers(self):
        html = render_side_by_side_html(
            "alice",
            "bob",
            "Q2",
            "Alice answer",
            "Bob answer",
            [{"text": "shared phrase", "count_a": 1, "count_b": 1}],
        )
        self.assertIn("alice", html)
        self.assertIn("bob", html)
        self.assertIn("Alice answer", html)
        self.assertIn("Bob answer", html)
        self.assertIn("shared phrase", html)

    def test_html_escapes_untrusted_content(self):
        html = render_side_by_side_html(
            "<script>alert(1)</script>",
            "bob",
            "Q1",
            "<img src=x onerror=alert(1)>",
            "safe",
            [{"text": "<b>shared</b>", "count_a": 1, "count_b": 1}],
        )
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertNotIn("<b>shared</b>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertIn("&lt;b&gt;shared&lt;/b&gt;", html)


if __name__ == "__main__":
    unittest.main()
