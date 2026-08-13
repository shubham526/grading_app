"""Tests for Submission & AI settings persistence/dialog behavior."""

import os
import tempfile
import unittest
from unittest.mock import Mock

try:
    import PyQt5
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QApplication
    _QT_AVAILABLE = (
        not isinstance(PyQt5, Mock)
        and not isinstance(QApplication, Mock)
        and not isinstance(QSettings, Mock)
    )
except (ImportError, ModuleNotFoundError):
    QApplication = None
    QSettings = None
    _QT_AVAILABLE = False


@unittest.skipUnless(_QT_AVAILABLE, "PyQt5 is required for settings-dialog tests")
class TestSubmissionSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings_path = os.path.join(self.tempdir.name, "settings.ini")
        self.store = QSettings(self.settings_path, QSettings.IniFormat)
        self.store.clear()

    def tearDown(self):
        self.store.clear()
        self.store.sync()
        self.tempdir.cleanup()

    def test_ui_defaults_target_mac_tunnel_and_production_model(self):
        from src.ui.dialogs.submission_settings import (
            DEFAULT_UI_OLLAMA_URL,
            SubmissionInferenceSettings,
        )
        value = SubmissionInferenceSettings().normalized()
        self.assertEqual(DEFAULT_UI_OLLAMA_URL, "http://127.0.0.1:11435")
        self.assertEqual(value.base_url, "http://127.0.0.1:11435")
        self.assertEqual(value.model, "gemma4:31b")

    def test_endpoint_normalization_removes_trailing_slash(self):
        from src.ui.dialogs.submission_settings import normalize_ollama_endpoint
        self.assertEqual(
            normalize_ollama_endpoint("  http://127.0.0.1:11435/  "),
            "http://127.0.0.1:11435",
        )

    def test_endpoint_rejects_non_http_and_embedded_credentials(self):
        from src.ui.dialogs.submission_settings import normalize_ollama_endpoint
        for bad in ("127.0.0.1:11435", "ssh://host:11434", "http://user:pw@host:11434"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_ollama_endpoint(bad)

    def test_save_load_round_trip_uses_qsettings(self):
        from src.ui.dialogs.submission_settings import (
            SubmissionInferenceSettings,
            load_submission_settings,
            save_submission_settings,
        )
        expected = SubmissionInferenceSettings("http://localhost:9999/", "gemma4:31b")
        saved = save_submission_settings(expected, self.store)
        loaded = load_submission_settings(self.store)
        self.assertEqual(saved, loaded)
        self.assertEqual(loaded.base_url, "http://localhost:9999")

    def test_invalid_persisted_values_fall_back_safely(self):
        from src.ui.dialogs.submission_settings import (
            DEFAULT_UI_OLLAMA_URL,
            SETTINGS_ENDPOINT_KEY,
            SETTINGS_GROUP,
            SETTINGS_MODEL_KEY,
            load_submission_settings,
        )
        self.store.beginGroup(SETTINGS_GROUP)
        self.store.setValue(SETTINGS_ENDPOINT_KEY, "garbage")
        self.store.setValue(SETTINGS_MODEL_KEY, "")
        self.store.endGroup()
        value = load_submission_settings(self.store)
        self.assertEqual(value.base_url, DEFAULT_UI_OLLAMA_URL)
        self.assertEqual(value.model, "gemma4:31b")

    def test_test_connection_emits_settings_but_performs_no_network_itself(self):
        from src.ui.dialogs.submission_settings import SubmissionSettingsDialog
        dialog = SubmissionSettingsDialog(settings=self.store)
        emitted = []
        dialog.test_connection_requested.connect(emitted.append)
        dialog.test_button.click()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].base_url, "http://127.0.0.1:11435")
        self.assertFalse(dialog.test_button.isEnabled())
        dialog.close()

    def test_preflight_result_updates_connection_status(self):
        from src.submissions.transcription.models import TranscriptionPreflightResult
        from src.ui.dialogs.submission_settings import SubmissionSettingsDialog
        dialog = SubmissionSettingsDialog(settings=self.store)
        result = TranscriptionPreflightResult(
            ok=True,
            backend="ollama",
            model="gemma4:31b",
            server_url="http://127.0.0.1:11435",
            capabilities=["completion", "vision"],
        )
        dialog.set_connection_test_result(result)
        self.assertIn("Connected", dialog.connection_status.text())
        self.assertIn("Vision", dialog.connection_status.text())
        self.assertTrue(dialog.test_button.isEnabled())
        dialog.close()

    def test_accept_validates_and_persists_without_storing_credentials(self):
        from src.ui.dialogs.submission_settings import (
            SETTINGS_GROUP,
            SubmissionSettingsDialog,
            load_submission_settings,
        )
        dialog = SubmissionSettingsDialog(settings=self.store)
        dialog.endpoint_edit.setText("http://localhost:11435/")
        dialog.model_edit.setText("gemma4:31b")
        dialog.accept()
        loaded = load_submission_settings(self.store)
        self.assertEqual(loaded.base_url, "http://localhost:11435")
        self.store.beginGroup(SETTINGS_GROUP)
        keys = set(self.store.allKeys())
        self.store.endGroup()
        self.assertEqual(keys, {"ollama_endpoint", "handwriting_model"})

    def test_invalid_accept_keeps_dialog_open_and_does_not_persist(self):
        from src.ui.dialogs.submission_settings import SubmissionSettingsDialog, load_submission_settings
        dialog = SubmissionSettingsDialog(settings=self.store)
        dialog.endpoint_edit.setText("not-a-url")
        dialog.accept()
        self.assertNotEqual(dialog.result(), dialog.Accepted)
        self.assertIn("absolute", dialog.connection_status.text())
        self.assertEqual(load_submission_settings(self.store).base_url, "http://127.0.0.1:11435")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
