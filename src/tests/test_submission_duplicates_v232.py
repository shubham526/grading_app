"""Tests for v2.3.2 Commit 3 duplicate and attempt preparation semantics."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import tempfile
import unittest

from src.submissions import SubmissionImporter, SubmissionRepository
from src.submissions.domain import VALIDATION_STATUS_DUPLICATE, VALIDATION_STATUS_READY
from src.submissions.importer import (
    DUPLICATE_STATUS_EXACT_ACTIVE,
    DUPLICATE_STATUS_EXACT_HISTORICAL,
    DUPLICATE_STATUS_IN_BATCH_EXACT,
    DUPLICATE_STATUS_SAME_FILENAMES_CHANGED,
)
from src.submissions.sources.local import discover_local_files


@dataclass
class StudentRecord:
    student_id: str
    student_name: str
    assessment_path: Optional[str] = None


class TestSubmissionDuplicatePreparation(unittest.TestCase):
    def _setup(self, root: Path):
        repository = SubmissionRepository(str(root / "evidence"))
        importer = SubmissionImporter(
            repository,
            assessment_id="PS1",
            roster=[StudentRecord("s001", "Jane Doe")],
        )
        return repository, importer

    def _candidate(self, path: Path, importer: SubmissionImporter):
        candidate = discover_local_files([str(path)], assessment_id="PS1")[0]
        return importer.prepare_candidate(candidate)

    def test_exact_active_duplicate_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "s001_PS1.tex"
            path.write_text("A", encoding="utf-8")
            repository, importer = self._setup(root)

            first = self._candidate(path, importer)
            saved = importer.commit_candidate(first)
            duplicate = self._candidate(path, importer)

            self.assertEqual(duplicate.validation_status, VALIDATION_STATUS_DUPLICATE)
            self.assertEqual(
                duplicate.metadata["duplicate_status"],
                DUPLICATE_STATUS_EXACT_ACTIVE,
            )
            self.assertEqual(
                duplicate.metadata["duplicate_submission_id"],
                saved.submission_id,
            )

    def test_same_filename_changed_bytes_becomes_new_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "s001_PS1.tex"
            path.write_text("A", encoding="utf-8")
            repository, importer = self._setup(root)

            importer.commit_candidate(self._candidate(path, importer))
            path.write_text("B changed", encoding="utf-8")
            changed = self._candidate(path, importer)

            self.assertEqual(changed.validation_status, VALIDATION_STATUS_READY)
            self.assertEqual(changed.proposed_attempt, 2)
            self.assertEqual(
                changed.metadata["duplicate_status"],
                DUPLICATE_STATUS_SAME_FILENAMES_CHANGED,
            )
            self.assertIn("same_filenames_different_bytes", changed.warnings)

    def test_exact_historical_duplicate_is_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "s001_PS1.tex"
            path.write_text("A", encoding="utf-8")
            repository, importer = self._setup(root)

            attempt1 = importer.commit_candidate(self._candidate(path, importer))
            path.write_text("B", encoding="utf-8")
            attempt2 = importer.commit_candidate(self._candidate(path, importer))
            self.assertTrue(attempt2.is_active_attempt)

            path.write_text("A", encoding="utf-8")
            duplicate = self._candidate(path, importer)
            self.assertEqual(duplicate.validation_status, VALIDATION_STATUS_DUPLICATE)
            self.assertEqual(
                duplicate.metadata["duplicate_status"],
                DUPLICATE_STATUS_EXACT_HISTORICAL,
            )
            self.assertEqual(
                duplicate.metadata["duplicate_submission_id"],
                attempt1.submission_id,
            )

    def test_exact_duplicates_inside_same_uncommitted_batch_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "a" / "s001_PS1.tex"
            second_path = root / "b" / "s001_PS1.tex"
            first_path.parent.mkdir()
            second_path.parent.mkdir()
            first_path.write_text("same", encoding="utf-8")
            second_path.write_text("same", encoding="utf-8")
            _, importer = self._setup(root)

            candidates = discover_local_files([str(first_path), str(second_path)], assessment_id="PS1")
            prepared = importer.prepare_candidates(candidates)

            self.assertEqual(prepared[0].validation_status, VALIDATION_STATUS_READY)
            self.assertEqual(prepared[0].proposed_attempt, 1)
            self.assertEqual(prepared[1].validation_status, VALIDATION_STATUS_DUPLICATE)
            self.assertEqual(
                prepared[1].metadata["duplicate_status"],
                DUPLICATE_STATUS_IN_BATCH_EXACT,
            )

    def test_two_changed_candidates_for_same_student_receive_sequential_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "a" / "s001_PS1.tex"
            second_path = root / "b" / "s001_PS1.tex"
            first_path.parent.mkdir()
            second_path.parent.mkdir()
            first_path.write_text("first", encoding="utf-8")
            second_path.write_text("second", encoding="utf-8")
            _, importer = self._setup(root)

            candidates = discover_local_files([str(first_path), str(second_path)], assessment_id="PS1")
            prepared = importer.prepare_candidates(candidates)

            self.assertEqual(
                [item.proposed_attempt for item in prepared],
                [1, 2],
            )
            self.assertTrue(all(item.validation_status == VALIDATION_STATUS_READY for item in prepared))

    def test_force_duplicate_creates_explicit_new_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "s001_PS1.tex"
            path.write_text("A", encoding="utf-8")
            repository, importer = self._setup(root)

            importer.commit_candidate(self._candidate(path, importer))
            duplicate = self._candidate(path, importer)
            forced = importer.commit_candidate(duplicate, force_duplicate=True)

            self.assertEqual(forced.attempt, 2)
            self.assertEqual(len(repository.list_submissions("PS1", "s001")), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
