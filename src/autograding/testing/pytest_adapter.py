"""Host-side structured pytest orchestration and student-safe redaction."""

from copy import deepcopy
from hashlib import sha256
from typing import Mapping

from ..errors import PytestAdapterError, PytestResultProtocolError
from ..execution.base import ExecutionBackend
from ..models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_TIMEOUT,
    TEST_STATUS_INFRASTRUCTURE_ERROR,
    TEST_STATUS_TIMEOUT,
    TEST_VISIBILITY_HIDDEN,
    TEST_VISIBILITY_PUBLIC,
    TestResult,
)
from ..planner import ExecutionPlan
from .protocol import PytestRunResult
from .result_parser import protocol_test_results, validate_pytest_protocol_payload


def build_pytest_runtime_config(plan: ExecutionPlan):
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be an ExecutionPlan")
    if plan.config.runner_type != "pytest":
        raise PytestAdapterError("Commit 6 pytest adapter requires runner_type='pytest'")

    tests = []
    for definition in plan.config.tests:
        selector = definition.metadata.get("pytest_nodeid") or definition.test_id
        tests.append(
            {
                "test_id": definition.test_id,
                "selector": str(selector),
                "visibility": definition.visibility,
                "group_id": definition.group_id,
                "display_name": definition.name,
                "timeout_seconds": definition.timeout_seconds,
            }
        )
    return {
        "schema_version": "1.0",
        "assessment_id": plan.assessment_id,
        "run_id": plan.run_id,
        "tests": tests,
        "max_capture_bytes": min(16384, plan.resource_limits.stdout_max_bytes, plan.resource_limits.stderr_max_bytes),
        "max_traceback_bytes": 32768,
    }


def _synthetic_results(plan, status, message, metadata=None):
    return tuple(
        TestResult(
            test_id=test.test_id,
            status=status,
            visibility=test.visibility,
            group_id=test.group_id,
            display_name=test.name,
            message=message,
            points_possible=test.points,
            points_awarded=None,
            metadata=dict(metadata or {}),
        )
        for test in plan.config.tests
    )


def execute_pytest_plan(plan: ExecutionPlan, backend: ExecutionBackend) -> PytestRunResult:
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be an ExecutionPlan")
    if not isinstance(backend, ExecutionBackend):
        raise TypeError("backend must be an ExecutionBackend")
    if plan.config.runner_type != "pytest":
        raise PytestAdapterError("Execution plan is not configured for pytest")

    record = backend.run(plan)
    execution = record.result

    if execution.status == EXECUTION_STATUS_TIMEOUT:
        return PytestRunResult(
            backend_record=record,
            test_results=_synthetic_results(
                plan,
                TEST_STATUS_TIMEOUT,
                "The isolated pytest run exceeded the overall wall-clock timeout.",
                {"run_level_timeout": True},
            ),
            pytest_exit_code=None,
            pytest_version=None,
            requires_review=True,
            review_reason="Overall pytest wall-clock timeout; exact test attribution is unavailable.",
            metadata={"run_level_timeout": True},
        )

    if execution.status != EXECUTION_STATUS_COMPLETED:
        return PytestRunResult(
            backend_record=record,
            test_results=_synthetic_results(
                plan,
                TEST_STATUS_INFRASTRUCTURE_ERROR,
                execution.error_message or "Isolated pytest execution did not complete cleanly.",
                {"execution_status": execution.status},
            ),
            pytest_exit_code=execution.exit_code,
            pytest_version=None,
            requires_review=True,
            review_reason=execution.error_message or "Isolated pytest execution failure.",
            metadata={"execution_status": execution.status},
        )

    raw_payload = execution.metadata.get("pytest_protocol")
    if not isinstance(raw_payload, Mapping):
        return PytestRunResult(
            backend_record=record,
            test_results=_synthetic_results(
                plan,
                TEST_STATUS_INFRASTRUCTURE_ERROR,
                "Docker pytest execution completed without a valid structured result protocol.",
                {"protocol_missing": True},
            ),
            pytest_exit_code=execution.exit_code,
            pytest_version=None,
            requires_review=True,
            review_reason="Structured pytest result protocol is missing.",
            metadata={"protocol_missing": True},
        )

    try:
        payload = validate_pytest_protocol_payload(raw_payload)
        test_results, diagnostics = protocol_test_results(payload, plan)
    except PytestResultProtocolError as exc:
        return PytestRunResult(
            backend_record=record,
            test_results=_synthetic_results(
                plan,
                TEST_STATUS_INFRASTRUCTURE_ERROR,
                "Structured pytest result protocol could not be validated.",
                {"protocol_error": str(exc)},
            ),
            pytest_exit_code=execution.exit_code,
            pytest_version=None,
            requires_review=True,
            review_reason=str(exc),
            metadata={"protocol_error": str(exc)},
        )

    review_reasons = []
    if diagnostics["missing_test_ids"]:
        review_reasons.append("missing configured test results")
    if diagnostics["selection_errors"]:
        review_reasons.append("pytest test-selection errors")
    if diagnostics["collection_errors"]:
        review_reasons.append("pytest collection errors")
    if diagnostics["runner_configuration_error"]:
        review_reasons.append("pytest runner configuration error")
    if diagnostics["runner_internal_error"]:
        review_reasons.append("pytest runner internal error")

    return PytestRunResult(
        backend_record=record,
        test_results=test_results,
        pytest_exit_code=payload.get("pytest_exit_code"),
        pytest_version=payload.get("pytest_version"),
        collected_count=int(payload.get("collected_count") or 0),
        selected_count=int(payload.get("selected_count") or 0),
        deselected_count=int(payload.get("deselected_count") or 0),
        collection_errors=tuple(diagnostics["collection_errors"]),
        selection_errors=tuple(diagnostics["selection_errors"]),
        student_preflight_errors=tuple(diagnostics["student_preflight_errors"]),
        requires_review=bool(review_reasons),
        review_reason="; ".join(review_reasons) if review_reasons else None,
        metadata={
            "pytest_protocol_schema": payload.get("schema_version"),
            "student_preflight_error": bool(diagnostics["student_preflight_errors"]),
        },
    )


