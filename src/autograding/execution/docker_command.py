"""Docker CLI primitives for the v2.3.3 isolated execution backend.

The desktop application intentionally talks to Docker through the CLI rather
than adding the Docker Python SDK as a hard dependency.  Commands are always
executed without a shell.  Attached container output is drained concurrently
with strict in-memory capture caps so hostile student output cannot grow Python
memory without bound.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..errors import DockerCommandError


DEFAULT_DOCKER_COMMAND_TIMEOUT_SECONDS = 10.0
DEFAULT_DOCKER_CONTROL_OUTPUT_BYTES = 256 * 1024


@dataclass(frozen=True)
class DockerCommandResult:
    """Bounded result from one Docker CLI invocation."""

    command: Tuple[str, ...]
    returncode: Optional[int]
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    duration_ms: int


class _BoundedBytes:
    def __init__(self, limit: int):
        if isinstance(limit, bool) or int(limit) <= 0:
            raise ValueError("capture limit must be a positive integer")
        self.limit = int(limit)
        self.data = bytearray()
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


def _drain_pipe(pipe: Any, buffer: _BoundedBytes) -> None:
    try:
        while True:
            chunk = pipe.read(64 * 1024)
            if not chunk:
                break
            buffer.add(chunk)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def run_bounded_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    stdout_max_bytes: int,
    stderr_max_bytes: int,
) -> DockerCommandResult:
    """Run one command without a shell while draining bounded output pipes."""

    argv = tuple(str(part) for part in command)
    if not argv or not argv[0].strip():
        raise ValueError("command must not be empty")
    if isinstance(timeout_seconds, bool) or float(timeout_seconds) <= 0:
        raise ValueError("timeout_seconds must be positive")

    stdout_buffer = _BoundedBytes(stdout_max_bytes)
    stderr_buffer = _BoundedBytes(stderr_max_bytes)
    started = time.monotonic()

    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )
    except FileNotFoundError as exc:
        raise DockerCommandError("Docker CLI executable was not found: %s" % argv[0]) from exc
    except OSError as exc:
        raise DockerCommandError("Could not start Docker CLI command: %s" % exc) from exc

    stdout_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stdout, stdout_buffer),
        name="grading-app-docker-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stderr, stderr_buffer),
        name="grading-app-docker-stderr",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        returncode = process.wait(timeout=float(timeout_seconds))
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            process.kill()
        except OSError:
            pass
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            returncode = process.poll()

    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    duration_ms = int(round((time.monotonic() - started) * 1000.0))

    return DockerCommandResult(
        command=argv,
        returncode=returncode,
        stdout=stdout_buffer.text(),
        stderr=stderr_buffer.text(),
        stdout_truncated=stdout_buffer.truncated,
        stderr_truncated=stderr_buffer.truncated,
        timed_out=timed_out,
        duration_ms=max(0, duration_ms),
    )


@dataclass(frozen=True)
class DockerImageInfo:
    """Minimal immutable identity extracted from ``docker image inspect``."""

    requested_reference: str
    image_id: str
    repo_digests: Tuple[str, ...]
    os: Optional[str]
    architecture: Optional[str]

    @property
    def immutable_reference(self) -> str:
        return self.image_id


@dataclass(frozen=True)
class DockerContainerState:
    """Final container state used to disambiguate CLI vs process outcomes."""

    status: str
    running: bool
    exit_code: Optional[int]
    oom_killed: bool
    error: Optional[str]


class DockerCLI:
    """Small injectable wrapper around the Docker CLI."""

    def __init__(self, binary: str = "docker"):
        value = str(binary or "").strip()
        if not value:
            raise ValueError("Docker binary must not be empty")
        self.binary = value

    def executable_path(self) -> Optional[str]:
        if "/" in self.binary or "\\" in self.binary:
            return self.binary if shutil.which(self.binary) else None
        return shutil.which(self.binary)

    def _control(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float = DEFAULT_DOCKER_COMMAND_TIMEOUT_SECONDS,
    ) -> DockerCommandResult:
        return run_bounded_command(
            (self.binary, *tuple(args)),
            timeout_seconds=timeout_seconds,
            stdout_max_bytes=DEFAULT_DOCKER_CONTROL_OUTPUT_BYTES,
            stderr_max_bytes=DEFAULT_DOCKER_CONTROL_OUTPUT_BYTES,
        )

    def server_version(self) -> str:
        result = self._control(("version", "--format", "{{.Server.Version}}"))
        if result.timed_out:
            raise DockerCommandError("Docker daemon version probe timed out")
        if result.returncode != 0:
            raise DockerCommandError(
                "Docker daemon is not reachable: %s" % (result.stderr.strip() or "unknown error")
            )
        value = result.stdout.strip()
        if not value:
            raise DockerCommandError("Docker daemon version probe returned no version")
        return value

    def inspect_image(self, reference: str) -> DockerImageInfo:
        reference = str(reference or "").strip()
        if not reference:
            raise ValueError("Docker image reference must not be empty")
        result = self._control(("image", "inspect", reference))
        if result.timed_out:
            raise DockerCommandError("Docker image inspection timed out for %s" % reference)
        if result.returncode != 0:
            raise DockerCommandError(
                "Docker image %r is not available locally: %s"
                % (reference, result.stderr.strip() or "image inspect failed")
            )
        try:
            payload = json.loads(result.stdout)
            item = payload[0]
        except (ValueError, TypeError, IndexError, KeyError) as exc:
            raise DockerCommandError("Docker image inspection returned invalid JSON") from exc
        image_id = str(item.get("Id") or "").strip().lower()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise DockerCommandError("Docker image inspection returned an invalid image ID")
        repo_digests_raw = item.get("RepoDigests") or []
        repo_digests = tuple(
            sorted(str(value).strip() for value in repo_digests_raw if str(value).strip())
        )
        return DockerImageInfo(
            requested_reference=reference,
            image_id=image_id,
            repo_digests=repo_digests,
            os=str(item.get("Os") or "").strip() or None,
            architecture=str(item.get("Architecture") or "").strip() or None,
        )

    def create(self, args: Sequence[str]) -> DockerCommandResult:
        return self._control(("create", *tuple(args)), timeout_seconds=20.0)

    def start_attached(
        self,
        container_name: str,
        *,
        timeout_seconds: float,
        stdout_max_bytes: int,
        stderr_max_bytes: int,
    ) -> DockerCommandResult:
        return run_bounded_command(
            (self.binary, "start", "--attach", str(container_name)),
            timeout_seconds=timeout_seconds,
            stdout_max_bytes=stdout_max_bytes,
            stderr_max_bytes=stderr_max_bytes,
        )

    def inspect_container_state(self, container_name: str) -> DockerContainerState:
        result = self._control(("container", "inspect", str(container_name)))
        if result.timed_out or result.returncode != 0:
            raise DockerCommandError(
                "Could not inspect Docker container state: %s"
                % (result.stderr.strip() or "container inspect failed")
            )
        try:
            payload = json.loads(result.stdout)
            state = payload[0]["State"]
        except (ValueError, TypeError, IndexError, KeyError) as exc:
            raise DockerCommandError("Docker container inspection returned invalid JSON") from exc
        exit_code = state.get("ExitCode")
        if exit_code is not None:
            try:
                exit_code = int(exit_code)
            except (TypeError, ValueError) as exc:
                raise DockerCommandError("Docker container exit code is invalid") from exc
        error = str(state.get("Error") or "").strip() or None
        return DockerContainerState(
            status=str(state.get("Status") or "").strip(),
            running=bool(state.get("Running")),
            exit_code=exit_code,
            oom_killed=bool(state.get("OOMKilled")),
            error=error,
        )

    def remove_force(self, container_name: str) -> Optional[str]:
        result = self._control(
            ("container", "rm", "--force", str(container_name)),
            timeout_seconds=10.0,
        )
        if result.timed_out:
            return "Docker container cleanup timed out"
        if result.returncode != 0:
            text = result.stderr.strip()
            # A concurrent/previous cleanup leaving no container is harmless.
            lowered = text.lower()
            if "no such container" in lowered:
                return None
            return text or "Docker container cleanup failed"
        return None



def safe_container_name(run_id: str) -> str:
    """Return a deterministic Docker-safe container name for one run ID."""

    import re

    raw = str(run_id or "").strip()
    if not raw:
        raise ValueError("run_id must not be empty")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")
    if not cleaned:
        cleaned = "run"
    return ("grading-app-%s" % cleaned)[:120]


def build_docker_create_args(
    *,
    container_name: str,
    image_reference: str,
    submission_dir: str,
    grader_dir: str,
    output_dir: str,
    entrypoint: str,
    memory_mb: Optional[int],
    cpu_count: Optional[float],
    pids_limit: Optional[int],
    runtime_user: str = "65534:65534",
    interpreter_command: str = "python",
    tmpfs_size_mb: int = 64,
) -> Tuple[str, ...]:
    """Build hardened ``docker create`` arguments for a smoke execution."""

    name = str(container_name or "").strip()
    image = str(image_reference or "").strip()
    user = str(runtime_user or "").strip()
    interpreter = str(interpreter_command or "").strip()
    if not all((name, image, user, interpreter)):
        raise ValueError("container/image/user/interpreter values must not be empty")
    if isinstance(tmpfs_size_mb, bool) or int(tmpfs_size_mb) <= 0:
        raise ValueError("tmpfs_size_mb must be positive")

    args = [
        "--name", name,
        "--pull=never",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", user,
        "--workdir", "/workspace/submission",
        "--env", "HOME=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "PYTHONNOUSERSITE=1",
        "--env", "PYTHONUNBUFFERED=1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=%dm,mode=1777" % int(tmpfs_size_mb),
        "--mount", "type=bind,src=%s,dst=/workspace/submission,readonly" % str(submission_dir),
        "--mount", "type=bind,src=%s,dst=/workspace/grader,readonly" % str(grader_dir),
        "--mount", "type=bind,src=%s,dst=/workspace/output" % str(output_dir),
    ]
    if memory_mb is not None:
        args.extend(("--memory", "%dm" % int(memory_mb)))
        # Setting memory-swap equal to memory prevents additional container swap.
        args.extend(("--memory-swap", "%dm" % int(memory_mb)))
    if cpu_count is not None:
        args.extend(("--cpus", str(float(cpu_count))))
    if pids_limit is not None:
        args.extend(("--pids-limit", str(int(pids_limit))))

    normalized_entrypoint = str(entrypoint or "").replace("\\", "/").lstrip("/")
    if not normalized_entrypoint or ".." in normalized_entrypoint.split("/"):
        raise ValueError("entrypoint must be a safe relative path")
    args.extend((
        image,
        interpreter,
        "-B",
        "-u",
        "/workspace/submission/%s" % normalized_entrypoint,
    ))
    return tuple(args)

__all__ = [
    "DEFAULT_DOCKER_COMMAND_TIMEOUT_SECONDS",
    "DockerCLI",
    "DockerCommandResult",
    "DockerContainerState",
    "DockerImageInfo",
    "build_docker_create_args",
    "run_bounded_command",
    "safe_container_name",
]
