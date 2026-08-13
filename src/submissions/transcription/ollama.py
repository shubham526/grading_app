"""Ollama vision backend for assistive handwriting transcription.

The default model is Gemma 4 31B, selected by the project's handwriting
benchmark.  There is deliberately no automatic fallback model: if the configured
model is unavailable or fails, the original PDF remains fully gradable and the
transcription is reported as unavailable/degraded.
"""

from __future__ import annotations

import base64
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .base import TranscriptionBackend
from .models import PageTranscription, TranscriptionPreflightResult, TranscriptionStatus
from .prompt import (
    HANDWRITING_PROMPT_SHA256,
    HANDWRITING_PROMPT_VERSION,
    HANDWRITING_TRANSCRIPTION_PROMPT,
)


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_HANDWRITING_MODEL = "gemma4:31b"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 42
DEFAULT_NUM_CTX = 8192
DEFAULT_NUM_PREDICT = 2048
DEFAULT_REQUEST_TIMEOUT = 180.0
DEFAULT_PREFLIGHT_TIMEOUT = 10.0
DEFAULT_KEEP_ALIVE = "10m"
DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

_ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class _OllamaRequestError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _normalize_base_url(url: str) -> str:
    value = str(url).strip().rstrip("/")
    if not value:
        raise ValueError("base_url must not be empty")
    parsed = urllib_parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL")
    return value


def _validate_positive_int(name: str, value: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if resolved <= 0:
        raise ValueError(f"{name} must be positive")
    return resolved


def _validate_timeout(name: str, value: float) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if resolved <= 0:
        raise ValueError(f"{name} must be positive")
    return resolved


def _read_image_as_base64(path: str, max_bytes: int) -> Tuple[str, int]:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked page images are not accepted: {requested}")
    source = requested.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    if source.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported page-image format: {source.suffix}")
    size = source.stat().st_size
    if size <= 0:
        raise ValueError("Page image is empty")
    if size > max_bytes:
        raise ValueError(
            f"Page image is {size} bytes; configured maximum is {max_bytes} bytes"
        )
    return base64.b64encode(source.read_bytes()).decode("ascii"), size


def detect_degenerate_repetition(text: str) -> bool:
    """Detect obvious runaway repetition without rewriting model output.

    The detector is intentionally conservative.  It targets failure patterns
    observed in the benchmark (for example thousands of repeated ``\\quad``
    tokens) rather than ordinary repeated mathematical notation.
    """
    value = (text or "").strip()
    if len(value) < 256:
        return False

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) >= 8:
        counts = Counter(lines)
        most_common_line, count = counts.most_common(1)[0]
        if len(most_common_line) >= 2 and count >= 8 and count / len(lines) >= 0.5:
            return True

    tokens = re.findall(r"\\[A-Za-z]+|[A-Za-z0-9_]+|[^\s]", value)
    if len(tokens) >= 80:
        _, count = Counter(tokens).most_common(1)[0]
        if count >= 25 and count / len(tokens) >= 0.45:
            return True

        for n in (2, 3, 4, 5):
            if len(tokens) < n * 12:
                continue
            ngrams = Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))
            _, repeats = ngrams.most_common(1)[0]
            covered_fraction = (repeats * n) / len(tokens)
            if repeats >= 12 and covered_fraction >= 0.60:
                return True

    return False


