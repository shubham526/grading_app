"""Tests for v2.3.2 Commit 2 hardened submission filesystem helpers."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from src.submissions.file_store import (
    atomic_write_json,
    atomic_write_text,
    compute_file_sha256,
    copy_regular_file,
    read_json_object,
    safe_path_component,
    safe_storage_filename,
    sha256_json,
)


class TestSubmissionFileStoreV232(unittest.TestCase):

    def test_sha256_matches_known_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_bytes(b"abc")

            self.assertEqual(
                compute_file_sha256(str(path)),
                "ba7816bf8f01cfea414140de5dae2223"
                "b00361a396177a9cb410ff61f20015ad",
            )

    def test_sha256_json_is_key_order_independent(self):
        self.assertEqual(
            sha256_json({"a": 1, "b": 2}),
            sha256_json({"b": 2, "a": 1}),
        )

    def test_atomic_json_and_text_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "data.json"
            text_path = root / "data.txt"

            atomic_write_json(
                json_path,
                {"b": 2, "a": 1},
            )
            atomic_write_text(
                text_path,
                "hello",
            )

            self.assertEqual(
                read_json_object(json_path),
                {"a": 1, "b": 2},
            )
            self.assertEqual(
                text_path.read_text(encoding="utf-8"),
                "hello",
            )

    def test_atomic_write_can_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"

            atomic_write_json(
                path,
                {"value": 1},
                overwrite=False,
            )

            with self.assertRaises(FileExistsError):
                atomic_write_json(
                    path,
                    {"value": 2},
                    overwrite=False,
                )

            self.assertEqual(
                read_json_object(path),
                {"value": 1},
            )

    def test_copy_regular_file_default_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            target = root / "target.txt"

            source.write_text(
                "first",
                encoding="utf-8",
            )

            copied = copy_regular_file(
                str(source),
                target,
            )

            self.assertEqual(
                Path(copied).read_text(encoding="utf-8"),
                "first",
            )

            source.write_text(
                "second",
                encoding="utf-8",
            )

            with self.assertRaises(FileExistsError):
                copy_regular_file(
                    str(source),
                    target,
                )

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "first",
            )

    def test_copy_regular_file_can_preserve_legacy_overwrite_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            target = root / "target.txt"

            source.write_text("first", encoding="utf-8")
            copy_regular_file(str(source), target)

            source.write_text("second", encoding="utf-8")
            copy_regular_file(
                str(source),
                target,
                overwrite=True,
            )

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "second",
            )

    @unittest.skipUnless(
        hasattr(os, "symlink"),
        "OS does not support symlinks",
    )
    def test_symlink_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            link = root / "link.txt"

            source.write_text("x", encoding="utf-8")

            try:
                os.symlink(source, link)
            except OSError as exc:
                self.skipTest(
                    f"Cannot create symlink on this platform: {exc}"
                )

            with self.assertRaises(ValueError):
                compute_file_sha256(str(link))

            with self.assertRaises(ValueError):
                copy_regular_file(
                    str(link),
                    root / "copy.txt",
                )

    def test_safe_path_component_is_deterministic_and_collision_resistant(self):
        first = safe_path_component("Alice Smith")
        second = safe_path_component("Alice Smith")
        normalized_collision = safe_path_component("Alice/Smith")

        self.assertEqual(first, second)
        self.assertNotEqual(first, normalized_collision)
        self.assertNotIn("/", first)

    def test_safe_storage_filename_strips_path_components(self):
        self.assertEqual(
            safe_storage_filename("../../answer.py"),
            "answer.py",
        )
        self.assertEqual(
            safe_storage_filename(r"C:\temp\answer.py"),
            "answer.py",
        )

    def test_read_json_requires_object_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps([1, 2, 3]),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                read_json_object(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
