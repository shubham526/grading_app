"""v2.3.3 Commit 1 tests for programming-autograder configuration."""

import json
from pathlib import Path
import tempfile
import unittest

from src.autograding import (
    AUTOGRADING_CONFIG_SCHEMA_VERSION,
    SCORING_METHOD_EQUAL_WITHIN_GROUP,
    SCORING_METHOD_EXPLICIT_TEST_POINTS,
    AutogradingConfig,
    AutogradingSerializationError,
    AutogradingValidationError,
    ResourceLimits,
    TestDefinition,
    TestGroup,
    UnsupportedAutogradingLanguageError,
    UnsupportedAutogradingRunnerError,
    UnsupportedAutogradingSchemaError,
    load_autograding_config,
    save_autograding_config,
)


class TestAutogradingConfig(unittest.TestCase):

    def test_minimal_explicit_points_config_derives_max_points(self):
        config = AutogradingConfig.from_dict(
            {
                "schema_version": "1.0",
                "assessment_id": "LAB1",
                "entrypoint": "submission.py",
                "tests": [
                    {
                        "test_id": "test_basic",
                        "name": "Basic",
                        "visibility": "public",
                        "points": 4,
                    },
                    {
                        "test_id": "test_hidden",
                        "name": "Hidden edge",
                        "visibility": "hidden",
                        "points": 6,
                    },
                ],
            }
        )
        self.assertEqual(config.max_points, 10)
        self.assertEqual(config.required_files, ("submission.py",))
        self.assertEqual(config.language, "python")
        self.assertEqual(config.runner_type, "pytest")
        self.assertEqual(config.scoring_method, SCORING_METHOD_EXPLICIT_TEST_POINTS)

    def test_explicit_group_points_must_reconcile(self):
        config = AutogradingConfig(
            assessment_id="LAB1",
            max_points=10,
            groups=(
                TestGroup("correctness", "Correctness", 6),
                TestGroup("edge", "Edge Cases", 4),
            ),
            tests=(
                TestDefinition("t1", "Basic", "correctness", points=2),
                TestDefinition("t2", "More", "correctness", points=4),
                TestDefinition("t3", "Edge", "edge", points=4),
            ),
        )
        self.assertEqual(config.tests_for_group("correctness")[1].test_id, "t2")
        self.assertEqual(config.group_by_id("edge").points, 4)
        self.assertEqual(config.test_by_id("t3").name, "Edge")

    def test_equal_within_group_accepts_omitted_test_points(self):
        config = AutogradingConfig(
            assessment_id="LAB1",
            max_points=10,
            groups=(TestGroup("correctness", "Correctness", 10),),
            tests=(
                TestDefinition("t1", "A", "correctness"),
                TestDefinition("t2", "B", "correctness"),
            ),
            scoring_method=SCORING_METHOD_EQUAL_WITHIN_GROUP,
        )
        self.assertEqual(config.max_points, 10)

    def test_equal_within_group_rejects_explicit_test_points(self):
        with self.assertRaises(AutogradingValidationError):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=10,
                groups=(TestGroup("g", "Group", 10),),
                tests=(TestDefinition("t", "T", "g", points=10),),
                scoring_method=SCORING_METHOD_EQUAL_WITHIN_GROUP,
            )

    def test_duplicate_test_ids_are_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "test_id"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=2,
                tests=(
                    TestDefinition("same", "A", points=1),
                    TestDefinition("same", "B", points=1),
                ),
            )

    def test_duplicate_group_ids_are_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "group_id"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=2,
                groups=(
                    TestGroup("same", "A", 1),
                    TestGroup("same", "B", 1),
                ),
                tests=(TestDefinition("t", "T", "same", points=1),),
            )

    def test_unknown_group_reference_is_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "unknown group_id"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=1,
                groups=(TestGroup("known", "Known", 1),),
                tests=(TestDefinition("t", "T", "missing", points=1),),
            )

    def test_empty_configured_group_is_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "at least one test"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=2,
                groups=(
                    TestGroup("g1", "One", 1),
                    TestGroup("g2", "Two", 1),
                ),
                tests=(TestDefinition("t", "T", "g1", points=1),),
            )

    def test_test_total_mismatch_is_rejected_without_groups(self):
        with self.assertRaisesRegex(AutogradingValidationError, "sum"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=10,
                tests=(TestDefinition("t", "T", points=9),),
            )

    def test_group_total_mismatch_is_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "group points sum"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=10,
                groups=(TestGroup("g", "G", 9),),
                tests=(TestDefinition("t", "T", "g", points=9),),
            )

    def test_group_internal_test_total_mismatch_is_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "test points in group"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=10,
                groups=(TestGroup("g", "G", 10),),
                tests=(TestDefinition("t", "T", "g", points=9),),
            )

    def test_unsupported_language_and_runner_are_specific_errors(self):
        with self.assertRaises(UnsupportedAutogradingLanguageError):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=1,
                tests=(TestDefinition("t", "T", points=1),),
                language="javascript",
            )
        with self.assertRaises(UnsupportedAutogradingRunnerError):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=1,
                tests=(TestDefinition("t", "T", points=1),),
                runner_type="unittest",
            )

    def test_entrypoint_and_required_files_are_normalized(self):
        config = AutogradingConfig(
            assessment_id="LAB1",
            max_points=1,
            tests=(TestDefinition("t", "T", points=1),),
            entrypoint="src\\submission.py",
            required_files=("data/input.txt",),
        )
        self.assertEqual(config.entrypoint, "src/submission.py")
        self.assertEqual(
            config.required_files,
            ("src/submission.py", "data/input.txt"),
        )

    def test_unsafe_paths_are_rejected(self):
        unsafe = (
            "../submission.py",
            "/tmp/submission.py",
            "C:\\temp\\submission.py",
            "src/../../submission.py",
        )
        for path in unsafe:
            with self.subTest(path=path):
                with self.assertRaises(AutogradingValidationError):
                    AutogradingConfig(
                        assessment_id="LAB1",
                        max_points=1,
                        tests=(TestDefinition("t", "T", points=1),),
                        entrypoint=path,
                    )

    def test_duplicate_required_files_after_normalization_are_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "duplicate"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=1,
                tests=(TestDefinition("t", "T", points=1),),
                required_files=("data\\input.txt", "data/input.txt"),
            )

    def test_reporting_policy_defaults_are_security_conservative(self):
        config = AutogradingConfig(
            assessment_id="LAB1",
            max_points=1,
            tests=(TestDefinition("t", "T", points=1),),
        )
        self.assertTrue(config.reporting_policy["show_public_test_details"])
        self.assertFalse(
            config.reporting_policy["show_hidden_test_names_to_students"]
        )

    def test_unknown_reporting_option_is_rejected(self):
        with self.assertRaisesRegex(AutogradingValidationError, "Unsupported reporting"):
            AutogradingConfig(
                assessment_id="LAB1",
                max_points=1,
                tests=(TestDefinition("t", "T", points=1),),
                reporting_policy={"typo": True},
            )

    def test_config_roundtrip_is_json_serializable_and_schema_versioned(self):
        config = AutogradingConfig(
            assessment_id="LAB1",
            max_points=10,
            groups=(TestGroup("g", "Correctness", 10),),
            tests=(
                TestDefinition(
                    "tests/public/test_basic.py::test_empty",
                    "Empty input",
                    "g",
                    visibility="public",
                    points=10,
                    timeout_seconds=2,
                ),
            ),
            resource_limits=ResourceLimits(
                wall_timeout_seconds=20,
                memory_mb=256,
                cpu_count=1,
                network_enabled=False,
            ),
            metadata={"course": "CS2580"},
        )
        payload = config.to_dict()
        self.assertEqual(
            payload["schema_version"],
            AUTOGRADING_CONFIG_SCHEMA_VERSION,
        )
        json.dumps(payload)
        loaded = AutogradingConfig.from_dict(payload)
        self.assertEqual(loaded.to_dict(), payload)

    def test_schema_version_1_integer_is_accepted_and_normalized(self):
        payload = {
            "schema_version": 1,
            "assessment_id": "LAB1",
            "tests": [{"test_id": "t", "name": "T", "points": 1}],
        }
        config = AutogradingConfig.from_dict(payload)
        self.assertEqual(config.to_dict()["schema_version"], "1.0")

    def test_unsupported_config_schema_is_rejected(self):
        with self.assertRaises(UnsupportedAutogradingSchemaError):
            AutogradingConfig.from_dict(
                {
                    "schema_version": "2.0",
                    "assessment_id": "LAB1",
                    "tests": [{"test_id": "t", "name": "T", "points": 1}],
                }
            )

    def test_load_and_save_roundtrip_uses_deterministic_json(self):
        config = AutogradingConfig(
            assessment_id="LAB1",
            max_points=2,
            tests=(TestDefinition("t", "T", points=2),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autograder.json"
            saved = save_autograding_config(config, path)
            self.assertEqual(saved, path.resolve())
            loaded = load_autograding_config(path)
            self.assertEqual(loaded, config)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertIn('"schema_version": "1.0"', text)

    def test_malformed_json_raises_serialization_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autograder.json"
            path.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(AutogradingSerializationError):
                load_autograding_config(path)

    def test_symlinked_config_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.json"
            real.write_text(
                json.dumps(
                    {
                        "assessment_id": "LAB1",
                        "tests": [{"test_id": "t", "name": "T", "points": 1}],
                    }
                ),
                encoding="utf-8",
            )
            link = root / "link.json"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")
            with self.assertRaises(AutogradingValidationError):
                load_autograding_config(link)


if __name__ == "__main__":
    unittest.main()
