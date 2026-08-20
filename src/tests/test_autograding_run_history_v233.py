from pathlib import Path
import tempfile
import unittest

from src.autograding.bundle_store import TestBundleStore
from src.autograding.repository import AutogradingRunRepository
from src.tests.autograding_v233_persistence_support import (
    ASSESSMENT_ID,
    STUDENT_ID,
    create_submission,
    make_plan,
    make_pytest_result,
    make_scored_result,
    prepare_workspace,
    write_bundle,
)


class TestAutogradingRunHistory(unittest.TestCase):
    def test_rerun_same_submission_and_bundle_creates_new_history(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            repo = AutogradingRunRepository(workspace)
            for index, run_id in enumerate(("agrun_repeat_1", "agrun_repeat_2"), start=1):
                plan = make_plan(
                    submissions,
                    bundle_store,
                    bundle,
                    run_id=run_id,
                    created_at="2026-08-20T01:00:0%dZ" % index,
                )
                pytest_result = make_pytest_result(plan)
                repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            refs = repo.list_run_references(ASSESSMENT_ID, STUDENT_ID)
            self.assertEqual([item.run_id for item in refs], ["agrun_repeat_1", "agrun_repeat_2"])
            self.assertEqual(refs[0].submission_id, refs[1].submission_id)
            self.assertEqual(refs[0].bundle_id, refs[1].bundle_id)

    def test_historical_submission_attempt_remains_distinct_after_active_changes(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, first = prepare_workspace(td)
            repo = AutogradingRunRepository(workspace)
            first_plan = make_plan(submissions, bundle_store, bundle, run_id="agrun_attempt1")
            first_pytest = make_pytest_result(first_plan)
            repo.commit_run(first_plan, first_pytest, make_scored_result(first_plan, first_pytest))

            second = create_submission(
                submissions,
                Path(td) / "submission_attempt2",
                attempt=2,
                make_active=True,
                value=2,
            )
            second_plan = make_plan(
                submissions,
                bundle_store,
                bundle,
                run_id="agrun_attempt2",
                submission_id=second.submission_id,
                created_at="2026-08-20T01:10:00Z",
            )
            second_pytest = make_pytest_result(second_plan, hidden_status="passed")
            repo.commit_run(second_plan, second_pytest, make_scored_result(second_plan, second_pytest))

            refs = repo.list_run_references(ASSESSMENT_ID, STUDENT_ID)
            self.assertEqual([item.attempt for item in refs], [1, 2])
            self.assertEqual(refs[0].submission_id, first.submission_id)
            self.assertEqual(refs[1].submission_id, second.submission_id)
            old = repo.load_run(ASSESSMENT_ID, STUDENT_ID, "agrun_attempt1")
            self.assertEqual(old.run.provenance.submission_id, first.submission_id)

    def test_changed_test_bundle_creates_separate_provenance_history(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, first_bundle, _ = prepare_workspace(td)
            repo = AutogradingRunRepository(workspace)
            plan1 = make_plan(submissions, bundle_store, first_bundle, run_id="agrun_bundle1")
            result1 = make_pytest_result(plan1)
            repo.commit_run(plan1, result1, make_scored_result(plan1, result1))

            source2 = write_bundle(Path(td) / "bundle_v2", version="v2")
            # Change exact grader bytes without changing scoring contract.
            (source2 / "tests" / "test_hidden.py").write_text(
                "# grader version 2\ndef test_hidden():\n    assert True\n", encoding="utf-8"
            )
            store2 = TestBundleStore(
                workspace,
                bundle_id_factory=lambda: "bundle_persist_v2",
                now_fn=lambda: "2026-08-20T01:05:00Z",
            )
            bundle2 = store2.import_bundle(source2, expected_assessment_id=ASSESSMENT_ID).bundle
            plan2 = make_plan(
                submissions,
                store2,
                bundle2,
                run_id="agrun_bundle2",
                created_at="2026-08-20T01:06:00Z",
            )
            result2 = make_pytest_result(plan2)
            repo.commit_run(plan2, result2, make_scored_result(plan2, result2))

            refs = repo.list_run_references(ASSESSMENT_ID, STUDENT_ID)
            self.assertEqual([item.bundle_id for item in refs], ["bundle_persist_v1", "bundle_persist_v2"])
            run1 = repo.load_run(ASSESSMENT_ID, STUDENT_ID, "agrun_bundle1")
            run2 = repo.load_run(ASSESSMENT_ID, STUDENT_ID, "agrun_bundle2")
            self.assertNotEqual(run1.run.provenance.bundle_sha256, run2.run.provenance.bundle_sha256)

    def test_latest_and_assessment_history_helpers(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            repo = AutogradingRunRepository(workspace)
            for sid, created in (("agrun_a", "2026-08-20T01:00:00Z"), ("agrun_b", "2026-08-20T01:01:00Z")):
                plan = make_plan(submissions, bundle_store, bundle, run_id=sid, created_at=created)
                result = make_pytest_result(plan)
                repo.commit_run(plan, result, make_scored_result(plan, result))
            self.assertEqual(repo.latest_run_reference(ASSESSMENT_ID, STUDENT_ID).run_id, "agrun_b")
            self.assertEqual(len(repo.list_assessment_run_references(ASSESSMENT_ID)), 2)

    def test_review_required_run_persists_without_final_numeric_score(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            repo = AutogradingRunRepository(workspace)
            plan = make_plan(submissions, bundle_store, bundle, run_id="agrun_review")
            pytest_result = make_pytest_result(
                plan,
                requires_review=True,
                review_reason="collection anomaly requires instructor review",
            )
            stored = repo.commit_run(
                plan, pytest_result, make_scored_result(plan, pytest_result)
            )
            self.assertTrue(stored.run.requires_review)
            self.assertEqual(stored.run.review_status, "flagged")
            self.assertIsNone(stored.run.score_summary.final_score)
            self.assertIsNone(stored.reference.final_score)
            self.assertTrue(stored.reference.requires_review)


if __name__ == "__main__":
    unittest.main()
