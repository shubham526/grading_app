import unittest

from src.autograding.config import (
    SCORING_METHOD_EQUAL_WITHIN_GROUP,
    AutogradingConfig,
)
from src.autograding.models import TestDefinition, TestGroup
from src.autograding.scoring import score_pytest_run
from src.tests.autograding_v233_scoring_support import make_run


class TestAutogradingGroupScoring(unittest.TestCase):
    def test_explicit_group_points_aggregate(self):
        config = AutogradingConfig(
            assessment_id="LAB2", max_points=10, entrypoint="main.py",
            groups=(
                TestGroup(group_id="core", name="Core", points=6),
                TestGroup(group_id="edge", name="Edge", points=4),
            ),
            tests=(
                TestDefinition(test_id="a", name="A", group_id="core", points=3),
                TestDefinition(test_id="b", name="B", group_id="core", points=3),
                TestDefinition(test_id="c", name="C", group_id="edge", points=4),
            ),
        )
        run = make_run(config, {"a": "passed", "b": "failed", "c": "passed"})
        scored = score_pytest_run(config, run)
        self.assertEqual(scored.score_summary.final_score, 7.0)
        groups = {g.group_id: g for g in scored.score_summary.group_results}
        self.assertEqual(groups["core"].points_awarded, 3.0)
        self.assertEqual(groups["edge"].points_awarded, 4.0)

    def test_equal_within_group_allocates_deterministic_fractional_points(self):
        config = AutogradingConfig(
            assessment_id="LAB2", max_points=10, entrypoint="main.py",
            scoring_method=SCORING_METHOD_EQUAL_WITHIN_GROUP,
            groups=(
                TestGroup(group_id="core", name="Core", points=6),
                TestGroup(group_id="edge", name="Edge", points=4),
            ),
            tests=(
                TestDefinition(test_id="a", name="A", group_id="core"),
                TestDefinition(test_id="b", name="B", group_id="core"),
                TestDefinition(test_id="c", name="C", group_id="core"),
                TestDefinition(test_id="d", name="D", group_id="edge"),
                TestDefinition(test_id="e", name="E", group_id="edge"),
            ),
        )
        run = make_run(config, {"a": "passed", "b": "passed", "c": "failed", "d": "passed", "e": "failed"})
        scored = score_pytest_run(config, run)
        possible = {t.test_id: t.points_possible for t in scored.test_results}
        self.assertEqual(possible, {"a": 2.0, "b": 2.0, "c": 2.0, "d": 2.0, "e": 2.0})
        self.assertEqual(scored.score_summary.final_score, 6.0)

    def test_equal_group_precision_sums_back_to_configured_max(self):
        config = AutogradingConfig(
            assessment_id="LAB3", max_points=1, entrypoint="main.py",
            scoring_method=SCORING_METHOD_EQUAL_WITHIN_GROUP,
            groups=(TestGroup(group_id="g", name="G", points=1),),
            tests=tuple(TestDefinition(test_id="t%d" % i, name="T%d" % i, group_id="g") for i in range(3)),
        )
        run = make_run(config, {"t0": "passed", "t1": "passed", "t2": "passed"})
        scored = score_pytest_run(config, run)
        self.assertEqual(scored.score_summary.final_score, 1.0)
        self.assertEqual(scored.score_summary.group_results[0].points_awarded, 1.0)


if __name__ == "__main__":
    unittest.main()
