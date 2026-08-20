import json
from pathlib import Path
import tempfile
import unittest

from src.autograding.execution import BackendExecutionRecord
from src.autograding.models import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    ExecutionEnvironment,
    ExecutionResult,
)
from src.autograding.testing import (
    build_pytest_runtime_config,
    execute_pytest_plan,
    student_safe_pytest_summary,
)
from src.tests.autograding_v233_execution_support import (
    FakeExecutionBackend,
    build_test_execution_plan,
)


class TestPytestAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plan = build_test_execution_plan(Path(self.tmp.name) / "plan")

    def protocol(self, status="passed"):
        return {
            "schema_version": "1.0",
            "runner": "pytest",
            "pytest_version": "9.1.1",
            "pytest_exit_code": 0 if status == "passed" else 1,
            "collected_count": 1,
            "selected_count": 1,
            "deselected_count": 0,
            "selection_errors": [],
            "collection_errors": [],
            "tests": [
                {
                    "test_id": "test_fixture",
                    "selector": "test_fixture",
                    "visibility": "hidden",
                    "group_id": None,
                    "display_name": "Fixture",
                    "status": status,
                    "duration_ms": 8,
                    "message": None if status == "passed" else "failure",
                    "traceback": None if status == "passed" else "trace",
                    "stdout": "",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "nodeids": ["tests/test_fixture.py::test_fixture"],
                    "item_count": 1,
                    "timeout_seconds": None,
                }
            ],
        }

    def backend_for(self, result):
        return FakeExecutionBackend(results=[result])

    def test_runtime_config_uses_stable_id_and_visibility(self):
        payload = build_pytest_runtime_config(self.plan)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["tests"][0]["test_id"], "test_fixture")
        self.assertEqual(payload["tests"][0]["selector"], "test_fixture")
        self.assertEqual(payload["tests"][0]["visibility"], "hidden")

    def test_completed_protocol_returns_structured_test_results_without_score(self):
        execution = ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=0,
            metadata={"pytest_protocol": self.protocol("passed")},
        )
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        self.assertEqual(run.pytest_version, "9.1.1")
        self.assertTrue(run.all_tests_passed)
        self.assertIsNone(run.test_results[0].points_awarded)
        self.assertFalse(run.requires_review)

    def test_student_safe_summary_omits_backend_and_hidden_identity(self):
        payload = self.protocol("failed")
        payload["tests"][0]["message"] = "secret assertion"
        payload["tests"][0]["traceback"] = "/workspace/grader/secret.py"
        execution = ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=1,
            stdout="backend secret output",
            metadata={"pytest_protocol": payload, "secret_backend": "do not publish"},
        )
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        safe = student_safe_pytest_summary(run, self.plan.config.reporting_policy)
        encoded = json.dumps(safe)
        self.assertNotIn("secret assertion", encoded)
        self.assertNotIn("/workspace/grader", encoded)
        self.assertNotIn("backend secret output", encoded)
        self.assertNotIn("secret_backend", encoded)
        self.assertNotIn("test_fixture", encoded)

    def test_normal_pytest_failure_is_not_infrastructure_failure(self):
        execution = ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=1,
            metadata={"pytest_protocol": self.protocol("failed")},
        )
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        self.assertEqual(run.test_results[0].status, "failed")
        self.assertFalse(run.requires_review)

    def test_missing_protocol_requires_review_and_never_assigns_zero(self):
        execution = ExecutionResult(status=EXECUTION_STATUS_COMPLETED, exit_code=1)
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        self.assertTrue(run.requires_review)
        self.assertEqual(run.test_results[0].status, "infrastructure_error")
        self.assertIsNone(run.test_results[0].points_awarded)

    def test_overall_wall_timeout_is_explicit_and_requires_review(self):
        execution = ExecutionResult(
            status=EXECUTION_STATUS_TIMEOUT,
            exit_code=None,
            error_message="wall timeout",
        )
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        self.assertTrue(run.requires_review)
        self.assertEqual(run.test_results[0].status, "timeout")
        self.assertIsNone(run.test_results[0].points_awarded)

    def test_backend_infrastructure_error_is_not_student_failure(self):
        execution = ExecutionResult(
            status=EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
            error_message="Docker unavailable",
        )
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        self.assertEqual(run.test_results[0].status, "infrastructure_error")
        self.assertTrue(run.requires_review)
        self.assertIsNone(run.test_results[0].points_awarded)

    def test_collection_error_requires_review(self):
        payload = self.protocol("passed")
        payload["collection_errors"] = [{"nodeid": "tests/test_fixture.py", "message": "import failed"}]
        execution = ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=2,
            metadata={"pytest_protocol": payload},
        )
        run = execute_pytest_plan(self.plan, self.backend_for(execution))
        self.assertTrue(run.requires_review)
        self.assertIn("collection", run.review_reason)


if __name__ == "__main__":
    unittest.main()
