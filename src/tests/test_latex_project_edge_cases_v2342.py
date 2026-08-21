"""Commit 8 edge-case hardening for Overleaf/LaTeX ZIP ingestion."""

from __future__ import annotations

from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

from src.submissions.latex_project import (
    LatexProjectArchiveRejectedError,
    LatexProjectIngestionConfig,
    LatexProjectSafetyLimits,
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_INVALID_PROJECT,
    ROOT_RESOLUTION_NO_ROOT_FOUND,
    ROOT_RESOLUTION_RESOLVED,
    discover_latex_project,
    inspect_latex_project_zip,
    safe_extract_latex_project_zip,
)
from src.tests.latex_project_v2342_hardening_support import (
    complete_document,
    discover_and_resolve,
    ingest_project,
    write_zip,
)


class TestLatexProjectEdgeCasesV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _preview(self, entries, name="project.zip"):
        return inspect_latex_project_zip(write_zip(self.root, name, entries))

    def test_empty_zip_is_invalid_project_not_crash(self):
        preview = self._preview([])
        self.assertEqual(preview.status, ROOT_RESOLUTION_INVALID_PROJECT)
        self.assertFalse(preview.is_valid)

    def test_non_zip_renamed_dot_zip_is_invalid_project(self):
        archive = self.root / "fake.zip"
        archive.write_bytes(b"not a zip archive")
        preview = inspect_latex_project_zip(archive)
        self.assertEqual(preview.status, ROOT_RESOLUTION_INVALID_PROJECT)
        self.assertIn("Invalid ZIP archive", preview.error_message)

    def test_zip_without_tex_is_invalid_project(self):
        preview = self._preview([
            ("README.txt", "nothing to compile"),
            ("figures/plot.png", b"opaque"),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_INVALID_PROJECT)
        codes = {item.get("code") for item in preview.diagnostics}
        self.assertIn("no_tex_sources", codes)

    def test_tex_without_complete_document_has_no_root(self):
        preview = self._preview([
            ("answer.tex", "Only an included fragment.\n"),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_NO_ROOT_FOUND)
        self.assertFalse(preview.is_valid)

    def test_deep_nested_root_resolves_with_full_relative_path(self):
        preview = self._preview([
            ("wrapper/submission/final/report.tex", complete_document("nested")),
            ("wrapper/submission/final/sections/q1.tex", "answer"),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(
            preview.root_relative_path,
            "wrapper/submission/final/report.tex",
        )

    def test_root_name_does_not_need_to_be_main_tex(self):
        preview = self._preview([
            ("submission.tex", complete_document("named submission")),
            ("main.tex", "fragment only"),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(preview.root_relative_path, "submission.tex")

    def test_spaces_unicode_and_utf8_content_survive_archive_and_discovery(self):
        root_name = "résumé project/final answer.tex"
        preview = self._preview([
            (root_name, complete_document("Café — naïve — Δ")),
            ("résumé project/sections/answer one.tex", "UTF-8 body — ✓\n"),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(preview.root_relative_path, root_name)

    def test_main_name_is_only_hint_when_two_roots_exist(self):
        preview = self._preview([
            ("main.tex", complete_document("main")),
            ("report.tex", complete_document("report")),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_AMBIGUOUS)
        self.assertIsNone(preview.root_relative_path)
        self.assertEqual(set(preview.candidate_paths), {"main.tex", "report.tex"})
        self.assertEqual(preview.metadata["preferred_name_hints"], ["main.tex"])

    def test_missing_include_is_diagnostic_but_root_remains_structurally_resolved(self):
        store, stored = ingest_project(self.root, [
            (
                "main.tex",
                complete_document("\\input{sections/missing}"),
            ),
        ])
        discovery, resolution = discover_and_resolve(stored)
        self.assertEqual(resolution.status, ROOT_RESOLUTION_RESOLVED)
        self.assertIn(
            "missing_include_reference",
            [item.code for item in discovery.diagnostics],
        )
        store.verify(stored)

    def test_cyclic_inputs_terminate_without_recursive_execution(self):
        _store, stored = ingest_project(self.root, [
            ("main.tex", complete_document("\\input{a}")),
            ("a.tex", "\\input{b}\n"),
            ("b.tex", "\\input{a}\n"),
        ])
        discovery = discover_latex_project(stored.extracted_root, stored.manifest)
        self.assertEqual(discovery.document_candidate_paths, ("main.tex",))
        self.assertEqual(set(discovery.included_tex_paths), {"a.tex", "b.tex"})

    def test_duplicate_and_commented_inputs_do_not_create_extra_candidates(self):
        _store, stored = ingest_project(self.root, [
            (
                "main.tex",
                complete_document(
                    "% \\input{ignored}\n\\input{part}\n\\input{part}\n"
                ),
            ),
            ("part.tex", "body\n"),
            ("ignored.tex", complete_document("must remain orphan")),
        ])
        discovery = discover_latex_project(stored.extracted_root, stored.manifest)
        # ignored.tex is a genuine complete document despite the commented input,
        # therefore ambiguity is structural rather than caused by the comment.
        self.assertEqual(
            set(discovery.document_candidate_paths),
            {"main.tex", "ignored.tex"},
        )
        main = discovery.source_by_path("main.tex")
        self.assertEqual(len(main.references), 2)
        self.assertTrue(all(ref.resolved_relative_path == "part.tex" for ref in main.references))

    def test_macos_noise_does_not_create_false_tex_candidates(self):
        preview = self._preview([
            ("project/main.tex", complete_document("clean")),
            ("__MACOSX/project/._main.tex", complete_document("metadata")),
            ("project/.DS_Store", b"finder"),
        ])
        self.assertEqual(preview.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(preview.root_relative_path, "project/main.tex")
        self.assertEqual(preview.tex_source_count, 1)

    def test_exact_duplicate_member_names_are_rejected(self):
        archive = self.root / "duplicate.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("main.tex", complete_document("first"))
                zf.writestr("main.tex", complete_document("second"))
        with self.assertRaises(LatexProjectArchiveRejectedError) as raised:
            safe_extract_latex_project_zip(
                archive,
                self.root / "out_duplicate",
                "lproj-duplicate",
            )
        self.assertEqual(raised.exception.diagnostics[0].code, "duplicate_member_path")

    def test_file_directory_conflict_is_rejected_before_extraction(self):
        archive = self.root / "conflict.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("parts", b"regular file")
            zf.writestr("parts/q1.tex", b"nested")
        with self.assertRaises(LatexProjectArchiveRejectedError) as raised:
            safe_extract_latex_project_zip(
                archive,
                self.root / "out_conflict",
                "lproj-conflict",
            )
        self.assertEqual(raised.exception.diagnostics[0].code, "file_directory_conflict")

    def test_link_member_in_nested_wrapper_is_rejected(self):
        info = zipfile.ZipInfo("wrapper/linked.tex")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(info, "../main.tex")
        preview = inspect_latex_project_zip(archive)
        self.assertEqual(preview.status, ROOT_RESOLUTION_INVALID_PROJECT)
        self.assertIn(
            "archive_link_rejected",
            {item.get("code") for item in preview.diagnostics},
        )

    def test_resource_limits_fail_closed_during_preview(self):
        archive = write_zip(
            self.root,
            "limits.zip",
            [
                ("main.tex", complete_document("A" * 2000)),
                ("part.tex", "B" * 2000),
            ],
        )
        configs = (
            LatexProjectIngestionConfig(
                limits=LatexProjectSafetyLimits(max_file_count=1)
            ),
            LatexProjectIngestionConfig(
                limits=LatexProjectSafetyLimits(max_member_bytes=100)
            ),
            LatexProjectIngestionConfig(
                limits=LatexProjectSafetyLimits(
                    max_member_bytes=100,
                    max_total_uncompressed_bytes=100,
                )
            ),
            LatexProjectIngestionConfig(
                limits=LatexProjectSafetyLimits(max_compression_ratio=1.1)
            ),
        )
        for config in configs:
            with self.subTest(config=config):
                preview = inspect_latex_project_zip(archive, config=config)
                self.assertEqual(preview.status, ROOT_RESOLUTION_INVALID_PROJECT)
                self.assertFalse(preview.is_valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
