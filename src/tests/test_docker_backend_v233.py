from pathlib import Path
from dataclasses import replace
import tempfile
import unittest

from src.autograding.errors import DockerBackendConfigurationError, DockerCommandError
from src.autograding.execution import DockerExecutionBackend
from src.autograding.execution.docker_command import (
    DockerCommandResult,
    DockerContainerState,
    DockerImageInfo,
)
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    ResourceLimits,
)
from src.autograding.planner import ExecutionPlan
from src.tests.autograding_v233_execution_support import build_test_execution_plan


def command_result(*, returncode=0, stdout="", stderr="", timed_out=False, duration_ms=10):
    return DockerCommandResult(
        command=("docker",),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=timed_out,
        duration_ms=duration_ms,
    )


class FakeDockerCLI:
    def __init__(self):
        self.path = "/usr/local/bin/docker"
        self.version = "29.0-test"
        self.image_info = DockerImageInfo(
            requested_reference="python:3.12-slim",
            image_id="sha256:" + "a" * 64,
            repo_digests=("python@sha256:" + "b" * 64,),
            os="linux",
            architecture="amd64",
        )
        self.create_result = command_result(stdout="container-id\n")
        self.start_result = command_result(stdout="student output\n", duration_ms=123)
        self.state = DockerContainerState(
            status="exited",
            running=False,
            exit_code=0,
            oom_killed=False,
            error=None,
        )
        self.create_args = None
        self.start_calls = []
        self.removed = []
        self.cleanup_error = None
        self.inspect_image_calls = []

    def executable_path(self):
        return self.path

    def server_version(self):
        if isinstance(self.version, Exception):
            raise self.version
        return self.version

    def inspect_image(self, reference):
        self.inspect_image_calls.append(reference)
        if isinstance(self.image_info, Exception):
            raise self.image_info
        return self.image_info

    def create(self, args):
        self.create_args = tuple(args)
        return self.create_result

    def start_attached(self, name, **kwargs):
        self.start_calls.append((name, dict(kwargs)))
        return self.start_result

    def inspect_container_state(self, name):
        if isinstance(self.state, Exception):
            raise self.state
        return self.state

    def remove_force(self, name):
        self.removed.append(name)
        return self.cleanup_error


class TestDockerExecutionBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = build_test_execution_plan(self.root / "plan")
        self.cli = FakeDockerCLI()
        self.backend = DockerExecutionBackend(
            cli=self.cli,
            staging_parent_dir=str(self.root),
        )

    def test_availability_requires_cli_daemon_and_local_image(self):
        availability = self.backend.availability()
        self.assertTrue(availability.available)
        self.assertEqual(availability.details["image_id"], "sha256:" + "a" * 64)

    def test_missing_cli_is_reported_without_execution(self):
        self.cli.path = None
        availability = self.backend.availability()
        self.assertFalse(availability.available)
        self.assertIn("not installed", availability.reason)

    def test_unreachable_daemon_is_reported(self):
        self.cli.version = DockerCommandError("daemon unavailable")
        availability = self.backend.availability()
        self.assertFalse(availability.available)
        self.assertIn("daemon unavailable", availability.reason)

    def test_missing_image_is_reported_and_never_auto_pulled(self):
        self.cli.image_info = DockerCommandError("image missing")
        availability = self.backend.availability()
        self.assertFalse(availability.available)
        self.assertIn("does not auto-pull", availability.reason)

    def test_environment_records_exact_resolved_image_identity(self):
        env = self.backend.describe_environment(self.plan)
        self.assertEqual(env.backend, "docker")
        self.assertEqual(env.container_image, "python:3.12-slim")
        self.assertEqual(env.container_image_digest, "sha256:" + "a" * 64)
        self.assertEqual(env.metadata["resolved_image_reference"], "sha256:" + "a" * 64)
        self.assertEqual(env.metadata["network_mode"], "none")
        self.assertTrue(env.metadata["rootfs_read_only"])

    def test_network_enabled_plan_is_refused(self):
        limits = ResourceLimits.from_dict({**self.plan.resource_limits.to_dict(), "network_enabled": True})
        config = replace(self.plan.config, resource_limits=limits)
        plan = ExecutionPlan(
            run_id=self.plan.run_id,
            created_at=self.plan.created_at,
            assessment_id=self.plan.assessment_id,
            student_id=self.plan.student_id,
            submission_id=self.plan.submission_id,
            attempt=self.plan.attempt,
            selected_submission_was_active=self.plan.selected_submission_was_active,
            bundle_reference=self.plan.bundle_reference,
            config=config,
            resource_limits=limits,
            workspace=self.plan.workspace,
            provenance=self.plan.provenance,
        )
        with self.assertRaisesRegex(DockerBackendConfigurationError, "network"):
            self.backend.execute(plan)

    def test_successful_smoke_execution_uses_hardened_create_args(self):
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_COMPLETED)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "student output\n")
        args = self.cli.create_args
        self.assertIsNotNone(args)
        joined = "\n".join(args)
        self.assertIn("--network\nnone", joined)
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop\nALL", joined)
        self.assertIn("--security-opt\nno-new-privileges", joined)
        self.assertIn("sha256:" + "a" * 64, args)
        self.assertNotIn("python:3.12-slim", args)
        self.assertTrue(self.cli.removed)
        self.assertEqual(self.backend.last_cleanup_diagnostics["container_cleanup_error"], None)

    def test_staging_paths_are_ephemeral_and_removed_after_run(self):
        self.backend.execute(self.plan)
        mounts = [value for value in self.cli.create_args if value.startswith("type=bind")]
        self.assertEqual(len(mounts), 3)
        for mount in mounts:
            src = mount.split("src=", 1)[1].split(",dst=", 1)[0]
            self.assertFalse(Path(src).exists())

    def test_timeout_is_normalized_and_container_is_force_removed(self):
        self.cli.start_result = command_result(
            stdout="partial",
            timed_out=True,
            duration_ms=10000,
        )
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_TIMEOUT)
        self.assertIsNone(result.exit_code)
        self.assertTrue(self.cli.removed)

    def test_create_failure_is_infrastructure_error(self):
        self.cli.create_result = command_result(returncode=125, stderr="create failed")
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_INFRASTRUCTURE_ERROR)
        self.assertIn("create", result.error_message.lower())
        self.assertTrue(self.cli.removed)

    def test_oom_is_student_execution_error_not_infrastructure_zero(self):
        self.cli.state = DockerContainerState(
            status="exited",
            running=False,
            exit_code=137,
            oom_killed=True,
            error=None,
        )
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_ERROR)
        self.assertEqual(result.exit_code, 137)
        self.assertIn("memory", result.error_message.lower())

    def test_nonzero_student_exit_is_still_completed_process(self):
        self.cli.state = DockerContainerState(
            status="exited",
            running=False,
            exit_code=7,
            oom_killed=False,
            error=None,
        )
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_COMPLETED)
        self.assertEqual(result.exit_code, 7)

    def test_runtime_state_error_is_infrastructure_error(self):
        self.cli.state = DockerContainerState(
            status="exited",
            running=False,
            exit_code=126,
            oom_killed=False,
            error="OCI runtime create failed",
        )
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_INFRASTRUCTURE_ERROR)
        self.assertIn("runtime", result.error_message.lower())

    def test_container_inspection_failure_is_infrastructure_error(self):
        self.cli.state = DockerCommandError("inspect failed")
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_INFRASTRUCTURE_ERROR)
        self.assertIn("inspect failed", result.error_message)

    def test_cleanup_failure_becomes_infrastructure_error(self):
        self.cli.cleanup_error = "cleanup failed"
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_INFRASTRUCTURE_ERROR)
        self.assertIn("cleanup", result.error_message.lower())
        self.assertEqual(
            self.backend.last_cleanup_diagnostics["container_cleanup_error"],
            "cleanup failed",
        )


if __name__ == "__main__":
    unittest.main()
