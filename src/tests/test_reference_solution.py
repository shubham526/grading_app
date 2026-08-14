"""Tests for assignment-level instructor reference solutions."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.submissions.reference_solution import (
    load_reference_solution,
    prepare_reference_solution,
)


class _Compilation:
    def __init__(self, pdf_path):
        self.success = True
        self.pdf_path = str(pdf_path)
        self.error_code = None

    def to_metadata(self, include_logs=False):
        return {
            "success": True,
            "pdf_path": self.pdf_path,
            "include_logs": bool(include_logs),
        }


class TestReferenceSolution(unittest.TestCase):
    def test_latex_is_canonical_and_question_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / "solution.tex"
            tex.write_text(
                r"""\documentclass{article}
\begin{document}
Question 1
Selection sort maintains the invariant for Q1.

Question 2
The running time is $\Theta(n^2)$.
\end{document}
""",
                encoding="utf-8",
            )
            assessments = root / "assessments"
            assessments.mkdir()

            def fake_compile(path, *, output_dir=None, **kwargs):
                out = Path(output_dir)
                out.mkdir(parents=True, exist_ok=True)
                pdf = out / "solution.pdf"
                pdf.write_bytes(b"%PDF-1.4\n% fake reference\n")
                return _Compilation(pdf)

            with mock.patch(
                "src.submissions.reference_solution.compile_tex_to_pdf",
                side_effect=fake_compile,
            ):
                solution = prepare_reference_solution(
                    str(tex), str(assessments), question_ids=["Q1", "Q2"]
                )

            self.assertEqual(solution.source_type, "latex")
            self.assertEqual(solution.metadata["canonical_format"], "latex")
            self.assertTrue(solution.metadata["preferred_for_ai_grading"])
            self.assertIn("Q1", solution.answers_by_question)
            self.assertIn("invariant", solution.answers_by_question["Q1"])
            self.assertIn("Theta", solution.answers_by_question["Q2"].replace("\\Theta", "Theta"))
            self.assertTrue(Path(solution.canonical_source_path).exists())
            self.assertTrue(Path(solution.display_pdf_path).exists())

            loaded = load_reference_solution(str(assessments))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.answers_by_question, solution.answers_by_question)
            self.assertEqual(loaded.source_type, "latex")

    def test_digital_pdf_is_supported_as_fallback(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("PyMuPDF not available")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "solution.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=612, height=792)
            page.insert_text(
                (72, 72),
                "Question 1\n" + "Correct selection-sort proof. " * 8 + "\nQuestion 2\nTheta(n^2) runtime. " * 8,
                fontsize=11,
            )
            doc.save(str(pdf))
            doc.close()
            assessments = root / "assessments"
            assessments.mkdir()

            solution = prepare_reference_solution(
                str(pdf), str(assessments), question_ids=["Q1", "Q2"]
            )
            self.assertEqual(solution.source_type, "pdf")
            self.assertEqual(solution.metadata["machine_readable_source"], "pdf_selectable_text")
            self.assertFalse(solution.metadata["preferred_for_ai_grading"])
            self.assertTrue(solution.answers_by_question)
            self.assertTrue(Path(solution.display_pdf_path).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
