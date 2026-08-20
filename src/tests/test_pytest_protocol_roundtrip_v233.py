from pathlib import Path
import tempfile
import unittest

from src.autograding.models import EXECUTION_STATUS_COMPLETED, ExecutionResult, TestResult
from src.autograding.testing import PytestRunResult
from src.tests.autograding_v233_execution_support import FakeExecutionBackend, build_test_execution_plan


class TestPytestProtocolRoundtrip(unittest.TestCase):
    def test_structured_run_roundtrips_for_future_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_test_execution_plan(Path(tmp) / "plan")
            backend = FakeExecutionBackend(
                results=[ExecutionResult(status=EXECUTION_STATUS_COMPLETED, exit_code=0)]
            )
            record = backend.run(plan)
            run = PytestRunResult(
                backend_record=record,
                test_results=(
                    TestResult(
                        test_id="test_fixture",
                        status="passed",
                        visibility="hidden",
                        display_name="Fixture",
                        points_possible=10,
                    ),
                ),
                pytest_exit_code=0,
                pytest_version="9.1.1",
                collected_count=1,
                selected_count=1,
            )
            restored = PytestRunResult.from_dict(run.to_dict())
            self.assertEqual(restored.to_dict(), run.to_dict())


if __name__ == "__main__":
    unittest.main()
