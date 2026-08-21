"""Regression boundaries that LaTeX-project ZIP support must not change."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import pymupdf

from src.submissions import (
    CandidateFile,
    ExplicitAccommodationRequiredError,
    SubmissionRepository,
    parse_canonical_submission,
    route_submission,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
)
from src.submissions.routing import (
    ROUTE_LATEX_SINGLE_SOURCE,
    ROUTE_PROGRAMMING_PYTHON,
    ROUTE_WRITTEN_PDF,
)


class TestLatexProjectRegressionBoundariesV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repository = SubmissionRepository(str(self.root / "evidence"))

    def tearDown(self):
        self.tmp.cleanup()

    def _submission(self, path, artifact_type, role=ARTIFACT_ROLE_PRIMARY):
        path = Path(path)
        return self.repository.create_submission(
            assessment_id="PS_BOUNDARY",
            student_id="alice",
            files=[CandidateFile(
                source_path=str(path),
                original_filename=path.name,
                artifact_type=artifact_type,
                role=role,
            )],
            attempt=1,
            imported_at="2026-08-21T03:40:00Z",
        )

    def test_legacy_single_tex_route_and_text_parsing_are_unchanged(self):
        source = self.root / "alice.tex"
        source.write_text("Question 1\nLegacy answer\n", encoding="utf-8")
        submission = self._submission(source, ARTIFACT_TYPE_TEX, ARTIFACT_ROLE_SOURCE)
        self.assertEqual(route_submission(submission).route, ROUTE_LATEX_SINGLE_SOURCE)
        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            compile_pdf=False,
        )
        self.assertEqual(parsed.answers_by_question, {"Q1": "Legacy answer"})
        self.assertIn("latex", parsed.files)
        self.assertNotIn("latex_project_zip", parsed.files)

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_legacy_single_tex_still_compiles_to_normal_compiled_pdf(self):
        source = self.root / "legacy.tex"
        source.write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Question 1\nLegacy compiled answer\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        submission = self._submission(source, ARTIFACT_TYPE_TEX, ARTIFACT_ROLE_SOURCE)
        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            compile_pdf=True,
            evidence_dir=str(self.root / "parsed"),
        )
        self.assertTrue(Path(parsed.files["compiled_pdf"]).is_file())
        self.assertNotIn("latex_project_zip", parsed.files)

    def test_pdf_accommodation_remains_explicit(self):
        pdf_path = self.root / "scan.pdf"
        document = pymupdf.open()
        document.new_page(width=612, height=792)
        document.save(str(pdf_path))
        document.close()
        submission = self._submission(pdf_path, ARTIFACT_TYPE_PDF)
        self.assertEqual(route_submission(submission).route, ROUTE_WRITTEN_PDF)
        with self.assertRaises(ExplicitAccommodationRequiredError):
            parse_canonical_submission(
                submission,
                self.repository,
                ["Q1"],
                accommodation_mode=False,
            )
        parsed = parse_canonical_submission(
            submission,
            self.repository,
            ["Q1"],
            accommodation_mode=True,
            render_dir=str(self.root / "rendered"),
            render_dpi=72,
        )
        self.assertTrue(parsed.accommodation_mode)
        self.assertIn("pdf", parsed.files)

    def test_python_submission_still_routes_only_to_programming_handler(self):
        sentinel = self.root / "EXECUTED.txt"
        source = self.root / "main.py"
        source.write_text(
            "from pathlib import Path\n"
            "Path(%r).write_text('executed')\n" % str(sentinel),
            encoding="utf-8",
        )
        submission = self._submission(source, ARTIFACT_TYPE_PYTHON)
        decision = route_submission(submission)
        self.assertEqual(decision.route, ROUTE_PROGRAMMING_PYTHON)
        self.assertEqual(decision.handler, "programming_autograder")
        self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
