"""Release-level acceptance coverage for v2.3.3 programming autograding.

This suite intentionally stays Docker-independent so it can run in every normal
repository regression pass.  Real Docker/Qt behavior is covered by the dedicated
integration tests and the permanent manual-acceptance fixture documented for the
release.
"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.autograding.bundles import validate_test_bundle
from src.autograding.execution.result_protocol import BackendExecutionRecord
from src.autograding.models import ExecutionEnvironment, ExecutionResult, TestResult
from src.autograding.scoring import score_pytest_run
from src.autograding.testing.protocol import PytestRunResult
from src.autograding.testing.pytest_adapter import student_safe_pytest_summary
from src.tests.autograding_v233_service_support import (
    ASSESSMENT_ID as SERVICE_ASSESSMENT_ID,
    STUDENT_ID as SERVICE_STUDENT_ID,
    prepare_service,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROOT = _REPO_ROOT / "fixtures" / "v2.3.3_autograding_acceptance"


class TestAutogradingReleaseAcceptanceV233(unittest.TestCase):
    def _fixture_expected(self):
        return json.loads((_FIXTURE_ROOT / "EXPECTED_RESULTS.json").read_text(encoding="utf-8"))

    def _synthetic_run(self, config, statuses):
        environment = ExecutionEnvironment(
            environment_id="release-acceptance-env",
            backend="docker_pytest",
            language="python",
            interpreter_version="3.12",
            container_image="grading-app-python312-pytest:9.1.1",
            container_image_digest="sha256:" + ("a" * 64),
            metadata={"fixture": True},
        )
        execution = ExecutionResult(
            status="completed",
            exit_code=0 if all(value == "passed" for value in statuses.values()) else 1,
            started_at="2026-08-20T05:00:00Z",
            finished_at="2026-08-20T05:00:01Z",
            duration_ms=1000,
            stdout="",
            stderr="",
        )
        record = BackendExecutionRecord(
            run_id="agrun_release_fixture",
            backend_name="docker_pytest",
            environment=environment,
            result=execution,
            recorded_at="2026-08-20T05:00:01Z",
        )
        tests = []
        for definition in config.tests:
            status = statuses[definition.test_id]
            tests.append(
                TestResult(
                    test_id=definition.test_id,
                    status=status,
                    visibility=definition.visibility,
                    group_id=definition.group_id,
                    display_name=definition.name,
                    duration_ms=20,
                    message=("synthetic hidden detail" if definition.visibility == "hidden" and status != "passed" else None),
                    traceback=("SECRET TRACEBACK" if definition.visibility == "hidden" and status != "passed" else None),
                    stdout=("SECRET STDOUT" if definition.visibility == "hidden" and status != "passed" else ""),
                    stderr=("SECRET STDERR" if definition.visibility == "hidden" and status != "passed" else ""),
                    metadata={"pytest_nodeids": [definition.metadata.get("pytest_nodeid")]},
                )
            )
        return PytestRunResult(
            backend_record=record,
            test_results=tuple(tests),
            pytest_exit_code=execution.exit_code,
            pytest_version="9.1.1",
            collected_count=len(tests),
            selected_count=len(tests),
            requires_review=False,
        )

    def test_permanent_fixture_manifest_and_required_files_are_self_consistent(self):
        self.assertTrue(_FIXTURE_ROOT.is_dir())
        manifest_path = _FIXTURE_ROOT / "MANIFEST.txt"
        entries = {}
        for line in manifest_path.read_text(encoding="utf-8").splitlines()[2:]:
            if not line.strip():
                continue
            relative, digest = line.rsplit("  ", 1)
            entries[relative] = digest

        expected_paths = {
            str(path.relative_to(_FIXTURE_ROOT))
            for path in _FIXTURE_ROOT.rglob("*")
            if path.is_file() and path.name != "MANIFEST.txt"
        }
        self.assertEqual(set(entries), expected_paths)
        for relative, expected_digest in entries.items():
            actual = hashlib.sha256((_FIXTURE_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected_digest, relative)

    def test_release_fixture_bundle_validates_and_matches_expected_contract(self):
        bundle = validate_test_bundle(
            _FIXTURE_ROOT / "autograder_bundle",
            expected_assessment_id="V233_AUTO1",
        )
        self.assertEqual(bundle.config.assessment_id, "V233_AUTO1")
        self.assertEqual(bundle.config.entrypoint, "main.py")
        self.assertEqual(bundle.config.max_points, 10.0)
        self.assertEqual(
            tuple(item.test_id for item in bundle.config.tests),
            ("public_basic", "hidden_zero", "hidden_negative"),
        )
        self.assertEqual(
            tuple(item.visibility for item in bundle.config.tests),
            ("public", "hidden", "hidden"),
        )

    def test_release_fixture_sources_have_expected_syntax_profile(self):
        submissions = _FIXTURE_ROOT / "submissions"
        for student_id in ("aaron", "alice", "bob", "dave"):
            source = (submissions / student_id / "main.py").read_text(encoding="utf-8")
            compile(source, str(submissions / student_id / "main.py"), "exec")

        carol_source = (submissions / "carol" / "main.py").read_text(encoding="utf-8")
        with self.assertRaises(SyntaxError):
            compile(carol_source, str(submissions / "carol" / "main.py"), "exec")
        self.assertFalse((submissions / "eve").exists())

    def test_expected_release_fixture_scores_match_commit7_policy(self):
        expected = self._fixture_expected()
        bundle = validate_test_bundle(
            _FIXTURE_ROOT / "autograder_bundle",
            expected_assessment_id=expected["assessment_id"],
        )
        for student_id in ("aaron", "alice", "bob", "carol", "dave"):
            spec = expected["students"][student_id]
            run = self._synthetic_run(bundle.config, spec["statuses"])
            scored = score_pytest_run(bundle.config, run)
            self.assertEqual(scored.score_summary.final_score, spec["score"], student_id)
            self.assertEqual(scored.score_summary.requires_review, spec["requires_review"], student_id)

    def test_student_safe_release_summary_redacts_hidden_identity_and_diagnostics(self):
        expected = self._fixture_expected()
        bundle = validate_test_bundle(
            _FIXTURE_ROOT / "autograder_bundle",
            expected_assessment_id=expected["assessment_id"],
        )
        run = self._synthetic_run(bundle.config, expected["students"]["bob"]["statuses"])
        summary = student_safe_pytest_summary(run, bundle.config.reporting_policy)
        hidden = [item for item in summary["tests"] if item["visibility"] == "hidden"]
        self.assertEqual(len(hidden), 2)
        for item in hidden:
            self.assertTrue(item["test_id"].startswith("hidden_"))
            self.assertNotIn(item["test_id"], {"hidden_zero", "hidden_negative"})
            self.assertIsNone(item["traceback"])
            self.assertEqual(item["stdout"], "")
            self.assertEqual(item["stderr"], "")
            self.assertNotIn("pytest_nodeids", item["metadata"])

    def test_service_rerun_history_is_immutable_and_separate_from_manual_grading(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, submission, _factory = prepare_service(td)
            first = service.grade_submission(
                SERVICE_ASSESSMENT_ID,
                SERVICE_STUDENT_ID,
                bundle.reference.bundle_id,
            )
            second = service.grade_submission(
                SERVICE_ASSESSMENT_ID,
                SERVICE_STUDENT_ID,
                bundle.reference.bundle_id,
            )
            self.assertEqual(first.plan.submission_id, submission.submission_id)
            self.assertEqual(second.plan.submission_id, submission.submission_id)
            self.assertNotEqual(first.plan.run_id, second.plan.run_id)
            refs = service.list_history(SERVICE_ASSESSMENT_ID, SERVICE_STUDENT_ID)
            self.assertEqual(len(refs), 2)
            self.assertEqual({item.run_id for item in refs}, {first.plan.run_id, second.plan.run_id})
            for ref in refs:
                stored = service.load_run(SERVICE_ASSESSMENT_ID, SERVICE_STUDENT_ID, ref.run_id)
                self.assertEqual(stored.run.submission_id, submission.submission_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
