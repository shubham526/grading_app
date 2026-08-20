import tempfile
import unittest
from pathlib import Path

from src.autograding.service import GRADE_STATUS_COMPLETED, GRADE_STATUS_REVIEW
from src.tests.autograding_v233_persistence_support import make_pytest_result
from src.tests.autograding_v233_service_support import (
    ASSESSMENT_ID,
    STUDENT_ID,
    BackendFactory,
    prepare_service,
)


class TestAutogradingService(unittest.TestCase):
    def test_grade_submission_executes_scores_and_persists(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, submission, factory = prepare_service(td)
            result = service.grade_submission(
                ASSESSMENT_ID, STUDENT_ID, bundle.reference.bundle_id
            )
            self.assertEqual(result.plan.submission_id, submission.submission_id)
            self.assertEqual(result.final_score, 4.0)
            self.assertEqual(result.max_score, 10.0)
            self.assertFalse(result.requires_review)
            self.assertEqual(result.stored_run.run.run_id, result.plan.run_id)
            refs = service.list_history(ASSESSMENT_ID, STUDENT_ID)
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0].final_score, 4.0)
            self.assertEqual(factory.instances[-1].image, "test-runtime:1")

    def test_regrading_creates_distinct_immutable_run_history(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            first = service.grade_submission(ASSESSMENT_ID, STUDENT_ID, bundle.reference.bundle_id)
            second = service.grade_submission(ASSESSMENT_ID, STUDENT_ID, bundle.reference.bundle_id)
            self.assertNotEqual(first.plan.run_id, second.plan.run_id)
            refs = service.list_history(ASSESSMENT_ID, STUDENT_ID)
            self.assertEqual(len(refs), 2)
            self.assertEqual({r.run_id for r in refs}, {first.plan.run_id, second.plan.run_id})

    def test_review_result_persists_without_numeric_grade(self):
        with tempfile.TemporaryDirectory() as td:
            def result_factory(plan):
                return make_pytest_result(
                    plan,
                    requires_review=True,
                    review_reason="synthetic collection anomaly",
                )

            service, bundle, _submission, _factory = prepare_service(
                td, pytest_result_factory=result_factory
            )
            result = service.grade_submission(ASSESSMENT_ID, STUDENT_ID, bundle.reference.bundle_id)
            self.assertTrue(result.requires_review)
            self.assertIsNone(result.final_score)
            self.assertTrue(result.stored_run.run.requires_review)
            self.assertIsNone(result.stored_run.reference.final_score)

    def test_unavailable_runtime_stops_before_executor_and_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            factory = BackendFactory(available=False, reason="Docker daemon unavailable")
            service, bundle, _submission, _ = prepare_service(td, backend_factory=factory)
            with self.assertRaisesRegex(Exception, "Docker daemon unavailable"):
                service.grade_submission(ASSESSMENT_ID, STUDENT_ID, bundle.reference.bundle_id)
            self.assertEqual(service.list_history(ASSESSMENT_ID, STUDENT_ID), ())

    def test_bundle_import_and_listing_are_workspace_scoped(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            refs = service.list_bundles(ASSESSMENT_ID)
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0], bundle.reference)
            loaded = service.load_bundle(ASSESSMENT_ID, bundle.reference.bundle_id)
            self.assertEqual(loaded.reference, bundle.reference)

    def test_eligible_active_students_preflights_without_persisting(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            eligible, rejected = service.eligible_active_students(
                ASSESSMENT_ID,
                [STUDENT_ID, "missing-student"],
                bundle.reference.bundle_id,
            )
            self.assertEqual(eligible, (STUDENT_ID,))
            self.assertIn("missing-student", rejected)
            self.assertEqual(service.list_history(ASSESSMENT_ID, STUDENT_ID), ())

    def test_runtime_availability_uses_requested_image(self):
        with tempfile.TemporaryDirectory() as td:
            service, _bundle, _submission, factory = prepare_service(td)
            availability = service.runtime_availability("custom-runtime:2")
            self.assertTrue(availability.available)
            self.assertEqual(factory.instances[-1].image, "custom-runtime:2")


if __name__ == "__main__":
    unittest.main()
