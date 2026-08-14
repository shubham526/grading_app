import hashlib
import tempfile
import unittest
from pathlib import Path

from src.similarity.hashing import compute_file_sha256, compute_text_sha256
from src.similarity.normalize import normalize_for_similarity


class TestSimilarityHashing(unittest.TestCase):
    def test_identical_files_produce_same_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.tex"
            b = Path(tmp) / "b.tex"
            a.write_bytes(b"same bytes\n")
            b.write_bytes(b"same bytes\n")
            self.assertEqual(compute_file_sha256(a), compute_file_sha256(b))

    def test_different_files_produce_different_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.tex"
            b = Path(tmp) / "b.tex"
            a.write_bytes(b"alpha")
            b.write_bytes(b"beta")
            self.assertNotEqual(compute_file_sha256(a), compute_file_sha256(b))

    def test_file_hash_matches_standard_library_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "submission.txt"
            payload = b"deterministic evidence"
            p.write_bytes(payload)
            self.assertEqual(compute_file_sha256(p), hashlib.sha256(payload).hexdigest())

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            compute_file_sha256("/definitely/not/a/real/submission.tex")

    def test_same_normalized_text_produces_same_hash(self):
        a = normalize_for_similarity("We PROVE   the claim.")
        b = normalize_for_similarity("we prove the claim")
        self.assertEqual(compute_text_sha256(a), compute_text_sha256(b))

    def test_template_and_whitespace_changes_do_not_change_normalized_hash(self):
        a = r"""
        \documentclass{article}
        \author{Alice}
        \begin{document}
        Write your solution here.
        The runtime is \Theta(n \log n).
        \end{document}
        """
        b = "the runtime is theta n log n"
        self.assertEqual(
            compute_text_sha256(normalize_for_similarity(a)),
            compute_text_sha256(normalize_for_similarity(b)),
        )

    def test_text_hash_is_deterministic(self):
        text = "normalized deterministic text"
        self.assertEqual(compute_text_sha256(text), compute_text_sha256(text))

    def test_text_hash_rejects_none(self):
        with self.assertRaises(TypeError):
            compute_text_sha256(None)


if __name__ == "__main__":
    unittest.main()
