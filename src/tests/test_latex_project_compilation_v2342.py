"""Tests for v2.3.4.2 Commit 4 whole-project LaTeX compilation."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from src.submissions.latex_project import (
    LatexProjectArchiveStore,
    LatexProjectCompilation,
    LatexProjectIntegrityError,
    LatexProjectValidationError,
    compile_stored_latex_project_to_pdf,
    discover_latex_project,
    resolve_latex_project_root,
)
from src.submissions.models import CompilationResult


class TestLatexProjectCompilationV2342(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        self.store = LatexProjectArchiveStore(self.root / "store")

    def tearDown(self):
        self.temp.cleanup()

    def _stored(self, entries, project_id="lproj-compile-test"):
        archive = self.incoming / ("%s.zip" % project_id)
        with zipfile.ZipFile(
            archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            for relative, data in entries:
                if isinstance(data, str):
                    data = data.encode("utf-8")
                zf.writestr(relative, data)
        return self.store.ingest_zip(
            archive,
            "artifact-source",
            project_id=project_id,
            imported_at="2026-08-20T21:00:00Z",
        )

    def _resolved(self, stored):
        discovery = discover_latex_project(
            stored.extracted_root,
            stored.manifest,
        )
        return resolve_latex_project_root(discovery)

    @patch("src.submissions.latex_project.compilation.compile_tex_to_pdf")
    def test_project_compiler_delegates_entire_verified_tree_to_existing_compiler(
        self,
        compiler,
    ):
        stored = self._stored([
            (
                "project/main.tex",
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\input{../sections/q1}\n"
                "\\includegraphics{../figures/plot.pdf}\n"
                "\\end{document}\n",
            ),
            ("sections/q1.tex", "Answer"),
            ("figures/plot.pdf", b"%PDF-synthetic"),
            ("refs.bib", "@book{x,title={X}}"),
        ])
        resolution = self._resolved(stored)
        output_pdf = self.root / "compiled" / "main.pdf"
        output_pdf.parent.mkdir()
        output_pdf.write_bytes(b"%PDF-1.4\nmock")
        compiler.return_value = CompilationResult(
            success=True,
            source_path=str(Path(stored.extracted_root) / "project" / "main.tex"),
            engine="pdflatex",
            pdf_path=str(output_pdf),
            return_code=0,
            passes_completed=1,
        )

        result = compile_stored_latex_project_to_pdf(
            stored,
            resolution,
            output_dir=str(output_pdf.parent),
        )

        self.assertIsInstance(result, LatexProjectCompilation)
        self.assertTrue(result.success)
        self.assertEqual(result.pdf_path, str(output_pdf))
        self.assertEqual(result.project_id, stored.project_id)
        self.assertEqual(result.root_relative_path, "project/main.tex")
        self.assertEqual(result.archive_sha256, stored.archive.archive_sha256)
        self.assertEqual(
            result.manifest_sha256,
            stored.manifest.manifest_sha256,
        )

        args, kwargs = compiler.call_args
        self.assertEqual(
            Path(args[0]),
            Path(stored.extracted_root) / "project" / "main.tex",
        )
        self.assertEqual(Path(kwargs["source_root"]), Path(stored.extracted_root))
        self.assertEqual(
            set(kwargs["allowed_source_paths"]),
            {item.relative_path for item in stored.manifest.files},
        )
        self.assertEqual(kwargs["max_source_files"], 1000)
        self.assertEqual(kwargs["max_source_bytes"], 250 * 1024 * 1024)
        self.assertEqual(kwargs["max_single_file_bytes"], 50 * 1024 * 1024)

    @patch("src.submissions.latex_project.compilation.compile_tex_to_pdf")
    def test_compiler_failure_is_preserved_as_structured_result(self, compiler):
        stored = self._stored([
            (
                "main.tex",
                "\\documentclass{article}\\begin{document}X\\end{document}",
            ),
        ])
        resolution = self._resolved(stored)
        compiler.return_value = CompilationResult(
            success=False,
            source_path=str(Path(stored.extracted_root) / "main.tex"),
            engine="pdflatex",
            error_code="latex_compilation_failed",
            error_message="synthetic compile error",
            return_code=1,
        )

        result = compile_stored_latex_project_to_pdf(stored, resolution)

        self.assertFalse(result.success)
        self.assertIsNone(result.pdf_path)
        self.assertEqual(
            result.compilation.error_code,
            "latex_compilation_failed",
        )

    @patch("src.submissions.latex_project.compilation.compile_tex_to_pdf")
    def test_unresolved_project_never_invokes_tex(self, compiler):
        stored = self._stored([
            (
                "main.tex",
                "\\documentclass{article}\\begin{document}A\\end{document}",
            ),
            (
                "report.tex",
                "\\documentclass{article}\\begin{document}B\\end{document}",
            ),
        ])
        resolution = self._resolved(stored)
        self.assertEqual(resolution.status, "ambiguous")

        with self.assertRaises(LatexProjectValidationError):
            compile_stored_latex_project_to_pdf(stored, resolution)

        compiler.assert_not_called()

    @patch("src.submissions.latex_project.compilation.compile_tex_to_pdf")
    def test_tampered_project_is_rejected_before_tex_execution(self, compiler):
        stored = self._stored([
            (
                "main.tex",
                "\\documentclass{article}\\begin{document}A\\end{document}",
            ),
        ])
        resolution = self._resolved(stored)
        (Path(stored.extracted_root) / "main.tex").write_text(
            "\\documentclass{article}\\begin{document}TAMPERED\\end{document}",
            encoding="utf-8",
        )

        with self.assertRaises(LatexProjectIntegrityError):
            compile_stored_latex_project_to_pdf(stored, resolution)

        compiler.assert_not_called()

    @patch("src.submissions.latex_project.compilation.compile_tex_to_pdf")
    def test_resolution_from_different_project_is_rejected(self, compiler):
        first = self._stored([
            (
                "main.tex",
                "\\documentclass{article}\\begin{document}A\\end{document}",
            ),
        ], project_id="lproj-first")
        second = self._stored([
            (
                "main.tex",
                "\\documentclass{article}\\begin{document}B\\end{document}",
            ),
        ], project_id="lproj-second")
        wrong_resolution = self._resolved(second)

        with self.assertRaises(LatexProjectIntegrityError):
            compile_stored_latex_project_to_pdf(first, wrong_resolution)

        compiler.assert_not_called()

    def test_metadata_is_json_friendly_and_exposes_compiler_provenance(self):
        stored = self._stored([
            (
                "main.tex",
                "\\documentclass{article}\\begin{document}A\\end{document}",
            ),
        ])
        resolution = self._resolved(stored)
        compilation = CompilationResult(
            success=True,
            source_path=str(Path(stored.extracted_root) / "main.tex"),
            engine="pdflatex",
            pdf_path="/tmp/main.pdf",
            return_code=0,
            passes_completed=1,
            stdout="compiler log",
        )
        result = LatexProjectCompilation(
            project_id=stored.project_id,
            root_relative_path="main.tex",
            resolution_method=resolution.resolution_method,
            archive_sha256=stored.archive.archive_sha256,
            manifest_sha256=stored.manifest.manifest_sha256,
            source_file_count=stored.manifest.file_count,
            source_total_bytes=stored.manifest.total_uncompressed_bytes,
            compilation=compilation,
        )

        metadata = result.to_metadata()
        self.assertEqual(metadata["project_id"], stored.project_id)
        self.assertTrue(metadata["compilation"]["success"])
        self.assertNotIn("stdout", metadata["compilation"])
        self.assertEqual(
            result.to_metadata(include_logs=True)["compilation"]["stdout"],
            "compiler log",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
