"""Commit-5 background submission worker tests.

No real Ollama server or GPU is required; worker dependencies are injected.
"""

import unittest
from unittest.mock import Mock

try:
    import PyQt5
    from PyQt5.QtCore import QCoreApplication
    _QT_AVAILABLE = not isinstance(PyQt5, Mock) and not isinstance(QCoreApplication, Mock)
except (ImportError, ModuleNotFoundError):
    QCoreApplication = None
    _QT_AVAILABLE = False


@unittest.skipUnless(_QT_AVAILABLE, "PyQt5 is required for Qt worker tests")
class TestSubmissionWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def _capture(self, worker):
        events = {"started": [], "progress": [], "completed": [], "failed": [], "cancelled": [], "finished": []}
        worker.signals.started.connect(lambda *args: events["started"].append(args))
        worker.signals.progress.connect(lambda *args: events["progress"].append(args))
        worker.signals.completed.connect(lambda *args: events["completed"].append(args))
        worker.signals.failed.connect(lambda *args: events["failed"].append(args))
        worker.signals.cancelled.connect(lambda *args: events["cancelled"].append(args))
        worker.signals.finished.connect(lambda *args: events["finished"].append(args))
        return events

    def test_normal_folder_operation_calls_controller_without_registering(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def __init__(self):
                self.calls = []
            def parse_normal_submissions(self, path, **kwargs):
                self.calls.append((path, kwargs))
                return {"alice": object()}

        controller = Controller()
        worker = SubmissionWorker(
            controller,
            SubmissionOperation.LOAD_NORMAL_SUBMISSIONS,
            request_id="job-1",
            parameters={"submissions_dir": "/tmp/submissions", "compile_pdf": False},
        )
        events = self._capture(worker)
        worker.run()
        self.assertEqual(controller.calls, [("/tmp/submissions", {"compile_pdf": False})])
        self.assertEqual(events["completed"][0][0:3], ("job-1", "", "load_normal_submissions"))
        self.assertEqual(set(events["completed"][0][3]), {"alice"})
        self.assertFalse(events["failed"])
        self.assertEqual(len(events["finished"]), 1)

    def test_generate_transcription_is_cache_first(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def __init__(self): self.kwargs = None
            def parse_pdf_accommodation(self, student_id, path, **kwargs):
                self.kwargs = (student_id, path, kwargs)
                return "parsed"

        class Backend: pass
        built = []
        def factory(**kwargs):
            built.append(kwargs)
            return Backend()

        controller = Controller()
        worker = SubmissionWorker(
            controller,
            SubmissionOperation.GENERATE_TRANSCRIPTION,
            student_id="alice",
            parameters={"pdf_path": "/tmp/a.pdf", "base_url": "http://127.0.0.1:11435", "model": "gemma4:31b"},
            backend_factory=factory,
        )
        events = self._capture(worker)
        worker.run()
        _, _, kwargs = controller.kwargs
        self.assertTrue(kwargs["transcribe_handwriting"])
        self.assertTrue(kwargs["reuse_cached_transcription"])
        self.assertIsInstance(kwargs["transcription_backend"], Backend)
        self.assertEqual(built, [{"base_url": "http://127.0.0.1:11435", "model": "gemma4:31b"}])
        self.assertEqual(events["completed"][0][3], "parsed")

    def test_refresh_transcription_forces_new_pass(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def parse_pdf_accommodation(self, student_id, path, **kwargs):
                self.kwargs = kwargs
                return "parsed"

        class Backend: pass
        controller = Controller()
        worker = SubmissionWorker(
            controller,
            SubmissionOperation.REFRESH_TRANSCRIPTION,
            student_id="alice",
            parameters={"pdf_path": "/tmp/a.pdf"},
            backend_factory=lambda **kwargs: Backend(),
        )
        worker.run()
        self.assertTrue(controller.kwargs["transcribe_handwriting"])
        self.assertFalse(controller.kwargs["reuse_cached_transcription"])

    def test_plain_pdf_load_never_starts_transcription(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def parse_pdf_accommodation(self, student_id, path, **kwargs):
                self.kwargs = kwargs
                return "parsed"

        controller = Controller()
        worker = SubmissionWorker(
            controller,
            SubmissionOperation.LOAD_PDF_ACCOMMODATION,
            student_id="alice",
            parameters={"pdf_path": "/tmp/a.pdf", "base_url": "http://unused"},
            backend_factory=lambda **kwargs: self.fail("backend must not be constructed"),
        )
        worker.run()
        self.assertFalse(controller.kwargs["transcribe_handwriting"])
        self.assertIsNone(controller.kwargs["transcription_backend"])

    def test_test_ollama_uses_force_preflight(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Backend:
            def __init__(self): self.force = None
            def preflight(self, *, force=False):
                self.force = force
                return {"ok": True}

        built = []
        def factory(**kwargs):
            backend = Backend()
            built.append((kwargs, backend))
            return backend

        worker = SubmissionWorker(
            None,
            SubmissionOperation.TEST_OLLAMA,
            request_id="probe",
            parameters={"base_url": "http://127.0.0.1:11435", "model": "gemma4:31b"},
            backend_factory=factory,
        )
        events = self._capture(worker)
        worker.run()
        self.assertEqual(
            built[0][0],
            {
                "base_url": "http://127.0.0.1:11435",
                "model": "gemma4:31b",
                "warm_model": False,
            },
        )
        self.assertTrue(built[0][1].force)
        self.assertEqual(events["completed"][0][3], {"ok": True})

    def test_exception_becomes_failed_signal_and_finished_still_emits(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def parse_normal_submissions(self, path, **kwargs):
                raise RuntimeError("compile exploded")

        worker = SubmissionWorker(
            Controller(),
            SubmissionOperation.LOAD_NORMAL_SUBMISSIONS,
            request_id="bad-job",
            parameters={"submissions_dir": "/tmp/submissions"},
        )
        events = self._capture(worker)
        worker.run()
        self.assertFalse(events["completed"])
        self.assertEqual(events["failed"][0][0:4], ("bad-job", "", "load_normal_submissions", "RuntimeError"))
        self.assertIn("compile exploded", events["failed"][0][4])
        self.assertEqual(len(events["finished"]), 1)

    def test_cancel_before_run_suppresses_execution(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def parse_normal_submissions(self, path, **kwargs):
                self.fail = True
                return {}

        controller = Controller()
        worker = SubmissionWorker(
            controller,
            SubmissionOperation.LOAD_NORMAL_SUBMISSIONS,
            request_id="cancelled-job",
            parameters={"submissions_dir": "/tmp/submissions"},
        )
        events = self._capture(worker)
        worker.cancel()
        worker.run()
        self.assertEqual(events["cancelled"], [("cancelled-job", "", "load_normal_submissions")])
        self.assertFalse(events["completed"])
        self.assertFalse(events["failed"])
        self.assertEqual(len(events["finished"]), 1)

    def test_request_id_is_preserved_for_stale_result_guard(self):
        from src.ui.workers.submission_worker import SubmissionOperation, SubmissionWorker

        class Controller:
            def parse_pdf_accommodation(self, student_id, path, **kwargs): return "alice-result"

        worker = SubmissionWorker(
            Controller(),
            SubmissionOperation.LOAD_PDF_ACCOMMODATION,
            student_id="alice",
            request_id="alice-request-42",
            parameters={"pdf_path": "/tmp/a.pdf"},
        )
        events = self._capture(worker)
        worker.run()
        self.assertEqual(events["completed"][0][0], "alice-request-42")
        self.assertEqual(events["completed"][0][1], "alice")

    def test_unknown_operation_is_rejected_early(self):
        from src.ui.workers.submission_worker import SubmissionWorker
        with self.assertRaises(ValueError):
            SubmissionWorker(object(), "not-a-real-operation")


if __name__ == "__main__":
    unittest.main()
