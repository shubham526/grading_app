"""Shared fixtures for v2.3.3 Commit 8 immutable run-history tests."""

import json
from pathlib import Path

from src.autograding.bundle_store import TestBundleStore
from src.autograding.execution.result_protocol import BackendExecutionRecord
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    ExecutionEnvironment,
    ExecutionResult,
    TestResult,
)
from src.autograding.planner import build_execution_plan
from src.autograding.scoring import score_pytest_run
from src.autograding.testing.protocol import PytestRunResult
from src.submissions.domain import ARTIFACT_ROLE_PRIMARY, ARTIFACT_TYPE_PYTHON, CandidateFile
from src.submissions.repository import SubmissionRepository


ASSESSMENT_ID = "LAB_PERSIST"
STUDENT_ID = "alice"
NOW = "2026-08-20T01:00:00Z"


def write_bundle(root, *, assessment_id=ASSESSMENT_ID, version="v1", max_points=10):
    root = Path(root)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": "1.0",
        "assessment_id": assessment_id,
        "language": "python",
        "runner_type": "pytest",
        "entrypoint": "main.py",
        "required_files": ["helpers.py"],
        "max_points": max_points,
        "tests": [
            {
                "test_id": "test_public",
                "name": "Public basic behavior",
                "visibility": "public",
                "points": 4,
            },
            {
                "test_id": "test_hidden",
                "name": "Hidden edge behavior",
                "visibility": "hidden",
                "points": max_points - 4,
            },
        ],
        "resource_limits": {
            "wall_timeout_seconds": 8,
            "memory_mb": 256,
            "cpu_count": 1,
            "pids_limit": 64,
            "stdout_max_bytes": 8192,
            "stderr_max_bytes": 8192,
            "network_enabled": False,
        },
        "metadata": {"version": version},
    }
    (root / "autograder.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (root / "tests" / "test_public.py").write_text(
        "def test_public():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "test_hidden.py").write_text(
        "def test_hidden():\n    assert True\n", encoding="utf-8"
    )
    return root


def create_submission(repository, source_root, *, student_id=STUDENT_ID, attempt=None, make_active=True, value=1):
    source_root = Path(source_root)
    source_root.mkdir(parents=True, exist_ok=True)
    main = source_root / "main.py"
    helper = source_root / "helpers.py"
    main.write_text("VALUE = %d\n" % value, encoding="utf-8")
    helper.write_text("def helper():\n    return %d\n" % value, encoding="utf-8")
    return repository.create_submission(
        assessment_id=ASSESSMENT_ID,
        student_id=student_id,
        files=[
            CandidateFile(
                source_path=str(main),
                original_filename="main.py",
                artifact_type=ARTIFACT_TYPE_PYTHON,
                role=ARTIFACT_ROLE_PRIMARY,
            ),
            CandidateFile(
                source_path=str(helper),
                original_filename="helpers.py",
                artifact_type=ARTIFACT_TYPE_PYTHON,
                role=ARTIFACT_ROLE_PRIMARY,
            ),
        ],
        make_active=make_active,
        attempt=attempt,
        imported_at="2026-08-20T00:30:00Z",
    )


def prepare_workspace(base, *, bundle_id="bundle_persist_v1", bundle_version="v1"):
    base = Path(base)
    workspace = base / "workspace"
    evidence = workspace / "submission_evidence"
    bundle_source = write_bundle(base / ("bundle_" + bundle_version), version=bundle_version)
    bundle_store = TestBundleStore(
        workspace,
        now_fn=lambda: "2026-08-20T00:40:00Z",
        bundle_id_factory=lambda: bundle_id,
    )
    imported = bundle_store.import_bundle(bundle_source, expected_assessment_id=ASSESSMENT_ID)
    submission_repository = SubmissionRepository(str(evidence))
    submission = create_submission(submission_repository, base / "submission_source")
    return workspace, submission_repository, bundle_store, imported.bundle, submission


def make_plan(submission_repository, bundle_store, bundle, *, run_id="agrun_persist_1", submission_id=None, created_at=NOW):
    return build_execution_plan(
        submission_repository,
        bundle_store,
        assessment_id=ASSESSMENT_ID,
        student_id=STUDENT_ID,
        bundle_id=bundle.reference.bundle_id,
        submission_id=submission_id,
        run_id=run_id,
        now_fn=lambda: created_at,
    )


def make_pytest_result(plan, *, hidden_status="failed", stdout="runner stdout\n", stderr="runner stderr\n", requires_review=False, review_reason=None):
    env = ExecutionEnvironment(
        environment_id="docker-env-commit8",
        backend="docker_pytest",
        language="python",
        interpreter_version="3.12.10",
        container_image="grading-app-python312-pytest:9.1.1",
        container_image_digest="sha256:" + ("a" * 64),
        metadata={"pytest_runner_sha256": "b" * 64},
    )
    execution = ExecutionResult(
        status=EXECUTION_STATUS_COMPLETED,
        exit_code=1 if hidden_status == "failed" else 0,
        started_at="2026-08-20T01:00:01Z",
        finished_at="2026-08-20T01:00:02Z",
        duration_ms=1000,
        stdout=stdout,
        stderr=stderr,
        metadata={"container_name": "grading-app-test"},
    )
    backend = BackendExecutionRecord(
        run_id=plan.run_id,
        backend_name="docker_pytest",
        environment=env,
        result=execution,
        recorded_at="2026-08-20T01:00:02Z",
        metadata={"cleanup_verified": True},
    )
    tests = (
        TestResult(
            test_id="test_public",
            status="passed",
            visibility="public",
            display_name="Public basic behavior",
            duration_ms=10,
            message=None,
            stdout="public output\n",
            points_possible=999,
            metadata={"pytest_nodeids": ["tests/test_public.py::test_public"]},
        ),
        TestResult(
            test_id="test_hidden",
            status=hidden_status,
            visibility="hidden",
            display_name="Hidden edge behavior",
            duration_ms=20,
            message="secret expected value was 42" if hidden_status == "failed" else None,
            traceback="SECRET TRACEBACK" if hidden_status == "failed" else None,
            stdout="SECRET HIDDEN STDOUT\n" if hidden_status == "failed" else "",
            stderr="SECRET HIDDEN STDERR\n" if hidden_status == "failed" else "",
            points_possible=999,
            metadata={"pytest_nodeids": ["tests/test_hidden.py::test_hidden"]},
        ),
    )
    return PytestRunResult(
        backend_record=backend,
        test_results=tests,
        pytest_exit_code=1 if hidden_status == "failed" else 0,
        pytest_version="9.1.1",
        collected_count=2,
        selected_count=2,
        requires_review=requires_review,
        review_reason=review_reason,
        metadata={"protocol_file_sha256": "c" * 64},
    )


def make_scored_result(plan, pytest_result):
    return score_pytest_run(plan.config, pytest_result)
