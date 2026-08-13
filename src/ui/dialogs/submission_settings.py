"""Submission/AI settings dialog for Commit 5.

Only endpoint and handwriting model are user-facing.  Low-level inference
parameters remain backend-owned production defaults.  The application also
does not manage SSH credentials or the remote Ollama process: the configured
endpoint is simply the service URL visible from the Mac application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.submissions import DEFAULT_HANDWRITING_MODEL


DEFAULT_UI_OLLAMA_URL = "http://127.0.0.1:11435"
SETTINGS_ORGANIZATION = "MissouriS&T"
SETTINGS_APPLICATION = "RubricGradingTool"
SETTINGS_GROUP = "submission_ai"
SETTINGS_ENDPOINT_KEY = "ollama_endpoint"
SETTINGS_MODEL_KEY = "handwriting_model"


@dataclass(frozen=True)
class SubmissionInferenceSettings:
    """Minimal UI-owned configuration for handwriting inference."""

    base_url: str = DEFAULT_UI_OLLAMA_URL
    model: str = DEFAULT_HANDWRITING_MODEL

    def normalized(self) -> "SubmissionInferenceSettings":
        return SubmissionInferenceSettings(
            base_url=normalize_ollama_endpoint(self.base_url),
            model=normalize_model_name(self.model),
        )

    def as_dict(self) -> dict:
        value = self.normalized()
        return {"base_url": value.base_url, "model": value.model}


def normalize_ollama_endpoint(value: Any) -> str:
    """Validate and normalize an absolute HTTP(S) Ollama endpoint."""

    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Ollama endpoint must be an absolute http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError("Do not embed credentials in the Ollama endpoint URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("Ollama endpoint must not include a query string or fragment.")
    return text


def normalize_model_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Handwriting model must not be empty.")
    if any(char.isspace() for char in text):
        raise ValueError("Handwriting model name must not contain whitespace.")
    return text


def _default_qsettings() -> QSettings:
    return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def load_submission_settings(settings: Optional[QSettings] = None) -> SubmissionInferenceSettings:
    """Load UI inference settings, falling back safely if persisted data is invalid."""

    store = settings or _default_qsettings()
    store.beginGroup(SETTINGS_GROUP)
    try:
        endpoint = store.value(SETTINGS_ENDPOINT_KEY, DEFAULT_UI_OLLAMA_URL, type=str)
        model = store.value(SETTINGS_MODEL_KEY, DEFAULT_HANDWRITING_MODEL, type=str)
    finally:
        store.endGroup()

    try:
        return SubmissionInferenceSettings(endpoint, model).normalized()
    except ValueError:
        # Corrupt/manual QSettings edits should never prevent the grader from
        # opening.  The dialog will show safe production UI defaults instead.
        return SubmissionInferenceSettings()


def save_submission_settings(
    value: SubmissionInferenceSettings,
    settings: Optional[QSettings] = None,
) -> SubmissionInferenceSettings:
    """Validate and persist endpoint/model UI preferences."""

    normalized = value.normalized()
    store = settings or _default_qsettings()
    store.beginGroup(SETTINGS_GROUP)
    try:
        store.setValue(SETTINGS_ENDPOINT_KEY, normalized.base_url)
        store.setValue(SETTINGS_MODEL_KEY, normalized.model)
    finally:
        store.endGroup()
    store.sync()
    return normalized


class SubmissionSettingsDialog(QDialog):
    """Configure the Ollama endpoint/model used for new transcription jobs.

    ``Test Connection`` deliberately does not perform network I/O on the GUI
    thread.  It emits ``test_connection_requested(settings)``.  Main-window
    wiring should start a ``SubmissionWorker(TEST_OLLAMA)`` and feed its result
    back through ``set_connection_test_result``.
    """

    test_connection_requested = pyqtSignal(object)
    settings_saved = pyqtSignal(object)

    def __init__(self, parent=None, *, settings: Optional[QSettings] = None):
        super().__init__(parent)
        self._settings_store = settings or _default_qsettings()
        self._last_valid_settings = load_submission_settings(self._settings_store)
        self._build_ui()
        self.set_settings(self._last_valid_settings)

    def _build_ui(self) -> None:
        self.setObjectName("submissionSettingsDialog")
        self.setWindowTitle("Submission & AI Settings")
        self.setMinimumWidth(500)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        title = QLabel("Submission & AI", self)
        title.setObjectName("dialogTitle")
        title.setProperty("labelType", "heading")
        outer.addWidget(title)

        description = QLabel(
            "Configure the Ollama endpoint used for assistive handwriting transcription. "
            "The original submitted PDF remains authoritative evidence.",
            self,
        )
        description.setObjectName("dialogDescription")
        description.setWordWrap(True)
        description.setStyleSheet("color: #667085;")
        outer.addWidget(description)

        form_host = QWidget(self)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.endpoint_edit = QLineEdit(form_host)
        self.endpoint_edit.setObjectName("ollamaEndpointEdit")
        self.endpoint_edit.setPlaceholderText(DEFAULT_UI_OLLAMA_URL)
        self.endpoint_edit.setClearButtonEnabled(True)
        form.addRow("Ollama endpoint", self.endpoint_edit)

        self.model_edit = QLineEdit(form_host)
        self.model_edit.setObjectName("handwritingModelEdit")
        self.model_edit.setPlaceholderText(DEFAULT_HANDWRITING_MODEL)
        self.model_edit.setClearButtonEnabled(True)
        form.addRow("Model", self.model_edit)

        outer.addWidget(form_host)

        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.setSpacing(10)
        self.test_button = QPushButton("Test Connection", self)
        self.test_button.setObjectName("testOllamaButton")
        self.test_button.setProperty("buttonRole", "secondary")
        self.test_button.clicked.connect(self._request_connection_test)
        test_row.addWidget(self.test_button)

        self.connection_status = QLabel("Not tested", self)
        self.connection_status.setObjectName("ollamaConnectionStatus")
        self.connection_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.connection_status.setStyleSheet("color: #667085;")
        test_row.addWidget(self.connection_status, 1)
        outer.addLayout(test_row)

        note = QLabel(
            "The app does not start or manage the SSH tunnel. Cached transcription can still "
            "be viewed when Ollama is unavailable.",
            self,
        )
        note.setObjectName("connectionNote")
        note.setWordWrap(True)
        note.setStyleSheet("color: #98A2B3; font-size: 11px;")
        outer.addWidget(note)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        save_button = self.button_box.button(QDialogButtonBox.Save)
        if save_button is not None:
            save_button.setProperty("buttonRole", "primary")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        outer.addWidget(self.button_box)

    def current_settings(self) -> SubmissionInferenceSettings:
        """Return validated values currently displayed in the dialog."""

        return SubmissionInferenceSettings(
            self.endpoint_edit.text(),
            self.model_edit.text(),
        ).normalized()

    # Backwards-friendly alias for generic dialog consumers.
    def get_config(self) -> dict:
        return self.current_settings().as_dict()

    def set_settings(self, value: SubmissionInferenceSettings) -> None:
        normalized = value.normalized()
        self.endpoint_edit.setText(normalized.base_url)
        self.model_edit.setText(normalized.model)
        self._clear_validation_error()

    def reset_to_defaults(self) -> None:
        self.set_settings(SubmissionInferenceSettings())
        self.connection_status.setText("Not tested")
        self.connection_status.setStyleSheet("color: #667085;")

    def set_testing_state(self, testing: bool) -> None:
        testing = bool(testing)
        self.test_button.setEnabled(not testing)
        self.endpoint_edit.setEnabled(not testing)
        self.model_edit.setEnabled(not testing)
        self.connection_status.setText("Testing connection…" if testing else "Not tested")
        self.connection_status.setStyleSheet("color: #3B5CCC;" if testing else "color: #667085;")

    def set_connection_test_result(self, result: Any) -> None:
        """Display a ``TranscriptionPreflightResult``-like object."""

        self.set_testing_state(False)
        ok = bool(getattr(result, "ok", False))
        model = str(getattr(result, "model", "") or self.model_edit.text()).strip()
        if ok:
            capabilities = list(getattr(result, "capabilities", []) or [])
            suffix = " · Vision" if "vision" in capabilities else ""
            self.connection_status.setText(f"Connected · {model}{suffix}")
            self.connection_status.setStyleSheet("color: #2E7D5B; font-weight: 600;")
            return

        message = str(getattr(result, "error_message", "") or "Connection test failed.")
        self.connection_status.setText(message)
        self.connection_status.setStyleSheet("color: #B94A48; font-weight: 600;")

    def set_connection_test_failure(self, message: str) -> None:
        self.set_testing_state(False)
        self.connection_status.setText(str(message or "Connection test failed."))
        self.connection_status.setStyleSheet("color: #B94A48; font-weight: 600;")

    def _request_connection_test(self) -> None:
        try:
            value = self.current_settings()
        except ValueError as exc:
            self._show_validation_error(str(exc))
            return
        self._clear_validation_error()
        self.set_testing_state(True)
        self.test_connection_requested.emit(value)

    def accept(self) -> None:  # noqa: D401 - Qt override
        """Validate, persist settings, and close the dialog."""

        try:
            value = self.current_settings()
        except ValueError as exc:
            self._show_validation_error(str(exc))
            return

        normalized = save_submission_settings(value, self._settings_store)
        self._last_valid_settings = normalized
        self.settings_saved.emit(normalized)
        super().accept()

    def _show_validation_error(self, message: str) -> None:
        self.connection_status.setText(str(message))
        self.connection_status.setStyleSheet("color: #B94A48; font-weight: 600;")

    def _clear_validation_error(self) -> None:
        # Preserve a useful successful/failed connection result; only clear an
        # obvious validation state when values are programmatically reset.
        if not self.connection_status.text():
            self.connection_status.setText("Not tested")
            self.connection_status.setStyleSheet("color: #667085;")


__all__ = [
    "DEFAULT_UI_OLLAMA_URL",
    "SETTINGS_APPLICATION",
    "SETTINGS_ENDPOINT_KEY",
    "SETTINGS_GROUP",
    "SETTINGS_MODEL_KEY",
    "SETTINGS_ORGANIZATION",
    "SubmissionInferenceSettings",
    "SubmissionSettingsDialog",
    "load_submission_settings",
    "normalize_model_name",
    "normalize_ollama_endpoint",
    "save_submission_settings",
]
