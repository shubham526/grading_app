import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.similarity.export import (
    CSV_COLUMNS,
    CSV_FILENAME,
    DISCLAIMER,
    HTML_FILENAME,
    JSON_FILENAME,
    MATRIX_FILENAME,
    export_similarity_html,
    export_similarity_json,
    export_similarity_matrix_csv,
    export_similarity_pairs_csv,
    export_similarity_report,
    render_similarity_report_html,
)
from src.similarity.report import generate_similarity_report


def assessment(student_id, answers, *, file_hashes=None):
    return {
        "student_id": student_id,
        "extracted_answers": dict(answers),
        "submission_meta": {
            "student_id": student_id,
            "file_hashes": dict(file_hashes or {}),
        },
    }


def build_fixture():
    exact_hash = "a" * 64
    shared = (
        "we prove the loop invariant by showing initialization maintenance and "
        "termination then conclude the algorithm returns the correct maximum "
        "element after processing every entry in the complete input sequence"
    )
    near = (
        "we prove the loop invariant by showing initialization maintenance and "
        "termination then conclude the algorithm returns the correct maximum "
        "element after processing every entry in the complete input array"
    )
    unrelated = (
        "dynamic programming stores subproblem solutions in a table and later "
        "reconstructs an optimal result by following predecessor decisions"
    )

    submissions = {
        "alice": assessment(
            "alice",
            {"Q1": shared, "Q2": unrelated},
            file_hashes={"latex_sha256": exact_hash},
        ),
        "bob": assessment(
            "bob",
            {"Q1": "different short source content", "Q2": unrelated + " changed"},
            file_hashes={"latex_sha256": exact_hash},
        ),
        "carol": assessment(
            "carol",
            {"Q1": near, "Q2": "another distinct response"},
        ),
    }
    report = generate_similarity_report(
        submissions,
        "PS3",
        ["Q1", "Q2"],
    )
    return submissions, report


class TestJsonExport(unittest.TestCase):
    def test_json_contains_full_structured_report(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_similarity_json(report, Path(tmp) / JSON_FILENAME)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["report_type"], "submission_similarity")
        self.assertEqual(payload["assignment_id"], "PS3")
        self.assertEqual(payload["methods"], report.methods)
        self.assertEqual(payload["thresholds"], report.thresholds)
        self.assertEqual(len(payload["pairs"]), len(report.pairs))
        self.assertIn("question_similarities", payload["pairs"][0])

    def test_json_preserves_shared_spans(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_similarity_json(report, Path(tmp) / JSON_FILENAME)
            payload = json.loads(path.read_text(encoding="utf-8"))

        question_entries = [
            question
            for pair in payload["pairs"]
            for question in pair["question_similarities"].values()
        ]
        self.assertTrue(
            any(question["shared_spans"] for question in question_entries)
        )


class TestCsvExport(unittest.TestCase):
    def test_pairs_csv_contains_expected_columns(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_similarity_pairs_csv(report, Path(tmp) / CSV_FILENAME)
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fieldnames = reader.fieldnames

        self.assertEqual(fieldnames, CSV_COLUMNS)
        self.assertEqual(len(rows), len(report.pairs))
        self.assertIn("Max Ngram Similarity", rows[0])

    def test_matrix_csv_is_square_and_symmetric(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_similarity_matrix_csv(report, Path(tmp) / MATRIX_FILENAME)
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))

        students = report.students
        self.assertEqual(rows[0], ["Student"] + students)
        self.assertEqual(len(rows), len(students) + 1)

        matrix = {
            row[0]: {
                column_student: float(value)
                for column_student, value in zip(students, row[1:])
            }
            for row in rows[1:]
        }

        for student in students:
            self.assertEqual(matrix[student][student], 1.0)

        for a in students:
            for b in students:
                self.assertEqual(matrix[a][b], matrix[b][a])


class TestHtmlExport(unittest.TestCase):
    def test_html_contains_required_disclaimer(self):
        submissions, report = build_fixture()
        html = render_similarity_report_html(report, submissions=submissions)
        self.assertIn(DISCLAIMER, html)

    def test_html_contains_summary_table(self):
        submissions, report = build_fixture()
        html = render_similarity_report_html(report, submissions=submissions)
        self.assertIn("Flagged pairs", html)
        self.assertIn("Student A", html)
        self.assertIn("Max N-gram", html)

    def test_html_contains_side_by_side_for_high_or_exact_pairs(self):
        submissions, report = build_fixture()
        html = render_similarity_report_html(report, submissions=submissions)
        self.assertIn('class="answer-grid"', html)
        self.assertIn("Shared phrases", html)

    def test_html_without_submissions_still_contains_pair_details(self):
        _, report = build_fixture()
        html = render_similarity_report_html(report)
        self.assertIn("Original answer text was not supplied", html)
        self.assertIn("High / exact pair details", html)

    def test_html_escapes_submission_answer_content(self):
        submissions, report = build_fixture()
        # Ensure a high/exact pair's answer contains unsafe markup.
        submissions["alice"]["extracted_answers"]["Q1"] += " <script>alert(1)</script>"
        html = render_similarity_report_html(report, submissions=submissions)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_file_is_written(self):
        submissions, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_similarity_html(
                report,
                Path(tmp) / HTML_FILENAME,
                submissions=submissions,
            )
            self.assertTrue(path.is_file())
            self.assertIn(DISCLAIMER, path.read_text(encoding="utf-8"))


class TestCombinedExport(unittest.TestCase):
    def test_default_export_writes_all_files(self):
        submissions, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                submissions=submissions,
            )

            self.assertEqual(results["json"].name, JSON_FILENAME)
            self.assertEqual(results["csv"].name, CSV_FILENAME)
            self.assertEqual(results["matrix_csv"].name, MATRIX_FILENAME)
            self.assertEqual(results["html"].name, HTML_FILENAME)
            for path in results.values():
                self.assertIsNotNone(path)
                self.assertTrue(path.is_file())

    def test_selected_formats_only_are_written(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("json",),
            )
            self.assertTrue(results["json"].is_file())
            self.assertIsNone(results["csv"])
            self.assertIsNone(results["matrix_csv"])
            self.assertIsNone(results["html"])
            self.assertEqual(
                {path.name for path in Path(tmp).iterdir()},
                {JSON_FILENAME},
            )

    def test_matrix_can_be_disabled(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("csv",),
                include_matrix=False,
            )
            self.assertTrue(results["csv"].is_file())
            self.assertIsNone(results["matrix_csv"])
            self.assertFalse((Path(tmp) / MATRIX_FILENAME).exists())

    def test_unknown_format_is_rejected(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_similarity_report(
                    report,
                    tmp,
                    formats=("csv", "pdf"),
                )

    def test_empty_format_selection_is_rejected(self):
        _, report = build_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_similarity_report(report, tmp, formats=())


if __name__ == "__main__":
    unittest.main()
