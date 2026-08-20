"""Instructor/student-safe report builders for persisted v2.3.3 runs."""

from copy import deepcopy
from typing import Mapping

from .storage import StoredAutogradingRun
from .testing.pytest_adapter import redact_test_result_for_student


def _reporting_policy(stored, reporting_policy):
    if reporting_policy is not None:
        return reporting_policy
    config = stored.plan_snapshot.get("config") or {}
    policy = config.get("reporting_policy") if isinstance(config, Mapping) else None
    return deepcopy(policy) if isinstance(policy, Mapping) else None


def build_instructor_run_report(stored):
    """Return a JSON-ready full instructor view of one immutable run."""

    if not isinstance(stored, StoredAutogradingRun):
        raise TypeError("stored must be a StoredAutogradingRun")
    run = stored.run
    environment = stored.pytest_result.backend_record.environment
    return {
        "run_id": run.run_id,
        "assessment_id": run.assessment_id,
        "student_id": run.student_id,
        "submission_id": run.submission_id,
        "attempt": run.attempt,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "status": run.status,
        "review_status": run.review_status,
        "requires_review": run.requires_review,
        "review_reason": run.review_reason,
        "score": (run.score_summary.to_dict() if run.score_summary is not None else None),
        "tests": [item.to_dict() for item in run.test_results],
        "execution": run.execution_result.to_dict() if run.execution_result is not None else None,
        "provenance": run.provenance.to_dict(),
        "environment": environment.to_dict(),
        "bundle_reference": deepcopy(stored.plan_snapshot.get("bundle_reference") or {}),
        "pytest": {
            "exit_code": stored.pytest_result.pytest_exit_code,
            "version": stored.pytest_result.pytest_version,
            "collected_count": stored.pytest_result.collected_count,
            "selected_count": stored.pytest_result.selected_count,
            "deselected_count": stored.pytest_result.deselected_count,
            "collection_errors": [deepcopy(item) for item in stored.pytest_result.collection_errors],
            "selection_errors": list(stored.pytest_result.selection_errors),
            "student_preflight_errors": [
                deepcopy(item) for item in stored.pytest_result.student_preflight_errors
            ],
        },
    }


def build_student_safe_run_report(stored, reporting_policy=None):
    """Return a narrow student-facing report with hidden/runtime provenance removed."""

    if not isinstance(stored, StoredAutogradingRun):
        raise TypeError("stored must be a StoredAutogradingRun")
    policy = _reporting_policy(stored, reporting_policy)
    tests = tuple(
        redact_test_result_for_student(item, policy)
        for item in stored.scoring_result.test_results
    )
    summary = stored.scoring_result.score_summary
    return {
        "assessment_id": stored.run.assessment_id,
        "attempt": stored.run.attempt,
        "status": stored.run.status,
        "requires_review": summary.requires_review,
        "score": {
            "max_score": summary.max_score,
            "final_score": summary.final_score,
        },
        "tests": [item.to_dict() for item in tests],
        "test_count": len(tests),
    }


def build_history_report(references):
    """Return a compact instructor-facing chronological history table payload."""

    rows = []
    for ref in tuple(references or ()):
        rows.append(
            {
                "run_id": ref.run_id,
                "assessment_id": ref.assessment_id,
                "student_id": ref.student_id,
                "submission_id": ref.submission_id,
                "attempt": ref.attempt,
                "bundle_id": ref.bundle_id,
                "created_at": ref.created_at,
                "finished_at": ref.finished_at,
                "status": ref.status,
                "final_score": ref.final_score,
                "max_score": ref.max_score,
                "requires_review": ref.requires_review,
                "review_status": ref.review_status,
                "environment_id": ref.environment_id,
                "container_image_digest": ref.container_image_digest,
            }
        )
    return {"runs": rows, "run_count": len(rows)}


__all__ = [
    "build_history_report",
    "build_instructor_run_report",
    "build_student_safe_run_report",
]