def redact_test_result_for_student(test_result: TestResult, reporting_policy=None) -> TestResult:
    if not isinstance(test_result, TestResult):
        raise TypeError("test_result must be a TestResult")
    policy = dict(reporting_policy or {})
    show_public_details = bool(policy.get("show_public_test_details", True))
    show_hidden_names = bool(policy.get("show_hidden_test_names_to_students", False))

    if test_result.visibility == TEST_VISIBILITY_PUBLIC:
        if show_public_details:
            return TestResult.from_dict(test_result.to_dict())
        return TestResult(
            test_id=test_result.test_id,
            status=test_result.status,
            visibility=test_result.visibility,
            group_id=test_result.group_id,
            display_name=test_result.display_name,
            duration_ms=test_result.duration_ms,
            message=None,
            traceback=None,
            stdout="",
            stderr="",
            points_possible=test_result.points_possible,
            points_awarded=test_result.points_awarded,
            metadata={"student_safe_redacted": True},
        )

    if test_result.visibility != TEST_VISIBILITY_HIDDEN:
        raise PytestAdapterError("Unsupported test visibility %r" % test_result.visibility)

    display_name = test_result.display_name if show_hidden_names else "Hidden test"
    generic_message = "Hidden test %s." % (
        "passed" if test_result.status == "passed" else "did not pass"
    )
    opaque_test_id = "hidden_%s" % sha256(
        test_result.test_id.encode("utf-8")
    ).hexdigest()[:12]
    return TestResult(
        test_id=opaque_test_id,
        status=test_result.status,
        visibility=test_result.visibility,
        group_id=None,
        display_name=display_name,
        duration_ms=test_result.duration_ms,
        message=generic_message,
        traceback=None,
        stdout="",
        stderr="",
        points_possible=test_result.points_possible,
        points_awarded=test_result.points_awarded,
        metadata={"student_safe_redacted": True, "hidden_test": True},
    )


def student_safe_test_results(run_result: PytestRunResult, reporting_policy=None):
    if not isinstance(run_result, PytestRunResult):
        raise TypeError("run_result must be a PytestRunResult")
    return tuple(
        redact_test_result_for_student(item, reporting_policy)
        for item in run_result.test_results
    )


def student_safe_pytest_summary(run_result: PytestRunResult, reporting_policy=None):
    """Return a deliberately narrow student-facing summary with no backend evidence."""

    tests = student_safe_test_results(run_result, reporting_policy)
    return {
        "pytest_exit_code": run_result.pytest_exit_code,
        "tests": [item.to_dict() for item in tests],
        "test_count": len(tests),
    }


__all__ = [
    "build_pytest_runtime_config",
    "execute_pytest_plan",
    "redact_test_result_for_student",
    "student_safe_test_results",
    "student_safe_pytest_summary",
]
