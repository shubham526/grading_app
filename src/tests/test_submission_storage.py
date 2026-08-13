"""Tests for persistent submission evidence and assessment metadata helpers."""

import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.submissions import (
    EVIDENCE_SCHEMA_VERSION,
    ParsedSubmission,
    assessment_submission_fields,
    compute_file_sha256,
    evidence_storage_paths,
    load_persisted_submission,
    parse_pdf_accommodation,
    parse_submission,
    persist_submission_evidence,
)


def _blank_pdf(path: Path, pages: int = 1):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=612, height=792)
    doc.save(str(path))
    doc.close()


class TestEvidenceStorage(unittest.TestCase):
    def test_sha256_matches_known_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_bytes(b"abc")
            self.assertEqual(
                compute_file_sha256(str(path)),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_storage_paths_normalize_student_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = evidence_storage_paths(tmp, "Alice Smith", create=True)
            self.assertEqual(Path(paths.student_dir).name, "alice_smith")
            self.assertTrue(Path(paths.pages_dir).is_dir())
            self.assertTrue(Path(paths.source_dir).is_dir())

    def test_pdf_accommodation_persists_authoritative_original_and_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf, pages=2)

            result = parse_pdf_accommodation(
                str(pdf),
                ["Q1", "Q2"],
                student_id="student",
                evidence_dir=str(evidence),
            )

            self.assertTrue(result.metadata["original_pdf_authoritative"])
            self.assertEqual(Path(result.files["pdf"]).name, "original.pdf")
            self.assertTrue(Path(result.files["pdf"]).is_file())
            self.assertTrue(result.evidence_metadata["persisted"])
            self.assertEqual(len(result.page_image_paths), 2)
            self.assertTrue(all(Path(path).is_file() for path in result.page_image_paths))
            self.assertTrue(all("/pages/" in path for path in result.page_image_paths))

            meta_path = Path(result.evidence_metadata["meta_path"])
            manifest = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], EVIDENCE_SCHEMA_VERSION)
            self.assertEqual(manifest["authoritative_source"], "original_pdf")
            self.assertIn("pdf_sha256", manifest["file_hashes"])
            self.assertIn("page_001_sha256", manifest["file_hashes"])
            self.assertNotIn("accommodation_reason", json.dumps(manifest).lower())
            self.assertNotIn("medical", json.dumps(manifest).lower())

    def test_roundtrip_load_requires_no_pdf_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf, pages=1)
            first = parse_pdf_accommodation(
                str(pdf),
                ["Q1"],
                student_id="student",
                evidence_dir=str(evidence),
            )

            loaded = load_persisted_submission(str(evidence), "student")
            self.assertEqual(loaded.student_id, first.student_id)
            self.assertEqual(loaded.submission_mode, "pdf_accommodation")
            self.assertTrue(loaded.accommodation_mode)
            self.assertEqual(loaded.files["pdf"], first.files["pdf"])
            self.assertEqual(loaded.page_image_paths, first.page_image_paths)
            self.assertTrue(loaded.evidence_metadata["loaded_from_persistence"])
            self.assertTrue(loaded.evidence_metadata["verification"]["ok"])

    def test_hash_mismatch_is_reported_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "scan.pdf"
            evidence = root / "evidence"
            _blank_pdf(pdf)
            result = parse_pdf_accommodation(
                str(pdf),
                student_id="student",
                evidence_dir=str(evidence),
            )
            Path(result.files["pdf"]).write_bytes(b"tampered")

            loaded = load_persisted_submission(str(evidence), "student")
            self.assertFalse(loaded.evidence_metadata["verification"]["ok"])
            self.assertIn("pdf_sha256", loaded.evidence_metadata["verification"]["mismatches"])
            self.assertIn("persisted_evidence_hash_mismatch:pdf_sha256", loaded.warnings)

    def test_latex_submission_is_persisted_without_requiring_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / "alice.tex"
            tex.write_text(
                "\\begin{document}\nQuestion 1\nAnswer A\n\\end{document}\n",
                encoding="utf-8",
            )
            evidence = root / "evidence"
            result = parse_submission(
                str(tex),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            self.assertEqual(Path(result.files["latex"]).name, "main.tex")
            self.assertEqual(result.answers_by_question, {"Q1": "Answer A"})
            self.assertIn("latex_sha256", result.evidence_metadata["file_hashes"])

            loaded = load_persisted_submission(str(evidence), result.student_id)
            self.assertEqual(loaded.answers_by_question, {"Q1": "Answer A"})
            self.assertEqual(loaded.raw_text, result.raw_text)

    def test_persist_function_does_not_mutate_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.tex"
            source.write_text("Question 1\nA", encoding="utf-8")
            parsed = ParsedSubmission(
                student_id="alice",
                source_used="latex",
                raw_text="Question 1\nA",
                answers_by_question={"Q1": "A"},
                files={"latex": str(source)},
            )
            persisted = persist_submission_evidence(parsed, str(root / "evidence"))
            self.assertEqual(parsed.files["latex"], str(source))
            self.assertNotIn("evidence", parsed.metadata)
            self.assertNotEqual(persisted.files["latex"], parsed.files["latex"])

    def test_assessment_fields_are_supporting_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / "alice.tex"
            tex.write_text("Question 1\nA", encoding="utf-8")
            result = parse_submission(
                str(tex),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(root / "evidence"),
            )
            fields = assessment_submission_fields(result)
            self.assertEqual(set(fields), {"submission_meta", "extracted_answers"})
            self.assertEqual(fields["extracted_answers"], {"Q1": "A"})
            self.assertIn("file_hashes", fields["submission_meta"])
            self.assertNotIn("points_awarded", fields["submission_meta"])
            self.assertNotIn("points_possible", fields["submission_meta"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
