"""Parse and validate the container-side structured pytest protocol."""

from copy import deepcopy
import json
from typing import Mapping

from ..errors import PytestResultProtocolError
from ..models import (
    TEST_STATUS_ERROR,
    TEST_STATUS_FAILED,
    TEST_STATUS_INFRASTRUCTURE_ERROR,
    TEST_STATUS_PASSED,
    TEST_STATUS_SKIPPED,
    TEST_STATUS_TIMEOUT,
    TEST_STATUS_XFAIL,
    TEST_STATUS_XPASS,
    TestResult,
)
from ..planner import ExecutionPlan
from .protocol import (
    DEFAULT_PYTEST_PROTOCOL_MAX_BYTES,
    PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION,
)


_RUNTIME_TO_MODEL_STATUS = {
    "passed": TEST_STATUS_PASSED,
    "failed": TEST_STATUS_FAILED,
    "error": TEST_STATUS_ERROR,
    "timeout": TEST_STATUS_TIMEOUT,
    "skipped": TEST_STATUS_SKIPPED,
    "xfail": TEST_STATUS_XFAIL,
    "xpass": TEST_STATUS_XPASS,
    "infrastructure_error": TEST_STATUS_INFRASTRUCTURE_ERROR,
    "pending": TEST_STATUS_INFRASTRUCTURE_ERROR,
}


def load_pytest_protocol_bytes(data, max_bytes=DEFAULT_PYTEST_PROTOCOL_MAX_BYTES):
    if not isinstance(data, (bytes, bytearray)):
        raise PytestResultProtocolError("pytest result protocol must be bytes")
    raw = bytes(data)
    if len(raw) > int(max_bytes):
        raise PytestResultProtocolError(
            "pytest result protocol exceeds the %d-byte safety limit" % int(max_bytes)
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PytestResultProtocolError("pytest result protocol is not valid UTF-8 JSON") from exc
    return validate_pytest_protocol_payload(payload)


def validate_pytest_protocol_payload(payload):
    if not isinstance(payload, Mapping):
        raise PytestResultProtocolError("pytest result protocol must be a JSON object")
    version = str(payload.get("schema_version") or "")
    if version != PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION:
        raise PytestResultProtocolError(
            "Unsupported pytest result protocol %r; expected %r"
            % (version, PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION)
        )
    if str(payload.get("runner") or "") != "pytest":
        raise PytestResultProtocolError("pytest result protocol runner must be 'pytest'")
    tests = payload.get("tests")
    if not isinstance(tests, list):
        raise PytestResultProtocolError("pytest result protocol tests must be a list")
    seen = set()
    for item in tests:
        if not isinstance(item, Mapping):
            raise PytestResultProtocolError("pytest result entries must be objects")
        test_id = str(item.get("test_id") or "").strip()
        if not test_id:
            raise PytestResultProtocolError("pytest result entry is missing test_id")
        if test_id in seen:
            raise PytestResultProtocolError("pytest result protocol contains duplicate test_id %r" % test_id)
        seen.add(test_id)
        status = str(item.get("status") or "").strip().lower()
        if status not in _RUNTIME_TO_MODEL_STATUS:
            raise PytestResultProtocolError(
                "pytest result for %r has unsupported status %r" % (test_id, status)
            )
    return deepcopy(dict(payload))


def protocol_test_results(payload, plan: ExecutionPlan):
    payload = validate_pytest_protocol_payload(payload)
    by_id = {str(item.get("test_id")): item for item in payload.get("tests") or ()}
    expected_ids = [test.test_id for test in plan.config.tests]
    unknown = sorted(set(by_id) - set(expected_ids))
    if unknown:
        raise PytestResultProtocolError(
            "pytest protocol returned unknown configured test ID(s): %s" % ", ".join(unknown)
        )

    collection_errors = tuple(payload.get("collection_errors") or ())
    selection_errors = tuple(payload.get("selection_errors") or ())
    student_preflight = tuple(payload.get("student_preflight_errors") or ())
    structural_error = bool(collection_errors or selection_errors or payload.get("runner_configuration_error") or payload.get("runner_internal_error"))

    results = []
    missing = []
    for definition in plan.config.tests:
        raw = by_id.get(definition.test_id)
        if raw is None:
            missing.append(definition.test_id)
            results.append(
                TestResult(
                    test_id=definition.test_id,
                    status=TEST_STATUS_INFRASTRUCTURE_ERROR,
                    visibility=definition.visibility,
                    group_id=definition.group_id,
                    display_name=definition.name,
                    message="Structured pytest output did not contain this configured test.",
                    points_possible=definition.points,
                    points_awarded=None,
                    metadata={"protocol_missing": True},
                )
            )
            continue

        status = _RUNTIME_TO_MODEL_STATUS[str(raw.get("status")).strip().lower()]
        if status == TEST_STATUS_INFRASTRUCTURE_ERROR or (
            status == "pending" and structural_error
        ):
            status = TEST_STATUS_INFRASTRUCTURE_ERROR
        elif str(raw.get("status")).strip().lower() == "pending":
            status = TEST_STATUS_INFRASTRUCTURE_ERROR

        metadata = {
            "pytest_selector": raw.get("selector"),
            "pytest_nodeids": list(raw.get("nodeids") or ()),
            "pytest_item_count": int(raw.get("item_count") or 0),
            "stdout_truncated": bool(raw.get("stdout_truncated", False)),
            "stderr_truncated": bool(raw.get("stderr_truncated", False)),
            "timeout_seconds": raw.get("timeout_seconds"),
        }
        results.append(
            TestResult(
                test_id=definition.test_id,
                status=status,
                visibility=definition.visibility,
                group_id=definition.group_id,
                display_name=definition.name,
                duration_ms=int(raw.get("duration_ms") or 0),
                message=raw.get("message"),
                traceback=raw.get("traceback"),
                stdout=raw.get("stdout") or "",
                stderr=raw.get("stderr") or "",
                points_possible=definition.points,
                points_awarded=None,
                metadata=metadata,
            )
        )

    diagnostics = {
        "missing_test_ids": missing,
        "collection_errors": [deepcopy(dict(item)) for item in collection_errors if isinstance(item, Mapping)],
        "selection_errors": [str(item) for item in selection_errors],
        "student_preflight_errors": [deepcopy(dict(item)) for item in student_preflight if isinstance(item, Mapping)],
        "runner_configuration_error": bool(payload.get("runner_configuration_error")),
        "runner_internal_error": payload.get("runner_internal_error"),
    }
    return tuple(results), diagnostics


__all__ = [
    "load_pytest_protocol_bytes",
    "protocol_test_results",
    "validate_pytest_protocol_payload",
]
