"""Tests for v2.3.2 Commit 3 source-agnostic import orchestration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import tempfile
import unittest

from src.submissions import (
    LocalFileSourceAdapter,
    SubmissionImporter,
    SubmissionRepository,
)
from src.submissions.domain import (
    MATCH_STATUS_AMBIGUOUS,
    MATCH_STATUS_MATCHED,
    SOURCE_SYSTEM_LOCAL_UPLOAD,
    VALIDATION_STATUS_NEEDS_MAPPING,
    VALIDATION_STATUS_READY,
)
from src.submissions.sources.local import discover_local_files


@dataclass
class StudentRecord:
    student_id: str
    student_name: str
    assessment_path: Optional[str] = None


class TestSubmissionImporter(unittest.TestCase):
    def _importer(self, root: Path, roster=None):
        return SubmissionImporter(
            SubmissionRepository(str(root / "evidence")),
            assessment_id="PS1",
            roster=roster or [
                StudentRecord("s001", "Jane Doe"),
                StudentRecord("s002", "Robert Smith"),
            ],
        )

    def test_matches_stable_student_id_token_in_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "s001_PS1.tex"
            path.write_text("A", encoding="utf-8")

            importer = self._importer(root)
            candidate = discover_local_files([str(path)], assessment_id="PS1")[0]
            prepared = importer.prepare_candidate(candidate)

            self.assertEqual(prepared.match_status, MATCH_STATUS_MATCHED)
            self.assertEqual(prepared.proposed_student_id, "s001")
            self.assertEqual(prepared.proposed_attempt, 1)
            self.assertEqual(prepared.validation_status, VALIDATION_STATUS_READY)

    def test_matches_student_name_tokens_in_either_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "Doe_Jane_PS1.tex"
            path.write_text("A", encoding="utf-8")

            importer = self._importer(root)
            prepared = importer.prepare_candidate(
                discover_local_files([str(path)], assessment_id="PS1")[0]
            )

            self.assertEqual(prepared.proposed_student_id, "s001")
            self.assertEqual(prepared.validation_status, VALIDATION_STATUS_READY)

    def test_ambiguous_name_match_requires_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "Alex_Kim_PS1.tex"
            path.write_text("A", encoding="utf-8")
            roster = [
                StudentRecord("s001", "Alex Kim"),
                StudentRecord("s002", "Alex Kim"),
            ]

            importer = self._importer(root, roster=roster)
            prepared = importer.prepare_candidate(
                discover_local_files([str(path)], assessment_id="PS1")[0]
            )

            self.assertEqual(prepared.match_status, MATCH_STATUS_AMBIGUOUS)
            self.assertEqual(prepared.validation_status, VALIDATION_STATUS_NEEDS_MAPPING)
            self.assertIsNone(prepared.proposed_student_id)

    def test_manual_student_override_resolves_unmatched_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "final_submission.tex"
            path.write_text("A", encoding="utf-8")

            importer = self._importer(root)
            candidate = discover_local_files([str(path)], assessment_id="PS1")[0]
            prepared = importer.prepare_candidate(candidate, student_override="s002")

            self.assertEqual(prepared.proposed_student_id, "s002")
            self.assertEqual(prepared.match_status, MATCH_STATUS_MATCHED)
            self.assertEqual(prepared.validation_status, VALIDATION_STATUS_READY)
            self.assertEqual(prepared.metadata["student_match"]["method"], "manual_override")

    def test_prepare_from_adapter_and_commit_creates_canonical_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "s001_PS1.tex"
            path.write_text("Question 1\nA", encoding="utf-8")

            repository = SubmissionRepository(str(root / "evidence"))
            importer = SubmissionImporter(
                repository,
                assessment_id="PS1",
                roster=[StudentRecord("s001", "Jane Doe")],
            )
            adapter = LocalFileSourceAdapter.from_files([str(path)])

            prepared = importer.prepare_from_adapter(adapter)
            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].validation_status, VALIDATION_STATUS_READY)

            submission = importer.commit_candidate(prepared[0], adapter=adapter)
            self.assertEqual(submission.student_id, "s001")
            self.assertEqual(submission.assessment_id, "PS1")
            self.assertEqual(submission.attempt, 1)
            self.assertTrue(submission.is_active_attempt)
            self.assertEqual(submission.source_system, SOURCE_SYSTEM_LOCAL_UPLOAD)
            self.assertEqual(len(submission.artifacts), 1)
            self.assertTrue(Path(repository.artifact_path(submission, submission.artifacts[0])).is_file())
            self.assertEqual(
                submission.metadata["import_candidate_id"],
                prepared[0].candidate_id,
            )

    def test_commit_batch_reports_imports_and_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jane = root / "s001_PS1.tex"
            unknown = root / "mystery_PS1.tex"
            jane.write_text("A", encoding="utf-8")
            unknown.write_text("B", encoding="utf-8")

            repository = SubmissionRepository(str(root / "evidence"))
            importer = SubmissionImporter(
                repository,
                assessment_id="PS1",
                roster=[StudentRecord("s001", "Jane Doe")],
            )
            adapter = LocalFileSourceAdapter.from_files([str(jane), str(unknown)])
            prepared = importer.prepare_from_adapter(adapter)

            result = importer.commit_candidates(prepared, adapter=adapter, created_by="tester")
            self.assertEqual(result.batch.candidate_count, 2)
            self.assertEqual(result.batch.imported_count, 1)
            self.assertEqual(result.batch.skipped_count, 1)
            self.assertEqual(result.batch.error_count, 0)
            self.assertEqual(len(result.submissions), 1)
            self.assertEqual(result.batch.created_by, "tester")


if __name__ == "__main__":
    unittest.main(verbosity=2)
