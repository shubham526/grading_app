"""Integration tests for PDF accommodation + assistive transcription."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.submissions import parse_pdf_accommodation, parse_pdf_accommodations
from src.submissions.transcription import (
    PageTranscription,
    TranscriptionBackend,
    TranscriptionPreflightResult,
    TranscriptionStatus,
)


class StaticBackend(TranscriptionBackend):
    def __init__(self, page_results):
        self.page_results = list(page_results)
        self.preflight_calls = 0
        self.page_calls = 0

    @property
    def backend_name(self):
        return "fake"

    @property
    def model_name(self):
        return "fake-vision"

    @property
    def prompt_version(self):
        return "test-1"

    def preflight(self, *, force=False):
        self.preflight_calls += 1
        return TranscriptionPreflightResult(
            ok=True,
            backend=self.backend_name,
            model=self.model_name,
            capabilities=["vision"],
        )

    def transcribe_page(self, image_path, *, page_number=None):
        self.page_calls += 1
        status, text, warning = self.page_results[page_number - 1]
        return PageTranscription(
            page_number=page_number,
            source_image=image_path,
            text=text,
            status=status,
            backend=self.backend_name,
            model=self.model_name,
            prompt_version=self.prompt_version,
            warning=warning,
        )



class FailingBackend(TranscriptionBackend):
    @property
    def backend_name(self):
        return "fake"

    @property
    def model_name(self):
        return "missing-model"

    @property
    def prompt_version(self):
        return "test-1"

    def preflight(self, *, force=False):
        return TranscriptionPreflightResult(
            ok=False,
            backend=self.backend_name,
            model=self.model_name,
            error_code="model_not_installed",
            error_message="missing",
        )

    def transcribe_page(self, image_path, *, page_number=None):
        raise AssertionError("page inference must not run after failed preflight")

def _blank_pdf(path: Path, pages=2):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=612, height=792)
    doc.save(str(path))
    doc.close()


def _typed_pdf(path: Path):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(
        (72, 100),
        "Question 1\n" + "Typed canonical-looking selectable text answer. " * 12,
    )
    doc.save(str(path))
    doc.close()


class TestPdfTranscriptionIntegration(unittest.TestCase):
    def test_scanlike_pdf_uses_complete_transcription_for_assistive_question_mapping(self):
        backend = StaticBackend(
            [
                (TranscriptionStatus.SUCCESSFUL, "Question 1\nStudent answer A", None),
                (TranscriptionStatus.SUCCESSFUL, "Question 2\nStudent answer B", None),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "student.pdf"
            _blank_pdf(pdf, pages=2)
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1", "Q2"],
                student_id="student",
                render_dir=str(Path(tmp) / "rendered"),
                transcription_backend=backend,
            )

        self.assertTrue(result.metadata["original_pdf_authoritative"])
        self.assertEqual(result.metadata["assistive_text_source"], "machine_transcription")
        self.assertEqual(result.answers_by_question["Q1"], "Student answer A")
        self.assertEqual(result.answers_by_question["Q2"], "Student answer B")
        self.assertEqual(result.metadata["transcription"]["status"], "successful")
        self.assertTrue(result.metadata["transcription"]["assistive_only"])
        self.assertFalse(result.metadata["transcription"]["authoritative"])
        self.assertEqual(len(result.page_transcriptions), 2)


    def test_scanlike_numeric_heading_transcription_maps_with_requested_question_ids(self):
        backend = StaticBackend(
            [(TranscriptionStatus.SUCCESSFUL, "1.\nStudent answer A", None)]
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "student.pdf"
            _blank_pdf(pdf, pages=1)
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=backend,
            )

        self.assertEqual(result.metadata["assistive_text_source"], "machine_transcription")
        self.assertEqual(result.answers_by_question, {"Q1": "Student answer A"})
        self.assertNotIn("could_not_split_by_question", result.warnings)

    def test_one_degraded_page_prevents_partial_submission_mapping(self):
        backend = StaticBackend(
            [
                (TranscriptionStatus.SUCCESSFUL, "Question 1\nStudent answer A", None),
                (
                    TranscriptionStatus.GENERATION_LIMIT,
                    "Question 2\npartial",
                    "generation_limit",
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "student.pdf"
            _blank_pdf(pdf, pages=2)
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1", "Q2"],
                transcription_backend=backend,
            )

        self.assertEqual(result.answers_by_question, {})
        self.assertIsNone(result.metadata["assistive_text_source"])
        self.assertEqual(result.metadata["question_split_status"], "unavailable")
        self.assertEqual(result.metadata["transcription"]["status"], "partial")
        self.assertIn("transcription_incomplete", result.warnings)

    def test_selectable_text_remains_preferred_when_transcription_is_enabled(self):
        backend = StaticBackend(
            [(TranscriptionStatus.SUCCESSFUL, "Question 9\nWrong alternate text", None)]
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "typed.pdf"
            _typed_pdf(pdf)
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                transcription_backend=backend,
            )

        self.assertEqual(result.metadata["assistive_text_source"], "pdf_selectable_text")
        self.assertIn("Typed canonical-looking", result.answers_by_question["Q1"])
        self.assertNotIn("Wrong alternate", result.answers_by_question["Q1"])
        self.assertEqual(result.metadata["transcription"]["status"], "successful")

    def test_transcription_is_not_requested_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "scan.pdf"
            _blank_pdf(pdf, pages=1)
            result = parse_pdf_accommodation(str(pdf), ["Q1"])
        self.assertFalse(result.metadata["transcription"]["enabled"])
        self.assertEqual(result.metadata["transcription"]["status"], "not_requested")

    def test_explicit_backend_and_options_are_not_silently_mixed(self):
        backend = StaticBackend(
            [(TranscriptionStatus.SUCCESSFUL, "Question 1\nA", None)]
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "scan.pdf"
            _blank_pdf(pdf, pages=1)
            with self.assertRaises(ValueError):
                parse_pdf_accommodation(
                    str(pdf),
                    ["Q1"],
                    transcription_backend=backend,
                    transcription_options={"model": "other"},
                )

    def test_transcription_failure_never_removes_authoritative_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "scan.pdf"
            _blank_pdf(pdf, pages=1)
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                transcription_backend=FailingBackend(),
            )

        self.assertTrue(result.metadata["original_pdf_authoritative"])
        self.assertEqual(result.files["pdf"], str(pdf.resolve()))
        self.assertEqual(result.answers_by_question, {})
        self.assertEqual(result.metadata["transcription"]["status"], "failed")
        self.assertEqual(
            result.page_transcriptions[0]["status"],
            "model_load_failure",
        )

    def test_batch_api_reuses_one_backend_instance(self):
        backend = StaticBackend(
            [(TranscriptionStatus.SUCCESSFUL, "Question 1\nA", None)]
        )
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.pdf"
            p2 = Path(tmp) / "b.pdf"
            _blank_pdf(p1, pages=1)
            _blank_pdf(p2, pages=1)
            parsed = parse_pdf_accommodations(
                {"alice": str(p1), "bob": str(p2)},
                ["Q1"],
                transcription_backend=backend,
            )
        self.assertEqual(set(parsed), {"alice", "bob"})
        self.assertEqual(backend.page_calls, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
