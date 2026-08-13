"""Tests for model-agnostic transcription data models and orchestration."""

import unittest

from src.submissions.transcription import (
    PageTranscription,
    TranscriptionBackend,
    TranscriptionPreflightResult,
    TranscriptionStatus,
    transcribe_page_images,
)


class FakeBackend(TranscriptionBackend):
    def __init__(self, page_results=None, *, preflight_ok=True, preflight_error=None):
        self._page_results = list(page_results or [])
        self._preflight_ok = preflight_ok
        self._preflight_error = preflight_error
        self.calls = 0

    @property
    def backend_name(self):
        return "fake"

    @property
    def model_name(self):
        return "fake-model"

    @property
    def prompt_version(self):
        return "test"

    def preflight(self, *, force=False):
        return TranscriptionPreflightResult(
            ok=self._preflight_ok,
            backend=self.backend_name,
            model=self.model_name,
            error_code=self._preflight_error,
            error_message="not ready" if not self._preflight_ok else None,
        )

    def transcribe_page(self, image_path, *, page_number=None):
        self.calls += 1
        status, text, warning = self._page_results[page_number - 1]
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


class TestTranscriptionModels(unittest.TestCase):
    def test_page_success_is_assistive_not_authoritative(self):
        page = PageTranscription(
            page_number=1,
            source_image="page_001.png",
            text="Q1\nanswer",
            status=TranscriptionStatus.SUCCESSFUL,
            backend="fake",
            model="m",
            prompt_version="1",
        )
        self.assertTrue(page.usable)
        meta = page.to_metadata()
        self.assertTrue(meta["assistive_only"])
        self.assertFalse(meta["authoritative"])
        self.assertEqual(meta["status"], "successful")

    def test_all_successful_pages_can_be_combined(self):
        backend = FakeBackend(
            [
                (TranscriptionStatus.SUCCESSFUL, "Question 1\nA", None),
                (TranscriptionStatus.SUCCESSFUL, "Question 2\nB", None),
            ]
        )
        result = transcribe_page_images(backend, ["p1.png", "p2.png"])
        self.assertTrue(result.all_pages_usable)
        self.assertEqual(result.status, "successful")
        self.assertEqual(result.combined_text(), "Question 1\nA\n\nQuestion 2\nB")
        self.assertEqual(backend.calls, 2)

    def test_partial_batch_is_never_combined(self):
        backend = FakeBackend(
            [
                (TranscriptionStatus.SUCCESSFUL, "Question 1\nA", None),
                (TranscriptionStatus.GENERATION_LIMIT, "partial", "generation_limit"),
            ]
        )
        result = transcribe_page_images(backend, ["p1.png", "p2.png"])
        self.assertEqual(result.status, "partial")
        self.assertFalse(result.all_pages_usable)
        self.assertEqual(result.combined_text(), "")
        self.assertIn("transcription_incomplete", result.warnings)

    def test_preflight_model_failure_is_page_aligned(self):
        backend = FakeBackend(preflight_ok=False, preflight_error="model_not_installed")
        result = transcribe_page_images(backend, ["p1.png", "p2.png"])
        self.assertEqual(backend.calls, 0)
        self.assertEqual(len(result.pages), 2)
        self.assertTrue(
            all(page.status == TranscriptionStatus.MODEL_LOAD_FAILURE for page in result.pages)
        )
        self.assertEqual(result.combined_text(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
