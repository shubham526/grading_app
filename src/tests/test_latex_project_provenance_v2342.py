from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile

from src.submissions.domain import ARTIFACT_ROLE_SOURCE, ARTIFACT_TYPE_ZIP, CandidateFile
from src.submissions.models import CompilationResult
from src.submissions.repository import SubmissionRepository
from src.submissions.latex_project.compilation import LatexProjectCompilation
from src.submissions.latex_project.errors import (
    LatexProjectIntegrityError,
    LatexProjectSerializationError,
)
from src.submissions.latex_project.provenance import (
    LATEX_PROJECT_PROVENANCE_FILENAME,
    PROJECT_STATUS_COMPILED,
    PROJECT_STATUS_COMPILATION_FAILED,
    load_latex_project_provenance,
)
from src.submissions.latex_project.written_bridge import (
    LatexProjectCompilationFailedError,
    canonical_latex_project_diagnostic,
    prepare_canonical_latex_project,
)


class TestLatexProjectProvenanceV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repository = SubmissionRepository(str(self.root / "evidence"))

    def tearDown(self):
        self.tmp.cleanup()

    def _submission(self, files=None):
        archive_path = self.root / "alice.zip"
        payload = files or {
            "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
        }
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, text in payload.items():
                archive.writestr(relative, text)
        return self.repository.create_submission(
            assessment_id="PS1",
            student_id="alice",
            files=[CandidateFile(
                source_path=str(archive_path),
                original_filename=archive_path.name,
                artifact_type=ARTIFACT_TYPE_ZIP,
                role=ARTIFACT_ROLE_SOURCE,
            )],
        )

    @staticmethod
    def _compile_success(stored, resolution, *, output_dir=None, **kwargs):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        pdf = output / (Path(resolution.root_relative_path).stem + ".pdf")
        pdf.write_bytes(b"%PDF-1.4\nprovenance-success")
        result = CompilationResult(
            success=True,
            source_path=str(Path(stored.extracted_root) / resolution.root_relative_path),
            engine=kwargs.get("engine", "pdflatex"),
            pdf_path=str(pdf),
            return_code=0,
            passes_completed=1,
            duration_seconds=0.25,
            stdout="compile ok",
            warnings=["fixture-warning"],
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

    @staticmethod
    def _compile_failure(stored, resolution, *, output_dir=None, **kwargs):
        result = CompilationResult(
            success=False,
            source_path=str(Path(stored.extracted_root) / resolution.root_relative_path),
            engine=kwargs.get("engine", "pdflatex"),
            return_code=1,
            duration_seconds=0.1,
            stdout="main.tex:47: Undefined control sequence",
            stderr="fixture stderr",
            error_code="latex_compilation_failed",
            error_message="Undefined control sequence at main.tex:47",
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

    def test_success_persists_hash_root_compiler_and_log(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ):
            context = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )

        state = load_latex_project_provenance(context.stored)
        self.assertIsNotNone(state)
        self.assertEqual(state.status, PROJECT_STATUS_COMPILED)
        self.assertEqual(state.root_relative_path, "main.tex")
        self.assertEqual(state.root_resolution_method, "unique_document")
        self.assertEqual(len(state.compilation_attempts), 1)
        latest = state.latest_attempt
        self.assertTrue(latest.success)
        self.assertEqual(latest.engine, "pdflatex")
        self.assertEqual(len(latest.compiled_pdf_sha256), 64)
        self.assertTrue(
            (Path(context.stored.project_dir) / latest.compilation_log_relative_path).is_file()
        )
        self.assertTrue((Path(context.stored.project_dir) / LATEX_PROJECT_PROVENANCE_FILENAME).is_file())
        payload = json.loads(
            (Path(context.stored.project_dir) / LATEX_PROJECT_PROVENANCE_FILENAME).read_text()
        )
        self.assertEqual(payload["archive_sha256"], context.stored.archive.archive_sha256)
        self.assertEqual(payload["manifest_sha256"], context.stored.manifest.manifest_sha256)

    def test_failure_is_persisted_as_structured_attempt(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_failure,
        ):
            with self.assertRaises(LatexProjectCompilationFailedError):
                prepare_canonical_latex_project(
                    submission, self.repository, submission.artifacts[0]
                )

        # Load through the same deterministic project store on the next call.
        from src.submissions.latex_project.written_bridge import _load_or_ingest_project
        from src.submissions.latex_project.config import LatexProjectIngestionConfig
        stored = _load_or_ingest_project(
            submission,
            self.repository,
            submission.artifacts[0],
            LatexProjectIngestionConfig(),
        )
        state = load_latex_project_provenance(stored)
        self.assertEqual(state.status, PROJECT_STATUS_COMPILATION_FAILED)
        latest = state.latest_attempt
        self.assertFalse(latest.success)
        self.assertEqual(latest.error_code, "latex_compilation_failed")
        log = Path(stored.project_dir) / latest.compilation_log_relative_path
        self.assertIn("Undefined control sequence", log.read_text())
        self.assertIn("fixture stderr", log.read_text())

    def test_failure_diagnostic_reloads_persisted_project_state_from_published_store_path(self):
        submission = self._submission({
            "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
            "report.tex": r"\documentclass{article}\begin{document}B\end{document}",
        })
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_failure,
        ):
            with self.assertRaises(LatexProjectCompilationFailedError) as raised:
                prepare_canonical_latex_project(
                    submission,
                    self.repository,
                    submission.artifacts[0],
                    root_relative_path="main.tex",
                )

        diagnostic = canonical_latex_project_diagnostic(
            submission,
            self.repository,
            submission.artifacts[0],
            error=raised.exception,
            root_relative_path="main.tex",
        )

        self.assertEqual(diagnostic["status"], PROJECT_STATUS_COMPILATION_FAILED)
        self.assertEqual(diagnostic["root_relative_path"], "main.tex")
        self.assertEqual(diagnostic["compiler"], "pdflatex")
        self.assertEqual(diagnostic["error_code"], "latex_compilation_failed")
        self.assertEqual(diagnostic["candidate_paths"], ["main.tex", "report.tex"])
        self.assertEqual(diagnostic["attempt_count"], 1)
        self.assertTrue(Path(diagnostic["compilation_log_path"]).is_file())
        self.assertTrue(Path(diagnostic["source_project_dir"]).is_dir())
        self.assertTrue(diagnostic["recoverable"])

    def test_persisted_success_reuses_verified_pdf_without_recompiling(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ) as compiler:
            first = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
            second = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        self.assertEqual(compiler.call_count, 1)
        self.assertEqual(first.compilation.pdf_path, second.compilation.pdf_path)
        self.assertEqual(len(second.provenance.compilation_attempts), 1)

    def test_missing_derived_pdf_is_safely_regenerated_from_verified_project(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ) as compiler:
            first = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
            Path(first.compilation.pdf_path).unlink()
            second = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        self.assertEqual(compiler.call_count, 2)
        self.assertTrue(Path(second.compilation.pdf_path).is_file())
        self.assertEqual(len(second.provenance.compilation_attempts), 2)

    def test_root_reselection_persists_and_attempt_history_is_retained(self):
        submission = self._submission({
            "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
            "report.tex": r"\documentclass{article}\begin{document}B\end{document}",
        })
        calls = [self._compile_failure, self._compile_success]
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=lambda *args, **kwargs: calls.pop(0)(*args, **kwargs),
        ):
            with self.assertRaises(LatexProjectCompilationFailedError):
                prepare_canonical_latex_project(
                    submission,
                    self.repository,
                    submission.artifacts[0],
                    root_relative_path="main.tex",
                )
            recovered = prepare_canonical_latex_project(
                submission,
                self.repository,
                submission.artifacts[0],
                root_relative_path="report.tex",
                force_recompile=True,
            )
        self.assertEqual(recovered.provenance.root_relative_path, "report.tex")
        self.assertEqual(len(recovered.provenance.compilation_attempts), 2)
        self.assertEqual(
            [a.root_relative_path for a in recovered.provenance.compilation_attempts],
            ["main.tex", "report.tex"],
        )

    def test_persisted_reselected_root_overrides_original_submission_metadata_on_restart(self):
        archive_path = self.root / "restart.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("main.tex", r"\documentclass{article}\begin{document}A\end{document}")
            archive.writestr("report.tex", r"\documentclass{article}\begin{document}B\end{document}")
        submission = self.repository.create_submission(
            assessment_id="PS1",
            student_id="restart",
            files=[CandidateFile(
                source_path=str(archive_path),
                original_filename=archive_path.name,
                artifact_type=ARTIFACT_TYPE_ZIP,
                role=ARTIFACT_ROLE_SOURCE,
            )],
            metadata={"latex_project_root": "main.tex"},
        )
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ):
            first = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
            self.assertEqual(first.resolution.root_relative_path, "main.tex")
            changed = prepare_canonical_latex_project(
                submission,
                self.repository,
                submission.artifacts[0],
                root_relative_path="report.tex",
                force_recompile=True,
            )
            self.assertEqual(changed.resolution.root_relative_path, "report.tex")
            restarted = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        self.assertEqual(restarted.resolution.root_relative_path, "report.tex")
        self.assertEqual(restarted.provenance.root_relative_path, "report.tex")

    def test_tampered_immutable_source_blocks_regeneration_before_compiler(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ):
            first = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        source = Path(first.stored.extracted_root) / "main.tex"
        source.write_text("tampered", encoding="utf-8")
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf"
        ) as compiler:
            with self.assertRaises(Exception) as raised:
                prepare_canonical_latex_project(
                    submission,
                    self.repository,
                    submission.artifacts[0],
                    force_recompile=True,
                )
        self.assertIn("match", str(raised.exception).lower())
        compiler.assert_not_called()

    def test_persisted_relative_paths_cannot_escape_project_directory(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ):
            context = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        state_path = Path(context.stored.project_dir) / LATEX_PROJECT_PROVENANCE_FILENAME
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["compilation_attempts"][0]["compilation_log_relative_path"] = "../escape.log"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(LatexProjectSerializationError):
            load_latex_project_provenance(context.stored)

    def test_persisted_success_must_be_boolean(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ):
            context = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        state_path = Path(context.stored.project_dir) / LATEX_PROJECT_PROVENANCE_FILENAME
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["compilation_attempts"][0]["success"] = "false"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(LatexProjectSerializationError):
            load_latex_project_provenance(context.stored)

    def test_persisted_state_is_bound_to_canonical_submission_id(self):
        submission = self._submission()
        with mock.patch(
            "src.submissions.latex_project.written_bridge.compile_stored_latex_project_to_pdf",
            side_effect=self._compile_success,
        ):
            context = prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )
        state_path = Path(context.stored.project_dir) / LATEX_PROJECT_PROVENANCE_FILENAME
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["submission_id"] = "sub_other"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(LatexProjectIntegrityError):
            prepare_canonical_latex_project(
                submission, self.repository, submission.artifacts[0]
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
