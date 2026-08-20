"""Execution backends for v2.3.3 programming autograding.

Commit 5 adds the first production backend capable of running student Python:
a hardened Docker CLI backend.  Direct host execution remains prohibited.
"""

from .availability import (
    BackendAvailability,
    EXECUTION_AVAILABILITY_SCHEMA_VERSION,
    probe_backends,
)
from .base import (
    ALLOWED_BACKEND_SECURITY_PROFILES,
    BACKEND_SECURITY_PROFILE_HOST,
    BACKEND_SECURITY_PROFILE_ISOLATED,
    BACKEND_SECURITY_PROFILE_TEST_FAKE,
    ExecutionBackend,
)
from .docker_backend import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_DOCKER_INTERPRETER,
    DEFAULT_DOCKER_RUNTIME_USER,
    DEFAULT_DOCKER_TMPFS_MB,
    DOCKER_BACKEND_NAME,
    DockerExecutionBackend,
)
from .docker_command import (
    DockerCLI,
    DockerCommandResult,
    DockerContainerState,
    DockerImageInfo,
    build_docker_create_args,
    run_bounded_command,
    safe_container_name,
)
from .result_protocol import (
    BACKEND_EXECUTION_RECORD_SCHEMA_VERSION,
    BackendExecutionRecord,
    NONTERMINAL_EXECUTION_STATUSES,
    TERMINAL_EXECUTION_STATUSES,
    validate_execution_result,
)
from .sandbox import MaterializedSandbox, SandboxMaterializer


__all__ = [
    "ALLOWED_BACKEND_SECURITY_PROFILES",
    "BACKEND_EXECUTION_RECORD_SCHEMA_VERSION",
    "BACKEND_SECURITY_PROFILE_HOST",
    "BACKEND_SECURITY_PROFILE_ISOLATED",
    "BACKEND_SECURITY_PROFILE_TEST_FAKE",
    "BackendAvailability",
    "BackendExecutionRecord",
    "DEFAULT_DOCKER_IMAGE",
    "DEFAULT_DOCKER_INTERPRETER",
    "DEFAULT_DOCKER_RUNTIME_USER",
    "DEFAULT_DOCKER_TMPFS_MB",
    "DOCKER_BACKEND_NAME",
    "DockerCLI",
    "DockerCommandResult",
    "DockerContainerState",
    "DockerExecutionBackend",
    "DockerImageInfo",
    "EXECUTION_AVAILABILITY_SCHEMA_VERSION",
    "ExecutionBackend",
    "MaterializedSandbox",
    "NONTERMINAL_EXECUTION_STATUSES",
    "SandboxMaterializer",
    "TERMINAL_EXECUTION_STATUSES",
    "build_docker_create_args",
    "probe_backends",
    "run_bounded_command",
    "safe_container_name",
    "validate_execution_result",
]
