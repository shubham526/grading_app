"""Execution-backend availability records for v2.3.3 Commit 4.

Availability is intentionally modeled as data rather than as a bare boolean so
later UI/service layers can explain *why* autograding is unavailable without
attempting unsafe fallbacks.  This module does not import Docker, subprocess,
pytest, or any concrete execution backend.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ..errors import ExecutionBackendContractError


EXECUTION_AVAILABILITY_SCHEMA_VERSION = "1.0"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        raise ExecutionBackendContractError("%s must not be empty" % name)
    return value


@dataclass(frozen=True)
class BackendAvailability:
    """One immutable backend-availability probe result."""

    backend: str
    available: bool
    checked_at: str = field(default_factory=_utc_now_iso)
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        backend = _text(self.backend, "backend")
        checked_at = _text(self.checked_at, "checked_at")
        if not isinstance(self.available, bool):
            raise ExecutionBackendContractError("available must be boolean")
        reason = None if self.reason is None else str(self.reason).strip() or None
        if not self.available and reason is None:
            raise ExecutionBackendContractError(
                "unavailable backend probes must include a reason"
            )
        if not isinstance(self.details, Mapping):
            raise ExecutionBackendContractError("details must be a mapping")
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "checked_at", checked_at)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "details", deepcopy(dict(self.details)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": EXECUTION_AVAILABILITY_SCHEMA_VERSION,
            "backend": self.backend,
            "available": self.available,
            "checked_at": self.checked_at,
            "reason": self.reason,
            "details": deepcopy(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackendAvailability":
        if not isinstance(data, Mapping):
            raise ExecutionBackendContractError(
                "BackendAvailability data must be a mapping"
            )
        version = data.get("schema_version")
        if version is not None and str(version) != EXECUTION_AVAILABILITY_SCHEMA_VERSION:
            raise ExecutionBackendContractError(
                "Unsupported backend-availability schema %r; expected %r"
                % (version, EXECUTION_AVAILABILITY_SCHEMA_VERSION)
            )
        return cls(
            backend=data.get("backend"),
            available=data.get("available"),
            checked_at=data.get("checked_at") or _utc_now_iso(),
            reason=data.get("reason"),
            details=data.get("details", {}),
        )


def probe_backends(backends: Iterable[Any]) -> Tuple[BackendAvailability, ...]:
    """Probe an ordered backend collection without selecting or executing one.

    Objects are intentionally duck-typed here to avoid an import cycle with the
    abstract base class.  Every object must expose ``probe_availability()`` and
    return :class:`BackendAvailability`.
    """

    results = []
    for backend in tuple(backends or ()):
        probe = getattr(backend, "probe_availability", None)
        if not callable(probe):
            raise ExecutionBackendContractError(
                "execution backend does not provide probe_availability()"
            )
        result = probe()
        if not isinstance(result, BackendAvailability):
            raise ExecutionBackendContractError(
                "probe_availability() must return BackendAvailability"
            )
        results.append(result)
    return tuple(results)


__all__ = [
    "BackendAvailability",
    "EXECUTION_AVAILABILITY_SCHEMA_VERSION",
    "probe_backends",
]
