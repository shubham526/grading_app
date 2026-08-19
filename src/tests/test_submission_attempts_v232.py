"""Tests for v2.3.2 Commit 2 canonical submission attempt history."""

import json
from pathlib import Path
import tempfile
import unittest

from src.submissions import (
    CandidateFile,
    SubmissionRepository,
)


class TestSubmissionAttemptsV232(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "submission_evidence"
        self.repo = SubmissionRepository(str(self.evidence))

    def tearDown(self):
        self.tmp.cleanup()

    def _candidate(self, name: str, contents: str) -> CandidateFile:
        path = self.root / name
        path.write_text(contents, encoding="utf-8")

        return CandidateFile(
            source_path=str(path),
            original_filename=name,
            artifact_type="tex",
        )

    def test_second_submission_preserves_first_and_becomes_active(self):
        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate(
                    "bob_attempt1.tex",
                    "attempt 1",
                )
            ],
        )

        first_path = Path(
            self.repo.artifact_path(
                first,
                first.artifacts[0],
            )
        )
        first_bytes = first_path.read_bytes()
        first_hash = first.artifacts[0].sha256

        second = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate(
                    "bob_attempt2.tex",
                    "attempt 2",
                )
            ],
        )

        self.assertEqual(first.attempt, 1)
        self.assertEqual(second.attempt, 2)
        self.assertTrue(second.is_active_attempt)

        history = self.repo.list_submissions(
            "PS1",
            "bob",
        )

        self.assertEqual(
            [item.attempt for item in history],
            [1, 2],
        )
        self.assertFalse(history[0].is_active_attempt)
        self.assertTrue(history[1].is_active_attempt)

        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(
            history[0].artifacts[0].sha256,
            first_hash,
        )

    def test_switching_active_attempt_does_not_modify_manifests(self):
        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate("one.tex", "one")
            ],
        )
        second = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate("two.tex", "two")
            ],
        )

        first_manifest = (
            Path(self.repo.submission_directory(first))
            / "submission.json"
        )
        second_manifest = (
            Path(self.repo.submission_directory(second))
            / "submission.json"
        )

        first_before = first_manifest.read_bytes()
        second_before = second_manifest.read_bytes()

        activated = self.repo.set_active_submission(
            "PS1",
            "bob",
            first.submission_id,
        )

        self.assertTrue(activated.is_active_attempt)
        self.assertEqual(
            self.repo.get_active_submission(
                "PS1",
                "bob",
            ).submission_id,
            first.submission_id,
        )

        history = self.repo.list_submissions(
            "PS1",
            "bob",
        )
        by_id = {
            item.submission_id: item
            for item in history
        }

        self.assertTrue(
            by_id[
                first.submission_id
            ].is_active_attempt
        )
        self.assertFalse(
            by_id[
                second.submission_id
            ].is_active_attempt
        )

        self.assertEqual(
            first_manifest.read_bytes(),
            first_before,
        )
        self.assertEqual(
            second_manifest.read_bytes(),
            second_before,
        )

    def test_make_active_false_preserves_existing_active_attempt(self):
        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate("one.tex", "one")
            ],
        )

        second = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            make_active=False,
            files=[
                self._candidate("two.tex", "two")
            ],
        )

        active = self.repo.get_active_submission(
            "PS1",
            "bob",
        )

        self.assertEqual(
            active.submission_id,
            first.submission_id,
        )
        self.assertFalse(
            self.repo.get_submission(
                second.submission_id,
                assessment_id="PS1",
                student_id="bob",
            ).is_active_attempt
        )

    def test_first_submission_becomes_active_even_if_make_active_false(self):
        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            make_active=False,
            files=[
                self._candidate("one.tex", "one")
            ],
        )

        self.assertTrue(first.is_active_attempt)
        self.assertEqual(
            self.repo.get_active_submission(
                "PS1",
                "bob",
            ).submission_id,
            first.submission_id,
        )

    def test_explicit_attempt_number_and_duplicate_attempt_rejection(self):
        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            attempt=4,
            files=[
                self._candidate("four.tex", "four")
            ],
        )

        self.assertEqual(first.attempt, 4)
        self.assertEqual(
            self.repo.next_attempt_number(
                "PS1",
                "bob",
            ),
            5,
        )

        with self.assertRaises(ValueError):
            self.repo.create_submission(
                assessment_id="PS1",
                student_id="bob",
                attempt=4,
                files=[
                    self._candidate(
                        "four_again.tex",
                        "different",
                    )
                ],
            )

    def test_active_attempt_survives_repository_restart(self):
        first = self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate("one.tex", "one")
            ],
        )
        self.repo.create_submission(
            assessment_id="PS1",
            student_id="bob",
            files=[
                self._candidate("two.tex", "two")
            ],
        )

        self.repo.set_active_submission(
            "PS1",
            "bob",
            first.submission_id,
        )

        reopened = SubmissionRepository(
            str(self.evidence),
            create=False,
        )

        active = reopened.get_active_submission(
            "PS1",
            "bob",
        )

        self.assertEqual(
            active.submission_id,
            first.submission_id,
        )
        self.assertTrue(active.is_active_attempt)

    def test_index_records_original_ids_not_only_path_components(self):
        self.repo.create_submission(
            assessment_id="PS 1 / Fall",
            student_id="Bob Smith",
            files=[
                self._candidate("one.tex", "one")
            ],
        )

        paths = self.repo.paths(
            "PS 1 / Fall",
            "Bob Smith",
        )
        index = json.loads(
            Path(paths.index_path).read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            index["assessment_id"],
            "PS 1 / Fall",
        )
        self.assertEqual(
            index["student_id"],
            "Bob Smith",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
