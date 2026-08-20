"""Tests for v2.3.4.2 Commit 2 safe ZIP inspection/extraction."""

import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from src.submissions.latex_project import (
    FILE_ROLE_BIBLIOGRAPHY,
    FILE_ROLE_FIGURE,
    FILE_ROLE_TEX_SOURCE,
    LatexProjectArchiveRejectedError,
    LatexProjectIngestionConfig,
    LatexProjectSafetyLimits,
    compute_manifest_sha256,
    safe_extract_latex_project_zip,
)


class TestSafeLatexProjectZipExtractionV2342(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _zip(self, name="project.zip", entries=None, compression=zipfile.ZIP_DEFLATED):
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=compression) as zf:
            for member_name, data in entries or ():
                if isinstance(member_name, zipfile.ZipInfo):
                    zf.writestr(member_name, data)
                else:
                    zf.writestr(member_name, data)
        return path

    def _extract(self, archive, config=None, dirname="out"):
        destination = self.root / dirname
        return safe_extract_latex_project_zip(
            archive,
            destination,
            "lproj_test",
            config=config,
        ), destination

    def _assert_rejected_code(self, archive, expected_code, config=None):
        with self.assertRaises(LatexProjectArchiveRejectedError) as ctx:
            self._extract(archive, config=config)
        self.assertTrue(ctx.exception.diagnostics)
        self.assertEqual(ctx.exception.diagnostics[0].code, expected_code)

    def test_valid_project_extracts_regular_files_and_builds_hashed_manifest(self):
        archive = self._zip(
            entries=[
                ("main.tex", b"\\documentclass{article}\\begin{document}Hi\\end{document}"),
                ("sections/q1.tex", b"Answer 1"),
                ("refs.bib", b"@article{x}"),
                ("figures/plot.png", b"not-a-real-png-but-opaque-input"),
            ]
        )
        summary, destination = self._extract(archive)

        self.assertEqual(summary.zip_member_count, 4)
        self.assertEqual(summary.regular_member_count, 4)
        self.assertEqual(summary.ignored_members, ())
        self.assertEqual(summary.manifest.file_count, 4)
        self.assertEqual(
            compute_manifest_sha256(summary.manifest),
            summary.manifest.manifest_sha256,
        )
        self.assertEqual(
            summary.manifest.file_by_path("main.tex").role,
            FILE_ROLE_TEX_SOURCE,
        )
        self.assertEqual(
            summary.manifest.file_by_path("refs.bib").role,
            FILE_ROLE_BIBLIOGRAPHY,
        )
        self.assertEqual(
            summary.manifest.file_by_path("figures/plot.png").role,
            FILE_ROLE_FIGURE,
        )
        self.assertEqual((destination / "sections" / "q1.tex").read_bytes(), b"Answer 1")

    def test_macos_and_metadata_noise_is_not_materialized_but_still_counted(self):
        archive = self._zip(
            entries=[
                ("main.tex", b"body"),
                (".DS_Store", b"finder"),
                ("__MACOSX/._main.tex", b"metadata"),
            ]
        )
        summary, destination = self._extract(archive)
        self.assertEqual(summary.regular_member_count, 3)
        self.assertEqual(
            summary.ignored_members,
            (".DS_Store", "__MACOSX/._main.tex"),
        )
        self.assertEqual(summary.manifest.file_count, 1)
        self.assertFalse((destination / ".DS_Store").exists())
        self.assertFalse((destination / "__MACOSX").exists())

    def test_parent_traversal_is_rejected(self):
        archive = self._zip(entries=[("../escape.tex", b"bad")])
        self._assert_rejected_code(archive, "unsafe_member_path")
        self.assertFalse((self.root / "escape.tex").exists())

    def test_absolute_and_windows_drive_paths_are_rejected(self):
        for index, member in enumerate(("/absolute.tex", "C:\\absolute.tex")):
            archive = self._zip("unsafe%d.zip" % index, entries=[(member, b"bad")])
            self._assert_rejected_code(
                archive,
                "unsafe_member_path",
                config=None,
            )
            shutil_target = self.root / "out"
            if shutil_target.exists():
                import shutil
                shutil.rmtree(str(shutil_target))

    def test_symlink_member_is_rejected_before_writing_project_bytes(self):
        info = zipfile.ZipInfo("linked.tex")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self._zip(entries=[(info, "main.tex")])
        self._assert_rejected_code(archive, "archive_link_rejected")
        self.assertFalse((self.root / "out" / "linked.tex").exists())

    def test_special_unix_member_is_rejected(self):
        info = zipfile.ZipInfo("pipe")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o600) << 16
        archive = self._zip(entries=[(info, b"")])
        self._assert_rejected_code(archive, "archive_special_file_rejected")

    def test_case_colliding_member_paths_are_rejected_portably(self):
        archive = self._zip(entries=[("A.tex", b"a"), ("a.tex", b"b")])
        self._assert_rejected_code(archive, "duplicate_member_path")

    def test_backslash_normalization_collision_is_rejected(self):
        archive = self._zip(entries=[("parts\\q1.tex", b"a"), ("parts/q1.tex", b"b")])
        self._assert_rejected_code(archive, "duplicate_member_path")


    def test_windows_reserved_and_nonportable_names_are_rejected(self):
        for index, member in enumerate(("CON.tex", "folder/name:stream.tex", "bad?.tex", "trail. ")):
            archive = self._zip("portable%d.zip" % index, entries=[(member, b"bad")])
            self._assert_rejected_code(archive, "unsafe_member_path")
            out = self.root / "out"
            if out.exists():
                import shutil
                shutil.rmtree(str(out))

    def test_unicode_normalization_collisions_are_rejected_portably(self):
        composed = "caf\u00e9.tex"
        decomposed = "cafe\u0301.tex"
        archive = self._zip(entries=[(composed, b"a"), (decomposed, b"b")])
        self._assert_rejected_code(archive, "duplicate_member_path")

    def test_file_count_limit_is_enforced(self):
        archive = self._zip(entries=[("a.tex", b"a"), ("b.tex", b"b")])
        config = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(max_file_count=1)
        )
        self._assert_rejected_code(archive, "file_count_limit_exceeded", config=config)

    def test_per_member_and_total_uncompressed_limits_are_enforced(self):
        archive = self._zip(entries=[("a.tex", b"12345"), ("b.tex", b"67890")])
        config_member = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(
                max_member_bytes=4,
                max_total_uncompressed_bytes=20,
            )
        )
        self._assert_rejected_code(
            archive,
            "member_size_limit_exceeded",
            config=config_member,
        )

        config_total = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(
                max_member_bytes=6,
                max_total_uncompressed_bytes=9,
            )
        )
        self._assert_rejected_code(
            archive,
            "total_size_limit_exceeded",
            config=config_total,
        )

    def test_archive_byte_limit_is_enforced_before_zip_processing(self):
        archive = self._zip(entries=[("main.tex", b"hello")], compression=zipfile.ZIP_STORED)
        config = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(max_archive_bytes=10)
        )
        self._assert_rejected_code(
            archive,
            "archive_size_limit_exceeded",
            config=config,
        )

    def test_compression_ratio_limit_is_enforced(self):
        archive = self._zip(entries=[("main.tex", b"0" * 10000)])
        config = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(max_compression_ratio=2.0)
        )
        self._assert_rejected_code(
            archive,
            "compression_ratio_limit_exceeded",
            config=config,
        )

    def test_corrupt_non_zip_is_rejected(self):
        archive = self.root / "not-a-zip.zip"
        archive.write_bytes(b"definitely not a zip")
        self._assert_rejected_code(archive, "invalid_zip")

    def test_nonempty_destination_is_rejected_without_overwriting(self):
        archive = self._zip(entries=[("main.tex", b"ok")])
        destination = self.root / "out"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            safe_extract_latex_project_zip(
                archive,
                destination,
                "lproj_test",
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlinked_archive_path_is_rejected(self):
        archive = self._zip(entries=[("main.tex", b"ok")])
        link = self.root / "link.zip"
        try:
            link.symlink_to(archive)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        self._assert_rejected_code(link, "archive_symlink_rejected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
