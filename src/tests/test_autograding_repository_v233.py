import json
from pathlib import Path
import tempfile
import unittest

from src.autograding.errors import AutogradingRunIntegrityError, AutogradingRunStorageError
from src.autograding.repository import AutogradingRunRepository
from src.autograding.storage import (
    AUTOGRADING_RUN_MANIFEST_FILENAME,
    RUN_FILE_ROLE_STDERR,
    RUN_FILE_ROLE_STDOUT,
)
from src.tests.autograding_v233_persistence_support import (
    ASSESSMENT_ID,
    STUDENT_ID,
    make_plan,
    make_pytest_result,
    make_scored_result,
    prepare_workspace,
)


class TestAutogradingRunRepository(unittest.TestCase):
    def test_commit_reopen_and_verify_immutable_run(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            score = make_scored_result(plan, pytest_result)
            repo = AutogradingRunRepository(workspace, now_fn=lambda: "2026-08-20T01:00:03Z")

            stored = repo.commit_run(plan, pytest_result, score)
            self.assertEqual(stored.run.run_id, plan.run_id)
            self.assertEqual(stored.run.provenance.bundle_sha256, bundle.reference.bundle_sha256)
            self.assertEqual(stored.run.score_summary.final_score, 4.0)
            self.assertFalse(stored.run.requires_review)
            self.assertNotIn("source_path", json.dumps(stored.plan_snapshot))
            self.assertTrue(repo.verify_run(stored))

            reopened = AutogradingRunRepository(workspace, create=False).load_run(
                ASSESSMENT_ID, STUDENT_ID, plan.run_id
            )
            self.assertEqual(reopened.reference, stored.reference)
            self.assertEqual(reopened.run.to_dict(), stored.run.to_dict())
            self.assertEqual(reopened.scoring_result.to_dict(), stored.scoring_result.to_dict())
            self.assertEqual(reopened.pytest_result.to_dict(), stored.pytest_result.to_dict())

    def test_execution_stdout_and_stderr_are_separate_hashed_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan, stdout="AAA\n", stderr="BBB\n")
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            stdout_record = stored.file_by_role(RUN_FILE_ROLE_STDOUT)
            stderr_record = stored.file_by_role(RUN_FILE_ROLE_STDERR)
            self.assertEqual((Path(stored.run_dir) / stdout_record.relative_path).read_text(), "AAA\n")
            self.assertEqual((Path(stored.run_dir) / stderr_record.relative_path).read_text(), "BBB\n")
            self.assertEqual(len(stdout_record.sha256), 64)
            self.assertEqual(len(stderr_record.sha256), 64)

    def test_same_run_id_can_never_be_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            score = make_scored_result(plan, pytest_result)
            repo = AutogradingRunRepository(workspace)
            repo.commit_run(plan, pytest_result, score)
            with self.assertRaisesRegex(AutogradingRunStorageError, "already exists"):
                repo.commit_run(plan, pytest_result, score)

    def test_tampered_component_file_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            score_file = Path(stored.run_dir) / "scoring.json"
            score_file.chmod(0o644)
            score_file.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "hash mismatch|size mismatch"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)

    def test_extra_unmanifested_file_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            (Path(stored.run_dir) / "extra.txt").write_text("not allowed", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "does not match manifest"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)

    def test_manifest_tampering_is_detected_against_index(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            manifest = Path(stored.run_dir) / AUTOGRADING_RUN_MANIFEST_FILENAME
            manifest.chmod(0o644)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["metadata"]["tampered"] = True
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "manifest (hash|size)"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)

    def test_tampered_execution_evidence_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan, stdout="ORIGINAL\n")
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            evidence = Path(stored.run_dir) / "evidence" / "execution_stdout.txt"
            evidence.chmod(0o644)
            evidence.write_text("TAMPERED\n", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "hash mismatch|size mismatch"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)

    def test_symlink_inserted_into_immutable_run_is_detected(self):
        import os
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            target = Path(stored.run_dir) / "evidence" / "execution_stdout.txt"
            target.chmod(0o644)
            target.unlink()
            os.symlink("execution_stderr.txt", str(target))
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "Symlink|symlink"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)

    def test_history_index_manifest_hash_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            index_path = Path(stored.run_dir).parent / "index.json"
            data = json.loads(index_path.read_text(encoding="utf-8"))
            data["runs"][0]["manifest_sha256"] = "0" * 64
            index_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "manifest hash"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)

    def test_history_index_summary_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, pytest_result, make_scored_result(plan, pytest_result))
            index_path = Path(stored.run_dir).parent / "index.json"
            data = json.loads(index_path.read_text(encoding="utf-8"))
            data["runs"][0]["final_score"] = 10.0
            index_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingRunIntegrityError, "index summary"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)


if __name__ == "__main__":
    unittest.main()