class OllamaTranscriptionBackend(TranscriptionBackend):
    """Handwriting transcription through Ollama's non-streaming chat API."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_HANDWRITING_MODEL,
        prompt: str = HANDWRITING_TRANSCRIPTION_PROMPT,
        prompt_version: str = HANDWRITING_PROMPT_VERSION,
        temperature: float = DEFAULT_TEMPERATURE,
        seed: int = DEFAULT_SEED,
        num_ctx: int = DEFAULT_NUM_CTX,
        num_predict: int = DEFAULT_NUM_PREDICT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        preflight_timeout: float = DEFAULT_PREFLIGHT_TIMEOUT,
        keep_alive: Any = DEFAULT_KEEP_ALIVE,
        max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        warm_model: bool = True,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self._model = str(model).strip()
        if not self._model:
            raise ValueError("model must not be empty")
        self.prompt = str(prompt)
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        self._prompt_version = str(prompt_version).strip()
        if not self._prompt_version:
            raise ValueError("prompt_version must not be empty")
        self.temperature = float(temperature)
        self.seed = int(seed)
        self.num_ctx = _validate_positive_int("num_ctx", num_ctx)
        self.num_predict = _validate_positive_int("num_predict", num_predict)
        self.request_timeout = _validate_timeout("request_timeout", request_timeout)
        self.preflight_timeout = _validate_timeout("preflight_timeout", preflight_timeout)
        self.keep_alive = keep_alive
        self.max_image_bytes = _validate_positive_int("max_image_bytes", max_image_bytes)
        self.max_response_bytes = _validate_positive_int("max_response_bytes", max_response_bytes)
        self.warm_model = bool(warm_model)
        self.api_key = api_key or os.environ.get("OLLAMA_API_KEY")
        self._preflight_cache: Optional[TranscriptionPreflightResult] = None

    @property
    def backend_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    def cache_identity(self) -> Dict[str, Any]:
        """Return generation-relevant provenance for cache invalidation."""
        prompt_sha256 = hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "prompt_version": self.prompt_version,
            "prompt_sha256": prompt_sha256,
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "think": False,
            "api_mode": "chat",
        }

    def _api_url(self, endpoint: str) -> str:
        endpoint = "/" + endpoint.lstrip("/")
        if self.base_url.endswith("/api"):
            return self.base_url + endpoint
        return self.base_url + "/api" + endpoint

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _json_request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        data = None
        headers = self._headers()
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib_request.Request(
            self._api_url(endpoint),
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib_request.urlopen(req, timeout=timeout or self.request_timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise _OllamaRequestError(
                        "ollama_response_too_large",
                        f"Ollama response exceeded {self.max_response_bytes} bytes.",
                    )
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read(8192).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            message = body.strip() or str(exc)
            raise _OllamaRequestError(
                "ollama_http_error",
                message,
                http_status=getattr(exc, "code", None),
            ) from exc
        except (urllib_error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise _OllamaRequestError("ollama_unavailable", str(exc)) from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _OllamaRequestError("ollama_invalid_response", str(exc)) from exc
        if not isinstance(parsed, dict):
            raise _OllamaRequestError("ollama_invalid_response", "Ollama returned a non-object JSON response.")
        if parsed.get("error"):
            raise _OllamaRequestError("ollama_api_error", str(parsed["error"]))
        return parsed

    def _installed_model_names(self, tags: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        models = tags.get("models", [])
        if not isinstance(models, list):
            return names
        for item in models:
            if not isinstance(item, dict):
                continue
            for key in ("name", "model"):
                value = item.get(key)
                if isinstance(value, str) and value and value not in names:
                    names.append(value)
        return names

    def _preflight_failure(
        self,
        code: str,
        message: str,
        *,
        warnings: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TranscriptionPreflightResult:
        return TranscriptionPreflightResult(
            ok=False,
            backend=self.backend_name,
            model=self.model_name,
            server_url=self.base_url,
            warnings=list(warnings or []),
            error_code=code,
            error_message=message,
            metadata=dict(metadata or {}),
        )

    def preflight(self, *, force: bool = False) -> TranscriptionPreflightResult:
        if self._preflight_cache is not None and not force:
            return self._preflight_cache

        try:
            tags = self._json_request("GET", "/tags", timeout=self.preflight_timeout)
        except _OllamaRequestError as exc:
            result = self._preflight_failure(exc.code, exc.message)
            self._preflight_cache = result
            return result

        installed = self._installed_model_names(tags)
        if self.model_name not in installed:
            result = self._preflight_failure(
                "model_not_installed",
                f"Configured Ollama model {self.model_name!r} is not installed.",
                metadata={"installed_models": installed},
            )
            self._preflight_cache = result
            return result

        capabilities: List[str] = []
        warnings: List[str] = []
        show_payload: Dict[str, Any] = {}
        try:
            show_payload = self._json_request(
                "POST",
                "/show",
                payload={"model": self.model_name},
                timeout=self.preflight_timeout,
            )
            raw_capabilities = show_payload.get("capabilities", [])
            if isinstance(raw_capabilities, list):
                capabilities = [str(value) for value in raw_capabilities]
            if capabilities and "vision" not in capabilities:
                result = self._preflight_failure(
                    "model_not_vision_capable",
                    f"Configured Ollama model {self.model_name!r} does not advertise vision capability.",
                    metadata={"capabilities": capabilities},
                )
                self._preflight_cache = result
                return result
            if not capabilities:
                warnings.append("model_capabilities_unknown")
        except _OllamaRequestError as exc:
            # Older Ollama builds may not expose all show metadata reliably.  We
            # already proved the model is installed, so continue and let the
            # actual image call establish capability unless the server itself is
            # unreachable.
            if exc.code == "ollama_unavailable":
                result = self._preflight_failure(exc.code, exc.message)
                self._preflight_cache = result
                return result
            warnings.append("model_capability_check_failed")

        if self.warm_model:
            try:
                self._json_request(
                    "POST",
                    "/generate",
                    payload={
                        "model": self.model_name,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": self.keep_alive,
                    },
                    timeout=self.request_timeout,
                )
            except _OllamaRequestError as exc:
                result = self._preflight_failure(
                    "model_load_failure",
                    f"Ollama could not load {self.model_name!r}: {exc.message}",
                    warnings=warnings,
                    metadata={"underlying_error_code": exc.code},
                )
                self._preflight_cache = result
                return result

        result = TranscriptionPreflightResult(
            ok=True,
            backend=self.backend_name,
            model=self.model_name,
            server_url=self.base_url,
            capabilities=capabilities,
            warnings=warnings,
            metadata={
                "warm_model": self.warm_model,
                "model_details": show_payload.get("details") if isinstance(show_payload, dict) else None,
            },
        )
        self._preflight_cache = result
        return result

    def reset_preflight(self) -> None:
        self._preflight_cache = None

    def _failure_page(
        self,
        image_path: str,
        page_number: int,
        status: TranscriptionStatus,
        warning: str,
        message: str,
        *,
        duration_seconds: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PageTranscription:
        payload = dict(metadata or {})
        if message:
            payload["error_message"] = message
        return PageTranscription(
            page_number=page_number,
            source_image=str(image_path),
            text="",
            status=status,
            backend=self.backend_name,
            model=self.model_name,
            prompt_version=self.prompt_version,
            duration_seconds=duration_seconds,
            warning=warning,
            metadata=payload,
        )

    def transcribe_page(
        self,
        image_path: str,
        *,
        page_number: Optional[int] = None,
    ) -> PageTranscription:
        page = int(page_number) if page_number is not None else 1
        if page <= 0:
            raise ValueError("page_number must be positive")

        started = time.monotonic()
        try:
            image_b64, image_size = _read_image_as_base64(image_path, self.max_image_bytes)
        except (OSError, ValueError) as exc:
            return self._failure_page(
                image_path,
                page,
                TranscriptionStatus.INFERENCE_FAILURE,
                "image_unavailable",
                str(exc),
                duration_seconds=time.monotonic() - started,
            )

        preflight = self.preflight()
        if not preflight.ok:
            status = (
                TranscriptionStatus.MODEL_LOAD_FAILURE
                if preflight.error_code in {
                    "model_not_installed",
                    "model_not_vision_capable",
                    "model_load_failure",
                }
                else TranscriptionStatus.UNAVAILABLE
            )
            return self._failure_page(
                image_path,
                page,
                status,
                preflight.error_code or "transcription_unavailable",
                preflight.error_message or "Transcription backend is unavailable.",
                duration_seconds=time.monotonic() - started,
            )

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": self.prompt,
                    "images": [image_b64],
                }
            ],
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

        try:
            response = self._json_request(
                "POST",
                "/chat",
                payload=payload,
                timeout=self.request_timeout,
            )
        except _OllamaRequestError as exc:
            return self._failure_page(
                image_path,
                page,
                TranscriptionStatus.INFERENCE_FAILURE,
                exc.code,
                exc.message,
                duration_seconds=time.monotonic() - started,
                metadata={"http_status": exc.http_status},
            )

        message = response.get("message")
        if not isinstance(message, dict):
            return self._failure_page(
                image_path,
                page,
                TranscriptionStatus.INFERENCE_FAILURE,
                "ollama_invalid_response",
                "Ollama chat response did not contain a message object.",
                duration_seconds=time.monotonic() - started,
            )

        content = message.get("content", "")
        text = content if isinstance(content, str) else str(content or "")
        text = text.strip()
        thinking = message.get("thinking", "")
        thinking_chars = len(thinking) if isinstance(thinking, str) else 0
        done_reason = response.get("done_reason")
        done_reason = str(done_reason) if done_reason is not None else None
        generated_tokens = response.get("eval_count")
        try:
            generated_tokens = int(generated_tokens) if generated_tokens is not None else None
        except (TypeError, ValueError):
            generated_tokens = None

        status = TranscriptionStatus.SUCCESSFUL
        warning: Optional[str] = None
        if done_reason == "length":
            status = TranscriptionStatus.GENERATION_LIMIT
            warning = "generation_limit"
        elif not text:
            status = TranscriptionStatus.EMPTY_OUTPUT
            warning = "empty_output"
        elif detect_degenerate_repetition(text):
            status = TranscriptionStatus.DEGENERATE_REPETITION
            warning = "degenerate_repetition"
        elif text.startswith("```") or text.endswith("```"):
            warning = "model_returned_markdown_fence"

        duration = time.monotonic() - started
        metadata = {
            "prompt_sha256": HANDWRITING_PROMPT_SHA256
            if self.prompt == HANDWRITING_TRANSCRIPTION_PROMPT
            else None,
            "prompt_eval_count": response.get("prompt_eval_count"),
            "thinking_chars": thinking_chars,
            "ollama_total_duration_ns": response.get("total_duration"),
            "ollama_load_duration_ns": response.get("load_duration"),
            "ollama_prompt_eval_duration_ns": response.get("prompt_eval_duration"),
            "ollama_eval_duration_ns": response.get("eval_duration"),
            "image_bytes": image_size,
            "temperature": self.temperature,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }

        return PageTranscription(
            page_number=page,
            source_image=str(Path(image_path).expanduser().resolve()),
            text=text,
            status=status,
            backend=self.backend_name,
            model=self.model_name,
            prompt_version=self.prompt_version,
            duration_seconds=duration,
            generated_tokens=generated_tokens,
            done_reason=done_reason,
            warning=warning,
            metadata=metadata,
        )


__all__ = [
    "DEFAULT_HANDWRITING_MODEL",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_MAX_IMAGE_BYTES",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_NUM_CTX",
    "DEFAULT_NUM_PREDICT",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_PREFLIGHT_TIMEOUT",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_SEED",
    "DEFAULT_TEMPERATURE",
    "OllamaTranscriptionBackend",
    "detect_degenerate_repetition",
]
