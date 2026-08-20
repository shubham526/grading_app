"""v2.3.3 Commit 2 tests for validated instructor test bundles."""

import json
from pathlib import Path
import tempfile
import unittest

from src.autograding import (
    AUTOGRADER_CONFIG_FILENAME,
    AutogradingBundleValidationError,
    AutogradingValidationError,
    BundleFile,
    ValidatedTestBundle,
    validate_test_bundle,
)


class TestAutogradingBundleValidation(unittest.TestCase):

    def _write_bundle(
        self,
        root,
        *,
        assessment_id="LAB1",
        tests=None,
        config_tests=None,
        metadata=None,
        requirements=None,
    ):
        root = Path(root)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        tests = tests or {
            "tests/test_public.py": "def test_basic():\n    assert True\n",
            "tests/test_hidden.py": "def test_hidden():\n    assert True\n",
        }
        for relative, text in tests.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        if config_tests is None:
            config_tests = [
                {
                    "test_id": "test_basic",
                    "name": "Basic",
                    "visibility": "public",
                    "points": 4,
                },
                {
                    "test_id": "test_hidden",
                    "name": "Hidden",
                    "visibility": "hidden",
                    "points": 6,
                },
            ]
        config = {
            "schema_version": "1.0",
            "assessment_id": assessment_id,
            "entrypoint": "submission.py",
            "max_points": 10,
            "tests": config_tests,
            "metadata": dict(metadata or {}),
        }
        (root / AUTOGRADER_CONFIG_FILENAME).write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )
        if requirements is not None:
            (root / "requirements.txt").write_text(requirements, encoding="utf-8")
        return root

    def test_valid_bundle_is_hashed_and_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(tmp)
            bundle = validate_test_bundle(root)

        self.assertIsInstance(bundle, ValidatedTestBundle)
        self.assertEqual(bundle.assessment_id, "LAB1")
        self.assertEqual(len(bundle.bundle_sha256), 64)
        self.assertEqual(len(bundle.config_sha256), 64)
        self.assertEqual(bundle.total_bytes, sum(item.size_bytes for item in bundle.files))
        by_path = {item.relative_path: item for item in bundle.files}
        self.assertEqual(by_path["autograder.json"].role, "config")
        self.assertEqual(by_path["tests/test_public.py"].role, "test")
        self.assertTrue(all(item.source_path for item in bundle.files))

    def test_explicit_pytest_node_ids_are_supported(self):
        config_tests = [
            {
                "test_id": "tests/test_public.py::test_basic",
                "name": "Basic",
                "visibility": "public",
                "points": 10,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={"tests/test_public.py": "def test_basic():\n    assert True\n"},
                config_tests=config_tests,
            )
            bundle = validate_test_bundle(root)
        self.assertEqual(bundle.config.tests[0].test_id, config_tests[0]["test_id"])

    def test_class_qualified_explicit_node_id_checks_final_function(self):
        config_tests = [
            {
                "test_id": "tests/test_public.py::TestCases::test_basic",
                "name": "Basic",
                "points": 10,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={
                    "tests/test_public.py": (
                        "class TestCases:\n"
                        "    def test_basic(self):\n"
                        "        assert True\n"
                    )
                },
                config_tests=config_tests,
            )
            bundle = validate_test_bundle(root)
        self.assertEqual(len(bundle.files), 2)


    def test_arbitrary_stable_test_id_can_map_through_pytest_nodeid_metadata(self):
        config_tests = [
            {
                "test_id": "edge_empty",
                "name": "Empty input",
                "points": 10,
                "metadata": {"pytest_nodeid": "tests/test_public.py::test_basic"},
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={"tests/test_public.py": "def test_basic():\n    assert True\n"},
                config_tests=config_tests,
            )
            bundle = validate_test_bundle(root)
        self.assertEqual(bundle.config.tests[0].test_id, "edge_empty")

    def test_parameterized_explicit_nodeid_resolves_base_function(self):
        config_tests = [
            {
                "test_id": "tests/test_public.py::test_basic[empty]",
                "name": "Empty parameter",
                "points": 10,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={"tests/test_public.py": "def test_basic():\n    assert True\n"},
                config_tests=config_tests,
            )
            bundle = validate_test_bundle(root)
        self.assertEqual(len(bundle.config.tests), 1)

    def test_missing_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_a.py").write_text(
                "def test_a():\n    pass\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(AutogradingBundleValidationError, "missing"):
                validate_test_bundle(root)

    def test_missing_tests_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "autograder.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "tests/"):
                validate_test_bundle(root)

    def test_test_directory_must_have_python_test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(tmp)
            for path in (root / "tests").glob("*.py"):
                path.unlink()
            (root / "tests" / "data.txt").write_text("fixture", encoding="utf-8")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "Python test"):
                validate_test_bundle(root)

    def test_unknown_config_test_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={"tests/test_a.py": "def test_actual():\n    pass\n"},
                config_tests=[{"test_id": "test_missing", "name": "M", "points": 10}],
            )
            with self.assertRaisesRegex(AutogradingBundleValidationError, "unknown pytest test"):
                validate_test_bundle(root)

    def test_undeclared_test_function_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={
                    "tests/test_a.py": (
                        "def test_basic():\n    pass\n\n"
                        "def test_forgotten():\n    pass\n"
                    )
                },
                config_tests=[{"test_id": "test_basic", "name": "B", "points": 10}],
            )
            with self.assertRaisesRegex(AutogradingBundleValidationError, "undeclared"):
                validate_test_bundle(root)

    def test_ambiguous_simple_test_id_requires_explicit_node_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={
                    "tests/test_a.py": "def test_same():\n    pass\n",
                    "tests/test_b.py": "def test_same():\n    pass\n",
                },
                config_tests=[{"test_id": "test_same", "name": "Same", "points": 10}],
            )
            with self.assertRaisesRegex(AutogradingBundleValidationError, "ambiguous"):
                validate_test_bundle(root)

    def test_explicit_node_id_unknown_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={"tests/test_a.py": "def test_a():\n    pass\n"},
                config_tests=[
                    {
                        "test_id": "tests/test_missing.py::test_a",
                        "name": "A",
                        "points": 10,
                    }
                ],
            )
            with self.assertRaisesRegex(AutogradingBundleValidationError, "unknown test file"):
                validate_test_bundle(root)

    def test_explicit_node_id_unknown_function_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                tests={"tests/test_a.py": "def test_a():\n    pass\n"},
                config_tests=[
                    {
                        "test_id": "tests/test_a.py::test_missing",
                        "name": "A",
                        "points": 10,
                    }
                ],
            )
            with self.assertRaisesRegex(AutogradingBundleValidationError, "unknown function"):
                validate_test_bundle(root)

    def test_expected_assessment_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(tmp, assessment_id="LAB1")
            with self.assertRaisesRegex(AutogradingBundleValidationError, "does not match"):
                validate_test_bundle(root, expected_assessment_id="LAB2")

    def test_config_point_errors_are_still_rejected_at_bundle_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(
                tmp,
                config_tests=[
                    {"test_id": "test_basic", "name": "B", "points": 1},
                    {"test_id": "test_hidden", "name": "H", "points": 1},
                ],
            )
            with self.assertRaises(AutogradingValidationError):
                validate_test_bundle(root)

    def test_support_and_safe_requirements_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(tmp, requirements="pytest==8.3.5\n# comment\nnumpy>=2\n")
            (root / "support").mkdir()
            (root / "support" / "helpers.py").write_text("VALUE = 3\n", encoding="utf-8")
            bundle = validate_test_bundle(root)
        roles = {item.relative_path: item.role for item in bundle.files}
        self.assertEqual(roles["support/helpers.py"], "support")
        self.assertEqual(roles["requirements.txt"], "requirements")

    def test_config_and_bundle_hashes_track_exact_bytes_while_normalized_hash_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_bundle(tmp)
            first = validate_test_bundle(root)
            payload = json.loads((root / "autograder.json").read_text(encoding="utf-8"))
            (root / "autograder.json").write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
            second = validate_test_bundle(root)
        self.assertNotEqual(first.config_sha256, second.config_sha256)
        self.assertNotEqual(first.bundle_sha256, second.bundle_sha256)
        self.assertEqual(
            first.metadata["normalized_config_sha256"],
            second.metadata["normalized_config_sha256"],
        )

    def test_bundle_file_and_validated_bundle_roundtrip_guards(self):
        item = BundleFile(
            relative_path="tests/test_a.py",
            role="test",
            size_bytes=3,
            sha256="a" * 64,
        )
        self.assertEqual(BundleFile.from_dict(item.to_dict()), item)
        with self.assertRaises(AutogradingBundleValidationError):
            BundleFile("../bad.py", "test", 1, "a" * 64)


if __name__ == "__main__":
    unittest.main()
