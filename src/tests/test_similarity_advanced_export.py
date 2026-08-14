import csv
import json
from pathlib import Path
import tempfile
import unittest

from src.similarity.advanced_report import generate_advanced_similarity_report
from src.similarity.export import (
    CLUSTER_CSV_COLUMNS,
    CLUSTERS_FILENAME,
    CSV_COLUMNS,
    CSV_FILENAME,
    EMBEDDING_DISCLAIMER,
    HTML_FILENAME,
    JSON_FILENAME,
    TREND_CSV_COLUMNS,
    TRENDS_FILENAME,
    export_similarity_report,
    render_similarity_report_html,
)
from src.similarity.mock_embedding_provider import MockEmbeddingProvider
from src.similarity.report import generate_similarity_report


def assessment(
    student_id,
    answer,
    *,
    source_used="latex",
    authoritative_source="latex",
    assistive_text_source=None,
    transcription=None,
):
    meta = {
        "student_id": student_id,
        "source_used": source_used,
        "authoritative_source": authoritative_source,
        "warnings": [],
    }
    if assistive_text_source is not None:
        meta["assistive_text_source"] = assistive_text_source
    if transcription is not None:
        meta["transcription"] = dict(transcription)
    if source_used == "pdf":
        meta["submission_mode"] = "pdf_accommodation"
        meta["accommodation_mode"] = True

    return {
        "student_id": student_id,
        "extracted_answers": {"Q1": answer},
        "submission_meta": meta,
    }


def build_advanced_fixture():
    alice_answer = (
        "Alice explains a priority queue shortest path procedure using different "
        "words and a careful invariant argument."
    )
    bob_answer = (
        "Bob gives semantically equivalent reasoning for shortest paths but uses "
        "substantially different wording."
    )

    submissions = {
        "alice": assessment("alice", alice_answer),
        "bob": assessment(
            "bob",
            bob_answer,
            source_used="pdf",
            authoritative_source="original_pdf",
            assistive_text_source="machine_transcription",
            transcription={
                "provider": "ollama",
                "model": "vision-model",
                "page_count": 1,
            },
        ),
    }

    base = generate_similarity_report(
        submissions,
        "PS3",
        ["Q1"],
    )
    provider = MockEmbeddingProvider(
        vectors={
            alice_answer: [1.0, 0.0],
            bob_answer: [1.0, 0.0],
        }
    )
    trend_records = [
        {
            "student_a": "alice",
            "student_b": "bob",
            "assignments": ["PS2", "PS3"],
            "count": 2,
            "max_similarity": 0.99,
            "questions": {"PS2": ["Q2"], "PS3": ["Q1"]},
            "signals": ["embedding_cosine"],
        }
    ]

    advanced = generate_advanced_similarity_report(
        base,
        submissions,
        ["Q1"],
        embedding_provider=provider,
        include_pseudocode=False,
        include_clustering=True,
        embedding_cache_enabled=False,
        trend_records=trend_records,
    )
    return submissions, advanced


class TestAdvancedJsonExport(unittest.TestCase):
    def test_json_preserves_advanced_report_fields_and_provenance(self):
        _, report = build_advanced_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("json",),
            )
            payload = json.loads(results["json"].read_text(encoding="utf-8"))

        self.assertEqual(payload["advanced_methods"], report.advanced_methods)
        self.assertEqual(payload["clusters"], report.clusters)
        self.assertEqual(payload["trends"], report.trends)
        self.assertEqual(payload["embedding_config"], report.embedding_config)
        self.assertIn("submission_provenance", payload)
        self.assertTrue(
            payload["submission_provenance"]["bob"]["uses_assistive_transcription"]
        )
        self.assertEqual(
            payload["pairs"][0]["embedding_max_similarity"],
            1.0,
        )


