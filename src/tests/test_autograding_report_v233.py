import json
import tempfile
import unittest

from src.autograding.reporting import (
    build_history_report,
    build_instructor_run_report,
    build_student_safe_run_report,
)
from src.autograding.repository import AutogradingRunRepository
from src.tests.autograding_v233_persistence_support import (
    ASSESSMENT_ID,
    STUDENT_ID,
    make_plan,
    make_pytest_result,
    make_scored_result,
    prepare_workspace,
)


class TestAutogradingRunReporting(unittest.TestCase):
    def _stored(self, td):
        workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
        plan = make_plan(submissions, bundle_store, bundle)
        result = make_pytest_result(plan)
        repo = AutogradingRunRepository(workspace)
        stored = repo.commit_run(plan, result, make_scored_result(plan, result))
        return repo, stored

    def test_instructor_report_contains_full_diagnostics_and_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            _, stored = self._stored(td)
            report = build_instructor_run_report(stored)
            text = json.dumps(report)
            self.assertIn("test_hidden", text)
            self.assertIn("SECRET TRACEBACK", text)
            self.assertIn("docker-env-commit8", text)
            self.assertIn(stored.run.provenance.bundle_sha256, text)
            self.assertEqual(report["score"]["final_score"], 4.0)

    def test_student_safe_report_never_leaks_hidden_or_runtime_identity(self):
        with tempfile.TemporaryDirectory() as td:
            _, stored = self._stored(td)
            report = build_student_safe_run_report(stored)
            text = json.dumps(report)
            self.assertNotIn("test_hidden", text)
            self.assertNotIn("SECRET TRACEBACK", text)
            self.assertNotIn("SECRET HIDDEN", text)
            self.assertNotIn("docker-env-commit8", text)
            self.assertNotIn(stored.run.provenance.bundle_sha256, text)
            hidden = next(item for item in report["tests"] if item["visibility"] == "hidden")
            self.assertTrue(hidden["test_id"].startswith("hidden_"))
            self.assertEqual(hidden["points_possible"], 6.0)
            self.assertEqual(hidden["points_awarded"], 0.0)

    def test_history_report_is_compact_and_chronological(self):
        with tempfile.TemporaryDirectory() as td:
            repo, stored = self._stored(td)
            report = build_history_report(repo.list_run_references(ASSESSMENT_ID, STUDENT_ID))
            self.assertEqual(report["run_count"], 1)
            row = report["runs"][0]
            self.assertEqual(row["run_id"], stored.run.run_id)
            self.assertEqual(row["final_score"], 4.0)
            self.assertIn("container_image_digest", row)
            self.assertNotIn("tests", row)


if __name__ == "__main__":
    unittest.main()
