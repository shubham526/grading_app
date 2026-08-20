"""Tests for v2.3.2 Commit 4 canonical artifact routing."""

import unittest

from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_TEXT,
    ARTIFACT_TYPE_ZIP,
    ArtifactFile,
    Submission,
)
from src.submissions.routing import (
    HANDLER_LATEX_PROJECT,
    HANDLER_LEGACY_LATEX,
    HANDLER_PDF_ACCOMMODATION,
    HANDLER_PROGRAMMING,
    REASON_LATEX_PROJECT_HANDLER_PENDING,
    REASON_MULTIPLE_LATEX_SOURCES,
    REASON_NO_ARTIFACTS,
    ROUTE_LATEX_PROJECT,
    ROUTE_LATEX_SINGLE_SOURCE,
    ROUTE_MIXED,
    ROUTE_PROGRAMMING_PYTHON,
    ROUTE_UNSUPPORTED,
    ROUTE_WRITTEN_PDF,
    route_submission,
)


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _artifact(
    artifact_id,
    submission_id,
    artifact_type,
    *,
    role=ARTIFACT_ROLE_PRIMARY,
    filename="submission.dat",
    sha256=_HASH_A,
):
    return ArtifactFile(
        artifact_id=artifact_id,
        submission_id=submission_id,
        role=role,
        artifact_type=artifact_type,
        original_filename=filename,
        stored_relative_path="originals/" + filename,
        size_bytes=10,
        sha256=sha256,
    )


def _submission(artifacts):
    return Submission(
        submission_id="sub_1",
        assessment_id="PS1",
        student_id="alice",
        source_system="local_upload",
        imported_at="2026-08-19T00:00:00Z",
        attempt=1,
        artifacts=artifacts,
    )


