"""Tests for faithful LaTeX source extraction."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.latex import extract_text_from_tex, strip_latex_comment


class TestLatexComments(unittest.TestCase):

    def test_removes_unescaped_comment(self):
        self.assertEqual(strip_latex_comment("answer % note"), "answer ")

    def test_preserves_escaped_percent(self):
        self.assertEqual(strip_latex_comment(r"improves by 10\% exactly"), r"improves by 10\% exactly")

    def test_even_backslashes_do_not_escape_percent(self):
        self.assertEqual(strip_latex_comment("text\\\\% comment"), "text\\\\")


class TestLatexExtraction(unittest.TestCase):

    def _write(self, directory, name, text):
        path = Path(directory) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_strips_preamble_and_trailer_but_preserves_math_and_environments(self):
        with tempfile.TemporaryDirectory() as tmp:
            tex = self._write(tmp, "main.tex", r"""
\documentclass{article}
% preamble comment
\usepackage{amsmath}
\begin{document}
\section*{Question 1}
The success rate is 10\%. % grading note
\[
T(n) = 2T(n/2) + n
\]
\begin{proof}
We prove the claim by induction.
\end{proof}
\begin{algorithmic}
\For{$i = 1$ to $n$}
\State work
\EndFor
\end{algorithmic}
\end{document}
THIS MUST NOT APPEAR
""")
            text, meta = extract_text_from_tex(str(tex))

        self.assertNotIn("documentclass", text)
        self.assertNotIn("grading note", text)
        self.assertNotIn("THIS MUST NOT APPEAR", text)
        self.assertIn(r"10\%", text)
        self.assertIn(r"T(n) = 2T(n/2) + n", text)
        self.assertIn(r"\begin{proof}", text)
        self.assertIn(r"\begin{algorithmic}", text)
        self.assertTrue(meta["document_environment_found"])
        self.assertEqual(meta["source"], "latex")

    def test_file_without_document_environment_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            tex = self._write(tmp, "answer.tex", "Question 1\n$x^2$\n")
            text, meta = extract_text_from_tex(str(tex))

        self.assertEqual(text, "Question 1\n$x^2$")
        self.assertFalse(meta["document_environment_found"])

    def test_expands_safe_local_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "answers/q1.tex", "Question 1\n$O(n)$\n")
            main = self._write(tmp, "main.tex", r"""
\begin{document}
\input{answers/q1}
\end{document}
""")
            text, meta = extract_text_from_tex(str(main))

        self.assertIn("Question 1", text)
        self.assertIn("$O(n)$", text)
        self.assertEqual(len(meta["included_files"]), 1)
        self.assertEqual(meta["warnings"], [])

    def test_symlinked_main_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.tex"
            real.write_text("Question 1\nAnswer", encoding="utf-8")
            link = root / "link.tex"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this platform")

            with self.assertRaises(ValueError):
                extract_text_from_tex(str(link))

    def test_symlinked_include_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            secret = Path(outside) / "secret.tex"
            secret.write_text("SECRET", encoding="utf-8")
            link = root / "answer.tex"
            try:
                link.symlink_to(secret)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this platform")

            main = root / "main.tex"
            main.write_text(
                "\\begin{document}\n\\input{answer}\n\\end{document}\n",
                encoding="utf-8",
            )
            text, meta = extract_text_from_tex(str(main))

        self.assertIn(r"\input{answer}", text)
        self.assertNotIn("SECRET", text)
        self.assertIn("latex_include_unavailable:answer", meta["warnings"])

    def test_missing_include_is_preserved_and_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = self._write(tmp, "main.tex", r"\begin{document}\input{missing}\end{document}")
            text, meta = extract_text_from_tex(str(main))

        self.assertIn(r"\input{missing}", text)
        self.assertIn("latex_include_unavailable:missing", meta["warnings"])

    def test_include_cycle_does_not_recurse_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = self._write(tmp, "main.tex", r"\begin{document}\input{a}\end{document}")
            self._write(tmp, "a.tex", r"A\input{main}")
            text, meta = extract_text_from_tex(str(main))

        self.assertIn("A", text)
        self.assertIn("latex_include_cycle", meta["warnings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
