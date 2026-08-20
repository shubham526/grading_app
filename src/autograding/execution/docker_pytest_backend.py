"""Structured pytest execution inside the Commit-5 hardened Docker sandbox."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any, Dict, Optional

from ..errors import DockerCommandError, DockerSandboxError, PytestResultProtocolError
from ..models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    ExecutionEnvironment,
    ExecutionResult,
)
from ..planner import ExecutionPlan
from ..testing.pytest_adapter import build_pytest_runtime_config
from ..testing.protocol import (
    DEFAULT_PYTEST_PROTOCOL_MAX_BYTES,
    PYTEST_RESULT_FILENAME,
    PYTEST_RUNTIME_CONFIG_FILENAME,
)
from ..testing.result_parser import load_pytest_protocol_bytes
from .availability import BackendAvailability
from .docker_backend import (
    DEFAULT_DOCKER_INTERPRETER,
    DEFAULT_DOCKER_RUNTIME_USER,
    DEFAULT_DOCKER_TMPFS_MB,
    DockerExecutionBackend,
)
from .docker_command import build_docker_create_args_for_command, safe_container_name
from .sandbox import SandboxMaterializer


DEFAULT_DOCKER_PYTEST_IMAGE = "grading-app-python312-pytest:9.1.1"
DEFAULT_EXPECTED_PYTEST_VERSION = "9.1.1"
DOCKER_PYTEST_BACKEND_NAME = "docker_pytest"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_runner_path() -> Path:
    return Path(__file__).resolve().parents[1] / "runtime" / "pytest_runner.py"


def _runtime_runner_bytes() -> bytes:
    path = _runtime_runner_path()
    data = path.read_bytes()
    if not data:
        raise DockerSandboxError("Structured pytest runtime runner is empty")
    return data


def _read_regular_file_no_follow(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink():
        raise PytestResultProtocolError("Structured pytest output must not be a symlink")
    flags = os.O_RDONLY
    if getattr(os, "O_NOFOLLOW", 0):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise PytestResultProtocolError("Could not open structured pytest output: %s" % exc) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PytestResultProtocolError("Structured pytest output is not a regular file")
        if info.st_size > int(max_bytes):
            raise PytestResultProtocolError(
                "Structured pytest output exceeds the %d-byte safety limit" % int(max_bytes)
            )
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, int(max_bytes) + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > int(max_bytes):
                raise PytestResultProtocolError(
                    "Structured pytest output exceeds the %d-byte safety limit" % int(max_bytes)
                )
        return b"".join(chunks)
    finally:
        os.close(fd)


class DockerPytestExecutionBackend(DockerExecutionBackend):
    """Docker backend that runs configured pytest tests and captures JSON results."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_DOCKER_PYTEST_IMAGE,
        expected_pytest_version: Optional[str] = DEFAULT_EXPECTED_PYTEST_VERSION,
        docker_binary: str = "docker",
        runtime_user: str = DEFAULT_DOCKER_RUNTIME_USER,
        interpreter_command: str = DEFAULT_DOCKER_INTERPRETER,
        tmpfs_size_mb: int = DEFAULT_DOCKER_TMPFS_MB,
        staging_parent_dir: Optional[str] = None,
        cli: Optional[Any] = None,
        protocol_max_bytes: int = DEFAULT_PYTEST_PROTOCOL_MAX_BYTES,
    ):
        super().__init__(
            image=image,
            docker_binary=docker_binary,
            runtime_user=runtime_user,
            interpreter_command=interpreter_command,
            tmpfs_size_mb=tmpfs_size_mb,
            staging_parent_dir=staging_parent_dir,
            cli=cli,
        )
        self.expected_pytest_version = (
            None
            if expected_pytest_version is None
            else str(expected_pytest_version).strip() or None
        )
        if isinstance(protocol_max_bytes, bool) or int(protocol_max_bytes) <= 0:
            raise ValueError("protocol_max_bytes must be a positive integer")
        self.protocol_max_bytes = int(protocol_max_bytes)

    @property
    def backend_name(self) -> str:
        return DOCKER_PYTEST_BACKEND_NAME

    def probe_availability(self) -> BackendAvailability:
        parent = super().probe_availability()
        if not parent.available:
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                checked_at=parent.checked_at,
                reason=parent.reason,
                details=dict(parent.details),
            )
        try:
            version = self.cli.probe_python_module_version(
                self.image,
                "pytest",
                interpreter=self.interpreter_command,
            )
        except Exception as exc:
            details = dict(parent.details)
            details["expected_pytest_version"] = self.expected_pytest_version
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                reason=str(exc),
                details=details,
            )
        if self.expected_pytest_version is not None and version != self.expected_pytest_version:
            details = dict(parent.details)
            details.update(
                {
                    "pytest_version": version,
                    "expected_pytest_version": self.expected_pytest_version,
                }
            )
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                reason=(
                    "Docker pytest runtime version mismatch: expected %s, found %s"
                    % (self.expected_pytest_version, version)
                ),
                details=details,
            )
        details = dict(parent.details)
        details["pytest_version"] = version
        details["expected_pytest_version"] = self.expected_pytest_version
        return BackendAvailability(
            backend=self.backend_name,
            available=True,
            details=details,
        )

    def describe_environment(self, plan: ExecutionPlan) -> ExecutionEnvironment:
        environment = super().describe_environment(plan)
        runner_hash = sha256(_runtime_runner_bytes()).hexdigest()
        metadata = dict(environment.metadata)
        metadata.update(
            {
                "structured_test_runner": "pytest",
                "expected_pytest_version": self.expected_pytest_version,
                "pytest_runner_sha256": runner_hash,
                "pytest_protocol_max_bytes": self.protocol_max_bytes,
            }
        )
        return ExecutionEnvironment(
            environment_id=environment.environment_id,
            backend=self.backend_name,
            language=environment.language,
            interpreter_version=environment.interpreter_version,
            container_image=environment.container_image,
            container_image_digest=environment.container_image_digest,
            dependency_lock_sha256=environment.dependency_lock_sha256,
            metadata=metadata,
        )

    def _runtime_files(self, plan: ExecutionPlan) -> Dict[str, bytes]:
        config_bytes = (
            json.dumps(build_pytest_runtime_config(plan), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        return {
            "pytest_runner.py": _runtime_runner_bytes(),
            PYTEST_RUNTIME_CONFIG_FILENAME: config_bytes,
        }

    def _run_pytest_container(
        self,
        plan: ExecutionPlan,
        environment: ExecutionEnvironment,
        sandbox: Any,
        container_name: str,
        started_at: str,
    ) -> ExecutionResult:
        if sandbox.runtime_dir is None:
            raise DockerSandboxError("Structured pytest execution requires a runtime directory")
        command = (
            self.interpreter_command,
            "-B",
            "-u",
            "/workspace/runtime/pytest_runner.py",
            "--config",
            "/workspace/runtime/%s" % PYTEST_RUNTIME_CONFIG_FILENAME,
            "--output",
            "/workspace/output/%s" % PYTEST_RESULT_FILENAME,
            "--submission-root",
            "/workspace/submission",
            "--grader-root",
            "/workspace/grader",
        )
        create_args = build_docker_create_args_for_command(
            container_name=container_name,
            image_reference=environment.container_image_digest,
            submission_dir=str(sandbox.submission_dir),
            grader_dir=str(sandbox.grader_dir),
            output_dir=str(sandbox.output_dir),
            runtime_dir=str(sandbox.runtime_dir),
            command=command,
            memory_mb=plan.resource_limits.memory_mb,
            cpu_count=plan.resource_limits.cpu_count,
            pids_limit=plan.resource_limits.pids_limit,
            runtime_user=self.runtime_user,
            tmpfs_size_mb=self.tmpfs_size_mb,
        )
        create_result = self.cli.create(create_args)
        if create_result.timed_out or create_result.returncode != 0:
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=create_result.duration_ms,
                stdout=create_result.stdout,
                stderr=create_result.stderr,
                stdout_truncated=create_result.stdout_truncated,
                stderr_truncated=create_result.stderr_truncated,
                error_message="Docker could not create the isolated pytest container.",
                metadata={"backend": self.backend_name, "container_name": container_name},
            )

        start_result = self.cli.start_attached(
            container_name,
            timeout_seconds=plan.resource_limits.wall_timeout_seconds,
            stdout_max_bytes=plan.resource_limits.stdout_max_bytes,
            stderr_max_bytes=plan.resource_limits.stderr_max_bytes,
        )
        if start_result.timed_out:
            return ExecutionResult(
                status=EXECUTION_STATUS_TIMEOUT,
                exit_code=None,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=start_result.duration_ms,
                stdout=start_result.stdout,
                stderr=start_result.stderr,
                stdout_truncated=start_result.stdout_truncated,
                stderr_truncated=start_result.stderr_truncated,
                error_message="Pytest execution exceeded the overall wall-clock timeout.",
                metadata={
                    "backend": self.backend_name,
                    "container_name": container_name,
                    "wall_timeout_seconds": plan.resource_limits.wall_timeout_seconds,
                },
            )

        try:
            state = self.cli.inspect_container_state(container_name)
        except Exception as exc:
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=start_result.duration_ms,
                stdout=start_result.stdout,
                stderr=start_result.stderr,
                stdout_truncated=start_result.stdout_truncated,
                stderr_truncated=start_result.stderr_truncated,
                error_message="Could not verify final Docker pytest container state: %s" % exc,
                metadata={"backend": self.backend_name, "container_name": container_name},
            )

        if state.running:
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=start_result.duration_ms,
                stdout=start_result.stdout,
                stderr=start_result.stderr,
                stdout_truncated=start_result.stdout_truncated,
                stderr_truncated=start_result.stderr_truncated,
                error_message="Docker reported the pytest container still running after attached execution.",
                metadata={"backend": self.backend_name, "container_name": container_name},
            )
        if state.error:
            status = EXECUTION_STATUS_ERROR if state.oom_killed else EXECUTION_STATUS_INFRASTRUCTURE_ERROR
            return ExecutionResult(
                status=status,
                exit_code=state.exit_code,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=start_result.duration_ms,
                stdout=start_result.stdout,
                stderr=start_result.stderr,
                stdout_truncated=start_result.stdout_truncated,
                stderr_truncated=start_result.stderr_truncated,
                error_message=(
                    "Pytest process was terminated by the memory limit."
                    if state.oom_killed
                    else "Docker pytest runtime error: %s" % state.error
                ),
                metadata={
                    "backend": self.backend_name,
                    "container_name": container_name,
                    "oom_killed": state.oom_killed,
                    "container_status": state.status,
                },
            )
        if state.oom_killed:
            return ExecutionResult(
                status=EXECUTION_STATUS_ERROR,
                exit_code=state.exit_code,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=start_result.duration_ms,
                stdout=start_result.stdout,
                stderr=start_result.stderr,
                stdout_truncated=start_result.stdout_truncated,
                stderr_truncated=start_result.stderr_truncated,
                error_message="Pytest process exceeded the configured memory limit.",
                metadata={"backend": self.backend_name, "oom_killed": True},
            )
        if state.exit_code is None:
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                duration_ms=start_result.duration_ms,
                stdout=start_result.stdout,
                stderr=start_result.stderr,
                stdout_truncated=start_result.stdout_truncated,
                stderr_truncated=start_result.stderr_truncated,
                error_message="Docker did not report a final pytest exit code.",
                metadata={"backend": self.backend_name},
            )

        metadata = {
            "backend": self.backend_name,
            "container_name": container_name,
            "container_status": state.status,
            "oom_killed": state.oom_killed,
            "docker_start_returncode": start_result.returncode,
            "structured_pytest_execution": True,
        }
        protocol_path = sandbox.output_dir / PYTEST_RESULT_FILENAME
        if protocol_path.exists() or protocol_path.is_symlink():
            try:
                protocol_bytes = _read_regular_file_no_follow(protocol_path, self.protocol_max_bytes)
                metadata["pytest_protocol"] = load_pytest_protocol_bytes(
                    protocol_bytes,
                    max_bytes=self.protocol_max_bytes,
                )
                metadata["pytest_protocol_sha256"] = sha256(protocol_bytes).hexdigest()
            except Exception as exc:
                metadata["pytest_protocol_error"] = str(exc)
        else:
            metadata["pytest_protocol_error"] = "Structured pytest output file was not created."

        return ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=state.exit_code,
            started_at=started_at,
            finished_at=_utc_now_iso(),
            duration_ms=start_result.duration_ms,
            stdout=start_result.stdout,
            stderr=start_result.stderr,
            stdout_truncated=start_result.stdout_truncated,
            stderr_truncated=start_result.stderr_truncated,
            metadata=metadata,
        )

    def _execute_plan(
        self,
        plan: ExecutionPlan,
        environment: ExecutionEnvironment,
    ) -> ExecutionResult:
        if plan.config.runner_type != "pytest":
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                error_message="DockerPytestExecutionBackend requires runner_type='pytest'.",
                metadata={"backend": self.backend_name},
            )
        if plan.resource_limits.network_enabled:
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                error_message="Network-enabled pytest execution is not supported.",
                metadata={"backend": self.backend_name},
            )

        container_name = safe_container_name(plan.run_id + "-pytest")
        started_at = _utc_now_iso()
        materializer = SandboxMaterializer(parent_dir=self.staging_parent_dir)
        result = None
        cleanup_error = None
        staging_cleanup_error = None

        try:
            sandbox = materializer.materialize(plan, runtime_files=self._runtime_files(plan))
            result = self._run_pytest_container(
                plan,
                environment,
                sandbox,
                container_name,
                started_at,
            )
        except (DockerSandboxError, DockerCommandError) as exc:
            result = ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                error_message=str(exc),
                metadata={"backend": self.backend_name, "container_name": container_name},
            )
        except Exception as exc:
            result = ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                error_message="Unexpected structured pytest execution failure: %s" % exc,
                metadata={"backend": self.backend_name, "container_name": container_name},
            )
        finally:
            try:
                cleanup_error = self.cli.remove_force(container_name)
            except Exception as exc:
                cleanup_error = str(exc)
            try:
                materializer.cleanup()
            except Exception as exc:
                staging_cleanup_error = str(exc)
            self._last_cleanup_diagnostics = {
                "container_cleanup_error": cleanup_error,
                "staging_cleanup_error": staging_cleanup_error,
            }

        if result is None:
            result = ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                error_message="Structured pytest execution ended without a result.",
                metadata={"backend": self.backend_name},
            )

        if cleanup_error or staging_cleanup_error:
            metadata = deepcopy(result.metadata)
            metadata.update(
                {
                    "original_execution_status": result.status,
                    "container_cleanup_error": cleanup_error,
                    "staging_cleanup_error": staging_cleanup_error,
                }
            )
            messages = [value for value in (cleanup_error, staging_cleanup_error) if value]
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                exit_code=result.exit_code,
                started_at=result.started_at or started_at,
                finished_at=_utc_now_iso(),
                duration_ms=result.duration_ms,
                stdout=result.stdout,
                stderr=result.stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                error_message="Structured pytest cleanup could not be verified: %s" % "; ".join(messages),
                metadata=metadata,
            )
        return result


__all__ = [
    "DEFAULT_DOCKER_PYTEST_IMAGE",
    "DEFAULT_EXPECTED_PYTEST_VERSION",
    "DOCKER_PYTEST_BACKEND_NAME",
    "DockerPytestExecutionBackend",
]
