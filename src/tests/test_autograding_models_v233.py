"""v2.3.3 Commit 1 tests for dependency-free autograding domain models."""

from dataclasses import FrozenInstanceError
import json
import unittest

from src.autograding import (
    AUTOGRADING_DOMAIN_SCHEMA_VERSION,
    EXECUTION_STATUS_COMPLETED,
    REVIEW_STATUS_FLAGGED,
    RUN_STATUS_COMPLETED_WITH_FAILURES,
    TEST_STATUS_FAILED,
    TEST_STATUS_INFRASTRUCTURE_ERROR,
    TEST_STATUS_PASSED,
    TEST_VISIBILITY_HIDDEN,
    TEST_VISIBILITY_PUBLIC,
    AutogradingProvenance,
    AutogradingRun,
    AutogradingValidationError,
    ExecutionEnvironment,
    ExecutionResult,
    ResourceLimits,
    ScoreSummary,
    TestBundleReference,
    TestDefinition,
    TestGroup,
    TestGroupResult,
    TestResult,
    UnsupportedAutogradingSchemaError,
    generate_autograding_run_id,
    generate_test_bundle_id,
)


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class TestAutogradingDomainModels(unittest.TestCase):

    def _provenance(self):
        return AutogradingProvenance(
            submission_id="sub_alice",
            artifact_id="art_python",
            submission_sha256=_HASH_A,
            bundle_id="bundle_1",
            bundle_sha256=_HASH_B,
            config_sha256=_HASH_C,
            runner_type="pytest",
            attempt=2,
            environment_id="cs-python-312-v1",
            runner_version="9.0",
        )

    def test_generated_ids_are_prefixed_unique_and_opaque(self):
        for prefix, generator in (
            ("agrun_", generate_autograding_run_id),
            ("bundle_", generate_test_bundle_id),
        ):
            values = {generator() for _ in range(25)}
            self.assertEqual(len(values), 25)
            self.assertTrue(all(value.startswith(prefix) for value in values))

    def test_resource_limits_roundtrip_and_safe_defaults(self):
        limits = ResourceLimits()
        self.assertEqual(limits.wall_timeout_seconds, 15.0)
        self.assertEqual(limits.memory_mb, 512)
        self.assertFalse(limits.network_enabled)
        loaded = ResourceLimits.from_dict(limits.to_dict())
        self.assertEqual(loaded, limits)

    def test_resource_limits_reject_invalid_or_boolean_numbers(self):
        bad_kwargs = (
            {"wall_timeout_seconds": 0},
            {"wall_timeout_seconds": True},
            {"memory_mb": 0},
            {"memory_mb": 1.5},
            {"cpu_count": 0},
            {"pids_limit": False},
            {"stdout_max_bytes": 0},
        )
        for kwargs in bad_kwargs:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(AutogradingValidationError):
                    ResourceLimits(**kwargs)

    def test_test_definition_defaults_hidden_and_roundtrips(self):
        test = TestDefinition(
            test_id="test_sort_empty",
            name="Empty input",
            group_id="correctness",
            points=2,
        )
        self.assertEqual(test.visibility, TEST_VISIBILITY_HIDDEN)
        self.assertEqual(TestDefinition.from_dict(test.to_dict()), test)

    def test_test_definition_rejects_invalid_points_and_timeout(self):
        with self.assertRaises(AutogradingValidationError):
            TestDefinition("t", "T", points=-1)
        with self.assertRaises(AutogradingValidationError):
            TestDefinition("t", "T", timeout_seconds=0)
        with self.assertRaises(AutogradingValidationError):
            TestDefinition("t", "T", points=True)

    def test_frozen_value_objects_cannot_be_reassigned(self):
        definition = TestDefinition("t", "T")
        with self.assertRaises(FrozenInstanceError):
            definition.visibility = TEST_VISIBILITY_PUBLIC

    def test_bundle_reference_requires_real_sha256_digests(self):
        with self.assertRaises(AutogradingValidationError):
            TestBundleReference(
                bundle_id="bundle_bad",
                assessment_id="LAB1",
                bundle_sha256="not-a-hash",
                config_sha256=_HASH_B,
                imported_at="2026-08-19T20:00:00Z",
            )

    def test_execution_environment_normalizes_container_digest(self):
        env = ExecutionEnvironment(
            environment_id="python312-v1",
            backend="docker",
            language="python",
            interpreter_version="3.12.5",
            container_image="grading-python:1",
            container_image_digest=_HASH_A,
            dependency_lock_sha256=_HASH_B,
        )
        self.assertEqual(env.container_image_digest, "sha256:" + _HASH_A)
        self.assertEqual(ExecutionEnvironment.from_dict(env.to_dict()), env)

    def test_execution_result_distinguishes_process_status_and_captures_output(self):
        result = ExecutionResult(
            status=EXECUTION_STATUS_COMPLETED,
            exit_code=1,
            duration_ms=42,
            stdout="hello",
            stderr="trace",
            stdout_truncated=True,
        )
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.stdout_truncated)
        self.assertEqual(ExecutionResult.from_dict(result.to_dict()), result)

    def test_execution_result_rejects_boolean_exit_code(self):
        with self.assertRaises(AutogradingValidationError):
            ExecutionResult(status=EXECUTION_STATUS_COMPLETED, exit_code=True)

    def test_test_result_keeps_student_failure_separate_from_infrastructure_error(self):
        failed = TestResult(
            test_id="test_basic",
            status=TEST_STATUS_FAILED,
            points_possible=2,
            points_awarded=0,
        )
        infra = TestResult(
            test_id="test_hidden",
            status=TEST_STATUS_INFRASTRUCTURE_ERROR,
        )
        self.assertEqual(failed.status, TEST_STATUS_FAILED)
        self.assertEqual(infra.status, TEST_STATUS_INFRASTRUCTURE_ERROR)
        self.assertIsNone(infra.points_awarded)

    def test_test_result_rejects_award_without_possible_or_overaward(self):
        with self.assertRaises(AutogradingValidationError):
            TestResult(
                test_id="t",
                status=TEST_STATUS_PASSED,
                points_awarded=1,
            )
        with self.assertRaises(AutogradingValidationError):
            TestResult(
                test_id="t",
                status=TEST_STATUS_PASSED,
                points_possible=1,
                points_awarded=2,
            )

    def test_score_summary_roundtrip_preserves_raw_and_final_separately(self):
        group = TestGroupResult(
            group_id="correctness",
            name="Correctness",
            points_possible=10,
            points_awarded=8,
            test_ids=("t1", "t2"),
        )
        summary = ScoreSummary(
            max_score=10,
            raw_score=8,
            final_score=9,
            requires_review=True,
            review_reason="manual adjustment pending approval",
            group_results=(group,),
        )
        loaded = ScoreSummary.from_dict(summary.to_dict())
        self.assertEqual(loaded, summary)
        self.assertEqual(loaded.raw_score, 8)
        self.assertEqual(loaded.final_score, 9)

    def test_score_summary_rejects_scores_above_max(self):
        with self.assertRaises(AutogradingValidationError):
            ScoreSummary(max_score=10, raw_score=11)
        with self.assertRaises(AutogradingValidationError):
            ScoreSummary(max_score=10, final_score=10.1)

    def test_provenance_roundtrip_preserves_exact_submission_and_bundle_hashes(self):
        provenance = self._provenance()
        loaded = AutogradingProvenance.from_dict(provenance.to_dict())
        self.assertEqual(loaded, provenance)
        self.assertEqual(loaded.submission_sha256, _HASH_A)
        self.assertEqual(loaded.bundle_sha256, _HASH_B)
        self.assertEqual(loaded.config_sha256, _HASH_C)

    def test_provenance_rejects_boolean_or_nonpositive_attempt(self):
        for attempt in (True, 0, -1):
            with self.subTest(attempt=attempt):
                with self.assertRaises(AutogradingValidationError):
                    AutogradingProvenance(
                        submission_id="sub_a",
                        artifact_id="art_a",
                        submission_sha256=_HASH_A,
                        bundle_id="bundle_a",
                        bundle_sha256=_HASH_B,
                        config_sha256=_HASH_C,
                        runner_type="pytest",
                        attempt=attempt,
                    )

    def test_autograding_run_roundtrip_is_json_serializable(self):
        tests = (
            TestResult(
                test_id="test_public",
                status=TEST_STATUS_PASSED,
                visibility=TEST_VISIBILITY_PUBLIC,
                points_possible=2,
                points_awarded=2,
            ),
            TestResult(
                test_id="test_hidden",
                status=TEST_STATUS_FAILED,
                visibility=TEST_VISIBILITY_HIDDEN,
                points_possible=3,
                points_awarded=0,
            ),
        )
        run = AutogradingRun(
            grading_run_id="agrun_1",
            assessment_id="LAB1",
            student_id="alice",
            submission_id="sub_alice",
            created_at="2026-08-19T20:00:00Z",
            provenance=self._provenance(),
            status=RUN_STATUS_COMPLETED_WITH_FAILURES,
            attempt=2,
            review_status=REVIEW_STATUS_FLAGGED,
            started_at="2026-08-19T20:00:01Z",
            finished_at="2026-08-19T20:00:02Z",
            duration_ms=1000,
            execution_result=ExecutionResult(
                status=EXECUTION_STATUS_COMPLETED,
                exit_code=1,
                duration_ms=1000,
            ),
            test_results=tests,
            score_summary=ScoreSummary(max_score=5, raw_score=2),
            requires_review=True,
            review_reason="failed hidden test",
        )
        payload = run.to_dict()
        self.assertEqual(payload["schema_version"], AUTOGRADING_DOMAIN_SCHEMA_VERSION)
        json.dumps(payload)
        loaded = AutogradingRun.from_dict(payload)
        self.assertEqual(loaded.to_dict(), payload)
        self.assertEqual(loaded.run_id, "agrun_1")

    def test_autograding_run_rejects_provenance_for_other_submission(self):
        provenance = self._provenance()
        with self.assertRaises(AutogradingValidationError):
            AutogradingRun(
                grading_run_id="agrun_1",
                assessment_id="LAB1",
                student_id="alice",
                submission_id="sub_other",
                created_at="2026-08-19T20:00:00Z",
                provenance=provenance,
            )

    def test_autograding_run_rejects_duplicate_test_results(self):
        result = TestResult(test_id="same", status=TEST_STATUS_PASSED)
        with self.assertRaises(AutogradingValidationError):
            AutogradingRun(
                grading_run_id="agrun_1",
                assessment_id="LAB1",
                student_id="alice",
                submission_id="sub_alice",
                created_at="2026-08-19T20:00:00Z",
                provenance=self._provenance(),
                attempt=2,
                test_results=(result, result),
            )

    def test_autograding_run_rejects_unsupported_serialized_schema(self):
        payload = {
            "schema_version": "99",
            "grading_run_id": "agrun_1",
        }
        with self.assertRaises(UnsupportedAutogradingSchemaError):
            AutogradingRun.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
