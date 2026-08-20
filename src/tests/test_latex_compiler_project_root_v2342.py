"""Regression tests for whole-project staging in the existing LaTeX compiler."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.submissions.compiler import compile_tex_to_pdf


class TestLatexCompilerProjectRootV2342(unittest.TestCase):
    @patch("src.submissions.compiler._run_tex_process")
    @patch("src.submissions.compiler.shutil.which", return_value="/usr/bin/pdflatex")
    def test_nested_root_compiles_from_project_root_with_complete_tree(
        self,
        _which,
        run_process,
    ):
        observed = {}

        def fake_run(command, *, cwd, env, timeout_seconds):
            root = Path(cwd)
            observed["cwd"] = root
            observed["command"] = list(command)
            self.assertTrue((root / "tex" / "main.tex").is_file())
            self.assertTrue((root / "sections" / "answer.tex").is_file())
            self.assertTrue((root / "figures" / "plot.pdf").is_file())
            output_arg = next(
                item for item in command
                if item.startswith("-output-directory=")
            )
            output_dir = Path(output_arg.split("=", 1)[1])
            (output_dir / "main.pdf").write_bytes(b"%PDF-1.4\nproject")
            return 0, "ok", "", False

        run_process.side_effect = fake_run

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            project = Path(td)
            (project / "tex").mkdir()
            (project / "sections").mkdir()
            (project / "figures").mkdir()
            root = project / "tex" / "main.tex"
            root.write_text(
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\input{../sections/answer}\n"
                "\\includegraphics{../figures/plot.pdf}\n"
                "\\end{document}\n",
                encoding="utf-8",
            )
            (project / "sections" / "answer.tex").write_text(
                "Answer",
                encoding="utf-8",
            )
            (project / "figures" / "plot.pdf").write_bytes(b"%PDF-synthetic")

            result = compile_tex_to_pdf(
                str(root),
                source_root=str(project),
                output_dir=out,
            )

            self.assertTrue(result.success)
            self.assertEqual(Path(result.pdf_path).read_bytes()[:5], b"%PDF-")

        self.assertEqual(observed["command"][-1], "tex/main.tex")

    @patch("src.submissions.compiler._run_tex_process")
    @patch("src.submissions.compiler.shutil.which", return_value="/usr/bin/pdflatex")
    def test_manifest_allowlist_excludes_unverified_injected_file(
        self,
        _which,
        run_process,
    ):
        def fake_run(command, *, cwd, env, timeout_seconds):
            root = Path(cwd)
            self.assertTrue((root / "main.tex").is_file())
            self.assertTrue((root / "sections" / "q1.tex").is_file())
            self.assertFalse((root / "injected.tex").exists())
            output_arg = next(
                item for item in command
                if item.startswith("-output-directory=")
            )
            output_dir = Path(output_arg.split("=", 1)[1])
            (output_dir / "main.pdf").write_bytes(b"%PDF-1.4\nproject")
            return 0, "", "", False

        run_process.side_effect = fake_run

        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / "sections").mkdir()
            root = project / "main.tex"
            root.write_text(
                "\\documentclass{article}\\begin{document}"
                "\\input{sections/q1}\\end{document}",
                encoding="utf-8",
            )
            (project / "sections" / "q1.tex").write_text("A", encoding="utf-8")
            (project / "injected.tex").write_text("DO NOT STAGE", encoding="utf-8")

            result = compile_tex_to_pdf(
                str(root),
                source_root=str(project),
                allowed_source_paths=("main.tex", "sections/q1.tex"),
            )
            build_dir = result.build_dir
            self.assertTrue(result.success)

        if build_dir:
            from src.submissions.compiler import cleanup_compilation_artifacts
            cleanup_compilation_artifacts(result)

    def test_source_root_must_contain_main_source(self):
        with tempfile.TemporaryDirectory() as project_td, tempfile.TemporaryDirectory() as other_td:
            project = Path(project_td)
            root = project / "main.tex"
            root.write_text(
                "\\documentclass{article}\\begin{document}A\\end{document}",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "latex_main_source_outside_source_root"):
                compile_tex_to_pdf(str(root), source_root=other_td)

    @patch("src.submissions.compiler.shutil.which", return_value="/usr/bin/pdflatex")
    def test_main_source_must_be_in_allowlist(self, _which):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            root = project / "main.tex"
            root.write_text(
                "\\documentclass{article}\\begin{document}A\\end{document}",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "latex_main_source_not_in_allowlist"):
                compile_tex_to_pdf(
                    str(root),
                    source_root=str(project),
                    allowed_source_paths=("other.tex",),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
