from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
import zipfile

from src.submissions.domain import ARTIFACT_ROLE_SOURCE, ARTIFACT_TYPE_ZIP, CandidateFile
from src.submissions.latex_project.errors import LatexProjectIntegrityError
from src.submissions.repository import SubmissionRepository


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "ui/workers/submission_import_worker.py"


class _DummySignal:
    def emit(self, *args, **kwargs):
        return None

    def connect(self, *args, **kwargs):
        return None


class _QObject:
    def __init__(self, *args, **kwargs):
        pass


class _QRunnable:
    def __init__(self, *args, **kwargs):
        pass

    def setAutoDelete(self, value):
        self.auto_delete = bool(value)


def _pyqt_signal(*args, **kwargs):
    return _DummySignal()


def _pyqt_slot(*args, **kwargs):
    def decorate(function):
        return function
    return decorate


def _load_worker_module():
    pyqt5 = types.ModuleType("PyQt5")
    qtcore = types.ModuleType("PyQt5.QtCore")
    qtcore.QObject = _QObject
    qtcore.QRunnable = _QRunnable
    qtcore.pyqtSignal = _pyqt_signal
    qtcore.pyqtSlot = _pyqt_slot
    previous_pyqt = sys.modules.get("PyQt5")
    previous_qtcore = sys.modules.get("PyQt5.QtCore")
    sys.modules["PyQt5"] = pyqt5
    sys.modules["PyQt5.QtCore"] = qtcore
    try:
        spec = importlib.util.spec_from_file_location("commit7_submission_import_worker", WORKER_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_pyqt is None:
            sys.modules.pop("PyQt5", None)
        else:
            sys.modules["PyQt5"] = previous_pyqt
        if previous_qtcore is None:
            sys.modules.pop("PyQt5.QtCore", None)
        else:
            sys.modules["PyQt5.QtCore"] = previous_qtcore


WORKER = _load_worker_module()


class _Student:
    def __init__(self, student_id):
        self.student_id = student_id
        self.student_name = student_id


class TestLatexProjectRecoveryWorkerV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repository = SubmissionRepository(str(self.root / "evidence"))
        archive_path = self.root / "alice.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "main.tex",
                r"\documentclass{article}\begin{document}A\end{document}",
            )
        self.submission = self.repository.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[CandidateFile(
                source_path=str(archive_path),
                original_filename=archive_path.name,
                artifact_type=ARTIFACT_TYPE_ZIP,
                role=ARTIFACT_ROLE_SOURCE,
            )],
            metadata={"latex_project_root": "main.tex"},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _worker(self):
        return WORKER.SubmissionImportWorker(
            self.repository,
            "PS1",
            [_Student("alice")],
            WORKER.SubmissionImportOperation.RECOVER_LATEX_PROJECT,
            parameters={
                "student_id": "alice",
                "root_relative_path": "main.tex",
                "question_ids": ["Q1"],
            },
        )

    def test_recovery_success_returns_existing_submission_and_parsed_evidence(self):
        parsed = object()
        worker = self._worker()
        with mock.patch.object(WORKER, "parse_canonical_submission", return_value=parsed) as parser:
            payload = worker._execute()
        self.assertEqual(payload["submission"].submission_id, self.submission.submission_id)
        self.assertIs(payload["parsed_by_student"]["alice"], parsed)
        self.assertEqual(payload["latex_project_diagnostics"], {})
        self.assertTrue(parser.call_args.kwargs["latex_project_force_recompile"])

    def test_integrity_failure_is_structured_and_not_marked_recoverable(self):
        worker = self._worker()
        with mock.patch.object(
            WORKER,
            "parse_canonical_submission",
            side_effect=LatexProjectIntegrityError("Stored ZIP SHA-256 does not match provenance"),
        ):
            payload = worker._execute()
        diagnostic = payload["latex_project_diagnostics"]["alice"]
        self.assertEqual(diagnostic["status"], "integrity_failed")
        self.assertEqual(diagnostic["error_code"], "latex_project_integrity_failure")
        self.assertFalse(diagnostic["recoverable"])
        self.assertIn("SHA-256", diagnostic["error_message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
