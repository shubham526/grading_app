"""v2.3.3 Commit 2 security/regression tests for instructor test bundles."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from src.autograding import (
    AutogradingBundleIntegrityError,
    AutogradingBundleValidationError,
    TestBundleStore,
    validate_requirements_text,
    validate_test_bundle,
)


class TestAutogradingBundleSecurity(unittest.TestCase):

    def _bundle(self, root):
        root = Path(root)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        (root / "tests" / "test_basic.py").write_text(
            "def test_basic():\n    assert True\n", encoding="utf-8"
        )
        (root / "autograder.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "assessment_id": "LAB1",
                    "max_points": 10,
                    "tests": [
                        {"test_id": "test_basic", "name": "Basic", "points": 10}
                    ],
                }
            ),
            encoding="utf-8",
        )
        return root


    def test_common_os_metadata_files_are_ignored_not_committed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            (root / ".DS_Store").write_bytes(b"finder metadata")
            (root / "tests" / ".DS_Store").write_bytes(b"finder metadata")
            bundle = validate_test_bundle(root)
        paths = {item.relative_path for item in bundle.files}
        self.assertNotIn(".DS_Store", paths)
        self.assertNotIn("tests/.DS_Store", paths)

    def test_unknown_top_level_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            (root / ".env").write_text("TOKEN=secret", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "top-level"):
                validate_test_bundle(root)

    def test_virtualenv_or_cache_directory_is_rejected(self):
        for name in ("venv", ".pytest_cache", "__pycache__"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = self._bundle(tmp)
                (root / name).mkdir()
                with self.assertRaises(AutogradingBundleValidationError):
                    validate_test_bundle(root)

    def test_nested_hidden_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            (root / "tests" / ".secret").write_text("secret", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "hidden"):
                validate_test_bundle(root)

    def test_case_insensitive_path_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            upper = root / "support" / "Data.txt"
            lower = root / "support" / "data.txt"
            upper.parent.mkdir()
            upper.write_text("A", encoding="utf-8")
            try:
                lower.write_text("B", encoding="utf-8")
            except OSError:
                self.skipTest("filesystem does not permit case-distinct names")

            # pathlib.resolve() may preserve the caller's lexical case on macOS
            # even when APFS maps both names to the same inode. Ask the filesystem
            # directly whether these are the same object before expecting two
            # directory entries for the validator to compare.
            try:
                if os.path.samefile(str(upper), str(lower)):
                    self.skipTest("filesystem is case-insensitive")
            except OSError:
                pass

            with self.assertRaisesRegex(AutogradingBundleValidationError, "collision"):
                validate_test_bundle(root)


    def test_external_ancestor_symlink_is_allowed_for_selected_bundle(self):
        """OS/user path aliases above the selected root are not bundle symlinks."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real_parent = base / "real_parent"
            real_parent.mkdir()
            alias_parent = base / "alias_parent"
            try:
                alias_parent.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")

            root = self._bundle(alias_parent / "bundle")
            bundle = validate_test_bundle(root)

        self.assertEqual(bundle.assessment_id, "LAB1")
        self.assertIn(
            "tests/test_basic.py",
            {item.relative_path for item in bundle.files},
        )

    def test_external_ancestor_symlink_is_allowed_for_workspace(self):
        """A workspace reached through an external alias is resolved, not rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real_parent = base / "real_parent"
            real_parent.mkdir()
            alias_parent = base / "alias_parent"
            try:
                alias_parent.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")

            store = TestBundleStore(alias_parent / "workspace")

        self.assertTrue(store.workspace_root.endswith("real_parent/workspace"))

    def test_symlinked_internal_originals_directory_is_detected(self):
        """Symlinks inside the app-controlled committed tree remain forbidden."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._bundle(base / "source")
            store = TestBundleStore(base / "workspace")
            bundle = store.import_bundle(source).bundle
            bundle_dir = Path(bundle.bundle_dir)
            originals = bundle_dir / "originals"
            outside = base / "outside_originals"
            shutil_target = base / "saved_originals"
            originals.rename(shutil_target)
            outside.mkdir()
            try:
                originals.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                shutil_target.rename(originals)
                self.skipTest("symlinks unavailable")
            with self.assertRaises(AutogradingBundleIntegrityError):
                store.verify_bundle(bundle)

    def test_symlinked_bundle_index_is_detected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._bundle(base / "source")
            store = TestBundleStore(base / "workspace")
            stored = store.import_bundle(source).bundle
            index = (
                Path(store.root)
                / stored.reference.assessment_id.replace("/", "_")
            )
            # Use the repository's actual path rather than reconstructing the safe
            # component, which may contain a digest suffix.
            matches = list(Path(store.root).glob("*/bundles/index.json"))
            self.assertEqual(len(matches), 1)
            index_path = matches[0]
            outside = base / "outside_index.json"
            outside.write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8")
            index_path.unlink()
            try:
                index_path.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(AutogradingBundleIntegrityError):
                store.list_bundle_references("LAB1")

    def test_source_root_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real = self._bundle(base / "real")
            link = base / "bundle_link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "Symlink"):
                validate_test_bundle(link)

    def test_nested_symlink_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._bundle(base / "bundle")
            target = base / "outside.py"
            target.write_text("SECRET = True\n", encoding="utf-8")
            link = root / "support" / "outside.py"
            link.parent.mkdir()
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "Symlink"):
                validate_test_bundle(root)

    def test_requirements_reject_pip_options_urls_vcs_and_local_files(self):
        bad = (
            "-r other.txt",
            "--index-url https://example.org/simple",
            "pkg @ https://example.org/pkg.whl",
            "git+https://example.org/repo.git",
            "thing @ file:///tmp/thing",
            "thing @ ./local.whl",
            "../local.whl",
            "/tmp/local.whl",
        )
        for line in bad:
            with self.subTest(line=line):
                with self.assertRaises(AutogradingBundleValidationError):
                    validate_requirements_text(line)

    def test_requirements_allow_standard_pinned_specs(self):
        result = validate_requirements_text(
            "pytest==8.3.5\nnumpy>=2.0,<3\npackage[extra]~=1.4\n"
        )
        self.assertEqual(len(result), 3)

    def test_max_file_count_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            with self.assertRaisesRegex(AutogradingBundleValidationError, "file limit"):
                validate_test_bundle(root, max_files=1)

    def test_max_single_file_size_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            with self.assertRaisesRegex(AutogradingBundleValidationError, "exceeds"):
                validate_test_bundle(root, max_file_bytes=5)

    def test_max_total_size_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            with self.assertRaisesRegex(AutogradingBundleValidationError, "total-size"):
                validate_test_bundle(root, max_total_bytes=20)

    def test_boolean_or_nonpositive_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._bundle(tmp)
            for kwargs in (
                {"max_files": True},
                {"max_files": 0},
                {"max_file_bytes": -1},
                {"max_total_bytes": 0},
            ):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(AutogradingBundleValidationError):
                        validate_test_bundle(root, **kwargs)

    def test_symlinked_workspace_autograding_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            workspace.mkdir()
            outside = base / "outside"
            outside.mkdir()
            link = workspace / "autograding"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises((ValueError, AutogradingBundleValidationError)):
                TestBundleStore(workspace)

    def test_symlink_inserted_into_committed_originals_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._bundle(base / "source")
            store = TestBundleStore(base / "workspace")
            bundle = store.import_bundle(source).bundle
            target = Path(bundle.original_path("tests/test_basic.py"))
            target.unlink()
            outside = base / "outside.py"
            outside.write_text("def test_basic(): pass\n", encoding="utf-8")
            try:
                target.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(AutogradingBundleIntegrityError):
                store.verify_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
