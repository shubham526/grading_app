from pathlib import Path
import tempfile
import unittest

from src.autograding.errors import PytestResultProtocolError
from src.autograding.testing.result_parser import (
    protocol_test_results,
    validate_pytest_protocol_payload,
)
from src.tests.autograding_v233_execution_support import build_test_execution_plan


class TestPytestResultParser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plan = build_test_execution_plan(Path(self.tmp.name) / "plan")

    def payload(self, **overrides):
        payload = {
            "schema_version": "1.0",
            "runner": "pytest",
            "pytest_version": "9.1.1",
            "pytest_exit_code": 0,
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
                    "status": "passed",
                    "duration_ms": 12,
                    "message": None,
                    "traceback": None,
                    "stdout": "hello\n",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "nodeids": ["tests/test_fixture.py::test_fixture"],
                    "item_count": 1,
                    "timeout_seconds": None,
                }
            ],
        }
        payload.update(overrides)
        return payload

    def test_valid_payload_maps_to_domain_test_result_without_scoring(self):
        payload = self.payload()
        results, diagnostics = protocol_test_results(payload, self.plan)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.test_id, "test_fixture")
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.points_possible, 10.0)
        self.assertIsNone(result.points_awarded)
        self.assertEqual(result.stdout, "hello\n")
        self.assertFalse(diagnostics["missing_test_ids"])

    def test_failed_timeout_error_skip_xfail_xpass_are_supported(self):
        for status in ("failed", "timeout", "error", "skipped", "xfail", "xpass"):
            payload = self.payload()
            payload["tests"][0]["status"] = status
            results, _ = protocol_test_results(payload, self.plan)
            self.assertEqual(results[0].status, status)

    def test_unknown_test_id_is_rejected(self):
        payload = self.payload()
        payload["tests"][0]["test_id"] = "unknown"
        with self.assertRaisesRegex(PytestResultProtocolError, "unknown"):
            protocol_test_results(payload, self.plan)

    def test_missing_test_becomes_infrastructure_error(self):
        payload = self.payload(tests=[])
        results, diagnostics = protocol_test_results(payload, self.plan)
        self.assertEqual(results[0].status, "infrastructure_error")
        self.assertEqual(diagnostics["missing_test_ids"], ["test_fixture"])

    def test_duplicate_protocol_ids_are_rejected(self):
        payload = self.payload()
        payload["tests"].append(dict(payload["tests"][0]))
        with self.assertRaisesRegex(PytestResultProtocolError, "duplicate"):
            validate_pytest_protocol_payload(payload)

    def test_wrong_protocol_version_is_rejected(self):
        with self.assertRaisesRegex(PytestResultProtocolError, "Unsupported"):
            validate_pytest_protocol_payload(self.payload(schema_version="999"))


if __name__ == "__main__":
    unittest.main()