class TestAdvancedCsvExport(unittest.TestCase):
    def test_pair_csv_includes_advanced_columns_and_provenance(self):
        _, report = build_advanced_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("csv",),
            )
            with results["csv"].open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(reader.fieldnames, CSV_COLUMNS)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Embedding Max"], "1.000000")
        self.assertEqual(row["Cluster"], "C1")
        self.assertEqual(row["Trend Count"], "2")
        self.assertEqual(row["Student A Text Source"], "latex")
        self.assertEqual(row["Student B Text Source"], "machine_transcription")
        self.assertEqual(row["Student B Assistive Transcription"], "True")

    def test_cluster_csv_has_expected_schema_and_content(self):
        _, report = build_advanced_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("csv",),
            )
            with results["clusters_csv"].open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(results["clusters_csv"].name, CLUSTERS_FILENAME)
        self.assertEqual(reader.fieldnames, CLUSTER_CSV_COLUMNS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Cluster ID"], "C1")
        self.assertEqual(rows[0]["Size"], "2")
        self.assertIn("alice", rows[0]["Students"])
        self.assertIn("embedding_cosine", rows[0]["Signals"])

    def test_trend_csv_has_expected_schema_and_content(self):
        _, report = build_advanced_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("csv",),
            )
            with results["trends_csv"].open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(results["trends_csv"].name, TRENDS_FILENAME)
        self.assertEqual(reader.fieldnames, TREND_CSV_COLUMNS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Student A"], "alice")
        self.assertEqual(rows[0]["Student B"], "bob")
        self.assertEqual(rows[0]["Count"], "2")
        self.assertIn("PS2", rows[0]["Assignments Flagged"])
        self.assertIn("PS3: Q1", rows[0]["Questions"])

    def test_base_report_still_writes_empty_advanced_csvs_with_headers(self):
        submissions = {
            "alice": assessment("alice", "one answer"),
            "bob": assessment("bob", "different answer"),
        }
        report = generate_similarity_report(
            submissions,
            "PS0",
            ["Q1"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                formats=("csv",),
            )
            with results["clusters_csv"].open(newline="", encoding="utf-8") as handle:
                cluster_rows = list(csv.reader(handle))
            with results["trends_csv"].open(newline="", encoding="utf-8") as handle:
                trend_rows = list(csv.reader(handle))

        self.assertEqual(len(cluster_rows), 1)
        self.assertEqual(len(trend_rows), 1)


class TestAdvancedHtmlExport(unittest.TestCase):
    def test_html_contains_advanced_tables_scores_and_semantic_warning(self):
        submissions, report = build_advanced_fixture()
        html = render_similarity_report_html(report, submissions=submissions)

        self.assertIn(EMBEDDING_DISCLAIMER, html)
        self.assertIn("<h2>Advanced methods</h2>", html)
        self.assertIn("<h2>Clusters</h2>", html)
        self.assertIn("<h2>Trends</h2>", html)
        self.assertIn("Embedding Max", html)
        self.assertIn("Pseudocode Max", html)
        self.assertIn("embedding_cosine", html)
        self.assertIn("C1", html)
        self.assertIn("PS2", html)

    def test_html_displays_assistive_transcription_provenance(self):
        submissions, report = build_advanced_fixture()
        html = render_similarity_report_html(report, submissions=submissions)

        self.assertIn("Submission provenance", html)
        self.assertIn("machine_transcription", html)
        self.assertIn("Assistive transcription:</strong> yes", html)
        self.assertIn(
            "Similarity analysis used assistive machine transcription",
            html,
        )

    def test_html_escapes_advanced_metadata(self):
        submissions, report = build_advanced_fixture()
        report.trends[0]["signals"] = ['<script>alert("x")</script>']

        html = render_similarity_report_html(report, submissions=submissions)

        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("&lt;script&gt;", html)


class TestAdvancedCombinedExport(unittest.TestCase):
    def test_default_export_writes_all_six_v231_outputs(self):
        submissions, report = build_advanced_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            results = export_similarity_report(
                report,
                tmp,
                submissions=submissions,
            )

            expected_names = {
                JSON_FILENAME,
                CSV_FILENAME,
                "similarity_matrix.csv",
                CLUSTERS_FILENAME,
                TRENDS_FILENAME,
                HTML_FILENAME,
            }
            written_names = {
                path.name
                for path in results.values()
                if path is not None
            }

        self.assertEqual(written_names, expected_names)


if __name__ == "__main__":
    unittest.main()
