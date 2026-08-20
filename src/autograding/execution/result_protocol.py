"""Normalized execution-result protocol for v2.3.3 Commit 4.

Concrete backends must return the existing domain ``ExecutionResult`` rather
than backend-specific process objects.  This module adds backend-independent
protocol checks and a reproducibility envelope binding a result to the exact
runtime environment and execution-plan run ID.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from ..errors import ExecutionResultProtocolError
from ..models import (
    EXECUTION_STATUS_CANCELLED,
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
    EXECUTION_STATUS_PENDING,
    EXECUTION_STATUS_RUNNING,
    EXECUTION_STATUS_TIMEOUT,
    ExecutionEnvironment,
    ExecutionResult,
    ResourceLimits,
)


BACKEND_EXECUTION_RECORD_SCHEMA_VERSION = "1.0"

TERMINAL_EXECUTION_STATUSES = (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    EXECUTION_STATUS_CANCELLED,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
)
NONTERMINAL_EXECUTION_STATUSES = (
    EXECUTION_STATUS_PENDING,
    EXECUTION_STATUS_RUNNING,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        raise ExecutionResultProtocolError("%s must not be empty" % name)
    return value


def _utf8_size(text: str) -> int:
    return len(str(text or "").encode("utf-8"))


def validate_execution_result(
    result: ExecutionResult,
    *,
    resource_limits: Optional[ResourceLimits] = None,
    require_terminal: bool = True,
) -> ExecutionResult:
    """Validate one backend result against the stable process-level protocol."""

    if not isinstance(result, ExecutionResult):
        raise ExecutionResultProtocolError(
            "execution backend must return an ExecutionResult"
        )
    if not isinstance(require_terminal, bool):
        raise TypeError("require_terminal must be a bool")
    if resource_limits is not None and not isinstance(resource_limits, ResourceLimits):
        raise TypeError("resource_limits must be ResourceLimits or None")

    if require_terminal and result.status not in TERMINAL_EXECUTION_STATUSES:
        raise ExecutionResultProtocolError(
            "execution backend returned non-terminal status %r" % result.status
        )

    if result.status == EXECUTION_STATUS_COMPLETED and result.exit_code is None:
        raise ExecutionResultProtocolError(
            "completed execution results must include an exit_code"
        )

    if resource_limits is not None:
        stdout_size = _utf8_size(result.stdout)
        stderr_size = _utf8_size(result.stderr)
        if stdout_size > resource_limits.stdout_max_bytes:
            raise ExecutionResultProtocolError(
                "stdout exceeds the configured captured-output limit"
            )
        if stderr_size > resource_limits.stderr_max_bytes:
            raise ExecutionResultProtocolError(
                "stderr exceeds the configured captured-output limit"
            )

    return result


@dataclass(frozen=True)
class BackendExecutionRecord:
    """Backend-independent evidence envelope for one execution attempt."""

    run_id: str
    backend_name: str
    environment: ExecutionEnvironment
    result: ExecutionResult
    recorded_at: str = field(default_factory=_utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        run_id = _text(self.run_id, "run_id")
        backend_name = _text(self.backend_name, "backend_name")
        recorded_at = _text(self.recorded_at, "recorded_at")
        if not isinstance(self.environment, ExecutionEnvironment):
            raise ExecutionResultProtocolError(
                "environment must be an ExecutionEnvironment"
            )
        if not isinstance(self.result, ExecutionResult):
            raise ExecutionResultProtocolError("result must be an ExecutionResult")
        if self.environment.backend != backend_name:
            raise ExecutionResultProtocolError(
                "environment backend does not match backend_name"
            )
        validate_execution_result(self.result, require_terminal=True)
        if not isinstance(self.metadata, Mapping):
            raise ExecutionResultProtocolError("metadata must be a mapping")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "backend_name", backend_name)
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": BACKEND_EXECUTION_RECORD_SCHEMA_VERSION,
            "run_id": self.run_id,
            "backend_name": self.backend_name,
            "environment": self.environment.to_dict(),
            "result": self.result.to_dict(),
            "recorded_at": self.recorded_at,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackendExecutionRecord":
        if not isinstance(data, Mapping):
            raise ExecutionResultProtocolError(
                "BackendExecutionRecord data must be a mapping"
            )
        version = data.get("schema_version")
        if version is not None and str(version) != BACKEND_EXECUTION_RECORD_SCHEMA_VERSION:
            raise ExecutionResultProtocolError(
                "Unsupported backend-execution-record schema %r; expected %r"
                % (version, BACKEND_EXECUTION_RECORD_SCHEMA_VERSION)
            )
        return cls(
            run_id=data.get("run_id"),
            backend_name=data.get("backend_name"),
            environment=ExecutionEnvironment.from_dict(data.get("environment") or {}),
            result=ExecutionResult.from_dict(data.get("result") or {}),
            recorded_at=data.get("recorded_at") or _utc_now_iso(),
            metadata=data.get("metadata", {}),
        )


__all__ = [
    "BACKEND_EXECUTION_RECORD_SCHEMA_VERSION",
    "BackendExecutionRecord",
    "NONTERMINAL_EXECUTION_STATUSES",
    "TERMINAL_EXECUTION_STATUSES",
    "validate_execution_result",
]
