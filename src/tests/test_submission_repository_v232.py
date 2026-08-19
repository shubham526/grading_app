"""Tests for v2.3.2 Commit 2 canonical submission repository."""

import json
from pathlib import Path
import tempfile
import unittest

from src.submissions import (
    CandidateFile,
    ExternalReference,
    SubmissionRepository,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_LATEX_PROJECT_ZIP,
    ARTIFACT_TYPE_PDF,
    SOURCE_SYSTEM_CANVAS,
)


class TestSubmissionRepositoryV232(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "submission_evidence"
        self.repo = SubmissionRepository(str(self.evidence))

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_create_submission_copies_original_immutably(self):
        source = self._write("alice.tex", b"Question 1\nA")

        submission = self.repo.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[
                CandidateFile(
                    source_path=str(source),
                    original_filename="alice.tex",
                    artifact_type="tex",
                )
            ],
        )

        self.assertEqual(submission.attempt, 1)
        self.assertTrue(submission.is_active_attempt)
        self.assertEqual(len(submission.artifacts), 1)

        artifact = submission.artifacts[0]
        stored = Path(
            self.repo.artifact_path(
                submission,
                artifact,
            )
        )

        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), b"Question 1\nA")
        self.assertNotEqual(stored.resolve(), source.resolve())
        self.assertEqual(artifact.size_bytes, len(b"Question 1\nA"))

        source.write_bytes(b"changed after import")

        self.assertEqual(stored.read_bytes(), b"Question 1\nA")
        self.assertTrue(
            self.repo.verify_submission(submission)["ok"]
        )

    def test_repository_supports_multi_artifact_submission(self):
        pdf = self._write("alice_PS1.pdf", b"%PDF fake")
        project = self._write("alice_PS1.zip", b"PK fake")

        submission = self.repo.create_submission(
            assessment_id="PS1",
            student_id="alice",
            source_system=SOURCE_SYSTEM_CANVAS,
            submitted_at="2026-08-18T20:00:00Z",
            files=[
                CandidateFile(
                    source_path=str(pdf),
                    original_filename="alice_PS1.pdf",
                    artifact_type=ARTIFACT_TYPE_PDF,
                    role=ARTIFACT_ROLE_RENDERED,
                ),
                CandidateFile(
                    source_path=str(project),
                    original_filename="alice_PS1.zip",
                    artifact_type=ARTIFACT_TYPE_LATEX_PROJECT_ZIP,
                    role=ARTIFACT_ROLE_SOURCE,
                ),
            ],
            external_refs=[
                ExternalReference(
                    system="canvas",
                    entity_type="assignment",
                    external_id="3889170",
                )
            ],
        )

        self.assertEqual(len(submission.artifacts), 2)
        self.assertEqual(
            len(
                submission.artifacts_by_role(
                    ARTIFACT_ROLE_RENDERED
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                submission.artifacts_by_role(
                    ARTIFACT_ROLE_SOURCE
                )
            ),
            1,
        )
        self.assertEqual(
            submission.external_refs[0].external_id,
            "3889170",
        )
        self.assertTrue(
            self.repo.verify_submission(submission)["ok"]
        )

    def test_manifest_and_index_use_relative_artifact_paths(self):
        source = self._write("alice.tex", b"A")

        submission = self.repo.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[
                CandidateFile(
                    source_path=str(source),
                    original_filename="alice.tex",
                    artifact_type="tex",
                )
            ],
        )

        submission_dir = Path(
            self.repo.submission_directory(submission)
        )
        manifest = json.loads(
            (
                submission_dir / "submission.json"
            ).read_text(encoding="utf-8")
        )

        stored_relative = manifest[
            "submission"
        ][
            "artifacts"
        ][0][
            "stored_relative_path"
        ]

        self.assertFalse(Path(stored_relative).is_absolute())
        self.assertTrue(
            (
                submission_dir / stored_relative
            ).is_file()
        )

    def test_get_submission_by_opaque_id_survives_restart(self):
        source = self._write("alice.tex", b"A")

        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[
                CandidateFile(
                    source_path=str(source),
                    original_filename="alice.tex",
                    artifact_type="tex",
                )
            ],
        )

        reopened = SubmissionRepository(
            str(self.evidence),
            create=False,
        )

        loaded = reopened.get_submission(
            first.submission_id
        )

        self.assertEqual(
            loaded.to_dict(),
            first.to_dict(),
        )
        self.assertTrue(
            reopened.verify_submission(loaded)["ok"]
        )

    def test_tampering_is_detected(self):
        source = self._write("alice.tex", b"A")

        submission = self.repo.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[
                CandidateFile(
                    source_path=str(source),
                    original_filename="alice.tex",
                    artifact_type="tex",
                )
            ],
        )

        stored = Path(
            self.repo.artifact_path(
                submission,
                submission.artifacts[0],
            )
        )
        stored.write_bytes(b"tampered")

        result = self.repo.verify_submission(submission)

        self.assertFalse(result["ok"])
        self.assertFalse(
            result[
                "artifacts"
            ][
                submission.artifacts[0].artifact_id
            ][
                "ok"
            ]
        )

    def test_candidate_hash_mismatch_aborts_commit(self):
        source = self._write("alice.tex", b"A")

        candidate = CandidateFile(
            source_path=str(source),
            original_filename="alice.tex",
            artifact_type="tex",
            size_bytes=1,
            sha256="a" * 64,
        )

        with self.assertRaises(ValueError):
            self.repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[candidate],
            )

        self.assertEqual(
            self.repo.list_submissions(
                "PS1",
                "alice",
            ),
            [],
        )

    def test_submission_lookup_with_wrong_context_fails(self):
        source = self._write("alice.tex", b"A")

        submission = self.repo.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[
                CandidateFile(
                    source_path=str(source),
                    original_filename="alice.tex",
                    artifact_type="tex",
                )
            ],
        )

        with self.assertRaises((KeyError, FileNotFoundError)):
            self.repo.get_submission(
                submission.submission_id,
                assessment_id="PS1",
                student_id="bob",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
