from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from src.autograding.config import AutogradingConfig
from src.autograding.execution import DockerPytestExecutionBackend
from src.autograding.models import (
    AutogradingProvenance,
    ResourceLimits,
    TestBundleReference,
    TestDefinition,
)
from src.autograding.planner import ExecutionPlan
from src.autograding.testing import execute_pytest_plan, student_safe_test_results
from src.autograding.workspace import (
    ExecutionWorkspaceSpec,
    PlannedWorkspaceFile,
    WORKSPACE_NAMESPACE_GRADER,
    WORKSPACE_NAMESPACE_SUBMISSION,
)


def digest(data):
    return sha256(data).hexdigest()


def build_plan(root, student_bytes, grader_bytes, tests, wall_timeout=5):
    root = Path(root)
    submission_dir = root / "submission"
    grader_dir = root / "grader"
    submission_dir.mkdir(parents=True)
    grader_dir.mkdir(parents=True)
    student_path = submission_dir / "main.py"
    grader_path = grader_dir / "test_main.py"
    student_path.write_bytes(student_bytes)
    grader_path.write_bytes(grader_bytes)

    limits = ResourceLimits(
        wall_timeout_seconds=wall_timeout,
        memory_mb=256,
        cpu_count=1,
        pids_limit=64,
        stdout_max_bytes=65536,
        stderr_max_bytes=65536,
        network_enabled=False,
    )
    config = AutogradingConfig(
        assessment_id="LAB_PYTEST",
        max_points=sum(float(test.points or 0) for test in tests),
        tests=tuple(tests),
        entrypoint="main.py",
        resource_limits=limits,
    )
    workspace = ExecutionWorkspaceSpec(
        submission_files=(
            PlannedWorkspaceFile(
                namespace=WORKSPACE_NAMESPACE_SUBMISSION,
                logical_path="main.py",
                source_path=str(student_path),
                sha256=digest(student_bytes),
                size_bytes=len(student_bytes),
                source_id="artifact-main",
            ),
        ),
        grader_files=(
            PlannedWorkspaceFile(
                namespace=WORKSPACE_NAMESPACE_GRADER,
                logical_path="tests/test_main.py",
                source_path=str(grader_path),
                sha256=digest(grader_bytes),
                size_bytes=len(grader_bytes),
                source_id="tests/test_main.py",
            ),
        ),
        entrypoint="main.py",
    )
    reference = TestBundleReference(
        bundle_id="bundle_pytest_fixture",
        assessment_id="LAB_PYTEST",
        bundle_sha256="b" * 64,
        config_sha256="c" * 64,
        imported_at="2026-08-19T21:00:00Z",
    )
    provenance = AutogradingProvenance(
        submission_id="sub_pytest_fixture",
        artifact_id="artifact-main",
        submission_sha256=digest(student_bytes),
        bundle_id=reference.bundle_id,
        bundle_sha256=reference.bundle_sha256,
        config_sha256=reference.config_sha256,
        runner_type="pytest",
        attempt=1,
    )
    return ExecutionPlan(
        run_id="agrun_pytest_fixture",
        created_at="2026-08-19T21:00:01Z",
        assessment_id="LAB_PYTEST",
        student_id="student1",
        submission_id="sub_pytest_fixture",
        attempt=1,
        selected_submission_was_active=True,
        bundle_reference=reference,
        config=config,
        resource_limits=limits,
        workspace=workspace,
        provenance=provenance,
    )


class TestRealDockerPytestExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = DockerPytestExecutionBackend()
        availability = cls.backend.availability()
        if not availability.available:
            raise unittest.SkipTest(availability.reason)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_real_public_and_hidden_pytest_results(self):
        student = b"def add(a, b):\n    return a + b\n"
        grader = (
            b"from main import add\n\n"
            b"def test_public():\n    assert add(1, 2) == 3\n\n"
            b"def test_hidden():\n    assert add(2, 2) == 5\n"
        )
        tests = (
            TestDefinition(
                test_id="public_basic",
                name="Basic addition",
                visibility="public",
                points=5,
                timeout_seconds=1,
                metadata={"pytest_nodeid": "tests/test_main.py::test_public"},
            ),
            TestDefinition(
                test_id="hidden_edge",
                name="Hidden addition edge",
                visibility="hidden",
                points=5,
                timeout_seconds=1,
                metadata={"pytest_nodeid": "tests/test_main.py::test_hidden"},
            ),
        )
        plan = build_plan(Path(self.tmp.name), student, grader, tests)
        run = execute_pytest_plan(plan, self.backend)
        self.assertEqual(run.test_by_id("public_basic").status, "passed")
        self.assertEqual(run.test_by_id("hidden_edge").status, "failed")
        self.assertEqual(run.pytest_version, "9.1.1")
        self.assertFalse(run.requires_review)
        self.assertIsNone(run.test_by_id("public_basic").points_awarded)
        safe = student_safe_test_results(run, plan.config.reporting_policy)
        hidden = next(item for item in safe if item.visibility == "hidden")
        self.assertNotEqual(hidden.test_id, "hidden_edge")
        self.assertTrue(hidden.test_id.startswith("hidden_"))
        self.assertEqual(hidden.display_name, "Hidden test")
        self.assertIsNone(hidden.group_id)
        self.assertEqual(hidden.message, "Hidden test did not pass.")
        self.assertIsNone(hidden.traceback)
        self.assertEqual(hidden.stdout, "")
        self.assertEqual(hidden.stderr, "")
        self.assertNotIn("pytest_nodeids", hidden.metadata)

    def test_real_per_test_timeout(self):
        student = b"def spin():\n    while True:\n        pass\n"
        grader = b"from main import spin\n\ndef test_timeout():\n    spin()\n"
        tests = (
            TestDefinition(
                test_id="timeout_case",
                name="Timeout case",
                visibility="hidden",
                points=10,
                timeout_seconds=0.2,
                metadata={"pytest_nodeid": "tests/test_main.py::test_timeout"},
            ),
        )
        plan = build_plan(Path(self.tmp.name), student, grader, tests, wall_timeout=3)
        run = execute_pytest_plan(plan, self.backend)
        self.assertEqual(run.test_by_id("timeout_case").status, "timeout")
        self.assertFalse(run.requires_review)
        self.assertEqual(self.backend.last_cleanup_diagnostics["container_cleanup_error"], None)
        self.assertEqual(self.backend.last_cleanup_diagnostics["staging_cleanup_error"], None)


if __name__ == "__main__":
    unittest.main()
