"""Tests for persistent assistive-transcription provenance and cache reuse."""

import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.submissions import (
    OllamaTranscriptionBackend,
    PageTranscription,
    TranscriptionBackend,
    TranscriptionPreflightResult,
    TranscriptionStatus,
    load_persisted_submission,
    parse_pdf_accommodation,
)


def _blank_pdf(path: Path, pages: int = 1):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=612, height=792)
    doc.save(str(path))
    doc.close()


class CountingBackend(TranscriptionBackend):
    def __init__(self, *, model="fake-vision", prompt_version="1", variant="A"):
        self._model = model
        self._prompt_version = prompt_version
        self.variant = variant
        self.preflight_calls = 0
        self.page_calls = 0

    @property
    def backend_name(self):
        return "fake"

    @property
    def model_name(self):
        return self._model

    @property
    def prompt_version(self):
        return self._prompt_version

    def cache_identity(self):
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "prompt_version": self.prompt_version,
            "variant": self.variant,
        }

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
        return PageTranscription(
            page_number=page_number,
            source_image=image_path,
            text=f"{page_number}.\nAnswer {page_number}",
            status=TranscriptionStatus.SUCCESSFUL,
            backend=self.backend_name,
            model=self.model_name,
            prompt_version=self.prompt_version,
            done_reason="stop",
            generated_tokens=10,
            metadata={"variant": self.variant},
        )


class OfflineSameIdentityBackend(CountingBackend):
    def preflight(self, *, force=False):
        raise AssertionError("cache hit must not contact the inference service")

    def transcribe_page(self, image_path, *, page_number=None):
        raise AssertionError("cache hit must not run inference")


class TestTranscriptionCache(unittest.TestCase):
    def test_ollama_cache_identity_tracks_output_relevant_configuration(self):
        a = OllamaTranscriptionBackend(
            model="gemma4:31b",
            temperature=0.0,
            seed=42,
            num_ctx=8192,
            num_predict=2048,
            warm_model=False,
        )
        b = OllamaTranscriptionBackend(
            model="gemma4:31b",
            temperature=0.0,
            seed=42,
            num_ctx=8192,
            num_predict=1024,
            warm_model=False,
        )
        identity = a.cache_identity()
        self.assertEqual(identity["model"], "gemma4:31b")
        self.assertIn("prompt_sha256", identity)
        self.assertEqual(identity["num_predict"], 2048)
        self.assertNotEqual(identity, b.cache_identity())
        self.assertNotIn("base_url", identity)

    def test_second_parse_reuses_cache_without_backend_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)

            first_backend = CountingBackend()
            first = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=first_backend,
                evidence_dir=str(evidence),
            )
            self.assertEqual(first_backend.preflight_calls, 1)
            self.assertEqual(first_backend.page_calls, 1)
            self.assertEqual(first.metadata["transcription"]["cache"]["status"], "miss")

            offline = OfflineSameIdentityBackend()
            second = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=offline,
                evidence_dir=str(evidence),
            )
            self.assertEqual(second.metadata["transcription"]["cache"]["status"], "hit")
            self.assertEqual(second.answers_by_question, {"Q1": "Answer 1"})
            self.assertTrue(second.page_transcriptions[0]["metadata"]["cache_reused"])

    def test_model_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=CountingBackend(model="model-a"),
                evidence_dir=str(evidence),
            )

            changed = CountingBackend(model="model-b")
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=changed,
                evidence_dir=str(evidence),
            )
            self.assertEqual(changed.page_calls, 1)
            self.assertEqual(result.metadata["transcription"]["cache"]["status"], "miss")
            self.assertEqual(
                result.metadata["transcription"]["cache"]["reason"],
                "cache_key_mismatch",
            )

    def test_prompt_or_generation_identity_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=CountingBackend(prompt_version="1", variant="A"),
                evidence_dir=str(evidence),
            )
            changed = CountingBackend(prompt_version="2", variant="B")
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=changed,
                evidence_dir=str(evidence),
            )
            self.assertEqual(changed.page_calls, 1)

    def test_render_dpi_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                render_dpi=200,
                transcription_backend=CountingBackend(),
                evidence_dir=str(evidence),
            )
            changed = CountingBackend()
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                render_dpi=180,
                transcription_backend=changed,
                evidence_dir=str(evidence),
            )
            self.assertEqual(changed.page_calls, 1)

    def test_source_pdf_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf, pages=1)
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=CountingBackend(),
                evidence_dir=str(evidence),
            )
            # Replace the submitted evidence with a genuinely different PDF.
            _blank_pdf(pdf, pages=2)
            changed = CountingBackend()
            parse_pdf_accommodation(
                str(pdf),
                ["Q1", "Q2"],
                student_id="student",
                transcription_backend=changed,
                evidence_dir=str(evidence),
            )
            self.assertEqual(changed.page_calls, 2)

    def test_reuse_can_be_explicitly_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)
            parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=CountingBackend(),
                evidence_dir=str(evidence),
            )
            backend = CountingBackend()
            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=backend,
                evidence_dir=str(evidence),
                reuse_cached_transcription=False,
            )
            self.assertEqual(backend.page_calls, 1)
            self.assertEqual(result.metadata["transcription"]["cache"]["status"], "disabled")

    def test_persisted_transcription_provenance_can_be_loaded_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)
            first = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                transcription_backend=CountingBackend(),
                evidence_dir=str(evidence),
            )
            loaded = load_persisted_submission(str(evidence), "student")
            self.assertEqual(loaded.answers_by_question, first.answers_by_question)
            self.assertEqual(loaded.transcription_metadata["status"], "successful")
            self.assertTrue(loaded.page_transcriptions[0]["assistive_only"])
            self.assertFalse(loaded.page_transcriptions[0]["authoritative"])
            self.assertEqual(loaded.page_transcriptions[0]["text"], "1.\nAnswer 1")

            cache_path = Path(loaded.evidence_metadata["transcription_cache_path"])
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertTrue(cache["cache_eligible"])
            self.assertEqual(cache["cache_inputs"]["backend"]["model"], "fake-vision")
            self.assertEqual(cache["cache_inputs"]["render_dpi"], 200)
            self.assertIn("source_sha256", cache["cache_inputs"])
            self.assertIn("sha256", cache["cache_inputs"]["pages"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
