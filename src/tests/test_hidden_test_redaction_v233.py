import unittest

from src.autograding.models import TestResult
from src.autograding.testing import redact_test_result_for_student


class TestHiddenTestRedaction(unittest.TestCase):
    def hidden(self):
        return TestResult(
            test_id="hidden_edge",
            status="failed",
            visibility="hidden",
            group_id="edge",
            display_name="Secret duplicate-values case",
            duration_ms=5,
            message="assert secret_answer == 17",
            traceback="/workspace/grader/tests/test_hidden.py:9 secret_answer=16",
            stdout="student printed hidden source",
            stderr="secret stderr",
            points_possible=3,
            metadata={"pytest_nodeids": ["tests/test_hidden.py::test_duplicates"]},
        )

    def test_hidden_details_are_never_exposed_to_student_safe_result(self):
        redacted = redact_test_result_for_student(self.hidden(), {})
        self.assertEqual(redacted.display_name, "Hidden test")
        self.assertNotEqual(redacted.test_id, "hidden_edge")
        self.assertTrue(redacted.test_id.startswith("hidden_"))
        self.assertIsNone(redacted.group_id)
        self.assertEqual(redacted.message, "Hidden test did not pass.")
        self.assertIsNone(redacted.traceback)
        self.assertEqual(redacted.stdout, "")
        self.assertEqual(redacted.stderr, "")
        self.assertNotIn("pytest_nodeids", redacted.metadata)

    def test_policy_may_show_hidden_name_but_not_hidden_diagnostics(self):
        redacted = redact_test_result_for_student(
            self.hidden(),
            {"show_hidden_test_names_to_students": True},
        )
        self.assertEqual(redacted.display_name, "Secret duplicate-values case")
        self.assertNotEqual(redacted.test_id, "hidden_edge")
        self.assertIsNone(redacted.traceback)
        self.assertEqual(redacted.stdout, "")
        self.assertNotIn("secret_answer", redacted.message)

    def test_public_details_follow_reporting_policy(self):
        public = TestResult(
            test_id="public_basic",
            status="failed",
            visibility="public",
            display_name="Basic input",
            message="expected 3, got 4",
            traceback="public trace",
            stdout="public stdout",
            points_possible=2,
        )
        detailed = redact_test_result_for_student(public, {"show_public_test_details": True})
        self.assertEqual(detailed.traceback, "public trace")
        hidden = redact_test_result_for_student(public, {"show_public_test_details": False})
        self.assertIsNone(hidden.traceback)
        self.assertEqual(hidden.stdout, "")


if __name__ == "__main__":
    unittest.main()
