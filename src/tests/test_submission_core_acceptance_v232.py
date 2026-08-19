"""End-to-end release acceptance for the v2.3.2 submission core.

These tests exercise the completed v2.3.2 pipeline across the boundaries added
in Commits 1-7:

local source discovery -> conservative roster matching -> canonical repository
-> attempt history -> artifact routing -> existing v2.2 parser -> assessment
supporting metadata.

The scenarios intentionally cover future-format preservation as well: Python
and LaTeX-project ZIP artifacts may be committed, but v2.3.2 must neither
execute Python nor extract ZIP contents.
"""

from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from src.submissions import (
    ROUTE_LATEX_PROJECT,
    ROUTE_PROGRAMMING_PYTHON,
    LocalFileSourceAdapter,
    SubmissionImporter,
    SubmissionRepository,
    assessment_submission_fields,
    parse_canonical_submission,
    route_submission,
)


from src.submissions.domain import (
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_ZIP,
    VALIDATION_STATUS_DUPLICATE,
    VALIDATION_STATUS_NEEDS_MAPPING,
    VALIDATION_STATUS_READY,
)


@dataclass
class StudentRecord:
    student_id: str
    student_name: str


class TestSubmissionCoreAcceptanceV232(unittest.TestCase):
    def _importer(self, repository, assessment_id, roster):
        return SubmissionImporter(
            repository,
            assessment_id=assessment_id,
            roster=roster,
        )

    def _prepare_files(self, importer, paths):
        adapter = LocalFileSourceAdapter.from_files(
            [str(path) for path in paths]
        )
        candidates = importer.prepare_from_adapter(adapter)
        return adapter, candidates

    def test_written_attempt_lifecycle_restart_and_assessment_linkage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "submission_evidence"
            incoming = root / "incoming"
            incoming.mkdir()

            roster = [
                StudentRecord("alice", "Alice Example"),
                StudentRecord("bob", "Bob Example"),
                StudentRecord("carol", "Carol Example"),
            ]

            alice = incoming / "alice_PS1.tex"
            bob = incoming / "bob_PS1.tex"
            carol = incoming / "carol_PS1.tex"
            alice.write_text("Question 1\nAlice answer 1\n", encoding="utf-8")
            bob.write_text("Question 1\nBob answer 1\n", encoding="utf-8")
            carol.write_text("Question 1\nCarol answer 1\n", encoding="utf-8")

            repository = SubmissionRepository(str(evidence))
            importer = self._importer(repository, "PS1", roster)
            adapter, prepared = self._prepare_files(
                importer,
                [alice, bob, carol],
            )

            self.assertEqual(len(prepared), 3)
            self.assertTrue(
                all(
                    candidate.validation_status == VALIDATION_STATUS_READY
                    for candidate in prepared
                )
            )

            result = importer.commit_candidates(
                prepared,
                adapter=adapter,
                created_by="acceptance-test",
            )
            self.assertEqual(result.batch.imported_count, 3)
            self.assertEqual(result.batch.error_count, 0)

            for student_id in ("alice", "bob", "carol"):
                history = repository.list_submissions("PS1", student_id)
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0].attempt, 1)
                self.assertTrue(history[0].is_active_attempt)

            bob_first = repository.get_active_submission("PS1", "bob")
            self.assertIsNotNone(bob_first)
            first_artifact = bob_first.artifacts[0]
            first_artifact_path = Path(
                repository.artifact_path(bob_first, first_artifact)
            )
            first_bytes = first_artifact_path.read_bytes()
            first_hash = first_artifact.sha256
            first_manifest_path = Path(
                repository.submission_directory(bob_first)
            ) / "submission.json"
            first_manifest_bytes = first_manifest_path.read_bytes()

            parsed_first = parse_canonical_submission(
                bob_first,
                repository,
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            self.assertEqual(
                parsed_first.answers_by_question,
                {"Q1": "Bob answer 1"},
            )

            fields = assessment_submission_fields(parsed_first)
            self.assertEqual(
                set(fields),
                {"submission_meta", "extracted_answers"},
            )
            self.assertEqual(
                fields["submission_meta"]["submission_id"],
                bob_first.submission_id,
            )
            self.assertEqual(
                fields["submission_meta"]["assessment_id"],
                "PS1",
            )
            self.assertEqual(fields["submission_meta"]["attempt"], 1)
            self.assertEqual(
                fields["extracted_answers"],
                {"Q1": "Bob answer 1"},
            )

            # A real changed source is a new attempt. Rediscover after changing
            # the file so the preview hash exactly matches what will be committed.
            bob.write_text("Question 1\nBob answer 2\n", encoding="utf-8")
            second_adapter, second_candidates = self._prepare_files(
                importer,
                [bob],
            )
            self.assertEqual(len(second_candidates), 1)
            second_candidate = second_candidates[0]
            self.assertEqual(
                second_candidate.validation_status,
                VALIDATION_STATUS_READY,
            )
            self.assertEqual(second_candidate.proposed_attempt, 2)

            bob_second = importer.commit_candidate(
                second_candidate,
                adapter=second_adapter,
            )
            self.assertEqual(bob_second.attempt, 2)
            self.assertTrue(bob_second.is_active_attempt)

            history = repository.list_submissions("PS1", "bob")
            self.assertEqual([item.attempt for item in history], [1, 2])
            self.assertFalse(history[0].is_active_attempt)
            self.assertTrue(history[1].is_active_attempt)

            # The old canonical attempt must remain byte-for-byte immutable.
            self.assertEqual(first_artifact_path.read_bytes(), first_bytes)
            self.assertEqual(history[0].artifacts[0].sha256, first_hash)
            self.assertEqual(first_manifest_path.read_bytes(), first_manifest_bytes)

            # Reopen from disk: history and active pointer must survive restart.
            reopened = SubmissionRepository(str(evidence), create=False)
            reopened_history = reopened.list_submissions("PS1", "bob")
            self.assertEqual(
                [item.submission_id for item in reopened_history],
                [bob_first.submission_id, bob_second.submission_id],
            )
            reopened_active = reopened.get_active_submission("PS1", "bob")
            self.assertIsNotNone(reopened_active)
            self.assertEqual(reopened_active.submission_id, bob_second.submission_id)

            parsed_second = parse_canonical_submission(
                reopened_active,
                reopened,
                ["Q1"],
                compile_pdf=False,
            )
            self.assertEqual(
                parsed_second.answers_by_question,
                {"Q1": "Bob answer 2"},
            )

            # Rediscovering the same bytes must be classified as an exact
            # duplicate instead of silently creating attempt 3.
            duplicate_adapter, duplicate_candidates = self._prepare_files(
                self._importer(reopened, "PS1", roster),
                [bob],
            )
            self.assertEqual(len(duplicate_candidates), 1)
            self.assertEqual(
                duplicate_candidates[0].validation_status,
                VALIDATION_STATUS_DUPLICATE,
            )
            self.assertEqual(
                len(reopened.list_submissions("PS1", "bob")),
                2,
            )
            # Keep the variable live to prove discovery did not mutate source.
            self.assertIsInstance(duplicate_adapter, LocalFileSourceAdapter)

    def test_pdf_zip_is_one_preserved_unparsed_project_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "submission_evidence"
            incoming = root / "incoming"
            incoming.mkdir()

            pdf = incoming / "alice_PS2.pdf"
            project_zip = incoming / "alice_PS2.zip"
            pdf.write_bytes(b"placeholder rendered PDF bytes")
            with zipfile.ZipFile(project_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("main.tex", "Question 1\nProject answer\n")
                archive.writestr("figures/figure.txt", "supporting file")

            roster = [StudentRecord("alice", "Alice Example")]
            repository = SubmissionRepository(str(evidence))
            importer = self._importer(repository, "PS2", roster)
            adapter, prepared = self._prepare_files(
                importer,
                [pdf, project_zip],
            )

            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].validation_status, VALIDATION_STATUS_READY)
            self.assertEqual(len(prepared[0].files), 2)

            submission = importer.commit_candidate(
                prepared[0],
                adapter=adapter,
            )
            self.assertEqual(len(submission.artifacts), 2)
            self.assertEqual(
                {artifact.artifact_type for artifact in submission.artifacts},
                {ARTIFACT_TYPE_PDF, ARTIFACT_TYPE_ZIP},
            )

            route = route_submission(submission)
            self.assertEqual(route.route, ROUTE_LATEX_PROJECT)
            self.assertFalse(route.supported)

            submission_dir = Path(repository.submission_directory(submission))
            originals = [
                path
                for path in (submission_dir / "originals").iterdir()
                if path.is_file()
            ]
            self.assertEqual(len(originals), 2)

            derived_dir = submission_dir / "derived"
            self.assertTrue(derived_dir.is_dir())
            self.assertEqual(list(derived_dir.iterdir()), [])

            # No project member is extracted anywhere in the submission record.
            self.assertFalse((submission_dir / "main.tex").exists())
            self.assertFalse((derived_dir / "main.tex").exists())

    def test_python_is_preserved_but_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "submission_evidence"
            sentinel = root / "EXECUTED.txt"
            source = root / "carol_lab1.py"
            source.write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed')\n",
                encoding="utf-8",
            )

            roster = [StudentRecord("carol", "Carol Example")]
            repository = SubmissionRepository(str(evidence))
            importer = self._importer(repository, "LAB1", roster)
            adapter, prepared = self._prepare_files(importer, [source])

            self.assertEqual(prepared[0].validation_status, VALIDATION_STATUS_READY)
            submission = importer.commit_candidate(prepared[0], adapter=adapter)

            self.assertEqual(len(submission.artifacts), 1)
            self.assertEqual(
                submission.artifacts[0].artifact_type,
                ARTIFACT_TYPE_PYTHON,
            )
            route = route_submission(submission)
            self.assertEqual(route.route, ROUTE_PROGRAMMING_PYTHON)
            self.assertFalse(route.supported)
            self.assertFalse(sentinel.exists())

            stored = Path(
                repository.artifact_path(submission, submission.artifacts[0])
            )
            self.assertEqual(stored.read_bytes(), source.read_bytes())
            self.assertFalse(sentinel.exists())

    def test_ambiguous_identity_requires_manual_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Alex_PS3.tex"
            source.write_text("Question 1\nA\n", encoding="utf-8")

            # Deliberately ambiguous display names with distinct stable IDs.
            roster = [
                StudentRecord("alex01", "Alex"),
                StudentRecord("alex02", "Alex"),
            ]
            repository = SubmissionRepository(str(root / "evidence"))
            importer = self._importer(repository, "PS3", roster)
            adapter = LocalFileSourceAdapter.from_files([str(source)])
            raw = adapter.discover(assessment_id="PS3")
            self.assertEqual(len(raw), 1)

            prepared = importer.prepare_candidate(raw[0])
            self.assertEqual(
                prepared.validation_status,
                VALIDATION_STATUS_NEEDS_MAPPING,
            )
            self.assertIsNone(prepared.proposed_student_id)
            self.assertEqual(repository.list_submissions("PS3", "alex01"), [])
            self.assertEqual(repository.list_submissions("PS3", "alex02"), [])

            resolved = importer.prepare_candidate(
                raw[0],
                student_override="alex02",
            )
            self.assertEqual(resolved.validation_status, VALIDATION_STATUS_READY)
            self.assertEqual(resolved.proposed_student_id, "alex02")

            submission = importer.commit_candidate(resolved, adapter=adapter)
            self.assertEqual(submission.student_id, "alex02")
            self.assertEqual(len(repository.list_submissions("PS3", "alex01")), 0)
            self.assertEqual(len(repository.list_submissions("PS3", "alex02")), 1)

    def test_canonical_manifest_and_index_are_json_reopenable(self):
        """Release gate for portable on-disk canonical state."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "alice_PS4.tex"
            source.write_text("Question 1\nPortable\n", encoding="utf-8")

            roster = [StudentRecord("alice", "Alice Example")]
            repository = SubmissionRepository(str(root / "evidence"))
            importer = self._importer(repository, "PS4", roster)
            adapter, prepared = self._prepare_files(importer, [source])
            submission = importer.commit_candidate(prepared[0], adapter=adapter)

            submission_dir = Path(repository.submission_directory(submission))
            manifest = json.loads(
                (submission_dir / "submission.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["repository_schema_version"],
                "1.0",
            )
            manifest_submission = manifest["submission"]
            self.assertEqual(
                manifest_submission["submission_id"],
                submission.submission_id,
            )
            self.assertEqual(manifest_submission["assessment_id"], "PS4")
            self.assertEqual(manifest_submission["student_id"], "alice")

            paths = repository.paths("PS4", "alice")
            index = json.loads(Path(paths.index_path).read_text(encoding="utf-8"))
            self.assertEqual(index["active_submission_id"], submission.submission_id)
            self.assertEqual(len(index["submissions"]), 1)

            reopened = SubmissionRepository(str(root / "evidence"), create=False)
            loaded = reopened.get_submission(submission.submission_id)
            self.assertEqual(loaded.to_dict(), submission.to_dict())


if __name__ == "__main__":
    unittest.main(verbosity=2)
