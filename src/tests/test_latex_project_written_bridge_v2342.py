from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile

from src.submissions.domain import (
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_ZIP,
    CandidateFile,
)
from src.submissions.models import CompilationResult, SOURCE_LATEX, SUBMISSION_MODE_LATEX
from src.submissions.repository import SubmissionRepository
from src.submissions.latex_project.compilation import LatexProjectCompilation
from src.submissions.latex_project.written_bridge import (
    LatexProjectCompilationFailedError,
    LatexProjectRootResolutionRequiredError,
    parse_canonical_latex_project,
    prepare_canonical_latex_project,
)


class TestLatexProjectWrittenBridgeV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repository = SubmissionRepository(str(self.root / "evidence"))

    def tearDown(self):
        self.tmp.cleanup()

    def _zip(self, name="alice.zip", files=None):
        path = self.root / name
        payload = files or {
            "main.tex": (
                r"\documentclass{article}" "\n"
                r"\begin{document}" "\n"
                r"\input{answers/q1}" "\n"
                r"\end{document}" "\n"
            ),
            "answers/q1.tex": "Question 1\nRendered answer\n",
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, text in payload.items():
                archive.writestr(relative, text)
        return path

    def _submission(self, *, files=None, with_pdf=False):
        zip_path = self._zip(files=files)
        candidates = [
            CandidateFile(
                source_path=str(zip_path),
                original_filename=zip_path.name,
                artifact_type=ARTIFACT_TYPE_ZIP,
                role=ARTIFACT_ROLE_SOURCE,
            )
        ]
        if with_pdf:
            pdf = self.root / "alice.pdf"
            pdf.write_bytes(b"%PDF-1.4\nsubmitted-reference")
            candidates.append(
                CandidateFile(
                    source_path=str(pdf),
                    original_filename=pdf.name,
                    artifact_type=ARTIFACT_TYPE_PDF,
                    role=ARTIFACT_ROLE_RENDERED,
                )
            )
        return self.repository.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=candidates,
        )

    @staticmethod
    def _fake_compile(stored, resolution, *, output_dir=None, **kwargs):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        pdf = output / "main.pdf"
        pdf.write_bytes(b"%PDF-1.4\nmock")
        result = CompilationResult(
            success=True,
            source_path=str(Path(stored.extracted_root) / resolution.root_relative_path),
            engine="pdflatex",
            pdf_path=str(pdf),
            passes_completed=1,
        )
        return LatexProjectCompilation(
            project_id=stored.project_id,
            root_relative_path=resolution.root_relative_path,
            resolution_method=resolution.resolution_method,
            archive_sha256=stored.archive.archive_sha256,
            manifest_sha256=stored.manifest.manifest_sha256,
            source_file_count=len(stored.manifest.files),
            source_total_bytes=stored.manifest.total_uncompressed_bytes,
            compilation=result,
        )

    def test_prepare_ingests_under_canonical_derived_tree_and_resolves_root(self):
        submission = self._submission()
        zip_artifact = submission.artifacts[0]
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._fake_compile,
        ):
            context = prepare_canonical_latex_project(
                submission,
                self.repository,
                zip_artifact,
            )

        submission_dir = Path(self.repository.submission_directory(submission))
        project_dir = Path(context.stored.project_dir)
        self.assertTrue(project_dir.is_relative_to(submission_dir / "derived" / "latex_project"))
        self.assertEqual(context.resolution.root_relative_path, "main.tex")
        self.assertTrue(context.compilation.success)
        self.assertTrue(Path(context.compilation.pdf_path).is_file())

    def test_prepare_reuses_same_verified_project_store(self):
        submission = self._submission()
        zip_artifact = submission.artifacts[0]
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._fake_compile,
        ):
            first = prepare_canonical_latex_project(submission, self.repository, zip_artifact)
            second = prepare_canonical_latex_project(submission, self.repository, zip_artifact)
        self.assertEqual(first.stored.project_id, second.stored.project_id)
        self.assertEqual(first.stored.project_dir, second.stored.project_dir)

    def test_ambiguous_root_requires_explicit_selection(self):
        submission = self._submission(files={
            "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
            "report.tex": r"\documentclass{article}\begin{document}B\end{document}",
        })
        zip_artifact = submission.artifacts[0]
        with self.assertRaises(LatexProjectRootResolutionRequiredError) as raised:
            prepare_canonical_latex_project(submission, self.repository, zip_artifact)
        self.assertEqual(set(raised.exception.resolution.candidate_paths), {"main.tex", "report.tex"})

    def test_explicit_selection_resolves_ambiguous_project(self):
        submission = self._submission(files={
            "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
            "report.tex": r"\documentclass{article}\begin{document}B\end{document}",
        })
        zip_artifact = submission.artifacts[0]
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._fake_compile,
        ):
            context = prepare_canonical_latex_project(
                submission,
                self.repository,
                zip_artifact,
                root_relative_path="report.tex",
            )
        self.assertEqual(context.resolution.root_relative_path, "report.tex")
        self.assertEqual(context.resolution.resolution_method, "instructor_selected")

    def test_compile_failure_is_structured_bridge_failure(self):
        submission = self._submission()
        zip_artifact = submission.artifacts[0]

        def fail(stored, resolution, *, output_dir=None, **kwargs):
            result = CompilationResult(
                success=False,
                source_path=str(Path(stored.extracted_root) / resolution.root_relative_path),
                engine="pdflatex",
                error_code="latex_compilation_failed",
                error_message="Undefined control sequence",
            )
            return LatexProjectCompilation(
                project_id=stored.project_id,
                root_relative_path=resolution.root_relative_path,
                resolution_method=resolution.resolution_method,
                archive_sha256=stored.archive.archive_sha256,
                manifest_sha256=stored.manifest.manifest_sha256,
                source_file_count=len(stored.manifest.files),
                source_total_bytes=stored.manifest.total_uncompressed_bytes,
                compilation=result,
            )

        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=fail,
        ):
            with self.assertRaises(LatexProjectCompilationFailedError) as raised:
                prepare_canonical_latex_project(submission, self.repository, zip_artifact)
        self.assertEqual(
            raised.exception.result.compilation.error_code,
            "latex_compilation_failed",
        )

    def test_parse_exposes_compiled_pdf_through_existing_written_contract(self):
        submission = self._submission()
        zip_artifact = submission.artifacts[0]
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._fake_compile,
        ), mock.patch(
            "src.submissions.latex_project.written_bridge.extract_text_from_pdf",
            return_value=(
                "Question 1\nThe rendered answer",
                {
                    "source": "pdf",
                    "selectable_text": True,
                    "warnings": [],
                    "page_count": 1,
                },
            ),
        ):
            parsed = parse_canonical_latex_project(
                submission,
                self.repository,
                zip_artifact,
                ["Q1"],
            )

        self.assertEqual(parsed.student_id, "alice")
        self.assertEqual(parsed.submission_mode, SUBMISSION_MODE_LATEX)
        self.assertEqual(parsed.source_used, SOURCE_LATEX)
        self.assertFalse(parsed.accommodation_mode)
        self.assertTrue(Path(parsed.files["compiled_pdf"]).is_file())
        self.assertTrue(Path(parsed.files["latex"]).name == "main.tex")
        self.assertTrue(Path(parsed.files["latex_project_zip"]).is_file())
        self.assertEqual(parsed.metadata["canonical_source"], "latex_project")
        self.assertEqual(parsed.metadata["authoritative_source"], "latex_project_zip")
        self.assertIn("Q1", parsed.answers_by_question)
        self.assertIn("rendered answer", parsed.answers_by_question["Q1"].lower())

    def test_paired_student_pdf_is_retained_but_compiled_pdf_remains_primary_visual(self):
        submission = self._submission(with_pdf=True)
        zip_artifact = next(a for a in submission.artifacts if a.artifact_type == ARTIFACT_TYPE_ZIP)
        pdf_artifact = next(a for a in submission.artifacts if a.artifact_type == ARTIFACT_TYPE_PDF)
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._fake_compile,
        ), mock.patch(
            "src.submissions.latex_project.written_bridge.extract_text_from_pdf",
            return_value=("Question 1\nA", {"warnings": [], "selectable_text": True}),
        ):
            parsed = parse_canonical_latex_project(
                submission,
                self.repository,
                zip_artifact,
                ["Q1"],
                reference_pdf_artifact=pdf_artifact,
            )
        self.assertIn("compiled_pdf", parsed.files)
        self.assertIn("pdf", parsed.files)
        self.assertNotEqual(parsed.files["compiled_pdf"], parsed.files["pdf"])

    def test_unknown_compiler_option_is_rejected(self):
        submission = self._submission()
        with self.assertRaises(ValueError):
            prepare_canonical_latex_project(
                submission,
                self.repository,
                submission.artifacts[0],
                compiler_options={"shell_escape": True},
            )

    def test_evidence_persistence_copies_root_and_compiled_pdf_not_project_zip(self):
        submission = self._submission()
        zip_artifact = submission.artifacts[0]
        evidence = self.root / "parsed_evidence"
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._fake_compile,
        ), mock.patch(
            "src.submissions.latex_project.written_bridge.extract_text_from_pdf",
            return_value=("Question 1\nA", {"warnings": [], "selectable_text": True}),
        ):
            parsed = parse_canonical_latex_project(
                submission,
                self.repository,
                zip_artifact,
                ["Q1"],
                evidence_dir=str(evidence),
            )
        self.assertTrue(Path(parsed.files["latex"]).is_file())
        self.assertTrue(Path(parsed.files["compiled_pdf"]).is_file())
        self.assertTrue(Path(parsed.files["latex_project_zip"]).is_file())
        self.assertIn("evidence", parsed.metadata)


if __name__ == "__main__":
    unittest.main(verbosity=2)
