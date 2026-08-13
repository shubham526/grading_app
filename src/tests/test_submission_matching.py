"""Tests for v2.2.0 commit-1 normal submission discovery."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions.matcher import (
    discover_submissions,
    match_student_directory,
    normalize_student_id,
    record_from_latex_file,
)


class TestStudentIdNormalization(unittest.TestCase):

    def test_normalization_examples(self):
        self.assertEqual(normalize_student_id("Alice Smith.pdf"), "alice_smith")
        self.assertEqual(normalize_student_id("bob_123.tex"), "bob_123")
        self.assertEqual(normalize_student_id("  CS-42  "), "cs-42")


class TestDirectoryMatching(unittest.TestCase):

    def test_prefers_main_tex_and_same_stem_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            student = Path(tmp) / "Alice Smith"
            student.mkdir()
            (student / "notes.tex").write_text("x" * 200, encoding="utf-8")
            (student / "main.tex").write_text("main", encoding="utf-8")
            (student / "other.pdf").write_bytes(b"%PDF-other")
            (student / "main.pdf").write_bytes(b"%PDF-main")

            record = match_student_directory(str(student))

        self.assertIsNotNone(record)
        self.assertEqual(record.student_id, "alice_smith")
        self.assertTrue(record.files["latex"].endswith("main.tex"))
        self.assertTrue(record.files["pdf"].endswith("main.pdf"))
        self.assertIn("multiple_tex_files", record.warnings)
        self.assertIn("multiple_pdf_files", record.warnings)

    def test_without_tex_is_not_normal_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            student = Path(tmp) / "alice"
            student.mkdir()
            (student / "main.pdf").write_bytes(b"%PDF")
            self.assertIsNone(match_student_directory(str(student)))


class TestSubmissionDiscovery(unittest.TestCase):

    def test_directory_flat_and_mixed_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            alice = root / "alice"
            alice.mkdir()
            (alice / "main.tex").write_text("Alice directory", encoding="utf-8")

            (root / "bob.tex").write_text("Bob flat", encoding="utf-8")
            (root / "bob.pdf").write_bytes(b"%PDF-bob")

            # Same ID exists in both layouts: directory must win.
            (root / "alice.tex").write_text("Alice flat", encoding="utf-8")

            # Commit 1 intentionally ignores PDF-only accommodation records.
            (root / "charlie.pdf").write_bytes(b"%PDF-charlie")

            records = discover_submissions(str(root))

        self.assertEqual([record.student_id for record in records], ["alice", "bob"])
        by_id = {record.student_id: record for record in records}
        self.assertIn("duplicate_student_submission", by_id["alice"].warnings)
        self.assertIn(os.path.join("alice", "main.tex"), by_id["alice"].files["latex"])
        self.assertTrue(by_id["bob"].files["latex"].endswith("bob.tex"))
        self.assertTrue(by_id["bob"].files["pdf"].endswith("bob.pdf"))

    def test_explicit_tex_file_pairs_optional_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tex = Path(tmp) / "student42.tex"
            pdf = Path(tmp) / "student42.pdf"
            tex.write_text("answer", encoding="utf-8")
            pdf.write_bytes(b"%PDF")
            record = record_from_latex_file(str(tex))

        self.assertEqual(record.student_id, "student42")
        self.assertTrue(record.files["latex"].endswith("student42.tex"))
        self.assertTrue(record.files["pdf"].endswith("student42.pdf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
