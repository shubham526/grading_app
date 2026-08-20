"""Structured pytest execution support for v2.3.3 Commit 6."""

from .protocol import (
    DEFAULT_PYTEST_PROTOCOL_MAX_BYTES,
    PYTEST_RESULT_FILENAME,
    PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION,
    PYTEST_RUNTIME_CONFIG_FILENAME,
    PytestRunResult,
)
from .pytest_adapter import (
    build_pytest_runtime_config,
    execute_pytest_plan,
    redact_test_result_for_student,
    student_safe_test_results,
    student_safe_pytest_summary,
)
from .result_parser import (
    load_pytest_protocol_bytes,
    protocol_test_results,
    validate_pytest_protocol_payload,
)

__all__ = [
    "DEFAULT_PYTEST_PROTOCOL_MAX_BYTES",
    "PYTEST_RESULT_FILENAME",
    "PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION",
    "PYTEST_RUNTIME_CONFIG_FILENAME",
    "PytestRunResult",
    "build_pytest_runtime_config",
    "execute_pytest_plan",
    "load_pytest_protocol_bytes",
    "protocol_test_results",
    "redact_test_result_for_student",
    "student_safe_test_results",
    "student_safe_pytest_summary",
    "validate_pytest_protocol_payload",
]
