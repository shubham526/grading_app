"""Optional real-Docker integration checks for v2.3.3 Commit 5.

These tests skip unless Docker is reachable and the configured runtime image is
already present locally.  The grading app never auto-pulls execution images.
"""

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from src.autograding.config import AutogradingConfig
from src.autograding.execution import DockerExecutionBackend
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_TIMEOUT,
    AutogradingProvenance,
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


def digest(data):
    return sha256(data).hexdigest()


def build_plan(root, source_bytes, *, timeout=3.0):
    root = Path(root)
    student_dir = root / "student"
    grader_dir = root / "grader"
    student_dir.mkdir(parents=True)
    grader_dir.mkdir(parents=True)
    student_path = student_dir / "main.py"
    grader_path = grader_dir / "test_dummy.py"
    student_path.write_bytes(source_bytes)
    grader_bytes = b"def test_dummy():\n    assert True\n"
    grader_path.write_bytes(grader_bytes)

    limits = ResourceLimits(
        wall_timeout_seconds=timeout,
        memory_mb=256,
        cpu_count=1,
        pids_limit=64,
        stdout_max_bytes=4096,
        stderr_max_bytes=4096,
        network_enabled=False,
    )
    config = AutogradingConfig(
        assessment_id="LAB_DOCKER",
        max_points=1,
        tests=(TestDefinition(test_id="test_dummy", name="Dummy", points=1),),
        entrypoint="main.py",
        resource_limits=limits,
    )
    student_file = PlannedWorkspaceFile(
        namespace=WORKSPACE_NAMESPACE_SUBMISSION,
        logical_path="main.py",
        source_path=str(student_path),
        sha256=digest(source_bytes),
        size_bytes=len(source_bytes),
        source_id="artifact-main",
    )
    grader_file = PlannedWorkspaceFile(
        namespace=WORKSPACE_NAMESPACE_GRADER,
        logical_path="tests/test_dummy.py",
        source_path=str(grader_path),
        sha256=digest(grader_bytes),
        size_bytes=len(grader_bytes),
        source_id="tests/test_dummy.py",
    )
    workspace = ExecutionWorkspaceSpec(
        submission_files=(student_file,),
        grader_files=(grader_file,),
        entrypoint="main.py",
    )
    bundle = TestBundleReference(
        bundle_id="bundle_docker",
        assessment_id="LAB_DOCKER",
        bundle_sha256="b" * 64,
        config_sha256="c" * 64,
        imported_at="2026-08-19T20:00:00Z",
    )
    provenance = AutogradingProvenance(
        submission_id="sub_docker",
        artifact_id="artifact-main",
        submission_sha256=digest(source_bytes),
        bundle_id="bundle_docker",
        bundle_sha256="b" * 64,
        config_sha256="c" * 64,
        runner_type="pytest",
        attempt=1,
    )
    return ExecutionPlan(
        run_id="agrun_docker_integration",
        created_at="2026-08-19T20:00:01Z",
        assessment_id="LAB_DOCKER",
        student_id="student1",
        submission_id="sub_docker",
        attempt=1,
        selected_submission_was_active=True,
        bundle_reference=bundle,
        config=config,
        resource_limits=limits,
        workspace=workspace,
        provenance=provenance,
    )


class TestDockerExecutionIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backend = DockerExecutionBackend(staging_parent_dir=str(self.root))
        availability = self.backend.availability()
        if not availability.available:
            self.skipTest(availability.reason)

    def test_real_container_is_read_only_unprivileged_and_offline(self):
        script = b'''\nimport os, socket\n\ndef can_write(path):\n    try:\n        with open(path, "w") as f:\n            f.write("x")\n        return True\n    except Exception:\n        return False\n\ndef can_connect():\n    try:\n        s = socket.socket()\n        s.settimeout(0.25)\n        s.connect(("1.1.1.1", 53))\n        s.close()\n        return True\n    except Exception:\n        return False\n\nprint("submission_write=" + str(can_write("/workspace/submission/probe.txt")))\nprint("rootfs_write=" + str(can_write("/etc/grading-app-probe")))\nprint("output_write=" + str(can_write("/workspace/output/result.txt")))\nprint("tmp_write=" + str(can_write("/tmp/result.txt")))\nprint("external_network=" + str(can_connect()))\nprint("uid=" + str(os.getuid()))\n'''
        plan = build_plan(self.root / "safe", script)
        result = self.backend.execute(plan)
        self.assertEqual(result.status, EXECUTION_STATUS_COMPLETED)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("submission_write=False", result.stdout)
        self.assertIn("rootfs_write=False", result.stdout)
        self.assertIn("output_write=True", result.stdout)
        self.assertIn("tmp_write=True", result.stdout)
        self.assertIn("external_network=False", result.stdout)
        self.assertIn("uid=65534", result.stdout)
        self.assertEqual(
            self.backend.last_cleanup_diagnostics,
            {"container_cleanup_error": None, "staging_cleanup_error": None},
        )

    def test_real_container_timeout_is_enforced(self):
        plan = build_plan(
            self.root / "timeout",
            b"import time\nprint('before-timeout', flush=True)\ntime.sleep(10)\n",
            timeout=0.5,
        )
        result = self.backend.execute(plan)
        self.assertEqual(result.status, EXECUTION_STATUS_TIMEOUT)
        self.assertIn("before-timeout", result.stdout)
        self.assertEqual(
            self.backend.last_cleanup_diagnostics,
            {"container_cleanup_error": None, "staging_cleanup_error": None},
        )


if __name__ == "__main__":
    unittest.main()
