"""Abstract isolated execution-backend contract for v2.3.3 Commit 4.

This commit deliberately provides *no concrete backend capable of running
student code*.  The contract requires a declared isolation security profile,
checks availability before dispatch, validates runtime identity, and normalizes
results through the stable domain protocol.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Tuple

from ..errors import (
    ExecutionBackendContractError,
    ExecutionBackendUnavailableError,
    HostExecutionDisabledError,
)
from ..models import ExecutionEnvironment, ExecutionResult
from ..planner import ExecutionPlan
from .availability import BackendAvailability
from .result_protocol import BackendExecutionRecord, validate_execution_result


BACKEND_SECURITY_PROFILE_ISOLATED = "isolated"
BACKEND_SECURITY_PROFILE_TEST_FAKE = "test_fake"
BACKEND_SECURITY_PROFILE_HOST = "host"
ALLOWED_BACKEND_SECURITY_PROFILES = (
    BACKEND_SECURITY_PROFILE_ISOLATED,
    BACKEND_SECURITY_PROFILE_TEST_FAKE,
)


def _text(value: Any, name: str) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        raise ExecutionBackendContractError("%s must not be empty" % name)
    return value


class ExecutionBackend(ABC):
    """Base contract implemented by every future isolated execution backend."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Stable backend identifier persisted in execution provenance."""

    @property
    @abstractmethod
    def security_profile(self) -> str:
        """Return ``isolated`` for production backends or ``test_fake`` in tests."""

    @abstractmethod
    def probe_availability(self) -> BackendAvailability:
        """Return a non-destructive availability probe."""

    @abstractmethod
    def describe_environment(self, plan: ExecutionPlan) -> ExecutionEnvironment:
        """Describe the exact runtime identity that would execute ``plan``."""

    @abstractmethod
    def _execute_plan(
        self,
        plan: ExecutionPlan,
        environment: ExecutionEnvironment,
    ) -> ExecutionResult:
        """Backend-specific execution hook.

        Commit 4 supplies no production implementation.  Commit 5's isolated
        container backend will implement this method.
        """

    def _validated_identity(self) -> Tuple[str, str]:
        name = _text(self.backend_name, "backend_name")
        profile = _text(self.security_profile, "security_profile").lower()
        if profile == BACKEND_SECURITY_PROFILE_HOST:
            raise HostExecutionDisabledError(
                "Direct host execution of student code is disabled. Configure a supported isolated execution backend."
            )
        if profile not in ALLOWED_BACKEND_SECURITY_PROFILES:
            raise ExecutionBackendContractError(
                "Unsupported execution-backend security profile %r; expected one of: %s"
                % (profile, ", ".join(ALLOWED_BACKEND_SECURITY_PROFILES))
            )
        return name, profile

    def availability(self) -> BackendAvailability:
        """Return a validated availability result for this backend."""

        name, _profile = self._validated_identity()
        result = self.probe_availability()
        if not isinstance(result, BackendAvailability):
            raise ExecutionBackendContractError(
                "probe_availability() must return BackendAvailability"
            )
        if result.backend != name:
            raise ExecutionBackendContractError(
                "availability backend does not match backend_name"
            )
        return result

    def is_available(self) -> bool:
        return self.availability().available

    def _prepare(self, plan: ExecutionPlan) -> ExecutionEnvironment:
        if not isinstance(plan, ExecutionPlan):
            raise TypeError("plan must be an ExecutionPlan")
        name, _profile = self._validated_identity()
        availability = self.availability()
        if not availability.available:
            raise ExecutionBackendUnavailableError(
                "Autograding execution backend %r is unavailable: %s"
                % (name, availability.reason)
            )

        environment = self.describe_environment(plan)
        if not isinstance(environment, ExecutionEnvironment):
            raise ExecutionBackendContractError(
                "describe_environment() must return ExecutionEnvironment"
            )
        if environment.backend != name:
            raise ExecutionBackendContractError(
                "execution environment backend does not match backend_name"
            )
        if environment.language != plan.language:
            raise ExecutionBackendContractError(
                "execution environment language %r does not match plan language %r"
                % (environment.language, plan.language)
            )
        return environment

    def _execute_checked(
        self,
        plan: ExecutionPlan,
    ) -> Tuple[ExecutionEnvironment, ExecutionResult]:
        environment = self._prepare(plan)
        result = self._execute_plan(plan, environment)
        validate_execution_result(
            result,
            resource_limits=plan.resource_limits,
            require_terminal=True,
        )
        return environment, result

    def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """Execute via the backend contract and return only the process result."""

        _environment, result = self._execute_checked(plan)
        return result

    def run(
        self,
        plan: ExecutionPlan,
        *,
        recorded_at_fn: Optional[Callable[[], str]] = None,
    ) -> BackendExecutionRecord:
        """Execute and return a reproducibility envelope with environment identity."""

        environment, result = self._execute_checked(plan)
        kwargs = {}
        if recorded_at_fn is not None:
            if not callable(recorded_at_fn):
                raise TypeError("recorded_at_fn must be callable or None")
            kwargs["recorded_at"] = _text(recorded_at_fn(), "recorded_at")
        return BackendExecutionRecord(
            run_id=plan.run_id,
            backend_name=self.backend_name,
            environment=environment,
            result=result,
            metadata={
                "security_profile": self.security_profile,
                "assessment_id": plan.assessment_id,
                "student_id": plan.student_id,
                "submission_id": plan.submission_id,
                "bundle_id": plan.bundle_reference.bundle_id,
            },
            **kwargs
        )


__all__ = [
    "ALLOWED_BACKEND_SECURITY_PROFILES",
    "BACKEND_SECURITY_PROFILE_HOST",
    "BACKEND_SECURITY_PROFILE_ISOLATED",
    "BACKEND_SECURITY_PROFILE_TEST_FAKE",
    "ExecutionBackend",
]
