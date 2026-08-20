import tempfile
import unittest
from pathlib import Path

from src.autograding.planner import build_execution_plan

from src.tests.autograding_v233_test_support import (
    create_python_submission,
    import_test_bundle,
    make_submission_repository,
    write_test_bundle,
)


class TestAutogradingAttemptSelection(unittest.TestCase):
    def _setup(self, root):
        repo = make_submission_repository(root / "evidence")
        first = create_python_submission(
            repo,
            root / "incoming1",
            files={"main.py": "VALUE=1\n", "helpers.py": "X=1\n"},
            make_active=True,
            attempt=1,
        )
        second = create_python_submission(
            repo,
            root / "incoming2",
            files={"main.py": "VALUE=2\n", "helpers.py": "X=2\n"},
            make_active=True,
            attempt=2,
        )
        source_bundle = write_test_bundle(root / "bundle")
        store, bundle = import_test_bundle(root / "workspace", source_bundle)
        return repo, first, second, store, bundle

    def test_default_plan_uses_active_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, first, second, store, bundle = self._setup(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
        self.assertEqual(plan.submission_id, second.submission_id)
        self.assertEqual(plan.attempt, 2)
        self.assertTrue(plan.selected_submission_was_active)
        self.assertNotEqual(plan.submission_id, first.submission_id)

    def test_explicit_historical_attempt_does_not_mutate_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, first, second, store, bundle = self._setup(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
                submission_id=first.submission_id,
            )
            active_after = repo.get_active_submission("LAB1", "alice")
        self.assertEqual(plan.submission_id, first.submission_id)
        self.assertEqual(plan.attempt, 1)
        self.assertFalse(plan.selected_submission_was_active)
        self.assertEqual(active_after.submission_id, second.submission_id)

    def test_switching_active_attempt_changes_default_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, first, second, store, bundle = self._setup(root)
            before = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
            repo.set_active_submission("LAB1", "alice", first.submission_id)
            after = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
        self.assertEqual(before.submission_id, second.submission_id)
        self.assertEqual(after.submission_id, first.submission_id)
        self.assertEqual(after.attempt, 1)
        self.assertTrue(after.selected_submission_was_active)

    def test_historical_attempt_hashes_are_distinct_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, first, second, store, bundle = self._setup(root)
            first_plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
                submission_id=first.submission_id,
            )
            second_plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
                submission_id=second.submission_id,
            )
        self.assertNotEqual(first_plan.entrypoint_sha256, second_plan.entrypoint_sha256)
        self.assertEqual(first_plan.provenance.attempt, 1)
        self.assertEqual(second_plan.provenance.attempt, 2)


if __name__ == "__main__":
    unittest.main()
