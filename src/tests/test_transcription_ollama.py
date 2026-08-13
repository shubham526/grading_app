"""Tests for the Ollama handwriting-transcription backend."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.submissions.transcription import (
    DEFAULT_HANDWRITING_MODEL,
    HANDWRITING_TRANSCRIPTION_PROMPT,
    OllamaTranscriptionBackend,
    TranscriptionStatus,
    detect_degenerate_repetition,
)
from src.submissions.transcription.ollama import _OllamaRequestError


def _image_file(root: str) -> str:
    path = Path(root) / "page_001.png"
    path.write_bytes(b"not-a-real-png-but-enough-for-request-construction")
    return str(path)


def _ready_request(capture=None, chat_response=None):
    def request(method, endpoint, *, payload=None, timeout=None):
        if endpoint == "/tags":
            return {"models": [{"name": DEFAULT_HANDWRITING_MODEL}]}
        if endpoint == "/show":
            return {
                "capabilities": ["completion", "vision"],
                "details": {"family": "gemma4"},
            }
        if endpoint == "/generate":
            return {"done": True}
        if endpoint == "/chat":
            if capture is not None:
                capture["payload"] = payload
            return chat_response or {
                "message": {"role": "assistant", "content": "Question 1\n$n^2$"},
                "done": True,
                "done_reason": "stop",
                "eval_count": 7,
                "total_duration": 123,
            }
        raise AssertionError(endpoint)
    return request


class TestOllamaBackend(unittest.TestCase):
    def test_default_model_is_benchmark_winner(self):
        backend = OllamaTranscriptionBackend(warm_model=False)
        self.assertEqual(backend.model_name, "gemma4:31b")

    def test_preflight_checks_model_and_vision_capability(self):
        backend = OllamaTranscriptionBackend()
        with mock.patch.object(backend, "_json_request", side_effect=_ready_request()):
            result = backend.preflight()
        self.assertTrue(result.ok)
        self.assertIn("vision", result.capabilities)

    def test_missing_model_is_structured_failure(self):
        backend = OllamaTranscriptionBackend(warm_model=False)

        def request(method, endpoint, *, payload=None, timeout=None):
            if endpoint == "/tags":
                return {"models": [{"name": "qwen3-vl:8b-instruct"}]}
            raise AssertionError(endpoint)

        with mock.patch.object(backend, "_json_request", side_effect=request):
            result = backend.preflight()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "model_not_installed")

    def test_nonvision_model_is_rejected(self):
        backend = OllamaTranscriptionBackend(warm_model=False)

        def request(method, endpoint, *, payload=None, timeout=None):
            if endpoint == "/tags":
                return {"models": [{"name": DEFAULT_HANDWRITING_MODEL}]}
            if endpoint == "/show":
                return {"capabilities": ["completion"]}
            raise AssertionError(endpoint)

        with mock.patch.object(backend, "_json_request", side_effect=request):
            result = backend.preflight()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "model_not_vision_capable")

    def test_model_load_failure_is_structured(self):
        backend = OllamaTranscriptionBackend(warm_model=True)

        def request(method, endpoint, *, payload=None, timeout=None):
            if endpoint == "/tags":
                return {"models": [{"name": DEFAULT_HANDWRITING_MODEL}]}
            if endpoint == "/show":
                return {"capabilities": ["vision"]}
            if endpoint == "/generate":
                raise _OllamaRequestError("ollama_http_error", "out of memory", http_status=500)
            raise AssertionError(endpoint)

        with mock.patch.object(backend, "_json_request", side_effect=request):
            result = backend.preflight()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "model_load_failure")

    def test_success_uses_benchmark_generation_settings(self):
        capture = {}
        backend = OllamaTranscriptionBackend()
        with tempfile.TemporaryDirectory() as tmp:
            image = _image_file(tmp)
            with mock.patch.object(
                backend,
                "_json_request",
                side_effect=_ready_request(capture=capture),
            ):
                result = backend.transcribe_page(image, page_number=1)

        self.assertEqual(result.status, TranscriptionStatus.SUCCESSFUL)
        self.assertEqual(result.text, "Question 1\n$n^2$")
        self.assertEqual(result.generated_tokens, 7)
        payload = capture["payload"]
        self.assertEqual(payload["model"], "gemma4:31b")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["messages"][0]["content"], HANDWRITING_TRANSCRIPTION_PROMPT)
        self.assertTrue(payload["messages"][0]["images"][0])
        self.assertEqual(payload["options"]["temperature"], 0.0)
        self.assertEqual(payload["options"]["seed"], 42)
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertEqual(payload["options"]["num_predict"], 2048)

    def test_generation_limit_is_degraded_not_usable(self):
        response = {
            "message": {"role": "assistant", "content": "partial answer"},
            "done": True,
            "done_reason": "length",
            "eval_count": 2048,
        }
        backend = OllamaTranscriptionBackend()
        with tempfile.TemporaryDirectory() as tmp:
            image = _image_file(tmp)
            with mock.patch.object(
                backend,
                "_json_request",
                side_effect=_ready_request(chat_response=response),
            ):
                result = backend.transcribe_page(image)
        self.assertEqual(result.status, TranscriptionStatus.GENERATION_LIMIT)
        self.assertFalse(result.usable)
        self.assertEqual(result.text, "partial answer")

    def test_empty_output_is_structured_failure(self):
        response = {
            "message": {"role": "assistant", "content": "", "thinking": "hidden reasoning"},
            "done": True,
            "done_reason": "stop",
            "eval_count": 100,
        }
        backend = OllamaTranscriptionBackend()
        with tempfile.TemporaryDirectory() as tmp:
            image = _image_file(tmp)
            with mock.patch.object(
                backend,
                "_json_request",
                side_effect=_ready_request(chat_response=response),
            ):
                result = backend.transcribe_page(image)
        self.assertEqual(result.status, TranscriptionStatus.EMPTY_OUTPUT)
        self.assertEqual(result.metadata["thinking_chars"], len("hidden reasoning"))

    def test_degenerate_repetition_detector_matches_benchmark_failure_shape(self):
        bad = "Question 1\nanswer starts\n" + ("\\quad " * 500)
        self.assertTrue(detect_degenerate_repetition(bad))
        normal = "Question 1\n" + "The recurrence is T(n)=2T(n/2)+n. " * 8
        self.assertFalse(detect_degenerate_repetition(normal))


    def test_malformed_chat_response_is_inference_failure(self):
        backend = OllamaTranscriptionBackend()
        with tempfile.TemporaryDirectory() as tmp:
            image = _image_file(tmp)
            with mock.patch.object(
                backend,
                "_json_request",
                side_effect=_ready_request(chat_response={"done": True, "done_reason": "stop"}),
            ):
                result = backend.transcribe_page(image)
        self.assertEqual(result.status, TranscriptionStatus.INFERENCE_FAILURE)
        self.assertEqual(result.warning, "ollama_invalid_response")

    def test_degenerate_chat_response_is_marked_degraded(self):
        response = {
            "message": {
                "role": "assistant",
                "content": "Question 1\nanswer starts\n" + ("\\quad " * 500),
            },
            "done": True,
            "done_reason": "stop",
            "eval_count": 900,
        }
        backend = OllamaTranscriptionBackend()
        with tempfile.TemporaryDirectory() as tmp:
            image = _image_file(tmp)
            with mock.patch.object(
                backend,
                "_json_request",
                side_effect=_ready_request(chat_response=response),
            ):
                result = backend.transcribe_page(image)
        self.assertEqual(result.status, TranscriptionStatus.DEGENERATE_REPETITION)
        self.assertFalse(result.usable)
        self.assertEqual(result.warning, "degenerate_repetition")

    def test_unavailable_server_maps_to_unavailable_page(self):
        backend = OllamaTranscriptionBackend(warm_model=False)
        with tempfile.TemporaryDirectory() as tmp:
            image = _image_file(tmp)
            with mock.patch.object(
                backend,
                "_json_request",
                side_effect=_OllamaRequestError("ollama_unavailable", "connection refused"),
            ):
                result = backend.transcribe_page(image)
        self.assertEqual(result.status, TranscriptionStatus.UNAVAILABLE)
        self.assertEqual(result.warning, "ollama_unavailable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
