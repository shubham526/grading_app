"""Background workers for submission ingestion and transcription.

Commit 5 keeps slow submission work off the Qt GUI thread.  The public worker
API is intentionally small: callers create a :class:`SubmissionWorker`, submit
it to a ``QThreadPool``, and register returned parsed submissions on the UI
thread through ``SubmissionController``.
"""

from .submission_worker import (
    SubmissionOperation,
    SubmissionWorker,
    SubmissionWorkerSignals,
    new_request_id,
)

__all__ = [
    "SubmissionOperation",
    "SubmissionWorker",
    "SubmissionWorkerSignals",
    "new_request_id",
]
