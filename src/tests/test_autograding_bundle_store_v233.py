"""v2.3.3 Commit 2 tests for immutable test-bundle storage."""

import json
from pathlib import Path
import tempfile
import unittest

from src.autograding import (
    BUNDLE_MANIFEST_FILENAME,
    BUNDLE_ORIGINALS_DIRECTORY,
    AutogradingBundleIntegrityError,
    StoredTestBundle,
    TestBundleStore,
    validate_test_bundle,
)


class TestAutogradingBundleStore(unittest.TestCase):

    def _write_bundle(self, root, answer="True", assessment_id="LAB1", version=None):
        root = Path(root)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        (root / "tests" / "test_basic.py").write_text(
            "def test_basic():\n    assert %s\n" % answer,
            encoding="utf-8",
        )
        config = {
            "schema_version": "1.0",
            "assessment_id": assessment_id,
            "max_points": 10,
            "tests": [
                {
                    "test_id": "test_basic",
                    "name": "Basic",
                    "points": 10,
                    "visibility": "public",
                }
            ],
            "metadata": ({"version": version} if version is not None else {}),
        }
        (root / "autograder.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
        return root

    def _store(self, workspace):
        ids = iter(["bundle_fixed_1", "bundle_fixed_2", "bundle_fixed_3"])
        times = iter([
            "2026-08-19T20:00:00Z",
            "2026-08-19T20:01:00Z",
            "2026-08-19T20:02:00Z",
        ])
        return TestBundleStore(
            workspace,
            bundle_id_factory=lambda: next(ids),
            now_fn=lambda: next(times),
        )

    def test_import_creates_immutable_manifest_and_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            workspace = base / "workspace"
            candidate = validate_test_bundle(source)
            store = self._store(workspace)
            result = store.import_bundle(source)

            self.assertTrue(result.created)
            bundle = result.bundle
            self.assertIsInstance(bundle, StoredTestBundle)
            self.assertEqual(bundle.reference.bundle_id, "bundle_fixed_1")
            self.assertEqual(bundle.reference.bundle_sha256, candidate.bundle_sha256)
            self.assertEqual(bundle.reference.config_sha256, candidate.config_sha256)
            self.assertTrue(Path(bundle.bundle_dir, BUNDLE_MANIFEST_FILENAME).is_file())
            self.assertTrue(
                Path(bundle.bundle_dir, BUNDLE_ORIGINALS_DIRECTORY, "autograder.json").is_file()
            )
            self.assertTrue(
                Path(bundle.original_path("tests/test_basic.py")).is_file()
            )
            self.assertTrue(store.verify_bundle(bundle))

    def test_reopen_store_loads_same_reference_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            workspace = base / "workspace"
            first_store = self._store(workspace)
            imported = first_store.import_bundle(source).bundle

            reopened = TestBundleStore(workspace, create=False)
            refs = reopened.list_bundle_references("LAB1")
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0], imported.reference)
            loaded = reopened.load_bundle("LAB1", imported.reference.bundle_id)
            self.assertEqual(loaded.reference, imported.reference)
            self.assertEqual(
                Path(loaded.original_path("tests/test_basic.py")).read_text(encoding="utf-8"),
                "def test_basic():\n    assert True\n",
            )

    def test_exact_reimport_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            first = store.import_bundle(source)
            second = store.import_bundle(source)

            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.bundle.reference.bundle_id, second.bundle.reference.bundle_id)
            self.assertEqual(len(store.list_bundle_references("LAB1")), 1)

    def test_changed_test_bytes_create_new_bundle_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            first = store.import_bundle(source).bundle
            (source / "tests" / "test_basic.py").write_text(
                "def test_basic():\n    assert 1 == 1\n", encoding="utf-8"
            )
            second = store.import_bundle(source).bundle

            self.assertNotEqual(first.reference.bundle_id, second.reference.bundle_id)
            self.assertNotEqual(first.reference.bundle_sha256, second.reference.bundle_sha256)
            self.assertEqual(len(store.list_bundle_references("LAB1")), 2)
            self.assertTrue(Path(first.original_path("tests/test_basic.py")).is_file())

    def test_source_mutation_after_import_does_not_change_committed_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            stored = Path(bundle.original_path("tests/test_basic.py"))
            before = stored.read_bytes()

            (source / "tests" / "test_basic.py").write_text(
                "def test_basic():\n    assert False\n", encoding="utf-8"
            )
            self.assertEqual(stored.read_bytes(), before)
            self.assertTrue(store.verify_bundle(bundle))

    def test_tampered_stored_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            stored = Path(bundle.original_path("tests/test_basic.py"))
            stored.chmod(0o644)
            stored.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleIntegrityError, "mismatch"):
                store.verify_bundle(bundle)

    def test_missing_stored_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            stored = Path(bundle.original_path("tests/test_basic.py"))
            stored.unlink()
            with self.assertRaises(AutogradingBundleIntegrityError):
                store.verify_bundle(bundle)

    def test_extra_unmanifested_original_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            extra = Path(bundle.bundle_dir) / "originals" / "support" / "extra.txt"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleIntegrityError, "extra"):
                store.verify_bundle(bundle)

    def test_manifest_config_tampering_is_detected_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            manifest = Path(bundle.bundle_dir) / "bundle.json"
            manifest.chmod(0o644)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["config"]["metadata"]["tampered"] = True
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            loaded = store.load_bundle("LAB1", bundle.reference.bundle_id, verify_hashes=False)
            with self.assertRaisesRegex(AutogradingBundleIntegrityError, "config SHA"):
                store.verify_bundle(loaded)


    def test_reference_config_sha_is_exact_original_config_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            expected = hashlib.sha256((source / "autograder.json").read_bytes()).hexdigest()
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
        self.assertEqual(bundle.reference.config_sha256, expected)

    def test_source_absolute_paths_are_not_persisted_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            manifest = Path(bundle.bundle_dir, "bundle.json").read_text(encoding="utf-8")
            self.assertNotIn(str(source.resolve()), manifest)
            self.assertNotIn('"source_path"', manifest)

    def test_manifest_reference_tampering_is_detected_against_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            manifest = Path(bundle.bundle_dir) / "bundle.json"
            manifest.chmod(0o644)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["reference"]["display_version"] = "tampered"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleIntegrityError, "index/reference"):
                store.load_bundle("LAB1", bundle.reference.bundle_id)

    def test_display_version_defaults_from_config_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source", version="2026.08.1")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
        self.assertEqual(bundle.reference.display_version, "2026.08.1")

    def test_explicit_display_version_overrides_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source", version="old")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source, display_version="release-candidate").bundle
        self.assertEqual(bundle.reference.display_version, "release-candidate")

    def test_assessments_have_separate_bundle_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source1 = self._write_bundle(base / "source1", assessment_id="LAB1")
            source2 = self._write_bundle(base / "source2", assessment_id="LAB2")
            store = self._store(base / "workspace")
            b1 = store.import_bundle(source1).bundle
            b2 = store.import_bundle(source2).bundle
            self.assertEqual(len(store.list_bundle_references("LAB1")), 1)
            self.assertEqual(len(store.list_bundle_references("LAB2")), 1)
            self.assertNotEqual(Path(b1.bundle_dir).parent.parent, Path(b2.bundle_dir).parent.parent)

    def test_find_by_fingerprint_returns_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._write_bundle(base / "source")
            store = self._store(base / "workspace")
            bundle = store.import_bundle(source).bundle
            found = store.find_by_fingerprint("LAB1", bundle.reference.bundle_sha256)
        self.assertEqual(found, bundle.reference)


if __name__ == "__main__":
    unittest.main()
