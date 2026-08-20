"""Deterministic score computation for v2.3.3 Commit 7.

This module converts Commit-6 normalized pytest outcomes into points using only
trusted instructor configuration.  Runtime-supplied point values are ignored.
Infrastructure/ambiguous outcomes never silently become student zeros.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Any, Dict, Mapping, Optional, Tuple

from .config import (
    SCORING_METHOD_EQUAL_WITHIN_GROUP,
    SCORING_METHOD_EXPLICIT_TEST_POINTS,
    AutogradingConfig,
)
from .errors import AutogradingScoringError, ScoringInputError
from .models import ScoreSummary, TestGroupResult, TestResult
from .policies import (
    DEFAULT_TEST_OUTCOME_SCORING_POLICY,
    SCORING_DECISION_REVIEW,
    TestOutcomeScoringPolicy,
)
from .testing.protocol import PytestRunResult


AUTOGRADING_SCORING_RESULT_SCHEMA_VERSION = "1.0"
_EPSILON = 1e-9


def _close(left, right):
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)


def _canonical_test_results(config: AutogradingConfig, run_result: PytestRunResult):
    if not isinstance(config, AutogradingConfig):
        raise TypeError("config must be an AutogradingConfig")
    if not isinstance(run_result, PytestRunResult):
        raise TypeError("run_result must be a PytestRunResult")

    configured = {item.test_id: item for item in config.tests}
    runtime = {item.test_id: item for item in run_result.test_results}
    configured_ids = set(configured)
    runtime_ids = set(runtime)
    missing = sorted(configured_ids - runtime_ids)
    extra = sorted(runtime_ids - configured_ids)
    if missing or extra:
        pieces = []
        if missing:
            pieces.append("missing configured test result(s): %s" % ", ".join(missing))
        if extra:
            pieces.append("unknown runtime test result(s): %s" % ", ".join(extra))
        raise ScoringInputError("; ".join(pieces))

    # Preserve instructor configuration order, never runtime/protocol order.
    return tuple((configured[item.test_id], runtime[item.test_id]) for item in config.tests)


def _points_by_test(config: AutogradingConfig):
    if config.scoring_method == SCORING_METHOD_EXPLICIT_TEST_POINTS:
        result = {}
        for test in config.tests:
            if test.points is None:
                raise ScoringInputError(
                    "explicit_test_points requires configured points for %r" % test.test_id
                )
            result[test.test_id] = float(test.points)
        return result

    if config.scoring_method != SCORING_METHOD_EQUAL_WITHIN_GROUP:
        raise ScoringInputError(
            "unsupported scoring method %r" % config.scoring_method
        )

    group_lookup = {group.group_id: group for group in config.groups}
    grouped = {group.group_id: [] for group in config.groups}
    for test in config.tests:
        if test.group_id not in grouped:
            raise ScoringInputError(
                "test %r references unavailable scoring group %r"
                % (test.test_id, test.group_id)
            )
        grouped[test.group_id].append(test)

    result = {}
    for group_id, tests in grouped.items():
        if not tests:
            raise ScoringInputError("scoring group %r contains no tests" % group_id)
        share = float(group_lookup[group_id].points) / float(len(tests))
        for test in tests:
            result[test.test_id] = share
    return result


def _scored_test_result(definition, runtime_result, points_possible, policy):
    decision = policy.decision_for(runtime_result)
    awarded = policy.awarded_points(runtime_result, points_possible)
    metadata = deepcopy(runtime_result.metadata)
    metadata.update(
        {
            "scoring_decision": decision,
            "scoring_source": "autograding_config",
            "runtime_points_possible_ignored": runtime_result.points_possible,
            "runtime_points_awarded_ignored": runtime_result.points_awarded,
        }
    )
    return TestResult(
        test_id=definition.test_id,
        status=runtime_result.status,
        visibility=definition.visibility,
        group_id=definition.group_id,
        display_name=definition.name,
        duration_ms=runtime_result.duration_ms,
        message=runtime_result.message,
        traceback=runtime_result.traceback,
        stdout=runtime_result.stdout,
        stderr=runtime_result.stderr,
        points_possible=points_possible,
        points_awarded=awarded,
        metadata=metadata,
    )


def _group_results(config, scored_tests):
    if not config.groups:
        return tuple()

    by_id = {item.test_id: item for item in scored_tests}
    results = []
    for group in config.groups:
        test_ids = tuple(
            test.test_id for test in config.tests if test.group_id == group.group_id
        )
        items = tuple(by_id[test_id] for test_id in test_ids)
        unresolved = tuple(
            item.test_id for item in items if item.points_awarded is None
        )
        awarded = None if unresolved else sum(float(item.points_awarded) for item in items)
        if awarded is not None and _close(awarded, group.points):
            awarded = float(group.points)
        results.append(
            TestGroupResult(
                group_id=group.group_id,
                name=group.name,
                points_possible=float(group.points),
                points_awarded=awarded,
                test_ids=test_ids,
                requires_review=bool(unresolved),
                metadata={
                    "unresolved_test_ids": list(unresolved),
                    "known_awarded_points": sum(
                        float(item.points_awarded)
                        for item in items
                        if item.points_awarded is not None
                    ),
                },
            )
        )
    return tuple(results)


def _review_reasons(run_result, scored_tests):
    reasons = []
    unresolved = [item.test_id for item in scored_tests if item.points_awarded is None]
    if unresolved:
        reasons.append("unresolved test outcome(s): %s" % ", ".join(unresolved))
    if run_result.requires_review:
        reasons.append(run_result.review_reason or "structured pytest run requires review")
    # Preserve order while deduplicating exact strings.
    unique = []
    seen = set()
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    return tuple(unique)


@dataclass(frozen=True)
class AutogradingScoringResult:
    """Deterministic scored view of one structured pytest run."""

    test_results: Tuple[TestResult, ...]
    score_summary: ScoreSummary
    scoring_method: str
    source_run_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        tests = tuple(self.test_results or ())
        if any(not isinstance(item, TestResult) for item in tests):
            raise AutogradingScoringError("test_results must contain TestResult objects")
        ids = [item.test_id for item in tests]
        if len(ids) != len(set(ids)):
            raise AutogradingScoringError("test_results contains duplicate test_id values")
        if not isinstance(self.score_summary, ScoreSummary):
            raise AutogradingScoringError("score_summary must be a ScoreSummary")
        method = str(self.scoring_method or "").strip().lower()
        if not method:
            raise AutogradingScoringError("scoring_method must not be empty")
        run_id = str(self.source_run_id or "").strip()
        if not run_id:
            raise AutogradingScoringError("source_run_id must not be empty")
        if not isinstance(self.metadata, Mapping):
            raise AutogradingScoringError("metadata must be a mapping")
        object.__setattr__(self, "test_results", tests)
        object.__setattr__(self, "scoring_method", method)
        object.__setattr__(self, "source_run_id", run_id)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def is_complete(self):
        return not self.score_summary.requires_review and self.score_summary.final_score is not None

    def test_by_id(self, test_id):
        target = str(test_id or "").strip()
        for item in self.test_results:
            if item.test_id == target:
                return item
        return None

    def to_dict(self):
        return {
            "schema_version": AUTOGRADING_SCORING_RESULT_SCHEMA_VERSION,
            "test_results": [item.to_dict() for item in self.test_results],
            "score_summary": self.score_summary.to_dict(),
            "scoring_method": self.scoring_method,
            "source_run_id": self.source_run_id,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingScoringError("AutogradingScoringResult data must be a mapping")
        version = data.get("schema_version")
        if version is not None and str(version) != AUTOGRADING_SCORING_RESULT_SCHEMA_VERSION:
            raise AutogradingScoringError(
                "Unsupported scoring-result schema %r; expected %r"
                % (version, AUTOGRADING_SCORING_RESULT_SCHEMA_VERSION)
            )
        summary_data = data.get("score_summary")
        if not isinstance(summary_data, Mapping):
            raise AutogradingScoringError("score_summary must be a mapping")
        return cls(
            test_results=tuple(
                TestResult.from_dict(item) for item in (data.get("test_results") or ())
            ),
            score_summary=ScoreSummary.from_dict(summary_data),
            scoring_method=data.get("scoring_method"),
            source_run_id=data.get("source_run_id"),
            metadata=data.get("metadata", {}),
        )


def score_pytest_run(
    config: AutogradingConfig,
    run_result: PytestRunResult,
    outcome_policy: Optional[TestOutcomeScoringPolicy] = None,
) -> AutogradingScoringResult:
    """Score a structured pytest run using trusted instructor configuration.

    A final numeric score is emitted only when every configured test is resolved
    and Commit 6 did not flag the overall run for instructor review.
    """

    policy = outcome_policy or DEFAULT_TEST_OUTCOME_SCORING_POLICY
    if not isinstance(policy, TestOutcomeScoringPolicy):
        raise TypeError("outcome_policy must be a TestOutcomeScoringPolicy")

    canonical_pairs = _canonical_test_results(config, run_result)
    points = _points_by_test(config)
    scored_tests = tuple(
        _scored_test_result(definition, runtime, points[definition.test_id], policy)
        for definition, runtime in canonical_pairs
    )

    group_results = _group_results(config, scored_tests)
    reasons = _review_reasons(run_result, scored_tests)
    requires_review = bool(reasons)

    known_awarded = sum(
        float(item.points_awarded)
        for item in scored_tests
        if item.points_awarded is not None
    )
    known_possible = sum(
        float(item.points_possible)
        for item in scored_tests
        if item.points_awarded is not None
    )

    if requires_review:
        raw_score = None
        final_score = None
    else:
        raw_score = sum(float(item.points_awarded) for item in scored_tests)
        if _close(raw_score, config.max_points):
            raw_score = float(config.max_points)
        # v2.3.3 Commit 7 has no override/curve layer: deterministic raw and final
        # score are the same whenever the result is complete.
        final_score = raw_score

    summary = ScoreSummary(
        max_score=float(config.max_points),
        raw_score=raw_score,
        final_score=final_score,
        requires_review=requires_review,
        review_reason="; ".join(reasons) if reasons else None,
        group_results=group_results,
        metadata={
            "known_awarded_points": known_awarded,
            "known_possible_points": known_possible,
            "unresolved_points": max(0.0, float(config.max_points) - known_possible),
            "scoring_method": config.scoring_method,
            "source_pytest_requires_review": run_result.requires_review,
        },
    )

    return AutogradingScoringResult(
        test_results=scored_tests,
        score_summary=summary,
        scoring_method=config.scoring_method,
        source_run_id=run_result.backend_record.run_id,
        metadata={
            "policy": {
                "full_credit_statuses": list(policy.full_credit_statuses),
                "zero_credit_statuses": list(policy.zero_credit_statuses),
                "review_statuses": list(policy.review_statuses),
            },
            "pytest_exit_code": run_result.pytest_exit_code,
            "pytest_version": run_result.pytest_version,
        },
    )


__all__ = [
    "AUTOGRADING_SCORING_RESULT_SCHEMA_VERSION",
    "AutogradingScoringResult",
    "score_pytest_run",
]
