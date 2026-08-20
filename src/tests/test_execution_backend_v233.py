from pathlib import Path
import tempfile
import unittest

from src.autograding.errors import (
    ExecutionBackendContractError,
    ExecutionBackendUnavailableError,
    ExecutionResultProtocolError,
    HostExecutionDisabledError,
)
from src.autograding.execution import (
    BACKEND_SECURITY_PROFILE_HOST,
    BACKEND_SECURITY_PROFILE_ISOLATED,
    BackendAvailability,
    ExecutionBackend,
)
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_RUNNING,
    ExecutionEnvironment,
    ExecutionResult,
)
from src.tests.autograding_v233_execution_support import (
    FakeExecutionBackend,
    build_test_execution_plan,
)


class TestExecutionBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = build_test_execution_plan(self.root)

    def test_fake_backend_execute_returns_validated_result(self):
        backend = FakeExecutionBackend()
        result = backend.execute(self.plan)
        self.assertEqual(result.status, EXECUTION_STATUS_COMPLETED)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(backend.execute_calls, [("agrun_fixture", "fake-env-1")])

    def test_run_returns_environment_bound_record(self):
        backend = FakeExecutionBackend()
        record = backend.run(
            self.plan,
            recorded_at_fn=lambda: "2026-08-19T20:20:00Z",
        )
        self.assertEqual(record.run_id, self.plan.run_id)
        self.assertEqual(record.backend_name, backend.backend_name)
        self.assertEqual(record.environment.environment_id, "fake-env-1")
        self.assertEqual(record.result.exit_code, 0)
        self.assertEqual(record.metadata["submission_id"], "sub_fixture")
        self.assertEqual(record.metadata["bundle_id"], "bundle_fixture")

    def test_unavailable_backend_fails_before_environment_or_execution(self):
        backend = FakeExecutionBackend(
            available=False,
            availability_reason="runtime unavailable",
        )
        with self.assertRaisesRegex(ExecutionBackendUnavailableError, "runtime unavailable"):
            backend.execute(self.plan)
        self.assertEqual(backend.environment_calls, [])
        self.assertEqual(backend.execute_calls, [])

    def test_environment_backend_must_match_backend_identity(self):
        backend = FakeExecutionBackend(
            environment=ExecutionEnvironment(
                environment_id="wrong",
                backend="other",
                language="python",
            )
        )
        with self.assertRaisesRegex(ExecutionBackendContractError, "backend"):
            backend.execute(self.plan)
        self.assertEqual(backend.execute_calls, [])

    def test_environment_language_must_match_plan(self):
        backend = FakeExecutionBackend(
            environment=ExecutionEnvironment(
                environment_id="wrong-language",
                backend="fake_isolated",
                language="java",
            )
        )
        with self.assertRaisesRegex(ExecutionBackendContractError, "language"):
            backend.execute(self.plan)
        self.assertEqual(backend.execute_calls, [])

    def test_backend_availability_identity_is_checked(self):
        class BadAvailabilityBackend(FakeExecutionBackend):
            def probe_availability(self):
                return BackendAvailability(backend="other", available=True)

        backend = BadAvailabilityBackend()
        with self.assertRaisesRegex(ExecutionBackendContractError, "availability backend"):
            backend.execute(self.plan)

    def test_direct_host_security_profile_is_blocked_before_probe(self):
        backend = FakeExecutionBackend(security_profile=BACKEND_SECURITY_PROFILE_HOST)
        with self.assertRaisesRegex(HostExecutionDisabledError, "Direct host execution"):
            backend.execute(self.plan)
        self.assertEqual(backend.probe_count, 0)
        self.assertEqual(backend.execute_calls, [])

    def test_unknown_security_profile_is_rejected(self):
        backend = FakeExecutionBackend(security_profile="mystery")
        with self.assertRaisesRegex(ExecutionBackendContractError, "security profile"):
            backend.execute(self.plan)

    def test_production_isolated_profile_is_accepted_by_contract(self):
        backend = FakeExecutionBackend(security_profile=BACKEND_SECURITY_PROFILE_ISOLATED)
        self.assertTrue(backend.is_available())

    def test_backend_result_type_is_enforced(self):
        class BadResultBackend(FakeExecutionBackend):
            def _execute_plan(self, plan, environment):
                return {"status": "completed"}

        with self.assertRaisesRegex(ExecutionResultProtocolError, "ExecutionResult"):
            BadResultBackend().execute(self.plan)

    def test_backend_result_must_be_terminal(self):
        backend = FakeExecutionBackend(
            results=[ExecutionResult(status=EXECUTION_STATUS_RUNNING)]
        )
        with self.assertRaisesRegex(ExecutionResultProtocolError, "non-terminal"):
            backend.execute(self.plan)

    def test_backend_result_respects_output_caps(self):
        plan = build_test_execution_plan(
            self.root / "small-cap",
            stdout_max_bytes=4,
        )
        backend = FakeExecutionBackend(
            results=[
                ExecutionResult(
                    status=EXECUTION_STATUS_COMPLETED,
                    exit_code=0,
                    stdout="12345",
                )
            ]
        )
        with self.assertRaisesRegex(ExecutionResultProtocolError, "stdout"):
            backend.execute(plan)

    def test_fake_backend_does_not_execute_student_or_grader_source(self):
        backend = FakeExecutionBackend()
        backend.execute(self.plan)
        self.assertFalse((self.root / "STUDENT_CODE_WAS_EXECUTED").exists())
        self.assertFalse((self.root / "GRADER_CODE_WAS_EXECUTED").exists())
        self.assertFalse(Path.cwd().joinpath("STUDENT_CODE_WAS_EXECUTED").exists())
        self.assertFalse(Path.cwd().joinpath("GRADER_CODE_WAS_EXECUTED").exists())

    def test_abstract_contract_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            ExecutionBackend()


if __name__ == "__main__":
    unittest.main()
