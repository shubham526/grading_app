import json
import tempfile
import unittest
from pathlib import Path

from src.autograding.errors import (
    AutogradingBundleIntegrityError,
    AutogradingBundleSelectionError,
    ExecutionPlanValidationError,
)
from src.autograding.planner import ExecutionPlan, build_execution_plan

from src.tests.autograding_v233_test_support import (
    create_python_submission,
    import_test_bundle,
    make_submission_repository,
    write_test_bundle,
)


class TestAutogradingExecutionPlanner(unittest.TestCase):
    def _fixture(self, root):
        repo = make_submission_repository(root / "evidence")
        submission = create_python_submission(repo, root / "incoming")
        source_bundle = write_test_bundle(root / "bundle")
        store, bundle = import_test_bundle(root / "workspace", source_bundle)
        return repo, submission, store, bundle

    def test_plan_binds_exact_submission_and_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, submission, store, bundle = self._fixture(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
                run_id="agrun_fixed",
                now_fn=lambda: "2026-08-19T20:10:00Z",
            )

        self.assertEqual(plan.run_id, "agrun_fixed")
        self.assertEqual(plan.submission_id, submission.submission_id)
        self.assertEqual(plan.bundle_reference, bundle.reference)
        self.assertEqual(plan.created_at, "2026-08-19T20:10:00Z")
        self.assertEqual(plan.language, "python")
        self.assertEqual(plan.runner_type, "pytest")
        self.assertEqual(plan.resource_limits.wall_timeout_seconds, 7.0)
        self.assertEqual(plan.workspace.entrypoint, "main.py")
        self.assertTrue(plan.selected_submission_was_active)

    def test_provenance_records_entrypoint_and_all_submission_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, submission, store, bundle = self._fixture(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
        entry = plan.workspace.entrypoint_file
        self.assertEqual(plan.provenance.artifact_id, entry.source_id)
        self.assertEqual(plan.provenance.submission_sha256, entry.sha256)
        self.assertEqual(plan.provenance.bundle_sha256, bundle.reference.bundle_sha256)
        artifacts = plan.provenance.metadata["submission_artifacts"]
        self.assertEqual(len(artifacts), 2)
        self.assertEqual({a["logical_path"] for a in artifacts}, {"main.py", "helpers.py"})

    def test_plan_contains_read_only_submission_and_grader_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _, store, bundle = self._fixture(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
            self.assertTrue(all(item.read_only for item in plan.workspace.submission_files))
            self.assertTrue(all(item.read_only for item in plan.workspace.grader_files))
            self.assertTrue(all(Path(item.source_path).is_file() for item in plan.workspace.grader_files))
            self.assertIn("autograder.json", {item.logical_path for item in plan.workspace.grader_files})

    def test_plan_roundtrip_preserves_exact_transient_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _, store, bundle = self._fixture(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
                run_id="agrun_roundtrip",
                now_fn=lambda: "2026-08-19T20:11:00Z",
            )
            restored = ExecutionPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.to_dict(), plan.to_dict())

    def test_portable_plan_serialization_omits_host_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _, store, bundle = self._fixture(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
            payload = plan.to_dict(include_source_paths=False)
        serialized = json.dumps(payload)
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("source_path", serialized)

    def test_unknown_bundle_has_selection_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            create_python_submission(repo, root / "incoming")
            source_bundle = write_test_bundle(root / "bundle")
            store, _ = import_test_bundle(root / "workspace", source_bundle)
            with self.assertRaises(AutogradingBundleSelectionError):
                build_execution_plan(
                    repo,
                    store,
                    assessment_id="LAB1",
                    student_id="alice",
                    bundle_id="bundle_missing",
                )

    def test_tampered_bundle_is_rejected_before_plan_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _, store, bundle = self._fixture(root)
            test_file = Path(bundle.original_path("tests/test_public.py"))
            test_file.chmod(0o644)
            test_file.write_text("def test_basic():\n    assert False\n", encoding="utf-8")
            with self.assertRaises(AutogradingBundleIntegrityError):
                build_execution_plan(
                    repo,
                    store,
                    assessment_id="LAB1",
                    student_id="alice",
                    bundle_id=bundle.reference.bundle_id,
                )

    def test_execution_plan_rejects_mismatched_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _, store, bundle = self._fixture(root)
            plan = build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
            data = plan.to_dict()
            data["provenance"]["bundle_sha256"] = "f" * 64
            with self.assertRaises(ExecutionPlanValidationError):
                ExecutionPlan.from_dict(data)

    def test_plan_creation_does_not_execute_student_code_or_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            student_sentinel = root / "STUDENT_EXECUTED"
            grader_sentinel = root / "GRADER_EXECUTED"
            repo = make_submission_repository(root / "evidence")
            create_python_submission(
                repo,
                root / "incoming",
                files={
                    "main.py": "from pathlib import Path\nPath(%r).write_text('x')\n" % str(student_sentinel),
                    "helpers.py": "raise RuntimeError('do not import')\n",
                },
            )
            source_bundle = write_test_bundle(root / "bundle")
            (source_bundle / "tests" / "test_public.py").write_text(
                "from pathlib import Path\n"
                "Path(%r).write_text('x')\n"
                "def test_basic():\n    assert True\n" % str(grader_sentinel),
                encoding="utf-8",
            )
            store, bundle = import_test_bundle(root / "workspace", source_bundle)
            build_execution_plan(
                repo,
                store,
                assessment_id="LAB1",
                student_id="alice",
                bundle_id=bundle.reference.bundle_id,
            )
            self.assertFalse(student_sentinel.exists())
            self.assertFalse(grader_sentinel.exists())


if __name__ == "__main__":
    unittest.main()
