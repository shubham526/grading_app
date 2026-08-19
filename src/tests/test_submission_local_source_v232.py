"""Tests for v2.3.2 Commit 3 local submission source discovery."""

from pathlib import Path
import tempfile
import unittest

from src.submissions import LocalFileSourceAdapter
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_UNKNOWN,
)
from src.submissions.sources.local import (
    discover_local_directory,
    discover_local_files,
)


class TestLocalSubmissionSource(unittest.TestCase):
    def test_explicit_same_stem_pdf_and_tex_are_one_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / "alice_PS1.tex"
            pdf = root / "alice_PS1.pdf"
            tex.write_text("Question 1\nA", encoding="utf-8")
            pdf.write_bytes(b"pdf-bytes")

            candidates = discover_local_files(
                [str(tex), str(pdf)],
                assessment_id="PS1",
            )

            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.proposed_assessment_id, "PS1")
            self.assertEqual(candidate.metadata["identity_hints"], ["alice_ps1"])
            self.assertEqual(len(candidate.files), 2)

            by_type = {item.artifact_type: item for item in candidate.files}
            self.assertEqual(by_type[ARTIFACT_TYPE_TEX].role, ARTIFACT_ROLE_SOURCE)
            self.assertEqual(by_type[ARTIFACT_TYPE_PDF].role, ARTIFACT_ROLE_RENDERED)
            self.assertTrue(by_type[ARTIFACT_TYPE_TEX].sha256)
            self.assertGreater(by_type[ARTIFACT_TYPE_TEX].size_bytes, 0)

    def test_single_python_file_is_primary_programming_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s001_lab1.py"
            path.write_text("print('hello')\n", encoding="utf-8")

            candidate = discover_local_files([str(path)])[0]
            self.assertEqual(len(candidate.files), 1)
            self.assertEqual(candidate.files[0].artifact_type, ARTIFACT_TYPE_PYTHON)
            self.assertEqual(candidate.files[0].role, ARTIFACT_ROLE_PRIMARY)

    def test_unknown_file_type_is_preserved_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alice.custom"
            path.write_bytes(b"opaque")

            candidate = discover_local_files([str(path)])[0]
            self.assertEqual(candidate.files[0].artifact_type, ARTIFACT_TYPE_UNKNOWN)
            self.assertIn("unknown_artifact_type:alice.custom", candidate.warnings)

    def test_directory_discovers_flat_files_and_student_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flat = root / "alice_PS1.tex"
            flat.write_text("A", encoding="utf-8")

            bob = root / "bob"
            bob.mkdir()
            (bob / "main.tex").write_text("B", encoding="utf-8")
            (bob / "reference.pdf").write_bytes(b"pdf")

            candidates = discover_local_directory(str(root), assessment_id="PS1")
            self.assertEqual(len(candidates), 2)

            groupings = {item.metadata["grouping"]: item for item in candidates}
            self.assertIn("same_stem_files", groupings)
            self.assertIn("student_directory", groupings)
            self.assertEqual(
                groupings["student_directory"].metadata["identity_hints"],
                ["bob"],
            )
            self.assertEqual(len(groupings["student_directory"].files), 2)

    def test_hidden_files_are_ignored_during_directory_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".DS_Store").write_bytes(b"junk")
            (root / "alice.tex").write_text("A", encoding="utf-8")

            candidates = discover_local_directory(str(root))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].files[0].original_filename, "alice.tex")

    def test_adapter_fetch_rejects_file_changed_after_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alice.tex"
            path.write_text("first", encoding="utf-8")

            adapter = LocalFileSourceAdapter.from_files([str(path)])
            candidate = adapter.discover(assessment_id="PS1")[0]
            path.write_text("second-and-different", encoding="utf-8")

            with self.assertRaises(ValueError):
                adapter.fetch(candidate)

    def test_symlinked_explicit_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.tex"
            link = root / "alice.tex"
            source.write_text("A", encoding="utf-8")
            try:
                link.symlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            with self.assertRaises(ValueError):
                discover_local_files([str(link)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
