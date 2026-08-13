"""Tests for v2.2.0 commit-1 LaTeX parser orchestration."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.models import CompilationResult
from src.submissions.parser import parse_submission, parse_submissions_folder


class TestSubmissionParser(unittest.TestCase):

    def _write_submission(self, directory, student, body):
        student_dir = Path(directory) / student
        student_dir.mkdir()
        tex = student_dir / "main.tex"
        tex.write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            + body
            + "\n\\end{document}\n",
            encoding="utf-8",
        )
        return student_dir, tex

    def test_parse_directory_without_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            student_dir, _ = self._write_submission(
                tmp,
                "Alice Smith",
                "Question 1\n$O(n)$\nQuestion 2\nProof",
            )
            parsed = parse_submission(
                str(student_dir),
                ["Q1", "Q2"],
                compile_pdf=False,
            )

        self.assertEqual(parsed.student_id, "alice_smith")
        self.assertEqual(parsed.submission_mode, "latex")
        self.assertEqual(parsed.source_used, "latex")
        self.assertEqual(parsed.answers_by_question["Q1"], "$O(n)$")
        self.assertEqual(parsed.answers_by_question["Q2"], "Proof")
        self.assertEqual(parsed.metadata["question_split_status"], "success")
        self.assertNotIn("compiled_pdf", parsed.files)

    @patch("src.submissions.parser.compile_tex_to_pdf")
    def test_parser_records_app_compiled_pdf(self, compile_mock):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            student_dir, tex = self._write_submission(tmp, "bob", "Q1\nAnswer")
            generated = Path(out) / "bob" / "main.pdf"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(b"%PDF-mock")
            compile_mock.return_value = CompilationResult(
                success=True,
                source_path=str(tex),
                engine="pdflatex",
                pdf_path=str(generated),
                return_code=0,
                passes_completed=1,
            )

            parsed = parse_submission(
                str(student_dir),
                ["Q1"],
                compilation_dir=out,
            )

        self.assertEqual(parsed.files["compiled_pdf"], str(generated))
        self.assertTrue(parsed.metadata["compilation"]["success"])
        compile_mock.assert_called_once()
        kwargs = compile_mock.call_args.kwargs
        self.assertTrue(kwargs["output_dir"].endswith(os.path.join(os.path.basename(out), "bob")))

    @patch("src.submissions.parser.compile_tex_to_pdf")
    def test_compilation_failure_does_not_destroy_extracted_answers(self, compile_mock):
        compile_mock.return_value = CompilationResult(
            success=False,
            source_path="main.tex",
            engine="pdflatex",
            error_code="engine_unavailable",
            error_message="missing",
        )
        with tempfile.TemporaryDirectory() as tmp:
            student_dir, _ = self._write_submission(tmp, "charlie", "Question 1\nAnswer")
            parsed = parse_submission(str(student_dir), ["Q1"])

        self.assertEqual(parsed.answers_by_question["Q1"], "Answer")
        self.assertIn("engine_unavailable", parsed.warnings)
        self.assertNotIn("compiled_pdf", parsed.files)

    def test_batch_parser_uses_discovery_and_canonical_question_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_submission(tmp, "alice", "Q1(a)\nA")
            self._write_submission(tmp, "bob", "Question 1(a)\nB")
            parsed = parse_submissions_folder(
                tmp,
                ["Q1A"],
                compile_pdf=False,
            )

        self.assertEqual(sorted(parsed), ["alice", "bob"])
        self.assertEqual(parsed["alice"].answers_by_question["Q1A"], "A")
        self.assertEqual(parsed["bob"].answers_by_question["Q1A"], "B")

    def test_root_with_multiple_students_requires_batch_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_submission(tmp, "alice", "Q1\nA")
            self._write_submission(tmp, "bob", "Q1\nB")
            with self.assertRaises(ValueError):
                parse_submission(tmp, ["Q1"], compile_pdf=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
