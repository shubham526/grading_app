"""v2.3.4.2 Commit 1 tests for dependency-free LaTeX-project domain models."""

from dataclasses import FrozenInstanceError
import json
import unittest

from src.submissions.latex_project import (
    ARCHIVE_VALIDATION_REJECTED,
    ARCHIVE_VALIDATION_VALID,
    DIAGNOSTIC_BLOCKING,
    FILE_ROLE_ROOT,
    FILE_ROLE_TEX_SOURCE,
    LATEX_PROJECT_DOMAIN_SCHEMA_VERSION,
    ROOT_METHOD_INSTRUCTOR_SELECTED,
    ROOT_METHOD_UNIQUE_DOCUMENT,
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_PENDING,
    ROOT_RESOLUTION_RESOLVED,
    LatexProjectArchive,
    LatexProjectDiagnostic,
    LatexProjectFile,
    LatexProjectImportCandidate,
    LatexProjectManifest,
    LatexProjectResolution,
    LatexProjectSerializationError,
    LatexProjectValidationError,
    UnsupportedLatexProjectSchemaError,
    generate_latex_project_candidate_id,
    generate_latex_project_id,
    normalize_project_relative_path,
)


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class TestLatexProjectDomainModelsV2342(unittest.TestCase):

    def test_generated_ids_are_prefixed_unique_and_opaque(self):
        for prefix, generator in (
            ("lproj_", generate_latex_project_id),
            ("lpcand_", generate_latex_project_candidate_id),
        ):
            values = {generator() for _ in range(25)}
            self.assertEqual(len(values), 25)
            self.assertTrue(all(value.startswith(prefix) for value in values))

    def test_project_paths_are_portable_and_normalized(self):
        self.assertEqual(
            normalize_project_relative_path("answers\\q1.tex"),
            "answers/q1.tex",
        )
        self.assertEqual(
            normalize_project_relative_path("./answers/q1.tex"),
            "answers/q1.tex",
        )

    def test_unsafe_project_paths_are_rejected(self):
        for value in (
            "../q1.tex",
            "/tmp/q1.tex",
            "C:\\tmp\\q1.tex",
            "answers/../../q1.tex",
            "\x00bad.tex",
        ):
            with self.subTest(value=value):
                with self.assertRaises(LatexProjectValidationError):
                    normalize_project_relative_path(value)

    def test_file_roundtrip_and_frozen_contract(self):
        item = LatexProjectFile(
            relative_path="answers\\q1.tex",
            size_bytes=42,
            sha256=_HASH_A,
            role=FILE_ROLE_TEX_SOURCE,
            media_type="text/x-tex",
            metadata={"source": "synthetic"},
        )
        self.assertEqual(item.relative_path, "answers/q1.tex")
        loaded = LatexProjectFile.from_dict(item.to_dict())
        self.assertEqual(loaded, item)
        with self.assertRaises(FrozenInstanceError):
            item.size_bytes = 0

    def test_file_rejects_bad_hash_size_or_role(self):
        with self.assertRaises(LatexProjectValidationError):
            LatexProjectFile("main.tex", -1, _HASH_A)
        with self.assertRaises(LatexProjectValidationError):
            LatexProjectFile("main.tex", 1, "not-a-hash")
        with self.assertRaises(LatexProjectValidationError):
            LatexProjectFile("main.tex", 1, _HASH_A, role="executable")

    def test_manifest_requires_exact_total_and_unique_paths(self):
        files = (
            LatexProjectFile("main.tex", 10, _HASH_A, role=FILE_ROLE_ROOT),
            LatexProjectFile("answers/q1.tex", 20, _HASH_B, role=FILE_ROLE_TEX_SOURCE),
        )
        manifest = LatexProjectManifest(
            project_id="lproj_1",
            files=files,
            total_uncompressed_bytes=30,
            manifest_sha256=_HASH_C,
        )
        self.assertEqual(manifest.file_count, 2)
        self.assertEqual(manifest.file_by_path("answers\\q1.tex"), files[1])
        self.assertIsNone(manifest.file_by_path("missing.tex"))
        self.assertEqual(LatexProjectManifest.from_dict(manifest.to_dict()), manifest)

        with self.assertRaises(LatexProjectValidationError):
            LatexProjectManifest("lproj_1", files, 31)
        with self.assertRaises(LatexProjectValidationError):
            LatexProjectManifest(
                "lproj_1",
                (files[0], LatexProjectFile("main.tex", 10, _HASH_B)),
                20,
            )

    def test_manifest_declared_file_count_is_verified_on_load(self):
        payload = {
            "schema_version": "1.0",
            "project_id": "lproj_1",
            "files": [],
            "file_count": 2,
            "total_uncompressed_bytes": 0,
        }
        with self.assertRaises(LatexProjectSerializationError):
            LatexProjectManifest.from_dict(payload)

    def test_diagnostic_roundtrip_and_blocking_archive_summary(self):
        diagnostic = LatexProjectDiagnostic(
            code="UNSAFE_MEMBER",
            message="Archive member attempts path traversal.",
            severity=DIAGNOSTIC_BLOCKING,
            relative_path="answers/q1.tex",
        )
        archive = LatexProjectArchive(
            project_id="lproj_1",
            source_artifact_id="art_zip",
            original_filename="alice.zip",
            archive_sha256=_HASH_A,
            archive_size_bytes=123,
            validation_status=ARCHIVE_VALIDATION_REJECTED,
            diagnostics=(diagnostic,),
        )
        self.assertTrue(archive.has_blocking_diagnostics)
        self.assertEqual(LatexProjectArchive.from_dict(archive.to_dict()), archive)

    def test_valid_archive_can_have_no_blocking_diagnostics(self):
        archive = LatexProjectArchive(
            project_id="lproj_1",
            source_artifact_id="art_zip",
            original_filename="alice.zip",
            archive_sha256=_HASH_A,
            archive_size_bytes=123,
            validation_status=ARCHIVE_VALIDATION_VALID,
        )
        self.assertFalse(archive.has_blocking_diagnostics)

    def test_resolved_root_requires_path_and_method(self):
        resolved = LatexProjectResolution(
            status=ROOT_RESOLUTION_RESOLVED,
            root_relative_path="report.tex",
            candidate_paths=("report.tex",),
            resolution_method=ROOT_METHOD_UNIQUE_DOCUMENT,
        )
        self.assertFalse(resolved.requires_instructor_selection)
        self.assertEqual(LatexProjectResolution.from_dict(resolved.to_dict()), resolved)

        with self.assertRaises(LatexProjectValidationError):
            LatexProjectResolution(status=ROOT_RESOLUTION_RESOLVED)

    def test_ambiguous_root_requires_multiple_candidates_and_no_selected_root(self):
        value = LatexProjectResolution(
            status=ROOT_RESOLUTION_AMBIGUOUS,
            candidate_paths=("main.tex", "report.tex"),
        )
        self.assertTrue(value.requires_instructor_selection)

        with self.assertRaises(LatexProjectValidationError):
            LatexProjectResolution(
                status=ROOT_RESOLUTION_AMBIGUOUS,
                candidate_paths=("main.tex",),
            )
        with self.assertRaises(LatexProjectValidationError):
            LatexProjectResolution(
                status=ROOT_RESOLUTION_AMBIGUOUS,
                root_relative_path="main.tex",
                candidate_paths=("main.tex", "report.tex"),
            )

    def test_instructor_selected_root_is_explicit_provenance(self):
        resolution = LatexProjectResolution(
            status=ROOT_RESOLUTION_RESOLVED,
            root_relative_path="report.tex",
            candidate_paths=("main.tex", "report.tex"),
            resolution_method=ROOT_METHOD_INSTRUCTOR_SELECTED,
        )
        self.assertEqual(
            resolution.resolution_method,
            ROOT_METHOD_INSTRUCTOR_SELECTED,
        )

    def test_candidate_supports_precommit_and_committed_identity_states(self):
        pending = LatexProjectImportCandidate(
            candidate_id="lpcand_1",
            assessment_id="PS1",
            archive_filename="alice.zip",
            archive_size_bytes=200,
            student_id="alice",
        )
        self.assertTrue(pending.mapped)
        self.assertFalse(pending.committed_identity_available)
        self.assertEqual(pending.resolution.status, ROOT_RESOLUTION_PENDING)

        committed = LatexProjectImportCandidate(
            candidate_id="lpcand_2",
            assessment_id="PS1",
            archive_filename="alice.zip",
            archive_size_bytes=200,
            student_id="alice",
            submission_id="sub_1",
            attempt=2,
            source_artifact_id="art_zip",
            rendered_artifact_id="art_pdf",
            archive_sha256=_HASH_A,
            project_id="lproj_1",
            validation_status=ARCHIVE_VALIDATION_VALID,
            resolution=LatexProjectResolution(
                status=ROOT_RESOLUTION_RESOLVED,
                root_relative_path="main.tex",
                candidate_paths=("main.tex",),
                resolution_method=ROOT_METHOD_UNIQUE_DOCUMENT,
            ),
        )
        self.assertTrue(committed.committed_identity_available)
        self.assertEqual(committed.rendered_artifact_id, "art_pdf")
        self.assertEqual(
            LatexProjectImportCandidate.from_dict(committed.to_dict()),
            committed,
        )

    def test_candidate_rejects_boolean_or_nonpositive_attempt(self):
        for attempt in (True, 0, -1):
            with self.subTest(attempt=attempt):
                with self.assertRaises(LatexProjectValidationError):
                    LatexProjectImportCandidate(
                        candidate_id="lpcand_1",
                        assessment_id="PS1",
                        archive_filename="alice.zip",
                        archive_size_bytes=1,
                        attempt=attempt,
                    )

    def test_serialized_domain_payloads_are_json_serializable(self):
        candidate = LatexProjectImportCandidate(
            candidate_id="lpcand_1",
            assessment_id="PS1",
            archive_filename="alice.zip",
            archive_size_bytes=200,
            metadata={"nested": {"value": 1}},
        )
        payload = candidate.to_dict()
        self.assertEqual(
            payload["schema_version"],
            LATEX_PROJECT_DOMAIN_SCHEMA_VERSION,
        )
        json.dumps(payload)

    def test_schema_version_1_integer_is_accepted_and_normalized(self):
        candidate = LatexProjectImportCandidate.from_dict(
            {
                "schema_version": 1,
                "candidate_id": "lpcand_1",
                "assessment_id": "PS1",
                "archive_filename": "alice.zip",
                "archive_size_bytes": 1,
            }
        )
        self.assertEqual(candidate.to_dict()["schema_version"], "1.0")

    def test_unsupported_domain_schema_is_rejected(self):
        with self.assertRaises(UnsupportedLatexProjectSchemaError):
            LatexProjectImportCandidate.from_dict(
                {
                    "schema_version": "2.0",
                    "candidate_id": "lpcand_1",
                    "assessment_id": "PS1",
                    "archive_filename": "alice.zip",
                    "archive_size_bytes": 1,
                }
            )


if __name__ == "__main__":
    unittest.main()
