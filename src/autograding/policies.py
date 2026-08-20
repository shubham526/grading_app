"""Deterministic scoring outcome policies for v2.3.3 Commit 7.

The configuration schema controls *how many* points each configured test is
worth.  This module controls the narrower question of whether a normalized test
outcome is eligible for full credit, zero credit, or must remain unresolved for
instructor review.

The default policy is intentionally conservative:
- passed / xfail / xpass are credit-eligible successful outcomes;
- failed / student error / attributable per-test timeout earn zero;
- pending / skipped / infrastructure errors remain unresolved;
- synthetic run-level timeouts remain unresolved even though Commit 6 represents
  them with per-test ``timeout`` records, because exact attribution is unknown.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from .errors import AutogradingScoringError
from .models import (
    TEST_STATUS_ERROR,
    TEST_STATUS_FAILED,
    TEST_STATUS_INFRASTRUCTURE_ERROR,
    TEST_STATUS_PASSED,
    TEST_STATUS_PENDING,
    TEST_STATUS_SKIPPED,
    TEST_STATUS_TIMEOUT,
    TEST_STATUS_XFAIL,
    TEST_STATUS_XPASS,
    TEST_STATUSES,
    TestResult,
)


SCORING_DECISION_FULL = "full_credit"
SCORING_DECISION_ZERO = "zero_credit"
SCORING_DECISION_REVIEW = "requires_review"
SCORING_DECISIONS = (
    SCORING_DECISION_FULL,
    SCORING_DECISION_ZERO,
    SCORING_DECISION_REVIEW,
)


@dataclass(frozen=True)
class TestOutcomeScoringPolicy:
    """Map normalized test statuses to deterministic scoring decisions."""

    full_credit_statuses: Tuple[str, ...] = (
        TEST_STATUS_PASSED,
        TEST_STATUS_XFAIL,
        TEST_STATUS_XPASS,
    )
    zero_credit_statuses: Tuple[str, ...] = (
        TEST_STATUS_FAILED,
        TEST_STATUS_ERROR,
        TEST_STATUS_TIMEOUT,
    )
    review_statuses: Tuple[str, ...] = (
        TEST_STATUS_PENDING,
        TEST_STATUS_SKIPPED,
        TEST_STATUS_INFRASTRUCTURE_ERROR,
    )

    def __post_init__(self):
        full = tuple(str(item).strip().lower() for item in self.full_credit_statuses)
        zero = tuple(str(item).strip().lower() for item in self.zero_credit_statuses)
        review = tuple(str(item).strip().lower() for item in self.review_statuses)
        all_values = full + zero + review
        if any(not item for item in all_values):
            raise AutogradingScoringError("scoring policy statuses must not be empty")
        if len(all_values) != len(set(all_values)):
            raise AutogradingScoringError(
                "scoring policy status sets must be mutually exclusive"
            )
        unknown = sorted(set(all_values) - set(TEST_STATUSES))
        if unknown:
            raise AutogradingScoringError(
                "scoring policy contains unsupported status(es): %s"
                % ", ".join(unknown)
            )
        missing = sorted(set(TEST_STATUSES) - set(all_values))
        if missing:
            raise AutogradingScoringError(
                "scoring policy must classify every TestResult status: %s"
                % ", ".join(missing)
            )
        object.__setattr__(self, "full_credit_statuses", full)
        object.__setattr__(self, "zero_credit_statuses", zero)
        object.__setattr__(self, "review_statuses", review)

    def decision_for(self, test_result: TestResult) -> str:
        if not isinstance(test_result, TestResult):
            raise TypeError("test_result must be a TestResult")

        # Commit 6 emits synthetic per-test timeouts for an overall Docker wall
        # timeout.  Those records are useful for reporting but cannot safely be
        # treated as four independently-attributable student timeouts.
        if bool(test_result.metadata.get("run_level_timeout")):
            return SCORING_DECISION_REVIEW

        status = test_result.status
        if status in self.full_credit_statuses:
            return SCORING_DECISION_FULL
        if status in self.zero_credit_statuses:
            return SCORING_DECISION_ZERO
        if status in self.review_statuses:
            return SCORING_DECISION_REVIEW
        raise AutogradingScoringError(
            "No scoring decision is defined for status %r" % status
        )

    def awarded_points(self, test_result: TestResult, points_possible: float) -> Optional[float]:
        decision = self.decision_for(test_result)
        if decision == SCORING_DECISION_FULL:
            return float(points_possible)
        if decision == SCORING_DECISION_ZERO:
            return 0.0
        return None


DEFAULT_TEST_OUTCOME_SCORING_POLICY = TestOutcomeScoringPolicy()


__all__ = [
    "DEFAULT_TEST_OUTCOME_SCORING_POLICY",
    "SCORING_DECISION_FULL",
    "SCORING_DECISION_REVIEW",
    "SCORING_DECISION_ZERO",
    "SCORING_DECISIONS",
    "TestOutcomeScoringPolicy",
]
