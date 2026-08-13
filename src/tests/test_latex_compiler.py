"""Tests for restricted LaTeX compilation without requiring TeX in CI."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.compiler import (
    cleanup_compilation_artifacts,
    compile_tex_to_pdf,
)


class TestLatexCompiler(unittest.TestCase):

    def _source(self, directory):
        path = Path(directory) / "main.tex"
        path.write_text(r"\documentclass{article}\begin{document}Hi\end{document}", encoding="utf-8")
        return path

    @patch("src.submissions.compiler.shutil.which", return_value=None)
    def test_missing_engine_returns_structured_failure(self, _which):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            result = compile_tex_to_pdf(str(source))

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "engine_unavailable")
        self.assertIsNone(result.pdf_path)

    def test_rejects_unsupported_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            with self.assertRaises(ValueError):
                compile_tex_to_pdf(str(source), engine="lualatex")

    def test_symlinked_main_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = self._source(tmp)
            link = root / "linked.tex"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this platform")

            with self.assertRaises(ValueError):
                compile_tex_to_pdf(str(link))

    @patch("src.submissions.compiler._run_tex_process")
    @patch("src.submissions.compiler.shutil.which", return_value="/usr/bin/pdflatex")
    def test_successful_compile_copies_pdf_to_requested_output(self, _which, run_process):
        def fake_run(command, *, cwd, env, timeout_seconds):
            output_arg = next(item for item in command if item.startswith("-output-directory="))
            output_dir = Path(output_arg.split("=", 1)[1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "main.pdf").write_bytes(b"%PDF-1.4\nmock")
            self.assertIn("-no-shell-escape", command)
            self.assertEqual(env["openin_any"], "p")
            self.assertEqual(env["openout_any"], "p")
            return 0, "ok", "", False

        run_process.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            source = self._source(tmp)
            result = compile_tex_to_pdf(str(source), output_dir=out)
            pdf_bytes = Path(result.pdf_path).read_bytes()

        self.assertTrue(result.success)
        self.assertEqual(pdf_bytes[:5], b"%PDF-")
        self.assertFalse(result.temporary_output)
        self.assertEqual(result.passes_completed, 1)

    @patch("src.submissions.compiler._run_tex_process")
    @patch("src.submissions.compiler.shutil.which", return_value="/usr/bin/pdflatex")
    def test_timeout_is_structured_failure(self, _which, run_process):
        run_process.return_value = (-9, "", "", True)
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            result = compile_tex_to_pdf(str(source), timeout_seconds=0.1)

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "latex_compilation_timeout")

    @patch("src.submissions.compiler._run_tex_process")
    @patch("src.submissions.compiler.shutil.which", return_value="/usr/bin/pdflatex")
    def test_symlink_in_source_tree_is_not_staged(self, _which, run_process):
        def fake_run(command, *, cwd, env, timeout_seconds):
            self.assertFalse((Path(cwd) / "outside.txt").exists())
            output_arg = next(item for item in command if item.startswith("-output-directory="))
            output_dir = Path(output_arg.split("=", 1)[1])
            (output_dir / "main.pdf").write_bytes(b"%PDF-1.4\nmock")
            return 0, "", "", False

        run_process.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            source = self._source(tmp)
            target = Path(outside) / "secret.txt"
            target.write_text("secret", encoding="utf-8")
            link = Path(tmp) / "outside.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this platform")
            result = compile_tex_to_pdf(str(source))
            build_dir = result.build_dir
            self.assertTrue(result.success)
            self.assertTrue(any(w.startswith("skipped_symlink:") for w in result.warnings))
            cleanup_compilation_artifacts(result)
            self.assertFalse(Path(build_dir).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
