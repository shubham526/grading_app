import unittest

from src.autograding.errors import ScoringInputError
from src.autograding.models import TestDefinition, TestResult
from src.autograding.config import AutogradingConfig
from src.autograding.policies import (
    SCORING_DECISION_REVIEW,
    TestOutcomeScoringPolicy,
)
from src.autograding.scoring import score_pytest_run
from src.autograding.testing.pytest_adapter import redact_test_result_for_student
from src.tests.autograding_v233_scoring_support import make_run


class TestAutogradingScoringReview(unittest.TestCase):
    def config(self):
        return AutogradingConfig(
            assessment_id="LABR", max_points=10, entrypoint="main.py",
            tests=(
                TestDefinition(test_id="public", name="Public", points=4, visibility="public"),
                TestDefinition(test_id="hidden", name="Hidden", points=6),
            ),
        )

    def test_infrastructure_error_never_becomes_student_zero(self):
        config = self.config()
        run = make_run(config, {"public": "passed", "hidden": "infrastructure_error"})
        scored = score_pytest_run(config, run)
        self.assertTrue(scored.score_summary.requires_review)
        self.assertIsNone(scored.score_summary.final_score)
        self.assertEqual(scored.test_by_id("public").points_awarded, 4.0)
        self.assertIsNone(scored.test_by_id("hidden").points_awarded)
        self.assertEqual(scored.score_summary.metadata["known_awarded_points"], 4.0)
        self.assertEqual(scored.score_summary.metadata["unresolved_points"], 6.0)

    def test_skipped_test_requires_review(self):
        config = self.config()
        run = make_run(config, {"public": "passed", "hidden": "skipped"})
        scored = score_pytest_run(config, run)
        self.assertIsNone(scored.score_summary.raw_score)
        self.assertIn("hidden", scored.score_summary.review_reason)

    def test_run_level_timeout_remains_unresolved_not_zero(self):
        config = self.config()
        run = make_run(
            config,
            {"public": "timeout", "hidden": "timeout"},
            requires_review=True,
            review_reason="Overall pytest wall-clock timeout; exact test attribution is unavailable.",
            metadata_by_test={
                "public": {"run_level_timeout": True},
                "hidden": {"run_level_timeout": True},
            },
        )
        scored = score_pytest_run(config, run)
        self.assertTrue(scored.score_summary.requires_review)
        self.assertIsNone(scored.score_summary.final_score)
        self.assertTrue(all(item.points_awarded is None for item in scored.test_results))
        self.assertEqual(scored.score_summary.metadata["known_awarded_points"], 0)
        self.assertEqual(scored.score_summary.metadata["unresolved_points"], 10.0)

    def test_source_run_review_flag_blocks_final_grade_even_when_tests_are_numeric(self):
        config = self.config()
        run = make_run(
            config,
            {"public": "passed", "hidden": "failed"},
            requires_review=True,
            review_reason="pytest collection errors",
        )
        scored = score_pytest_run(config, run)
        self.assertEqual([x.points_awarded for x in scored.test_results], [4.0, 0.0])
        self.assertIsNone(scored.score_summary.final_score)
        self.assertIn("pytest collection errors", scored.score_summary.review_reason)

    def test_missing_or_extra_runtime_test_ids_are_rejected(self):
        config = self.config()
        run = make_run(config, {"public": "passed", "hidden": "passed"})
        data = run.to_dict()
        data["test_results"] = data["test_results"][:1]
        short = type(run).from_dict(data)
        with self.assertRaisesRegex(ScoringInputError, "missing configured"):
            score_pytest_run(config, short)

        data = run.to_dict()
        extra = TestResult(test_id="unexpected", status="passed")
        data["test_results"].append(extra.to_dict())
        long_run = type(run).from_dict(data)
        with self.assertRaisesRegex(ScoringInputError, "unknown runtime"):
            score_pytest_run(config, long_run)

    def test_scored_hidden_result_still_redacts_identity_and_diagnostics(self):
        config = self.config()
        run = make_run(config, {"public": "passed", "hidden": "failed"})
        scored = score_pytest_run(config, run)
        hidden = scored.test_by_id("hidden")
        self.assertEqual(hidden.points_possible, 6.0)
        self.assertEqual(hidden.points_awarded, 0.0)
        safe = redact_test_result_for_student(hidden, config.reporting_policy)
        self.assertNotEqual(safe.test_id, "hidden")
        self.assertTrue(safe.test_id.startswith("hidden_"))
        self.assertEqual(safe.display_name, "Hidden test")
        self.assertEqual(safe.points_possible, 6.0)
        self.assertEqual(safe.points_awarded, 0.0)
        self.assertIsNone(safe.traceback)
        self.assertEqual(safe.stdout, "")
        self.assertEqual(safe.stderr, "")

    def test_custom_policy_must_classify_every_status(self):
        with self.assertRaisesRegex(Exception, "classify every"):
            TestOutcomeScoringPolicy(
                full_credit_statuses=("passed",),
                zero_credit_statuses=("failed",),
                review_statuses=("infrastructure_error",),
            )


if __name__ == "__main__":
    unittest.main()
