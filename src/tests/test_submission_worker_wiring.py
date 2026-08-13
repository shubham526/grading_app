"""Structural tests for main-window worker lifecycle and stale-result guards."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
_SOURCE = _PATH.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _class():
    return next(
        node for node in _TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "RubricGrader"
    )


def _method(name):
    return next(
        node for node in _class().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _segment(name):
    return ast.get_source_segment(_SOURCE, _method(name)) or ""


class TestSubmissionWorkerWiring(unittest.TestCase):

    def test_window_uses_thread_pool_and_tracks_workers(self):
        init = _segment("__init__")
        self.assertIn("QThreadPool.globalInstance()", init)
        self.assertIn("self._submission_workers = {}", init)
        self.assertIn("self.active_submission_requests = {}", init)
        self.assertIn("self._latest_request_by_student = {}", init)

    def test_start_worker_connects_complete_worker_signal_contract(self):
        source = _segment("_start_submission_worker")
        for signal in (
            "started.connect",
            "progress.connect",
            "completed.connect",
            "failed.connect",
            "cancelled.connect",
            "finished.connect",
        ):
            with self.subTest(signal=signal):
                self.assertIn(signal, source)
        self.assertIn("submission_thread_pool.start(worker)", source)

    def test_latest_request_guard_is_operation_and_student_aware(self):
        source = _segment("_submission_request_is_latest")
        self.assertIn("_latest_folder_request_id", source)
        self.assertIn("_latest_connection_request_id", source)
        self.assertIn("_latest_request_by_student", source)
        self.assertIn("canonical_student_id", source)

    def test_completed_callback_checks_stale_guard_before_registration(self):
        source = _segment("_on_submission_worker_completed")
        guard_index = source.index("_submission_request_is_latest")
        registration_index = source.index("register_loaded_submissions")
        self.assertLess(guard_index, registration_index)
        self.assertIn("register_pdf_accommodation", source)

    def test_alice_job_can_finish_without_forcing_alice_into_current_view(self):
        source = _segment("register_pdf_accommodation")
        self.assertIn("active_id", source)
        self.assertIn("canonical_student_id", source)
        self.assertIn("self.current_submission = parsed", source)

    def test_settings_connection_test_uses_worker(self):
        source = _segment("_on_submission_test_connection_requested")
        self.assertIn("SubmissionOperation.TEST_OLLAMA", source)
        self.assertIn("_start_submission_worker", source)

    def test_test_connection_result_returns_to_open_dialog(self):
        source = _segment("_on_submission_worker_completed")
        self.assertIn("SubmissionOperation.TEST_OLLAMA.value", source)
        self.assertIn("set_connection_test_result", source)

    def test_worker_failures_do_not_open_modal_error_dialogs(self):
        source = _segment("_on_submission_worker_failed")
        self.assertNotIn("QMessageBox", source)
        self.assertIn("show_temporary_message", source)

    def test_finished_callback_releases_worker_references(self):
        source = _segment("_on_submission_worker_finished")
        self.assertIn("self._submission_workers.pop", source)
        self.assertIn("self.active_submission_requests.pop", source)
        self.assertIn("self._submission_request_meta.pop", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
