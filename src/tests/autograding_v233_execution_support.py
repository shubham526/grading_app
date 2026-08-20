"""Test-only helpers for v2.3.3 Commit 4 execution-backend tests."""

from hashlib import sha256
from pathlib import Path
from typing import Iterable, Optional

from src.autograding.config import AutogradingConfig
from src.autograding.execution import (
    BACKEND_SECURITY_PROFILE_TEST_FAKE,
    BackendAvailability,
    ExecutionBackend,
)
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    AutogradingProvenance,
    ExecutionEnvironment,
    ExecutionResult,
    ResourceLimits,
    TestBundleReference,
    TestDefinition,
)
from src.autograding.planner import ExecutionPlan
from src.autograding.workspace import (
    ExecutionWorkspaceSpec,
    PlannedWorkspaceFile,
    WORKSPACE_NAMESPACE_GRADER,
    WORKSPACE_NAMESPACE_SUBMISSION,
)


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def build_test_execution_plan(
    root: Path,
    *,
    stdout_max_bytes: int = 1024,
    stderr_max_bytes: int = 1024,
) -> ExecutionPlan:
    root = Path(root)
    submission_dir = root / "submission_source"
    grader_dir = root / "grader_source"
    submission_dir.mkdir(parents=True, exist_ok=True)
    grader_dir.mkdir(parents=True, exist_ok=True)

    student_bytes = (
        b"from pathlib import Path\n"
        b"Path('STUDENT_CODE_WAS_EXECUTED').write_text('bad')\n"
    )
    grader_bytes = (
        b"from pathlib import Path\n"
        b"Path('GRADER_CODE_WAS_EXECUTED').write_text('bad')\n"
        b"def test_fixture():\n    assert True\n"
    )
    student_path = submission_dir / "main.py"
    grader_path = grader_dir / "tests.py"
    student_path.write_bytes(student_bytes)
    grader_path.write_bytes(grader_bytes)

    limits = ResourceLimits(
        wall_timeout_seconds=10,
        memory_mb=256,
        cpu_count=1,
        pids_limit=64,
        stdout_max_bytes=stdout_max_bytes,
        stderr_max_bytes=stderr_max_bytes,
        network_enabled=False,
    )
    config = AutogradingConfig(
        assessment_id="LAB1",
        max_points=10,
        tests=(
            TestDefinition(
                test_id="test_fixture",
                name="Fixture",
                visibility="hidden",
                points=10,
            ),
        ),
        entrypoint="main.py",
        resource_limits=limits,
    )

    submission_file = PlannedWorkspaceFile(
        namespace=WORKSPACE_NAMESPACE_SUBMISSION,
        logical_path="main.py",
        source_path=str(student_path),
        sha256=_digest(student_bytes),
        size_bytes=len(student_bytes),
        source_id="artifact-main",
    )
    grader_file = PlannedWorkspaceFile(
        namespace=WORKSPACE_NAMESPACE_GRADER,
        logical_path="tests/test_fixture.py",
        source_path=str(grader_path),
        sha256=_digest(grader_bytes),
        size_bytes=len(grader_bytes),
        source_id="tests/test_fixture.py",
    )
    workspace = ExecutionWorkspaceSpec(
        submission_files=(submission_file,),
        grader_files=(grader_file,),
        entrypoint="main.py",
    )
    bundle_reference = TestBundleReference(
        bundle_id="bundle_fixture",
        assessment_id="LAB1",
        bundle_sha256="b" * 64,
        config_sha256="c" * 64,
        imported_at="2026-08-19T20:00:00Z",
    )
    provenance = AutogradingProvenance(
        submission_id="sub_fixture",
        artifact_id="artifact-main",
        submission_sha256=_digest(student_bytes),
        bundle_id="bundle_fixture",
        bundle_sha256="b" * 64,
        config_sha256="c" * 64,
        runner_type="pytest",
        attempt=1,
    )
    return ExecutionPlan(
        run_id="agrun_fixture",
        created_at="2026-08-19T20:00:01Z",
        assessment_id="LAB1",
        student_id="student1",
        submission_id="sub_fixture",
        attempt=1,
        selected_submission_was_active=True,
        bundle_reference=bundle_reference,
        config=config,
        resource_limits=limits,
        workspace=workspace,
        provenance=provenance,
    )


class FakeExecutionBackend(ExecutionBackend):
    """Deterministic test backend that never reads or invokes planned files."""

    def __init__(
        self,
        *,
        available: bool = True,
        availability_reason: str = "fake backend disabled",
        backend_name: str = "fake_isolated",
        security_profile: str = BACKEND_SECURITY_PROFILE_TEST_FAKE,
        environment: Optional[ExecutionEnvironment] = None,
        results: Optional[Iterable[ExecutionResult]] = None,
    ):
        self._available = available
        self._availability_reason = availability_reason
        self._backend_name = backend_name
        self._security_profile = security_profile
        self._environment = environment
        self._results = list(results or ())
        self.execute_calls = []
        self.environment_calls = []
        self.probe_count = 0

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def security_profile(self) -> str:
        return self._security_profile

    def probe_availability(self) -> BackendAvailability:
        self.probe_count += 1
        return BackendAvailability(
            backend=self.backend_name,
            available=self._available,
            checked_at="2026-08-19T20:00:02Z",
            reason=None if self._available else self._availability_reason,
            details={"fake": True},
        )

    def describe_environment(self, plan: ExecutionPlan) -> ExecutionEnvironment:
        self.environment_calls.append(plan.run_id)
        if self._environment is not None:
            return self._environment
        return ExecutionEnvironment(
            environment_id="fake-env-1",
            backend=self.backend_name,
            language=plan.language,
            interpreter_version="3.12.0-test",
            metadata={"fake": True},
        )

    def _execute_plan(
        self,
        plan: ExecutionPlan,
        environment: ExecutionEnvironment,
    ) -> ExecutionResult:
        self.execute_calls.append((plan.run_id, environment.environment_id))
        if self._results:
            return self._results.pop(0)
        return ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=0,
            started_at="2026-08-19T20:00:03Z",
            finished_at="2026-08-19T20:00:04Z",
            duration_ms=1000,
            stdout="",
            stderr="",
            metadata={"fake": True},
        )
