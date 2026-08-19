"""Tests for v2.3.2 Commit 1 canonical submission-domain models."""

from dataclasses import FrozenInstanceError
import json
import unittest

from src.submissions import (
    SUBMISSION_DOMAIN_SCHEMA_VERSION,
    ArtifactFile,
    CandidateFile,
    DerivedArtifact,
    ExternalReference,
    ImportBatch,
    ImportCandidate,
    ParsedSubmission,
    Submission,
    generate_artifact_id,
    generate_candidate_id,
    generate_derived_artifact_id,
    generate_import_batch_id,
    generate_submission_id,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_LATEX_PROJECT_ZIP,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_TEX,
    IMPORT_BATCH_STATUS_COMPLETED,
    MATCH_STATUS_MATCHED,
    SOURCE_SYSTEM_CANVAS,
    SOURCE_SYSTEM_LOCAL_UPLOAD,
    SUBMISSION_STATUS_IMPORTED,
    VALIDATION_STATUS_READY,
)


_HASH_A = "a" * 64
_HASH_B = "b" * 64


class TestCanonicalSubmissionDomain(unittest.TestCase):

    def test_generated_ids_are_prefixed_and_unique(self):
        generators = (
            ("sub_", generate_submission_id),
            ("art_", generate_artifact_id),
            ("drv_", generate_derived_artifact_id),
            ("imp_", generate_import_batch_id),
            ("cand_", generate_candidate_id),
        )

        for prefix, generator in generators:
            values = {generator() for _ in range(20)}
            self.assertEqual(len(values), 20)
            self.assertTrue(
                all(value.startswith(prefix) for value in values)
            )

    def test_external_reference_roundtrip(self):
        ref = ExternalReference(
            system=SOURCE_SYSTEM_CANVAS,
            entity_type="assignment",
            external_id="3889170",
            metadata={"course_id": "410438"},
        )

        loaded = ExternalReference.from_dict(ref.to_dict())
        self.assertEqual(loaded, ref)

    def test_artifact_requires_valid_sha256(self):
        with self.assertRaises(ValueError):
            ArtifactFile(
                artifact_id="art_bad",
                submission_id="sub_1",
                role=ARTIFACT_ROLE_PRIMARY,
                artifact_type=ARTIFACT_TYPE_TEX,
                original_filename="alice.tex",
                stored_relative_path="originals/alice.tex",
                size_bytes=10,
                sha256="not-a-hash",
            )

    def test_frozen_provenance_objects_cannot_be_reassigned(self):
        artifact = ArtifactFile(
            artifact_id="art_1",
            submission_id="sub_1",
            role=ARTIFACT_ROLE_PRIMARY,
            artifact_type=ARTIFACT_TYPE_TEX,
            original_filename="alice.tex",
            stored_relative_path="originals/alice.tex",
            size_bytes=10,
            sha256=_HASH_A,
        )

        with self.assertRaises(FrozenInstanceError):
            artifact.sha256 = _HASH_B

    def test_submission_supports_multiple_artifacts_and_external_refs(self):
        submission_id = "sub_multi"

        pdf = ArtifactFile(
            artifact_id="art_pdf",
            submission_id=submission_id,
            role=ARTIFACT_ROLE_RENDERED,
            artifact_type=ARTIFACT_TYPE_PDF,
            original_filename="alice_PS1.pdf",
            stored_relative_path="originals/alice_PS1.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            sha256=_HASH_A,
        )

        source = ArtifactFile(
            artifact_id="art_zip",
            submission_id=submission_id,
            role=ARTIFACT_ROLE_SOURCE,
            artifact_type=ARTIFACT_TYPE_LATEX_PROJECT_ZIP,
            original_filename="alice_PS1.zip",
            stored_relative_path="originals/alice_PS1.zip",
            mime_type="application/zip",
            size_bytes=200,
            sha256=_HASH_B,
        )

        ref = ExternalReference(
            system=SOURCE_SYSTEM_CANVAS,
            entity_type="assignment",
            external_id="3889170",
        )

        submission = Submission(
            submission_id=submission_id,
            assessment_id="PS1",
            student_id="alice",
            source_system=SOURCE_SYSTEM_CANVAS,
            imported_at="2026-08-18T23:00:00Z",
            submitted_at="2026-08-18T21:30:00Z",
            attempt=2,
            artifacts=[pdf, source],
            external_refs=[ref],
            metadata={"section": "301"},
        )

        self.assertEqual(submission.artifact_by_id("art_zip"), source)
        self.assertEqual(
            submission.artifacts_by_type(ARTIFACT_TYPE_PDF),
            [pdf],
        )
        self.assertEqual(
            submission.artifacts_by_role(ARTIFACT_ROLE_SOURCE),
            [source],
        )

        payload = submission.to_dict()

        self.assertEqual(
            payload["schema_version"],
            SUBMISSION_DOMAIN_SCHEMA_VERSION,
        )

        json.dumps(payload)

        loaded = Submission.from_dict(payload)

        self.assertEqual(loaded.to_dict(), payload)
        self.assertEqual(loaded.attempt, 2)
        self.assertEqual(len(loaded.artifacts), 2)
        self.assertEqual(
            loaded.external_refs[0].external_id,
            "3889170",
        )

    def test_submission_rejects_artifact_owned_by_another_submission(self):
        artifact = ArtifactFile(
            artifact_id="art_1",
            submission_id="sub_other",
            role=ARTIFACT_ROLE_PRIMARY,
            artifact_type=ARTIFACT_TYPE_TEX,
            original_filename="alice.tex",
            stored_relative_path="originals/alice.tex",
            size_bytes=10,
            sha256=_HASH_A,
        )

        with self.assertRaises(ValueError):
            Submission(
                submission_id="sub_parent",
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                imported_at="2026-08-18T23:00:00Z",
                artifacts=[artifact],
            )

    def test_submission_rejects_duplicate_artifact_ids(self):
        first = ArtifactFile(
            artifact_id="art_same",
            submission_id="sub_1",
            role=ARTIFACT_ROLE_PRIMARY,
            artifact_type=ARTIFACT_TYPE_TEX,
            original_filename="alice.tex",
            stored_relative_path="originals/alice.tex",
            size_bytes=10,
            sha256=_HASH_A,
        )

        second = ArtifactFile(
            artifact_id="art_same",
            submission_id="sub_1",
            role=ARTIFACT_ROLE_SOURCE,
            artifact_type=ARTIFACT_TYPE_PDF,
            original_filename="alice.pdf",
            stored_relative_path="originals/alice.pdf",
            size_bytes=20,
            sha256=_HASH_B,
        )

        with self.assertRaises(ValueError):
            Submission(
                submission_id="sub_1",
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                imported_at="2026-08-18T23:00:00Z",
                artifacts=[first, second],
            )

    def test_submission_rejects_duplicate_external_refs(self):
        refs = [
            ExternalReference(
                system=SOURCE_SYSTEM_CANVAS,
                entity_type="assignment",
                external_id="123",
            ),
            ExternalReference(
                system=SOURCE_SYSTEM_CANVAS,
                entity_type="assignment",
                external_id="123",
            ),
        ]

        with self.assertRaises(ValueError):
            Submission(
                submission_id="sub_1",
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_CANVAS,
                imported_at="2026-08-18T23:00:00Z",
                external_refs=refs,
            )

    def test_submission_rejects_nonpositive_attempt(self):
        for attempt in (0, -1):
            with self.subTest(attempt=attempt):
                with self.assertRaises(ValueError):
                    Submission(
                        submission_id="sub_1",
                        assessment_id="PS1",
                        student_id="alice",
                        source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                        imported_at="2026-08-18T23:00:00Z",
                        attempt=attempt,
                    )

    def test_submission_rejects_boolean_attempt(self):
        with self.assertRaises(TypeError):
            Submission(
                submission_id="sub_1",
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                imported_at="2026-08-18T23:00:00Z",
                attempt=True,
            )

    def test_submission_defaults_preserve_source_agnostic_behavior(self):
        submission = Submission(
            submission_id="sub_1",
            assessment_id="PS1",
            student_id="alice",
            source_system="future_source",
            imported_at="2026-08-18T23:00:00Z",
        )

        self.assertEqual(
            submission.status,
            SUBMISSION_STATUS_IMPORTED,
        )
        self.assertTrue(submission.is_active_attempt)
        self.assertEqual(
            submission.source_system,
            "future_source",
        )

    def test_derived_artifact_roundtrip(self):
        derived = DerivedArtifact(
            derived_artifact_id="drv_1",
            source_artifact_ids=["art_1", "art_2"],
            kind="parsed_questions",
            generator="submission_parser",
            generator_version="2.3.2",
            created_at="2026-08-18T23:00:00Z",
            stored_relative_path="derived/questions.json",
            sha256=_HASH_A,
            metadata={"question_ids": ["Q1", "Q2"]},
        )

        payload = derived.to_dict()
        json.dumps(payload)

        loaded = DerivedArtifact.from_dict(payload)
        self.assertEqual(loaded.to_dict(), payload)

    def test_derived_artifact_requires_source_lineage(self):
        with self.assertRaises(ValueError):
            DerivedArtifact(
                derived_artifact_id="drv_1",
                source_artifact_ids=[],
                kind="parsed_questions",
                generator="parser",
                generator_version="1",
                created_at="2026-08-18T23:00:00Z",
            )

    def test_candidate_file_allows_hash_to_be_unknown_before_commit(self):
        candidate_file = CandidateFile(
            source_path="/tmp/alice.tex",
            original_filename="alice.tex",
            artifact_type=ARTIFACT_TYPE_TEX,
        )

        self.assertIsNone(candidate_file.sha256)
        self.assertIsNone(candidate_file.size_bytes)

    def test_import_candidate_roundtrip(self):
        candidate = ImportCandidate(
            candidate_id="cand_1",
            source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
            source_locator="/tmp/submissions",
            proposed_student_id="alice",
            proposed_assessment_id="PS1",
            proposed_attempt=1,
            files=[
                CandidateFile(
                    source_path="/tmp/submissions/alice.tex",
                    original_filename="alice.tex",
                    artifact_type=ARTIFACT_TYPE_TEX,
                    size_bytes=123,
                    sha256=_HASH_A,
                )
            ],
            match_status=MATCH_STATUS_MATCHED,
            validation_status=VALIDATION_STATUS_READY,
            warnings=["example_warning"],
            metadata={"confidence": "high"},
        )

        payload = candidate.to_dict()
        json.dumps(payload)

        loaded = ImportCandidate.from_dict(payload)

        self.assertEqual(loaded.to_dict(), payload)
        self.assertEqual(
            loaded.files[0].original_filename,
            "alice.tex",
        )

    def test_import_batch_roundtrip_and_count_validation(self):
        batch = ImportBatch(
            import_batch_id="imp_1",
            source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
            started_at="2026-08-18T23:00:00Z",
            completed_at="2026-08-18T23:01:00Z",
            candidate_count=3,
            imported_count=2,
            skipped_count=1,
            status=IMPORT_BATCH_STATUS_COMPLETED,
        )

        payload = batch.to_dict()
        json.dumps(payload)

        self.assertEqual(
            ImportBatch.from_dict(payload).to_dict(),
            payload,
        )

        with self.assertRaises(ValueError):
            ImportBatch(
                import_batch_id="imp_bad",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                started_at="2026-08-18T23:00:00Z",
                candidate_count=1,
                imported_count=1,
                skipped_count=1,
            )

    def test_schema_version_mismatch_is_rejected(self):
        submission = Submission(
            submission_id="sub_1",
            assessment_id="PS1",
            student_id="alice",
            source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
            imported_at="2026-08-18T23:00:00Z",
        )

        payload = submission.to_dict()
        payload["schema_version"] = "999"

        with self.assertRaises(ValueError):
            Submission.from_dict(payload)

    def test_to_dict_does_not_alias_mutable_metadata(self):
        submission = Submission(
            submission_id="sub_1",
            assessment_id="PS1",
            student_id="alice",
            source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
            imported_at="2026-08-18T23:00:00Z",
            metadata={
                "nested": {
                    "value": 1,
                },
            },
        )

        payload = submission.to_dict()
        payload["metadata"]["nested"]["value"] = 99

        self.assertEqual(
            submission.metadata["nested"]["value"],
            1,
        )

    def test_existing_parsed_submission_remains_public_and_unchanged(self):
        parsed = ParsedSubmission(
            student_id="alice"
        )

        self.assertEqual(
            parsed.student_id,
            "alice",
        )
        self.assertEqual(
            parsed.answers_by_question,
            {},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
