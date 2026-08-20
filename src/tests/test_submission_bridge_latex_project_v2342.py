from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile

from src.submissions.bridge import (
    CanonicalArtifactVerificationError,
    CanonicalSubmissionBridgeError,
    parse_canonical_submission,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_ZIP,
    CandidateFile,
)
from src.submissions.models import ParsedSubmission, SOURCE_LATEX, SUBMISSION_MODE_LATEX
from src.submissions.repository import SubmissionRepository
from src.submissions.routing import HANDLER_LATEX_PROJECT, ROUTE_LATEX_PROJECT, route_submission
from src.submissions.latex_project import LatexProjectIngestionConfig


class TestCanonicalLatexProjectBridgeV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repository = SubmissionRepository(str(self.root / "evidence"))

    def tearDown(self):
        self.tmp.cleanup()

    def _submission(self):
        archive = self.root / "alice.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(
                "main.tex",
                r"\documentclass{article}\begin{document}Question 1 A\end{document}",
            )
        return self.repository.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[CandidateFile(
                source_path=str(archive),
                original_filename=archive.name,
                artifact_type=ARTIFACT_TYPE_ZIP,
                role=ARTIFACT_ROLE_SOURCE,
            )],
        )

    def test_router_marks_latex_project_handler_available(self):
        submission = self._submission()
        decision = route_submission(submission)
        self.assertEqual(decision.route, ROUTE_LATEX_PROJECT)
        self.assertEqual(decision.handler, HANDLER_LATEX_PROJECT)
        self.assertTrue(decision.supported)
        self.assertIsNone(decision.reason)
        self.assertEqual(decision.metadata["handler_available_since"], "2.3.4.2")

    def test_canonical_bridge_delegates_project_without_changing_written_mode(self):
        submission = self._submission()
        returned = ParsedSubmission(
            student_id="alice",
            source_used=SOURCE_LATEX,
            submission_mode=SUBMISSION_MODE_LATEX,
            files={"compiled_pdf": "/tmp/main.pdf"},
        )
        with mock.patch(
            "src.submissions.bridge.parse_canonical_latex_project",
            return_value=returned,
        ) as parser:
            parsed = parse_canonical_submission(
                submission,
                self.repository,
                ["Q1"],
                latex_project_root="main.tex",
                latex_project_config=LatexProjectIngestionConfig(),
            )
        self.assertIs(parsed, returned)
        self.assertEqual(parsed.submission_mode, SUBMISSION_MODE_LATEX)
        self.assertFalse(parsed.accommodation_mode)
        parser.assert_called_once()
        kwargs = parser.call_args.kwargs
        self.assertEqual(kwargs["root_relative_path"], "main.tex")
        self.assertIsInstance(kwargs["config"], LatexProjectIngestionConfig)
        self.assertEqual(
            parsed.metadata["canonical_submission"]["route"],
            ROUTE_LATEX_PROJECT,
        )

    def test_project_bridge_requires_visual_compilation(self):
        submission = self._submission()
        with self.assertRaises(CanonicalSubmissionBridgeError):
            parse_canonical_submission(
                submission,
                self.repository,
                compile_pdf=False,
            )

    def test_canonical_zip_is_verified_before_project_handler(self):
        submission = self._submission()
        path = Path(self.repository.artifact_path(submission, submission.artifacts[0]))
        path.write_bytes(b"tampered")
        with mock.patch("src.submissions.bridge.parse_canonical_latex_project") as parser:
            with self.assertRaises(CanonicalArtifactVerificationError):
                parse_canonical_submission(submission, self.repository)
        parser.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
