import json
from pathlib import Path
import tempfile
import unittest

from src.autograding.errors import AutogradingRunIntegrityError
from src.autograding.repository import AutogradingRunRepository
from src.tests.autograding_v233_persistence_support import (
    ASSESSMENT_ID,
    STUDENT_ID,
    make_plan,
    make_pytest_result,
    make_scored_result,
    prepare_workspace,
)


class TestAutogradingRunProvenance(unittest.TestCase):
    def test_exact_submission_bundle_and_runtime_identity_are_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, submission = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            pytest_result = make_pytest_result(plan)
            stored = AutogradingRunRepository(workspace).commit_run(
                plan, pytest_result, make_scored_result(plan, pytest_result)
            )
            provenance = stored.run.provenance
            self.assertEqual(provenance.submission_id, submission.submission_id)
            self.assertEqual(provenance.bundle_id, bundle.reference.bundle_id)
            self.assertEqual(provenance.bundle_sha256, bundle.reference.bundle_sha256)
            self.assertEqual(provenance.config_sha256, bundle.reference.config_sha256)
            self.assertEqual(provenance.environment_id, "docker-env-commit8")
            self.assertEqual(provenance.runner_version, "9.1.1")
            self.assertEqual(
                provenance.metadata["environment"]["container_image_digest"],
                "sha256:" + ("a" * 64),
            )
            artifacts = provenance.metadata["submission_artifacts"]
            self.assertEqual({item["logical_path"] for item in artifacts}, {"main.py", "helpers.py"})
            self.assertTrue(all(len(item["sha256"]) == 64 for item in artifacts))

    def test_portable_plan_never_persists_host_source_paths(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            result = make_pytest_result(plan)
            stored = AutogradingRunRepository(workspace).commit_run(
                plan, result, make_scored_result(plan, result)
            )
            plan_text = (Path(stored.run_dir) / "plan.json").read_text(encoding="utf-8")
            self.assertNotIn("source_path", plan_text)
            self.assertNotIn(str(Path(td).resolve()), plan_text)

    def test_cross_file_identity_tampering_is_detected_even_with_updated_file_hash(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, submissions, bundle_store, bundle, _ = prepare_workspace(td)
            plan = make_plan(submissions, bundle_store, bundle)
            result = make_pytest_result(plan)
            repo = AutogradingRunRepository(workspace)
            stored = repo.commit_run(plan, result, make_scored_result(plan, result))

            # Alter plan identity, then also rewrite the run manifest's recorded file
            # hash so ordinary file hashing alone would no longer catch it.  The
            # cross-file consistency verifier must still reject the history.
            plan_path = Path(stored.run_dir) / "plan.json"
            plan_path.chmod(0o644)
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_data["submission_id"] = "sub_tampered"
            plan_path.write_text(json.dumps(plan_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            from src.submissions.file_store import compute_file_sha256
            manifest_path = Path(stored.run_dir) / "run.json"
            manifest_path.chmod(0o644)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest["files"]:
                if item["relative_path"] == "plan.json":
                    item["sha256"] = compute_file_sha256(str(plan_path))
                    item["size_bytes"] = plan_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            # Update index manifest hash too, simulating coordinated metadata
            # tampering. Cross-file semantic identity still must fail.
            index_path = Path(stored.run_dir).parent / "index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for item in index["runs"]:
                if item["run_id"] == plan.run_id:
                    item["manifest_sha256"] = compute_file_sha256(str(manifest_path))
                    item["manifest_size_bytes"] = manifest_path.stat().st_size
            index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AutogradingRunIntegrityError, "submission mismatch"):
                repo.load_run(ASSESSMENT_ID, STUDENT_ID, plan.run_id)


if __name__ == "__main__":
    unittest.main()
