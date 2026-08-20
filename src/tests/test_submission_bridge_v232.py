"""Tests for v2.3.2 Commit 4 canonical-to-v2.2 parser bridge."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.submissions import (
    CandidateFile,
    CanonicalArtifactVerificationError,
    ExplicitAccommodationRequiredError,
    SubmissionHandlerUnavailableError,
    SubmissionRecord,
    SubmissionRepository,
    parse_canonical_submission,
    parse_submission_record,
    route_submission,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_ZIP,
)
from src.submissions.routing import (
    ROUTE_LATEX_PROJECT,
    ROUTE_LATEX_SINGLE_SOURCE,
    ROUTE_PROGRAMMING_PYTHON,
)


def _blank_pdf(path):
    document = pymupdf.open()
    document.new_page(width=612, height=792)
    document.save(str(path))
    document.close()


def _candidate(path, artifact_type, role):
    path = Path(path)
    return CandidateFile(
        source_path=str(path),
        original_filename=path.name,
        artifact_type=artifact_type,
        role=role,
        size_bytes=path.stat().st_size,
        sha256=None,
    )


class TestSubmissionBridgeV232(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repository = SubmissionRepository(
            str(self.root / "submission_evidence")
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _create_submission(self, files, student_id="stable_student_42"):
        return self.repository.create_submission(
            assessment_id="PS1",
            student_id=student_id,
            files=files,
            source_system="local_upload",
            attempt=1,
        )

    def test_public_record_parser_preserves_explicit_student_identity(self):
        tex = self.root / "filename_that_is_not_student_id.tex"
        tex.write_text(
            "Question 1\nAnswer A\n",
            encoding="utf-8",
        )
        record = SubmissionRecord(
            student_id="stable_student_42",
            files={"latex": str(tex)},
        )

        parsed = parse_submission_record(
            record,
            ["Q1"],
            compile_pdf=False,
        )

        self.assertEqual(parsed.student_id, "stable_student_42")
        self.assertEqual(parsed.answers_by_question, {"Q1": "Answer A"})

    def test_canonical_tex_bridge_uses_canonical_student_not_storage_filename(self):
        tex = self.root / "some_random_upload_name.tex"
        tex.write_text(
            "Question 1\nCanonical answer\n",
            encoding="utf-8",
        )
        submission = self._create_submission([
            _candidate(tex, ARTIFACT_TYPE_TEX, ARTIFACT_ROLE_SOURCE)
        ])

        decision = route_submission(submission)
        self.assertEqual(decision.route, ROUTE_LATEX_SINGLE_SOURCE)

        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            compile_pdf=False,
        )

        self.assertEqual(parsed.student_id, "stable_student_42")
        self.assertEqual(
            parsed.answers_by_question,
            {"Q1": "Canonical answer"},
        )
        self.assertEqual(
            parsed.metadata["canonical_submission"]["submission_id"],
            submission.submission_id,
        )
        self.assertEqual(
            parsed.metadata["canonical_submission"]["assessment_id"],
            "PS1",
        )
        self.assertTrue(
            parsed.metadata["canonical_verification"]["ok"]
        )
        self.assertIn("/canonical/", parsed.files["latex"].replace("\\", "/"))

    def test_tex_plus_pdf_bridge_preserves_optional_pdf_reference(self):
        tex = self.root / "alice.tex"
        pdf = self.root / "alice.pdf"
        tex.write_text("Question 1\nA\n", encoding="utf-8")
        pdf.write_bytes(b"reference-only")

        submission = self._create_submission([
            _candidate(tex, ARTIFACT_TYPE_TEX, ARTIFACT_ROLE_SOURCE),
            _candidate(pdf, ARTIFACT_TYPE_PDF, ARTIFACT_ROLE_RENDERED),
        ])

        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            compile_pdf=False,
        )

        self.assertIn("latex", parsed.files)
        self.assertIn("pdf", parsed.files)
        self.assertTrue(Path(parsed.files["pdf"]).is_file())

    def test_pdf_only_requires_explicit_accommodation_mode(self):
        pdf = self.root / "scan.pdf"
        _blank_pdf(pdf)
        submission = self._create_submission([
            _candidate(pdf, ARTIFACT_TYPE_PDF, ARTIFACT_ROLE_PRIMARY)
        ])

        with self.assertRaises(ExplicitAccommodationRequiredError):
            parse_canonical_submission(
                submission,
                self.repository,
                ["Q1"],
                accommodation_mode=False,
            )

    def test_pdf_accommodation_bridge_uses_canonical_student_id(self):
        pdf = self.root / "anonymous_scan.pdf"
        _blank_pdf(pdf)
        submission = self._create_submission([
            _candidate(pdf, ARTIFACT_TYPE_PDF, ARTIFACT_ROLE_PRIMARY)
        ])

        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            accommodation_mode=True,
            render_dir=str(self.root / "rendered"),
            render_dpi=72,
        )

        self.assertEqual(parsed.student_id, "stable_student_42")
        self.assertTrue(parsed.accommodation_mode)
        self.assertEqual(
            parsed.metadata["canonical_submission"]["submission_id"],
            submission.submission_id,
        )

    def test_tampered_canonical_artifact_is_rejected_before_parsing(self):
        tex = self.root / "alice.tex"
        tex.write_text("Question 1\nA\n", encoding="utf-8")
        submission = self._create_submission([
            _candidate(tex, ARTIFACT_TYPE_TEX, ARTIFACT_ROLE_SOURCE)
        ])

        canonical_path = Path(
            self.repository.artifact_path(
                submission,
                submission.artifacts[0],
            )
        )
        canonical_path.write_text("tampered", encoding="utf-8")

        with self.assertRaises(CanonicalArtifactVerificationError):
            parse_canonical_submission(
                submission,
                self.repository,
                ["Q1"],
                compile_pdf=False,
            )

    def test_programming_submission_is_recognized_but_not_executed(self):
        source = self.root / "main.py"
        source.write_text(
            "raise RuntimeError('must never run in v2.3.2')\n",
            encoding="utf-8",
        )
        submission = self._create_submission([
            _candidate(source, ARTIFACT_TYPE_PYTHON, ARTIFACT_ROLE_PRIMARY)
        ])

        self.assertEqual(
            route_submission(submission).route,
            ROUTE_PROGRAMMING_PYTHON,
        )
        with self.assertRaises(SubmissionHandlerUnavailableError):
            parse_canonical_submission(
                submission,
                self.repository,
            )

    def test_pdf_plus_zip_is_recognized_by_installed_v2342_handler(self):
        pdf = self.root / "alice.pdf"
        zip_path = self.root / "alice.zip"
        pdf.write_bytes(b"rendered-reference")
        zip_path.write_bytes(b"not-read-in-v232")
        submission = self._create_submission([
            _candidate(zip_path, ARTIFACT_TYPE_ZIP, ARTIFACT_ROLE_SOURCE),
            _candidate(pdf, ARTIFACT_TYPE_PDF, ARTIFACT_ROLE_RENDERED),
        ])

        decision = route_submission(submission)
        self.assertEqual(decision.route, ROUTE_LATEX_PROJECT)
        self.assertTrue(decision.supported)
        self.assertEqual(decision.metadata["handler_available_since"], "2.3.4.2")

    def test_bridge_can_skip_hash_verification_only_when_explicitly_requested(self):
        tex = self.root / "alice.tex"
        tex.write_text("Question 1\nA\n", encoding="utf-8")
        submission = self._create_submission([
            _candidate(tex, ARTIFACT_TYPE_TEX, ARTIFACT_ROLE_SOURCE)
        ])
        canonical_path = Path(
            self.repository.artifact_path(
                submission,
                submission.artifacts[0],
            )
        )
        canonical_path.write_text("Question 1\nChanged\n", encoding="utf-8")

        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            compile_pdf=False,
            verify_artifacts=False,
        )
        self.assertEqual(parsed.answers_by_question, {"Q1": "Changed"})
        self.assertIsNone(
            parsed.metadata["canonical_verification"]["ok"]
        )

    def test_record_parser_rejects_pdf_accommodation_record(self):
        pdf = self.root / "scan.pdf"
        _blank_pdf(pdf)
        record = SubmissionRecord(
            student_id="alice",
            files={"pdf": str(pdf)},
            submission_mode="pdf_accommodation",
            accommodation_mode=True,
        )
        with self.assertRaises(ValueError):
            parse_submission_record(record, ["Q1"], compile_pdf=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
