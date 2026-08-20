"""Shared service fixtures for v2.3.3 Commit 9 tests."""

from pathlib import Path

from src.autograding.execution.availability import BackendAvailability
from src.autograding.repository import AutogradingRunRepository
from src.autograding.service import AutogradingService
from src.tests.autograding_v233_persistence_support import (
    ASSESSMENT_ID,
    STUDENT_ID,
    make_pytest_result,
    prepare_workspace,
)


class StubBackend:
    def __init__(self, *, image="test-image", expected_pytest_version=None, available=True, reason=None):
        self.image = image
        self.expected_pytest_version = expected_pytest_version
        self._available = bool(available)
        self._reason = reason

    def availability(self):
        return BackendAvailability(
            backend="stub_pytest",
            available=self._available,
            reason=None if self._available else (self._reason or "stub unavailable"),
            details={"image": self.image},
        )


class BackendFactory:
    def __init__(self, *, available=True, reason=None):
        self.available = available
        self.reason = reason
        self.instances = []

    def __call__(self, **kwargs):
        backend = StubBackend(available=self.available, reason=self.reason, **kwargs)
        self.instances.append(backend)
        return backend


def prepare_service(base, *, pytest_result_factory=None, backend_factory=None):
    workspace, submission_repository, bundle_store, bundle, submission = prepare_workspace(base)
    run_repository = AutogradingRunRepository(workspace)
    factory = backend_factory or BackendFactory()

    def executor(plan, _backend):
        if pytest_result_factory is not None:
            return pytest_result_factory(plan)
        return make_pytest_result(plan)

    service = AutogradingService(
        str(workspace),
        submission_repository=submission_repository,
        bundle_store=bundle_store,
        run_repository=run_repository,
        backend_factory=factory,
        pytest_executor=executor,
        default_image="test-runtime:1",
        expected_pytest_version="9.1.1",
    )
    return service, bundle, submission, factory


__all__ = [
    "ASSESSMENT_ID",
    "STUDENT_ID",
    "BackendFactory",
    "StubBackend",
    "prepare_service",
]
