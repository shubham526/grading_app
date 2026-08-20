"""Tests for v2.3.4.2 Commit 2 immutable LaTeX-project storage."""

from pathlib import Path
import os
import tempfile
import unittest
import zipfile

from src.submissions.latex_project import (
    ARCHIVE_VALIDATION_VALID,
    LatexProjectArchiveRejectedError,
    LatexProjectArchiveStore,
    LatexProjectIngestionConfig,
    LatexProjectIntegrityError,
    LatexProjectSafetyLimits,
    LatexProjectStorageError,
)


class TestLatexProjectArchiveStoreV2342(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "incoming"
        self.source_dir.mkdir()
        self.store = LatexProjectArchiveStore(self.root / "store")

    def tearDown(self):
        self.temp.cleanup()

    def _zip(self, name="student-overleaf.zip", entries=None):
        path = self.source_dir / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for member, data in entries or [("main.tex", b"hello")]:
                zf.writestr(member, data)
        return path

    def test_ingest_preserves_exact_original_and_verified_extracted_bytes(self):
        source = self._zip(
            entries=[
                ("main.tex", b"\\input{sections/q1}"),
                ("sections/q1.tex", b"answer"),
            ]
        )
        original_bytes = source.read_bytes()
        stored = self.store.ingest_zip(
            source,
            "artifact_source_1",
            project_id="lproj_storage_test",
            imported_at="2026-08-20T20:00:00Z",
        )

        self.assertEqual(Path(stored.original_archive_path).read_bytes(), original_bytes)
        self.assertEqual(stored.archive.validation_status, ARCHIVE_VALIDATION_VALID)
        self.assertEqual(stored.archive.original_filename, "student-overleaf.zip")
        self.assertEqual(stored.archive.source_artifact_id, "artifact_source_1")
        self.assertEqual(stored.manifest.file_count, 2)
        self.assertEqual(
            (Path(stored.extracted_root) / "sections" / "q1.tex").read_bytes(),
            b"answer",
        )
        self.assertTrue(self.store.verify(stored))

    def test_archive_size_limit_rejects_before_publishing_storage(self):
        source = self._zip("too-large.zip", [("main.tex", b"hello")])
        config = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(max_archive_bytes=10)
        )
        with self.assertRaises(LatexProjectArchiveRejectedError) as ctx:
            self.store.ingest_zip(
                source,
                "artifact",
                config=config,
                project_id="too-large",
            )
        self.assertEqual(
            ctx.exception.diagnostics[0].code,
            "archive_size_limit_exceeded",
        )
        self.assertFalse(self.store.project_dir("too-large").exists())
        self.assertEqual(
            [p for p in Path(self.store.storage_root).iterdir() if p.name.startswith(".latex-project-")],
            [],
        )

    def test_same_project_id_cannot_be_overwritten(self):
        first = self._zip("first.zip", [("main.tex", b"first")])
        self.store.ingest_zip(first, "artifact1", project_id="fixed-project")
        second = self._zip("second.zip", [("main.tex", b"second")])
        with self.assertRaises(FileExistsError):
            self.store.ingest_zip(second, "artifact2", project_id="fixed-project")
        loaded = self.store.load("fixed-project")
        self.assertEqual((Path(loaded.extracted_root) / "main.tex").read_bytes(), b"first")

    def test_rejected_archive_leaves_no_partial_published_project_or_staging_dir(self):
        source = self._zip("unsafe.zip", [("../escape.tex", b"bad")])
        with self.assertRaises(LatexProjectArchiveRejectedError):
            self.store.ingest_zip(source, "artifact", project_id="unsafe-project")
        self.assertFalse(self.store.project_dir("unsafe-project").exists())
        leftovers = [
            path for path in Path(self.store.storage_root).iterdir()
            if path.name.startswith(".latex-project-")
        ]
        self.assertEqual(leftovers, [])
        self.assertFalse((self.root / "escape.tex").exists())

    def test_tampered_original_archive_is_detected(self):
        stored = self.store.ingest_zip(
            self._zip(),
            "artifact",
            project_id="tamper-archive",
        )
        Path(stored.original_archive_path).write_bytes(b"tampered")
        with self.assertRaises(LatexProjectIntegrityError):
            self.store.load("tamper-archive", verify=True)

    def test_tampered_extracted_file_is_detected(self):
        stored = self.store.ingest_zip(
            self._zip(),
            "artifact",
            project_id="tamper-file",
        )
        (Path(stored.extracted_root) / "main.tex").write_text(
            "changed",
            encoding="utf-8",
        )
        with self.assertRaises(LatexProjectIntegrityError):
            self.store.load("tamper-file", verify=True)

    def test_unexpected_extra_file_is_detected(self):
        stored = self.store.ingest_zip(
            self._zip(),
            "artifact",
            project_id="extra-file",
        )
        (Path(stored.extracted_root) / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaises(LatexProjectIntegrityError):
            self.store.load("extra-file", verify=True)

    def test_manifest_metadata_tampering_is_detected_by_manifest_digest(self):
        stored = self.store.ingest_zip(
            self._zip(),
            "artifact",
            project_id="tamper-manifest",
        )
        import json
        manifest_path = Path(stored.manifest_path)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["metadata"]["zip_member_count"] = 999
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(LatexProjectIntegrityError):
            self.store.load("tamper-manifest", verify=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_inserted_into_extracted_tree_is_detected(self):
        stored = self.store.ingest_zip(
            self._zip(),
            "artifact",
            project_id="tamper-symlink",
        )
        target = Path(stored.extracted_root) / "main.tex"
        external = self.root / "outside.tex"
        external.write_text("outside", encoding="utf-8")
        try:
            target.unlink()
            target.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(LatexProjectIntegrityError):
            self.store.load("tamper-symlink", verify=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlinked_source_archive_is_rejected_before_storage(self):
        source = self._zip()
        link = self.source_dir / "source-link.zip"
        try:
            link.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(LatexProjectStorageError):
            self.store.ingest_zip(link, "artifact", project_id="source-link")
        self.assertFalse(self.store.project_dir("source-link").exists())

    def test_load_without_verification_is_available_for_metadata_only_callers(self):
        self.store.ingest_zip(
            self._zip(),
            "artifact",
            project_id="metadata-only",
        )
        stored = self.store.load("metadata-only", verify=False)
        self.assertEqual(stored.project_id, "metadata-only")
        self.assertEqual(stored.manifest.file_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
