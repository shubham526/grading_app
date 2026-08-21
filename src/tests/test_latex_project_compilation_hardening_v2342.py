"""Commit 8 compilation/integrity hardening for whole LaTeX projects."""

from __future__ import annotations

import base64
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from src.submissions.latex_project import (
    LatexProjectIntegrityError,
    compile_stored_latex_project_to_pdf,
)
from src.tests.latex_project_v2342_hardening_support import (
    complete_document,
    discover_and_resolve,
    ingest_project,
)


# 1x1 transparent PNG, used only as opaque project input to real pdflatex.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class TestLatexProjectCompilationHardeningV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _compile(self, entries, *, project_id="lproj-compile-hard", **kwargs):
        _store, stored = ingest_project(
            self.root / project_id,
            entries,
            project_id=project_id,
        )
        _discovery, resolution = discover_and_resolve(stored)
        result = compile_stored_latex_project_to_pdf(
            stored,
            resolution,
            output_dir=self.root / project_id / "compiled",
            **kwargs,
        )
        return stored, result

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_real_multifile_nested_project_compiles(self):
        stored, result = self._compile([
            (
                "submission/main.tex",
                complete_document("\\input{submission/sections/q1}"),
            ),
            ("submission/sections/q1.tex", "WHOLE-PROJECT-HARDENING-PASS\n"),
        ])
        self.assertTrue(result.success, result.compilation.error_message)
        self.assertTrue(Path(result.pdf_path).is_file())
        self.assertEqual(result.root_relative_path, "submission/main.tex")
        self.assertEqual(result.source_file_count, len(stored.manifest.files))

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_real_custom_macros_and_figure_project_compiles(self):
        stored, result = self._compile([
            (
                "main.tex",
                "\\documentclass{article}\n"
                "\\usepackage{graphicx}\n"
                "\\input{macros}\n"
                "\\begin{document}\n"
                "\\fixtureword\n"
                "\\includegraphics[width=1pt]{figures/pixel.png}\n"
                "\\end{document}\n",
            ),
            ("macros.tex", "\\newcommand{\\fixtureword}{MACRO-PASS}\n"),
            ("figures/pixel.png", _PIXEL_PNG),
            ("references.bib", "@book{x,title={Fixture}}\n"),
        ], project_id="lproj-assets")
        self.assertTrue(result.success, result.compilation.error_message)
        self.assertEqual(result.source_file_count, 4)
        self.assertEqual(result.source_total_bytes, stored.manifest.total_uncompressed_bytes)

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_real_compile_disables_shell_escape(self):
        sentinel = self.root / "SHELL_ESCAPE_MUST_NOT_RUN"
        body = "\\immediate\\write18{touch %s}\nSHELL-ESCAPE-BLOCKED" % sentinel.as_posix()
        _stored, result = self._compile([
            ("main.tex", complete_document(body)),
        ], project_id="lproj-shell-escape")
        self.assertTrue(result.success, result.compilation.error_message)
        self.assertFalse(sentinel.exists())

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_missing_input_is_structured_compiler_failure(self):
        _stored, result = self._compile([
            ("main.tex", complete_document("\\input{missing-file}")),
        ], project_id="lproj-missing")
        self.assertFalse(result.success)
        self.assertEqual(result.compilation.error_code, "latex_compilation_failed")
        self.assertIsNone(result.pdf_path)

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_generated_pdf_size_limit_is_enforced(self):
        _stored, result = self._compile([
            ("main.tex", complete_document("PDF size hardening")),
        ], project_id="lproj-pdf-limit", max_pdf_bytes=5)
        self.assertFalse(result.success)
        self.assertEqual(result.compilation.error_code, "compiled_pdf_too_large")
        self.assertIsNone(result.pdf_path)

    def test_engine_unavailable_is_structured_failure(self):
        _store, stored = ingest_project(self.root / "engine", [
            ("main.tex", complete_document("engine")),
        ], project_id="lproj-engine")
        _discovery, resolution = discover_and_resolve(stored)
        with mock.patch("src.submissions.compiler.shutil.which", return_value=None):
            result = compile_stored_latex_project_to_pdf(
                stored,
                resolution,
                output_dir=self.root / "engine" / "compiled",
            )
        self.assertFalse(result.success)
        self.assertEqual(result.compilation.error_code, "engine_unavailable")

    def test_timeout_is_structured_failure(self):
        _store, stored = ingest_project(self.root / "timeout", [
            ("main.tex", complete_document("timeout")),
        ], project_id="lproj-timeout")
        _discovery, resolution = discover_and_resolve(stored)
        with mock.patch(
            "src.submissions.compiler.shutil.which",
            return_value="/synthetic/pdflatex",
        ), mock.patch(
            "src.submissions.compiler._run_tex_process",
            return_value=(-9, "partial log", "", True),
        ):
            result = compile_stored_latex_project_to_pdf(
                stored,
                resolution,
                output_dir=self.root / "timeout" / "compiled",
                timeout_seconds=0.01,
            )
        self.assertFalse(result.success)
        self.assertEqual(result.compilation.error_code, "latex_compilation_timeout")
        self.assertIn("partial log", result.compilation.stdout)

    def test_unexpected_file_inserted_after_extraction_blocks_tex(self):
        _store, stored = ingest_project(self.root / "inserted", [
            ("main.tex", complete_document("clean")),
        ], project_id="lproj-inserted")
        _discovery, resolution = discover_and_resolve(stored)
        (Path(stored.extracted_root) / "injected.tex").write_text(
            complete_document("INJECTED"), encoding="utf-8"
        )
        with mock.patch(
            "src.submissions.latex_project.compilation.compile_tex_to_pdf"
        ) as compiler:
            with self.assertRaises(LatexProjectIntegrityError):
                compile_stored_latex_project_to_pdf(stored, resolution)
        compiler.assert_not_called()

    def test_tampered_original_zip_blocks_tex(self):
        _store, stored = ingest_project(self.root / "zip-tamper", [
            ("main.tex", complete_document("clean")),
        ], project_id="lproj-zip-tamper")
        _discovery, resolution = discover_and_resolve(stored)
        original = Path(stored.original_archive_path)
        original.write_bytes(original.read_bytes() + b"tamper")
        with mock.patch(
            "src.submissions.latex_project.compilation.compile_tex_to_pdf"
        ) as compiler:
            with self.assertRaises(LatexProjectIntegrityError):
                compile_stored_latex_project_to_pdf(stored, resolution)
        compiler.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
