"""Background Qt worker for v2.3.3 programming autograding."""

from __future__ import annotations

from enum import Enum
import threading
import uuid
from typing import Any, Dict, Mapping, Optional

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from src.autograding.service import AutogradingService


class AutogradingOperation(str, Enum):
    GRADE_ONE = "grade_one"
    GRADE_BATCH = "grade_batch"
    CHECK_RUNTIME = "check_runtime"


def new_autograding_request_id() -> str:
    return uuid.uuid4().hex


class AutogradingWorkerSignals(QObject):
    started = pyqtSignal(str, str)
    progress = pyqtSignal(str, int, int, str, str)
    completed = pyqtSignal(str, str, object)
    failed = pyqtSignal(str, str, str, str)
    cancelled = pyqtSignal(str, str)
    finished = pyqtSignal(str, str)


class AutogradingWorker(QRunnable):
    """Run grading or runtime-availability work off the GUI thread.

    Cancellation is cooperative.  A batch stops before the next student; the
    currently running Docker container is allowed to reach its configured
    timeout/cleanup boundary so the worker never bypasses Commit-5 cleanup.
    """

    def __init__(
        self,
        service: AutogradingService,
        operation: Any,
        *,
        parameters: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        if not isinstance(service, AutogradingService):
            raise TypeError("service must be AutogradingService")
        self.service = service
        try:
            self.operation = (
                operation
                if isinstance(operation, AutogradingOperation)
                else AutogradingOperation(str(operation))
            )
        except ValueError as exc:
            raise ValueError("Unknown autograding worker operation %r" % operation) from exc
        self.parameters: Dict[str, Any] = dict(parameters or {})
        self.request_id = str(request_id or new_autograding_request_id())
        self.signals = AutogradingWorkerSignals()
        self._cancel_event = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @pyqtSlot()
    def run(self) -> None:
        op = self.operation.value
        self.signals.started.emit(self.request_id, op)
        try:
            if self.is_cancelled:
                self.signals.cancelled.emit(self.request_id, op)
                return
            if self.operation == AutogradingOperation.GRADE_ONE:
                payload = self._grade_one()
            elif self.operation == AutogradingOperation.GRADE_BATCH:
                payload = self._grade_batch()
            else:
                payload = self._check_runtime()
            if self.is_cancelled and self.operation in (
                AutogradingOperation.GRADE_ONE,
                AutogradingOperation.CHECK_RUNTIME,
            ):
                self.signals.cancelled.emit(self.request_id, op)
                return
            self.signals.completed.emit(self.request_id, op, payload)
        except Exception as exc:
            self.signals.failed.emit(
                self.request_id,
                op,
                type(exc).__name__,
                str(exc) or type(exc).__name__,
            )
        finally:
            self.signals.finished.emit(self.request_id, op)

    def _grade_one(self):
        required = ("assessment_id", "student_id", "bundle_id")
        missing = [name for name in required if not self.parameters.get(name)]
        if missing:
            raise ValueError("Missing grade-one parameters: %s" % ", ".join(missing))
        return self.service.grade_submission(
            self.parameters["assessment_id"],
            self.parameters["student_id"],
            self.parameters["bundle_id"],
            submission_id=self.parameters.get("submission_id"),
            image=self.parameters.get("image"),
            metadata=self.parameters.get("metadata"),
        )

    def _check_runtime(self):
        return self.service.runtime_availability(self.parameters.get("image"))

    def _grade_batch(self):
        required = ("assessment_id", "student_ids", "bundle_id")
        missing = [name for name in required if not self.parameters.get(name)]
        if missing:
            raise ValueError("Missing batch parameters: %s" % ", ".join(missing))

        def progress(index, total, student_id, status):
            self.signals.progress.emit(
                self.request_id,
                int(index),
                int(total),
                str(student_id),
                str(status),
            )

        return self.service.grade_batch(
            self.parameters["assessment_id"],
            self.parameters["student_ids"],
            self.parameters["bundle_id"],
            image=self.parameters.get("image"),
            cancel_check=lambda: self.is_cancelled,
            progress_callback=progress,
            metadata=self.parameters.get("metadata"),
        )


__all__ = [
    "AutogradingOperation",
    "AutogradingWorker",
    "AutogradingWorkerSignals",
    "new_autograding_request_id",
]
