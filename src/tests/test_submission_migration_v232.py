"""Tests for v2.3.2 Commit 5 legacy evidence migration/linkage."""

import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.submissions import (
    MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT,
    MIGRATION_STATUS_CREATED,
    MIGRATION_STATUS_EXISTING,
    LegacyEvidenceAssessmentMismatchError,
    LegacyEvidenceVerificationError,
    SubmissionRepository,
    assessment_submission_fields,
    ensure_canonical_submission,
    load_persisted_submission,
    migrate_legacy_submission,
    parse_canonical_submission,
    parse_pdf_accommodation,
    parse_submission,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_TEX,
    CandidateFile,
    SOURCE_SYSTEM_LEGACY_LOCAL,
    SOURCE_SYSTEM_LOCAL_UPLOAD,
)


def _blank_pdf(path):
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(path))
    doc.close()


class TestLegacySubmissionMigration(unittest.TestCase):

    def test_legacy_latex_migration_is_nondestructive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text(
                "\\begin{document}\nQuestion 1\nAnswer A\n\\end{document}\n",
                encoding="utf-8",
            )

            parsed = parse_submission(
                str(source),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            legacy_source = Path(parsed.files["latex"])
            legacy_before = legacy_source.read_bytes()

            repository = SubmissionRepository(str(evidence))
            first = migrate_legacy_submission(
                str(evidence),
                "PS1",
                "alice",
                repository=repository,
            )

            self.assertEqual(first.status, MIGRATION_STATUS_CREATED)
            self.assertTrue(first.created)
            self.assertEqual(first.submission.attempt, 1)
            self.assertTrue(first.submission.is_active_attempt)
            self.assertEqual(
                first.submission.source_system,
                SOURCE_SYSTEM_LEGACY_LOCAL,
            )
            self.assertEqual(len(first.submission.artifacts), 1)
            self.assertEqual(
                first.submission.artifacts[0].artifact_type,
                ARTIFACT_TYPE_TEX,
            )
            self.assertEqual(
                first.submission.artifacts[0].original_filename,
                "alice.tex",
            )

            canonical_path = Path(
                repository.artifact_path(
                    first.submission,
                    first.submission.artifacts[0],
                )
            )
            self.assertEqual(canonical_path.read_bytes(), legacy_before)
            self.assertEqual(legacy_source.read_bytes(), legacy_before)
            self.assertTrue(legacy_source.exists())

            again = migrate_legacy_submission(
                str(evidence),
                "PS1",
                "alice",
                repository=repository,
            )
            self.assertEqual(again.status, MIGRATION_STATUS_EXISTING)
            self.assertFalse(again.created)
            self.assertEqual(
                again.submission.submission_id,
                first.submission.submission_id,
            )
            self.assertEqual(
                len(repository.list_submissions("PS1", "alice")),
                1,
            )

    def test_repersisting_same_source_does_not_create_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text(
                "Question 1\nSame answer\n",
                encoding="utf-8",
            )

            parse_submission(
                str(source),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            repository = SubmissionRepository(str(evidence))
            first = migrate_legacy_submission(
                str(evidence), "PS1", "alice", repository=repository
            )

            # Refresh the legacy v2.2 evidence. Its persisted_at/manifest changes,
            # but the authoritative source bytes do not.
            parse_submission(
                str(source),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            second = migrate_legacy_submission(
                str(evidence), "PS1", "alice", repository=repository
            )

            self.assertEqual(second.status, MIGRATION_STATUS_EXISTING)
            self.assertEqual(
                second.submission.submission_id,
                first.submission.submission_id,
            )
            self.assertEqual(
                len(repository.list_submissions("PS1", "alice")), 1
            )

    def test_changed_legacy_source_creates_new_attempt_and_preserves_old_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text("Question 1\nAnswer A\n", encoding="utf-8")

            parse_submission(
                str(source),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            repository = SubmissionRepository(str(evidence))
            first = migrate_legacy_submission(
                str(evidence), "PS1", "alice", repository=repository
            )
            first_path = Path(
                repository.artifact_path(
                    first.submission,
                    first.submission.artifacts[0],
                )
            )
            first_bytes = first_path.read_bytes()

            source.write_text("Question 1\nAnswer B\n", encoding="utf-8")
            parse_submission(
                str(source),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            second = migrate_legacy_submission(
                str(evidence), "PS1", "alice", repository=repository
            )

            self.assertEqual(second.status, MIGRATION_STATUS_CREATED)
            self.assertEqual(second.submission.attempt, 2)
            self.assertTrue(second.submission.is_active_attempt)
            self.assertNotEqual(
                second.submission.submission_id,
                first.submission.submission_id,
            )
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertIn(b"Answer A", first_path.read_bytes())
            second_path = Path(
                repository.artifact_path(
                    second.submission,
                    second.submission.artifacts[0],
                )
            )
            self.assertIn(b"Answer B", second_path.read_bytes())

            history = repository.list_submissions("PS1", "alice")
            self.assertEqual([item.attempt for item in history], [1, 2])
            self.assertFalse(history[0].is_active_attempt)
            self.assertTrue(history[1].is_active_attempt)

    def test_tampered_legacy_evidence_is_not_promoted_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text("Question 1\nA\n", encoding="utf-8")

            parsed = parse_submission(
                str(source),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            Path(parsed.files["latex"]).write_text(
                "tampered",
                encoding="utf-8",
            )

            with self.assertRaises(LegacyEvidenceVerificationError):
                migrate_legacy_submission(
                    str(evidence),
                    "PS1",
                    "alice",
                )

    def test_pdf_accommodation_migrates_original_pdf_not_derived_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            pdf = root / "alice.pdf"
            _blank_pdf(pdf)

            parsed = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="alice",
                evidence_dir=str(evidence),
            )
            self.assertTrue(parsed.page_image_paths)

            result = migrate_legacy_submission(
                str(evidence),
                "PS1",
                "alice",
            )

            self.assertEqual(len(result.submission.artifacts), 1)
            artifact = result.submission.artifacts[0]
            self.assertEqual(artifact.artifact_type, ARTIFACT_TYPE_PDF)
            self.assertEqual(artifact.role, ARTIFACT_ROLE_PRIMARY)
            self.assertEqual(artifact.original_filename, "alice.pdf")

    def test_ensure_returns_existing_active_canonical_without_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text("Question 1\nA\n", encoding="utf-8")

            repository = SubmissionRepository(str(evidence))
            canonical = repository.create_submission(
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                files=[
                    CandidateFile(
                        source_path=str(source),
                        original_filename="alice.tex",
                        artifact_type=ARTIFACT_TYPE_TEX,
                    )
                ],
            )

            ensured = ensure_canonical_submission(
                str(evidence),
                "PS1",
                "alice",
                repository=repository,
            )

            self.assertIsNotNone(ensured)
            self.assertEqual(
                ensured.status,
                MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT,
            )
            self.assertEqual(
                ensured.submission.submission_id,
                canonical.submission_id,
            )


    def test_linked_legacy_evidence_cannot_migrate_into_another_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text("Question 1\nPS1 answer\n", encoding="utf-8")

            repository = SubmissionRepository(str(evidence))
            ps1 = repository.create_submission(
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                files=[
                    CandidateFile(
                        source_path=str(source),
                        original_filename="alice_PS1.tex",
                        artifact_type=ARTIFACT_TYPE_TEX,
                    )
                ],
            )
            parse_canonical_submission(
                ps1,
                repository,
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )

            with self.assertRaises(LegacyEvidenceAssessmentMismatchError):
                migrate_legacy_submission(
                    str(evidence),
                    "PS2",
                    "alice",
                    repository=repository,
                )

            self.assertEqual(repository.list_submissions("PS2", "alice"), [])

    def test_ensure_ignores_legacy_evidence_linked_to_another_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text("Question 1\nPS1 answer\n", encoding="utf-8")

            repository = SubmissionRepository(str(evidence))
            ps1 = repository.create_submission(
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                files=[
                    CandidateFile(
                        source_path=str(source),
                        original_filename="alice_PS1.tex",
                        artifact_type=ARTIFACT_TYPE_TEX,
                    )
                ],
            )
            parse_canonical_submission(
                ps1,
                repository,
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )

            ensured = ensure_canonical_submission(
                str(evidence),
                "PS2",
                "alice",
                repository=repository,
            )

            self.assertIsNone(ensured)
            self.assertEqual(repository.list_submissions("PS2", "alice"), [])

    def test_canonical_bridge_link_survives_legacy_reload_and_assessment_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            source = root / "alice.tex"
            source.write_text("Question 1\nAnswer A\n", encoding="utf-8")

            repository = SubmissionRepository(str(evidence))
            canonical = repository.create_submission(
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                files=[
                    CandidateFile(
                        source_path=str(source),
                        original_filename="alice.tex",
                        artifact_type=ARTIFACT_TYPE_TEX,
                    )
                ],
            )

            parsed = parse_canonical_submission(
                canonical,
                repository,
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )

            fields = assessment_submission_fields(parsed)
            self.assertEqual(
                set(fields),
                {"submission_meta", "extracted_answers"},
            )
            meta = fields["submission_meta"]
            self.assertEqual(meta["submission_id"], canonical.submission_id)
            self.assertEqual(meta["assessment_id"], "PS1")
            self.assertEqual(meta["attempt"], 1)
            self.assertEqual(meta["source_system"], SOURCE_SYSTEM_LOCAL_UPLOAD)
            self.assertEqual(
                meta["artifact_ids"],
                [canonical.artifacts[0].artifact_id],
            )
            self.assertEqual(
                meta["canonical_store"]["schema_version"],
                "1.0",
            )

            reloaded = load_persisted_submission(str(evidence), "alice")
            link = reloaded.metadata.get("canonical_submission", {})
            self.assertEqual(link.get("submission_id"), canonical.submission_id)
            self.assertEqual(link.get("assessment_id"), "PS1")
            self.assertEqual(link.get("attempt"), 1)

            manifest_path = Path(reloaded.evidence_metadata["meta_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["canonical_submission"]["submission_id"],
                canonical.submission_id,
            )

            migrated = migrate_legacy_submission(
                str(evidence),
                "PS1",
                "alice",
                repository=repository,
            )
            self.assertEqual(
                migrated.status,
                MIGRATION_STATUS_CANONICAL_ALREADY_PRESENT,
            )
            self.assertEqual(
                migrated.submission.submission_id,
                canonical.submission_id,
            )
            self.assertEqual(
                len(repository.list_submissions("PS1", "alice")),
                1,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
