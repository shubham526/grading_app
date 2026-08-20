import json
from pathlib import Path
import tempfile
import unittest

from src.autograding.errors import DockerCommandError
from src.autograding.execution import DockerPytestExecutionBackend
from src.autograding.execution.docker_command import (
    DockerCommandResult,
    DockerContainerState,
    DockerImageInfo,
)
from src.autograding.models import EXECUTION_STATUS_COMPLETED
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


class FakePytestDockerCLI:
    def __init__(self):
        self.path = "/usr/local/bin/docker"
        self.version = "29-test"
        self.pytest_version = "9.1.1"
        self.image_info = DockerImageInfo(
            requested_reference="grading-app-python312-pytest:9.1.1",
            image_id="sha256:" + "a" * 64,
            repo_digests=(),
            os="linux",
            architecture="arm64",
        )
        self.create_args = None
        self.removed = []

    def executable_path(self):
        return self.path

    def server_version(self):
        return self.version

    def inspect_image(self, reference):
        return self.image_info

    def probe_python_module_version(self, image_reference, module_name, **kwargs):
        if isinstance(self.pytest_version, Exception):
            raise self.pytest_version
        return self.pytest_version

    def create(self, args):
        self.create_args = tuple(args)
        return command_result(stdout="container\n")

    def _output_dir(self):
        for value in self.create_args or ():
            if value.startswith("type=bind") and ",dst=/workspace/output" in value:
                return Path(value.split("src=", 1)[1].split(",dst=", 1)[0])
        raise AssertionError("output mount missing")

    def start_attached(self, name, **kwargs):
        payload = {
            "schema_version": "1.0",
            "runner": "pytest",
            "pytest_version": "9.1.1",
            "pytest_exit_code": 0,
            "collected_count": 1,
            "selected_count": 1,
            "deselected_count": 0,
            "selection_errors": [],
            "collection_errors": [],
            "tests": [
                {
                    "test_id": "test_fixture",
                    "selector": "test_fixture",
                    "visibility": "hidden",
                    "group_id": None,
                    "display_name": "Fixture",
                    "status": "passed",
                    "duration_ms": 4,
                    "message": None,
                    "traceback": None,
                    "stdout": "",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "nodeids": ["tests/test_fixture.py::test_fixture"],
                    "item_count": 1,
                    "timeout_seconds": None,
                }
            ],
        }
        (self._output_dir() / "pytest_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return command_result(returncode=0, stdout=".", duration_ms=50)

    def inspect_container_state(self, name):
        return DockerContainerState(
            status="exited",
            running=False,
            exit_code=0,
            oom_killed=False,
            error=None,
        )

    def remove_force(self, name):
        self.removed.append(name)
        return None


class TestDockerPytestExecutionBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = build_test_execution_plan(self.root / "plan")
        self.cli = FakePytestDockerCLI()
        self.backend = DockerPytestExecutionBackend(
            cli=self.cli,
            staging_parent_dir=str(self.root),
        )

    def test_availability_requires_expected_pytest_runtime(self):
        availability = self.backend.availability()
        self.assertTrue(availability.available)
        self.assertEqual(availability.details["pytest_version"], "9.1.1")

    def test_wrong_pytest_version_disables_backend(self):
        self.cli.pytest_version = "9.0.0"
        availability = self.backend.availability()
        self.assertFalse(availability.available)
        self.assertIn("mismatch", availability.reason)

    def test_missing_pytest_disables_backend(self):
        self.cli.pytest_version = DockerCommandError("cannot import pytest")
        availability = self.backend.availability()
        self.assertFalse(availability.available)
        self.assertIn("cannot import pytest", availability.reason)

    def test_structured_run_mounts_runtime_read_only_and_collects_protocol(self):
        result = self.backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_COMPLETED)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("pytest_protocol", result.metadata)
        self.assertEqual(result.metadata["pytest_protocol"]["pytest_version"], "9.1.1")
        joined = "\n".join(self.cli.create_args)
        self.assertIn("dst=/workspace/runtime,readonly", joined)
        self.assertIn("/workspace/runtime/pytest_runner.py", self.cli.create_args)
        self.assertNotIn("/workspace/submission/main.py", self.cli.create_args[-1])
        self.assertTrue(self.cli.removed)

    def test_runtime_and_staging_paths_are_removed_after_run(self):
        self.backend.execute(self.plan)
        mounts = [value for value in self.cli.create_args if value.startswith("type=bind")]
        self.assertEqual(len(mounts), 4)
        for mount in mounts:
            src = mount.split("src=", 1)[1].split(",dst=", 1)[0]
            self.assertFalse(Path(src).exists())


if __name__ == "__main__":
    unittest.main()
