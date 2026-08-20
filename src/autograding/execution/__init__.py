"""Execution-backend contracts for v2.3.3 Commit 4.

No production backend capable of executing student code is included here yet.
Commit 5 will provide the first concrete isolated container backend.
"""

from .availability import (
    BackendAvailability,
    EXECUTION_AVAILABILITY_SCHEMA_VERSION,
    probe_backends,
)
from .base import (
    ALLOWED_BACKEND_SECURITY_PROFILES,
    BACKEND_SECURITY_PROFILE_HOST,
    BACKEND_SECURITY_PROFILE_ISOLATED,
    BACKEND_SECURITY_PROFILE_TEST_FAKE,
    ExecutionBackend,
)
from .result_protocol import (
    BACKEND_EXECUTION_RECORD_SCHEMA_VERSION,
    BackendExecutionRecord,
    NONTERMINAL_EXECUTION_STATUSES,
    TERMINAL_EXECUTION_STATUSES,
    validate_execution_result,
)


__all__ = [
    "ALLOWED_BACKEND_SECURITY_PROFILES",
    "BACKEND_EXECUTION_RECORD_SCHEMA_VERSION",
    "BACKEND_SECURITY_PROFILE_HOST",
    "BACKEND_SECURITY_PROFILE_ISOLATED",
    "BACKEND_SECURITY_PROFILE_TEST_FAKE",
    "BackendAvailability",
    "BackendExecutionRecord",
    "EXECUTION_AVAILABILITY_SCHEMA_VERSION",
    "ExecutionBackend",
    "NONTERMINAL_EXECUTION_STATUSES",
    "TERMINAL_EXECUTION_STATUSES",
    "probe_backends",
    "validate_execution_result",
]