class TestSubmissionRoutingV232(unittest.TestCase):

    def test_empty_submission_is_unsupported(self):
        decision = route_submission(_submission([]))
        self.assertEqual(decision.route, ROUTE_UNSUPPORTED)
        self.assertFalse(decision.supported)
        self.assertEqual(decision.reason, REASON_NO_ARTIFACTS)

    def test_single_tex_routes_to_existing_latex_handler(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_tex",
                    "sub_1",
                    ARTIFACT_TYPE_TEX,
                    role=ARTIFACT_ROLE_SOURCE,
                    filename="alice.tex",
                )
            ])
        )
        self.assertEqual(decision.route, ROUTE_LATEX_SINGLE_SOURCE)
        self.assertEqual(decision.handler, HANDLER_LEGACY_LATEX)
        self.assertTrue(decision.supported)
        self.assertEqual(decision.artifact_ids, ("art_tex",))

    def test_tex_plus_pdf_remains_existing_latex_route(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_tex",
                    "sub_1",
                    ARTIFACT_TYPE_TEX,
                    role=ARTIFACT_ROLE_SOURCE,
                    filename="alice.tex",
                    sha256=_HASH_A,
                ),
                _artifact(
                    "art_pdf",
                    "sub_1",
                    ARTIFACT_TYPE_PDF,
                    role=ARTIFACT_ROLE_RENDERED,
                    filename="alice.pdf",
                    sha256=_HASH_B,
                ),
            ])
        )
        self.assertEqual(decision.route, ROUTE_LATEX_SINGLE_SOURCE)
        self.assertEqual(decision.handler, HANDLER_LEGACY_LATEX)
        self.assertTrue(decision.supported)
        self.assertEqual(
            set(decision.artifact_ids),
            {"art_tex", "art_pdf"},
        )

    def test_pdf_only_routes_to_explicit_accommodation_handler(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_pdf",
                    "sub_1",
                    ARTIFACT_TYPE_PDF,
                    filename="scan.pdf",
                )
            ])
        )
        self.assertEqual(decision.route, ROUTE_WRITTEN_PDF)
        self.assertEqual(decision.handler, HANDLER_PDF_ACCOMMODATION)
        self.assertTrue(decision.supported)
        self.assertTrue(decision.requires_explicit_accommodation)

    def test_python_route_is_supported_by_v233_planner(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_py1",
                    "sub_1",
                    ARTIFACT_TYPE_PYTHON,
                    filename="main.py",
                    sha256=_HASH_A,
                ),
                _artifact(
                    "art_py2",
                    "sub_1",
                    ARTIFACT_TYPE_PYTHON,
                    filename="helpers.py",
                    sha256=_HASH_B,
                ),
            ])
        )
        self.assertEqual(decision.route, ROUTE_PROGRAMMING_PYTHON)
        self.assertEqual(decision.handler, HANDLER_PROGRAMMING)
        self.assertTrue(decision.supported)
        self.assertIsNone(decision.reason)
        self.assertEqual(decision.metadata["handler_available_since"], "2.3.3")
        self.assertEqual(len(decision.artifact_ids), 2)

    def test_pdf_plus_zip_routes_to_future_latex_project_handler(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_zip",
                    "sub_1",
                    ARTIFACT_TYPE_ZIP,
                    role=ARTIFACT_ROLE_SOURCE,
                    filename="alice.zip",
                    sha256=_HASH_A,
                ),
                _artifact(
                    "art_pdf",
                    "sub_1",
                    ARTIFACT_TYPE_PDF,
                    role=ARTIFACT_ROLE_RENDERED,
                    filename="alice.pdf",
                    sha256=_HASH_B,
                ),
            ])
        )
        self.assertEqual(decision.route, ROUTE_LATEX_PROJECT)
        self.assertEqual(decision.handler, HANDLER_LATEX_PROJECT)
        self.assertFalse(decision.supported)
        self.assertEqual(
            decision.reason,
            REASON_LATEX_PROJECT_HANDLER_PENDING,
        )

    def test_multiple_tex_sources_are_not_silently_selected(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_1",
                    "sub_1",
                    ARTIFACT_TYPE_TEX,
                    filename="main.tex",
                    sha256=_HASH_A,
                ),
                _artifact(
                    "art_2",
                    "sub_1",
                    ARTIFACT_TYPE_TEX,
                    filename="answers.tex",
                    sha256=_HASH_B,
                ),
            ])
        )
        self.assertEqual(decision.route, ROUTE_MIXED)
        self.assertFalse(decision.supported)
        self.assertEqual(decision.reason, REASON_MULTIPLE_LATEX_SOURCES)

    def test_tex_plus_python_is_mixed_not_guessed(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_tex",
                    "sub_1",
                    ARTIFACT_TYPE_TEX,
                    filename="main.tex",
                    sha256=_HASH_A,
                ),
                _artifact(
                    "art_py",
                    "sub_1",
                    ARTIFACT_TYPE_PYTHON,
                    filename="main.py",
                    sha256=_HASH_B,
                ),
            ])
        )
        self.assertEqual(decision.route, ROUTE_MIXED)
        self.assertFalse(decision.supported)

    def test_unknown_single_type_is_unsupported(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_txt",
                    "sub_1",
                    ARTIFACT_TYPE_TEXT,
                    filename="answer.txt",
                    sha256=_HASH_C,
                )
            ])
        )
        self.assertEqual(decision.route, ROUTE_UNSUPPORTED)
        self.assertFalse(decision.supported)

    def test_route_decision_is_json_friendly(self):
        decision = route_submission(
            _submission([
                _artifact(
                    "art_tex",
                    "sub_1",
                    ARTIFACT_TYPE_TEX,
                    filename="alice.tex",
                )
            ])
        )
        payload = decision.to_dict()
        self.assertEqual(payload["artifact_ids"], ["art_tex"])
        self.assertEqual(payload["route"], ROUTE_LATEX_SINGLE_SOURCE)

    def test_requires_submission_model(self):
        with self.assertRaises(TypeError):
            route_submission(object())


if __name__ == "__main__":
    unittest.main(verbosity=2)
