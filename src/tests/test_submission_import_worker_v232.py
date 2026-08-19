"""Headless tests for Commit 7 import-worker orchestration.

A tiny fake PyQt5.QtCore surface lets the QRunnable be imported without a GUI
installation; the worker's backend methods are then exercised directly.
"""

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

from src.submissions import SubmissionRepository
from src.submissions.domain import VALIDATION_STATUS_READY


class _Signal:
    def connect(self, *args, **kwargs):
        return None

    def emit(self, *args, **kwargs):
        return None


class _QObject:
    pass


class _QRunnable:
    def setAutoDelete(self, value):
        self._auto_delete = bool(value)


def _pyqt_signal(*args, **kwargs):
    return _Signal()


def _pyqt_slot(*args, **kwargs):
    def decorator(function):
        return function
    return decorator


def _load_worker_module():
    qtcore = types.ModuleType("PyQt5.QtCore")
    qtcore.QObject = _QObject
    qtcore.QRunnable = _QRunnable
    qtcore.pyqtSignal = _pyqt_signal
    qtcore.pyqtSlot = _pyqt_slot
    pyqt = types.ModuleType("PyQt5")
    pyqt.QtCore = qtcore
    old_pyqt = sys.modules.get("PyQt5")
    old_qtcore = sys.modules.get("PyQt5.QtCore")
    sys.modules["PyQt5"] = pyqt
    sys.modules["PyQt5.QtCore"] = qtcore
    try:
        path = Path(__file__).resolve().parents[1] / "ui" / "workers" / "submission_import_worker.py"
        spec = importlib.util.spec_from_file_location("_submission_import_worker_v232", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if old_pyqt is None:
            sys.modules.pop("PyQt5", None)
        else:
            sys.modules["PyQt5"] = old_pyqt
        if old_qtcore is None:
            sys.modules.pop("PyQt5.QtCore", None)
        else:
            sys.modules["PyQt5.QtCore"] = old_qtcore


WORKER = _load_worker_module()


@dataclass
class StudentRecord:
    student_id: str
    student_name: str


class TestSubmissionImportWorkerV232(unittest.TestCase):
    def test_discover_and_commit_latex_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice_PS1.tex"
            source.write_text("Question 1\nAnswer A\n", encoding="utf-8")
            repository = SubmissionRepository(str(evidence))
            roster = [StudentRecord("alice", "Alice Example")]

            discover = WORKER.SubmissionImportWorker(
                repository,
                "PS1",
                roster,
                WORKER.SubmissionImportOperation.DISCOVER_FILES,
                parameters={"file_paths": [str(source)]},
            )
            payload = discover._execute()
            self.assertEqual(len(payload["candidates"]), 1)
            candidate = payload["candidates"][0]
            self.assertEqual(candidate.validation_status, VALIDATION_STATUS_READY)
            self.assertEqual(candidate.proposed_student_id, "alice")

            commit = WORKER.SubmissionImportWorker(
                repository,
                "PS1",
                roster,
                WORKER.SubmissionImportOperation.COMMIT,
                parameters={
                    "candidates": [candidate],
                    "question_ids": ["Q1"],
                    "evidence_dir": str(evidence),
                    "compile_pdf": False,
                },
            )
            result = commit._execute()
            commit_result = result["commit_result"]
            self.assertEqual(commit_result.batch.imported_count, 1)
            self.assertEqual(len(commit_result.submissions), 1)
            self.assertIn("alice", result["parsed_by_student"])
            self.assertEqual(
                result["parsed_by_student"]["alice"].answers_by_question,
                {"Q1": "Answer A"},
            )

    def test_python_submission_is_committed_but_never_executed_or_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice_lab.py"
            source.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
            repository = SubmissionRepository(str(evidence))
            roster = [StudentRecord("alice", "Alice Example")]

            discover = WORKER.SubmissionImportWorker(
                repository,
                "LAB1",
                roster,
                WORKER.SubmissionImportOperation.DISCOVER_FILES,
                parameters={"file_paths": [str(source)]},
            )
            candidate = discover._execute()["candidates"][0]
            commit = WORKER.SubmissionImportWorker(
                repository,
                "LAB1",
                roster,
                WORKER.SubmissionImportOperation.COMMIT,
                parameters={"candidates": [candidate]},
            )
            result = commit._execute()
            self.assertEqual(result["commit_result"].batch.imported_count, 1)
            self.assertEqual(result["parsed_by_student"], {})
            self.assertIn("alice", result["handler_pending"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
