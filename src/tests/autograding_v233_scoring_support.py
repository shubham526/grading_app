"""Test helpers for v2.3.3 Commit 7 deterministic scoring tests."""

from datetime import datetime, timezone

from src.autograding.config import AutogradingConfig
from src.autograding.execution.availability import BackendAvailability
from src.autograding.execution.result_protocol import BackendExecutionRecord
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    ExecutionEnvironment,
    ExecutionResult,
    TestResult,
)
from src.autograding.testing.protocol import PytestRunResult


_NOW = "2026-08-20T00:00:00+00:00"


def make_backend_record(run_id="agrun_scoring_test"):
    return BackendExecutionRecord(
        run_id=run_id,
        backend_name="test_backend",
        environment=ExecutionEnvironment(
            environment_id="env_scoring_test",
            backend="test_backend",
            language="python",
            interpreter_version="3.12.0",
        ),
        result=ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=0,
            started_at=_NOW,
            finished_at=_NOW,
            duration_ms=1,
        ),
        recorded_at=_NOW,
    )


def make_run(config, statuses, requires_review=False, review_reason=None, metadata_by_test=None):
    metadata_by_test = metadata_by_test or {}
    if set(statuses) != {item.test_id for item in config.tests}:
        raise ValueError("statuses must include exactly every configured test")
    results = []
    for test in config.tests:
        results.append(
            TestResult(
                test_id=test.test_id,
                status=statuses[test.test_id],
                visibility=test.visibility,
                group_id=test.group_id,
                display_name=test.name,
                points_possible=test.points,
                points_awarded=None,
                metadata=metadata_by_test.get(test.test_id, {}),
            )
        )
    return PytestRunResult(
        backend_record=make_backend_record(),
        test_results=tuple(results),
        pytest_exit_code=0,
        pytest_version="9.1.1",
        collected_count=len(results),
        selected_count=len(results),
        requires_review=requires_review,
        review_reason=review_reason,
    )
