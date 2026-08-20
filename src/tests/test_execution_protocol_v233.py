import unittest

from src.autograding.errors import ExecutionResultProtocolError
from src.autograding.execution import BackendExecutionRecord, validate_execution_result
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_RUNNING,
    ExecutionEnvironment,
    ExecutionResult,
    ResourceLimits,
)


class TestExecutionResultProtocol(unittest.TestCase):
    def _environment(self, backend="fake"):
        return ExecutionEnvironment(
            environment_id="env-1",
            backend=backend,
            language="python",
        )

    def test_terminal_completed_result_is_valid(self):
        result = ExecutionResult(status=EXECUTION_STATUS_COMPLETED, exit_code=0)
        self.assertIs(validate_execution_result(result), result)

    def test_completed_requires_exit_code(self):
        result = ExecutionResult(status=EXECUTION_STATUS_COMPLETED)
        with self.assertRaisesRegex(ExecutionResultProtocolError, "exit_code"):
            validate_execution_result(result)

    def test_nonterminal_result_is_rejected_by_default(self):
        result = ExecutionResult(status=EXECUTION_STATUS_RUNNING)
        with self.assertRaisesRegex(ExecutionResultProtocolError, "non-terminal"):
            validate_execution_result(result)

    def test_nonterminal_result_can_be_validated_for_intermediate_use(self):
        result = ExecutionResult(status=EXECUTION_STATUS_RUNNING)
        self.assertIs(
            validate_execution_result(result, require_terminal=False),
            result,
        )

    def test_backend_must_return_execution_result(self):
        with self.assertRaisesRegex(ExecutionResultProtocolError, "ExecutionResult"):
            validate_execution_result({"status": "completed"})

    def test_captured_output_must_fit_configured_limits(self):
        limits = ResourceLimits(stdout_max_bytes=4, stderr_max_bytes=4)
        result = ExecutionResult(
            status=EXECUTION_STATUS_ERROR,
            stdout="12345",
            stderr="",
        )
        with self.assertRaisesRegex(ExecutionResultProtocolError, "stdout"):
            validate_execution_result(result, resource_limits=limits)

    def test_output_limit_is_utf8_byte_based(self):
        limits = ResourceLimits(stdout_max_bytes=4, stderr_max_bytes=4)
        result = ExecutionResult(
            status=EXECUTION_STATUS_ERROR,
            stdout="ééé",
        )
        with self.assertRaisesRegex(ExecutionResultProtocolError, "stdout"):
            validate_execution_result(result, resource_limits=limits)

    def test_backend_execution_record_roundtrip(self):
        record = BackendExecutionRecord(
            run_id="agrun_1",
            backend_name="fake",
            environment=self._environment(),
            result=ExecutionResult(
                status=EXECUTION_STATUS_COMPLETED,
                exit_code=0,
            ),
            recorded_at="2026-08-19T20:11:00Z",
            metadata={"x": 1},
        )
        self.assertEqual(BackendExecutionRecord.from_dict(record.to_dict()), record)

    def test_backend_execution_record_checks_environment_backend(self):
        with self.assertRaisesRegex(ExecutionResultProtocolError, "backend"):
            BackendExecutionRecord(
                run_id="agrun_1",
                backend_name="fake",
                environment=self._environment(backend="other"),
                result=ExecutionResult(
                    status=EXECUTION_STATUS_COMPLETED,
                    exit_code=0,
                ),
            )

    def test_backend_execution_record_requires_terminal_result(self):
        with self.assertRaisesRegex(ExecutionResultProtocolError, "non-terminal"):
            BackendExecutionRecord(
                run_id="agrun_1",
                backend_name="fake",
                environment=self._environment(),
                result=ExecutionResult(status=EXECUTION_STATUS_RUNNING),
            )


if __name__ == "__main__":
    unittest.main()
