import unittest

from src.autograding.config import AutogradingConfig
from src.autograding.models import TestDefinition
from src.autograding.scoring import AutogradingScoringResult, score_pytest_run
from src.tests.autograding_v233_scoring_support import make_run


class TestAutogradingScoring(unittest.TestCase):
    def config(self):
        return AutogradingConfig(
            assessment_id="LAB1",
            max_points=10,
            entrypoint="main.py",
            tests=(
                TestDefinition(test_id="t1", name="Basic", points=4, visibility="public"),
                TestDefinition(test_id="t2", name="Edge", points=3),
                TestDefinition(test_id="t3", name="Error", points=2),
                TestDefinition(test_id="t4", name="Timeout", points=1),
            ),
        )

    def test_student_attributable_outcomes_score_deterministically(self):
        config = self.config()
        run = make_run(config, {"t1": "passed", "t2": "failed", "t3": "error", "t4": "timeout"})
        scored = score_pytest_run(config, run)
        self.assertTrue(scored.is_complete)
        self.assertEqual(scored.score_summary.raw_score, 4.0)
        self.assertEqual(scored.score_summary.final_score, 4.0)
        self.assertFalse(scored.score_summary.requires_review)
        self.assertEqual([x.points_awarded for x in scored.test_results], [4.0, 0.0, 0.0, 0.0])

    def test_xfail_and_xpass_receive_full_credit_under_default_policy(self):
        config = AutogradingConfig(
            assessment_id="LAB1", max_points=4, entrypoint="main.py",
            tests=(
                TestDefinition(test_id="x1", name="Expected", points=2),
                TestDefinition(test_id="x2", name="Unexpected pass", points=2),
            ),
        )
        run = make_run(config, {"x1": "xfail", "x2": "xpass"})
        scored = score_pytest_run(config, run)
        self.assertEqual(scored.score_summary.final_score, 4.0)

    def test_runtime_point_values_are_not_trusted(self):
        config = self.config()
        run = make_run(config, {"t1": "passed", "t2": "passed", "t3": "passed", "t4": "passed"})
        tampered = []
        for item in run.test_results:
            data = item.to_dict()
            data["points_possible"] = 999
            data["points_awarded"] = 999
            tampered.append(type(item).from_dict(data))
        run_data = run.to_dict()
        run_data["test_results"] = [item.to_dict() for item in tampered]
        tampered_run = type(run).from_dict(run_data)
        scored = score_pytest_run(config, tampered_run)
        self.assertEqual(scored.score_summary.final_score, 10.0)
        self.assertEqual([x.points_possible for x in scored.test_results], [4.0, 3.0, 2.0, 1.0])
        self.assertTrue(all(x.metadata["scoring_source"] == "autograding_config" for x in scored.test_results))

    def test_scoring_result_roundtrip_is_stable(self):
        config = self.config()
        run = make_run(config, {"t1": "passed", "t2": "failed", "t3": "passed", "t4": "passed"})
        first = score_pytest_run(config, run)
        second = AutogradingScoringResult.from_dict(first.to_dict())
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict(), score_pytest_run(config, run).to_dict())

    def test_config_order_controls_scored_test_order(self):
        config = self.config()
        run = make_run(config, {"t1": "passed", "t2": "passed", "t3": "passed", "t4": "passed"})
        data = run.to_dict()
        data["test_results"] = list(reversed(data["test_results"]))
        reversed_run = type(run).from_dict(data)
        scored = score_pytest_run(config, reversed_run)
        self.assertEqual([x.test_id for x in scored.test_results], ["t1", "t2", "t3", "t4"])


if __name__ == "__main__":
    unittest.main()
