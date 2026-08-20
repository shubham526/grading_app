"""Concrete isolated Docker backend for v2.3.3 Commit 5.

This is the first production backend allowed to execute student Python.  It
never runs student code directly on the instructor host: inputs are copied into
an ephemeral staging tree and mounted read-only into a locked-down container.
The container has no network, a read-only root filesystem, dropped Linux
capabilities, no-new-privileges, an unprivileged UID, resource limits, and an
explicit temporary writable area.

Commit 5 intentionally performs only a smoke execution of the configured Python
entrypoint.  Commit 6 adds the structured pytest adapter and test-result
protocol on top of this backend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Optional

from ..errors import (
    DockerBackendConfigurationError,
    DockerCommandError,
    DockerSandboxError,
)
from ..models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    ExecutionEnvironment,
    ExecutionResult,
)
from ..planner import ExecutionPlan
from .availability import BackendAvailability
from .base import BACKEND_SECURITY_PROFILE_ISOLATED, ExecutionBackend
from .docker_command import (
    DockerCLI,
    DockerImageInfo,
    build_docker_create_args,
    safe_container_name,
)
from .sandbox import SandboxMaterializer


DEFAULT_DOCKER_IMAGE = "python:3.12-slim"
DEFAULT_DOCKER_RUNTIME_USER = "65534:65534"
DEFAULT_DOCKER_INTERPRETER = "python"
DEFAULT_DOCKER_TMPFS_MB = 64
DOCKER_BACKEND_NAME = "docker"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _environment_id(image: DockerImageInfo, interpreter: str) -> str:
    payload = "%s\0%s\0%s" % (image.image_id, image.architecture or "", interpreter)
    return "docker-%s" % sha256(payload.encode("utf-8")).hexdigest()[:20]


class DockerExecutionBackend(ExecutionBackend):
    """Docker CLI backend implementing the Commit-4 isolation contract."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_DOCKER_IMAGE,
        docker_binary: str = "docker",
        runtime_user: str = DEFAULT_DOCKER_RUNTIME_USER,
        interpreter_command: str = DEFAULT_DOCKER_INTERPRETER,
        tmpfs_size_mb: int = DEFAULT_DOCKER_TMPFS_MB,
        staging_parent_dir: Optional[str] = None,
        cli: Optional[Any] = None,
    ):
        self.image = str(image or "").strip()
        self.runtime_user = str(runtime_user or "").strip()
        self.interpreter_command = str(interpreter_command or "").strip()
        if not self.image:
            raise DockerBackendConfigurationError("Docker runtime image must not be empty")
        if not self.runtime_user:
            raise DockerBackendConfigurationError("Docker runtime user must not be empty")
        if not self.interpreter_command:
            raise DockerBackendConfigurationError("Docker interpreter command must not be empty")
        if isinstance(tmpfs_size_mb, bool):
            raise DockerBackendConfigurationError("tmpfs_size_mb must be a positive integer")
        try:
            tmpfs_size_mb = int(tmpfs_size_mb)
        except (TypeError, ValueError) as exc:
            raise DockerBackendConfigurationError("tmpfs_size_mb must be a positive integer") from exc
        if tmpfs_size_mb <= 0:
            raise DockerBackendConfigurationError("tmpfs_size_mb must be a positive integer")
        self.tmpfs_size_mb = tmpfs_size_mb
        self.staging_parent_dir = staging_parent_dir
        self.cli = cli if cli is not None else DockerCLI(binary=docker_binary)

    @property
    def backend_name(self) -> str:
        return DOCKER_BACKEND_NAME

    @property
    def security_profile(self) -> str:
        return BACKEND_SECURITY_PROFILE_ISOLATED

    def _inspect_image(self) -> DockerImageInfo:
        info = self.cli.inspect_image(self.image)
        if not isinstance(info, DockerImageInfo):
            raise DockerCommandError("Docker CLI inspect_image() returned an invalid result")
        return info

    def probe_availability(self) -> BackendAvailability:
        executable = None
        try:
            executable = self.cli.executable_path()
        except Exception as exc:
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                reason="Could not resolve Docker CLI executable: %s" % exc,
            )
        if not executable:
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                reason="Docker CLI is not installed or is not on PATH.",
                details={"image": self.image},
            )
        try:
            server_version = self.cli.server_version()
        except Exception as exc:
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                reason=str(exc),
                details={"docker_binary": str(executable), "image": self.image},
            )
        try:
            image = self._inspect_image()
        except Exception as exc:
            return BackendAvailability(
                backend=self.backend_name,
                available=False,
                reason=(
                    "%s. Pull the configured runtime image explicitly before grading; "
                    "the app does not auto-pull execution images." % exc
                ),
                details={
                    "docker_binary": str(executable),
                    "server_version": str(server_version),
                    "image": self.image,
                },
            )
        return BackendAvailability(
            backend=self.backend_name,
            available=True,
            details={
                "docker_binary": str(executable),
                "server_version": str(server_version),
                "image": self.image,
                "image_id": image.image_id,
                "repo_digests": list(image.repo_digests),
                "os": image.os,
                "architecture": image.architecture,
            },
        )

    def describe_environment(self, plan: ExecutionPlan) -> ExecutionEnvironment:
        if plan.resource_limits.network_enabled:
            raise DockerBackendConfigurationError(
                "v2.3.3 Docker autograding does not permit network-enabled student execution"
            )
        image = self._inspect_image()
        requirements = None
        for item in plan.workspace.grader_files:
            if item.logical_path.casefold() == "requirements.txt":
                requirements = item.sha256
                break
        return ExecutionEnvironment(
            environment_id=_environment_id(image, self.interpreter_command),
            backend=self.backend_name,
            language=plan.language,
            interpreter_version=None,
            container_image=self.image,
            container_image_digest=image.image_id,
            dependency_lock_sha256=None,
            metadata={
                "resolved_image_reference": image.immutable_reference,
                "repo_digests": list(image.repo_digests),
                "os": image.os,
                "architecture": image.architecture,
                "runtime_user": self.runtime_user,
                "interpreter_command": self.interpreter_command,
                "rootfs_read_only": True,
                "network_mode": "none",
                "cap_drop": ["ALL"],
                "no_new_privileges": True,
                "tmpfs_size_mb": self.tmpfs_size_mb,
                "requirements_declared": requirements is not None,
                "requirements_sha256": requirements,
                "requirements_installed_by_backend": False,
            },
        )

    def _run_materialized_container(
        self,
        plan: ExecutionPlan,
        environment: ExecutionEnvironment,
        sandbox: Any,
        container_name: str,
        started_at: str,
    ) -> ExecutionResult:
        create_args = build_docker_create_args(
            container_name=container_name,
            image_reference=environment.container_image_digest,
            submission_dir=str(sandbox.submission_dir),
            grader_dir=str(sandbox.grader_dir),
            output_dir=str(sandbox.output_dir),
            entrypoint=plan.workspace.entrypoint,
            memory_mb=plan.resource_limits.memory_mb,
            cpu_count=plan.resource_limits.cpu_count,
            pids_limit=plan.resource_limits.pids_limit,
            runtime_user=self.runtime_user,
            interpreter_command=self.interpreter_command,
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
                error_message="Docker could not create the isolated grading container.",
                metadata={
                    "backend": self.backend_name,
                    "container_name": container_name,
                    "docker_create_returncode": create_result.returncode,
                },
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
                error_message="Student program exceeded the wall-clock timeout.",
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
                error_message="Could not verify final Docker container state: %s" % exc,
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
                error_message="Docker reported the grading container still running after attached execution.",
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
                    "Student process was terminated by the memory limit."
                    if state.oom_killed
                    else "Docker container runtime error: %s" % state.error
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
                error_message="Student process exceeded the configured memory limit.",
                metadata={
                    "backend": self.backend_name,
                    "container_name": container_name,
                    "oom_killed": True,
                    "container_status": state.status,
                },
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
                error_message="Docker did not report a final student-process exit code.",
                metadata={"backend": self.backend_name, "container_name": container_name},
            )

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
            metadata={
                "backend": self.backend_name,
                "container_name": container_name,
                "container_status": state.status,
                "oom_killed": state.oom_killed,
                "docker_start_returncode": start_result.returncode,
                "smoke_execution": True,
                "test_results_parsed": False,
            },
        )

    def _execute_plan(
        self,
        plan: ExecutionPlan,
        environment: ExecutionEnvironment,
    ) -> ExecutionResult:
        if plan.resource_limits.network_enabled:
            return ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                error_message="Network-enabled student execution is not supported by the Docker backend.",
                metadata={"backend": self.backend_name},
            )

        container_name = safe_container_name(plan.run_id)
        started_at = _utc_now_iso()
        materializer = SandboxMaterializer(parent_dir=self.staging_parent_dir)
        result = None
        cleanup_error = None
        staging_cleanup_error = None

        try:
            sandbox = materializer.materialize(plan)
            result = self._run_materialized_container(
                plan,
                environment,
                sandbox,
                container_name,
                started_at,
            )
        except DockerSandboxError as exc:
            result = ExecutionResult(
                status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                error_message="Could not materialize isolated execution inputs: %s" % exc,
                metadata={"backend": self.backend_name, "container_name": container_name},
            )
        except DockerCommandError as exc:
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
                error_message="Unexpected isolated-execution failure: %s" % exc,
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
                error_message="Isolated execution ended without a process result.",
                metadata={"backend": self.backend_name, "container_name": container_name},
            )

        if cleanup_error or staging_cleanup_error:
            metadata = dict(result.metadata)
            metadata.update(
                {
                    "original_execution_status": result.status,
                    "container_cleanup_error": cleanup_error,
                    "staging_cleanup_error": staging_cleanup_error,
                }
            )
            messages = [
                value
                for value in (cleanup_error, staging_cleanup_error)
                if value
            ]
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
                error_message="Isolated execution cleanup could not be verified: %s" % "; ".join(messages),
                metadata=metadata,
            )

        return result

    @property
    def last_cleanup_diagnostics(self) -> Dict[str, Optional[str]]:
        value = getattr(self, "_last_cleanup_diagnostics", None)
        if not isinstance(value, dict):
            return {"container_cleanup_error": None, "staging_cleanup_error": None}
        return dict(value)


__all__ = [
    "DEFAULT_DOCKER_IMAGE",
    "DEFAULT_DOCKER_INTERPRETER",
    "DEFAULT_DOCKER_RUNTIME_USER",
    "DEFAULT_DOCKER_TMPFS_MB",
    "DOCKER_BACKEND_NAME",
    "DockerExecutionBackend",
]
