"""v2.3.4.2 Commit 1 tests for LaTeX-project ingestion configuration."""

import json
from pathlib import Path
import tempfile
import unittest

from src.submissions.latex_project import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_FILE_COUNT,
    DEFAULT_MAX_INCLUDE_DEPTH,
    DEFAULT_MAX_MEMBER_BYTES,
    DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES,
    DEFAULT_PREFERRED_ROOT_NAMES,
    LATEX_PROJECT_CONFIG_SCHEMA_VERSION,
    LatexProjectIngestionConfig,
    LatexProjectSafetyLimits,
    LatexProjectSerializationError,
    LatexProjectValidationError,
    UnsupportedLatexProjectSchemaError,
    load_latex_project_config,
    save_latex_project_config,
)


class TestLatexProjectConfigV2342(unittest.TestCase):

    def test_safe_defaults_are_bounded(self):
        config = LatexProjectIngestionConfig()
        self.assertEqual(config.limits.max_archive_bytes, DEFAULT_MAX_ARCHIVE_BYTES)
        self.assertEqual(
            config.limits.max_total_uncompressed_bytes,
            DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES,
        )
        self.assertEqual(config.limits.max_member_bytes, DEFAULT_MAX_MEMBER_BYTES)
        self.assertEqual(config.limits.max_file_count, DEFAULT_MAX_FILE_COUNT)
        self.assertEqual(
            config.limits.max_compression_ratio,
            DEFAULT_MAX_COMPRESSION_RATIO,
        )
        self.assertEqual(config.max_include_depth, DEFAULT_MAX_INCLUDE_DEPTH)
        self.assertEqual(config.preferred_root_names, DEFAULT_PREFERRED_ROOT_NAMES)

    def test_limits_reject_boolean_zero_fractional_or_infinite_values(self):
        invalid = (
            {"max_archive_bytes": 0},
            {"max_archive_bytes": True},
            {"max_file_count": 2.5},
            {"max_compression_ratio": 0},
            {"max_compression_ratio": float("inf")},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(LatexProjectValidationError):
                    LatexProjectSafetyLimits(**kwargs)

    def test_member_limit_cannot_exceed_total_limit(self):
        with self.assertRaisesRegex(
            LatexProjectValidationError,
            "must not exceed",
        ):
            LatexProjectSafetyLimits(
                max_member_bytes=20,
                max_total_uncompressed_bytes=10,
            )

    def test_unknown_limit_option_is_rejected(self):
        with self.assertRaisesRegex(LatexProjectValidationError, "Unsupported limit"):
            LatexProjectSafetyLimits.from_dict({"disable_path_checks": True})

    def test_preferred_roots_are_case_insensitively_unique_tex_basenames(self):
        config = LatexProjectIngestionConfig(
            preferred_root_names=("main.tex", "report.tex")
        )
        self.assertEqual(config.preferred_root_names, ("main.tex", "report.tex"))

        for roots in (
            ("main.tex", "MAIN.tex"),
            ("folder/main.tex",),
            ("main.pdf",),
        ):
            with self.subTest(roots=roots):
                with self.assertRaises(LatexProjectValidationError):
                    LatexProjectIngestionConfig(preferred_root_names=roots)

    def test_include_depth_must_be_positive_integer(self):
        for value in (0, -1, True, 2.5):
            with self.subTest(value=value):
                with self.assertRaises(LatexProjectValidationError):
                    LatexProjectIngestionConfig(max_include_depth=value)

    def test_config_roundtrip_is_schema_versioned_and_json_serializable(self):
        config = LatexProjectIngestionConfig(
            limits=LatexProjectSafetyLimits(
                max_archive_bytes=100,
                max_total_uncompressed_bytes=500,
                max_member_bytes=100,
                max_file_count=25,
                max_compression_ratio=50,
            ),
            preferred_root_names=("main.tex", "report.tex"),
            max_include_depth=20,
            metadata={"course": "CS2500"},
        )
        payload = config.to_dict()
        self.assertEqual(
            payload["schema_version"],
            LATEX_PROJECT_CONFIG_SCHEMA_VERSION,
        )
        json.dumps(payload)
        loaded = LatexProjectIngestionConfig.from_dict(payload)
        self.assertEqual(loaded, config)
        self.assertEqual(loaded.to_dict(), payload)

    def test_schema_version_1_integer_is_accepted_and_normalized(self):
        config = LatexProjectIngestionConfig.from_dict({"schema_version": 1})
        self.assertEqual(config.to_dict()["schema_version"], "1.0")

    def test_unsupported_config_schema_is_rejected(self):
        with self.assertRaises(UnsupportedLatexProjectSchemaError):
            LatexProjectIngestionConfig.from_dict({"schema_version": "2.0"})

    def test_unknown_top_level_or_resolution_options_are_rejected(self):
        with self.assertRaisesRegex(
            LatexProjectValidationError,
            "Unsupported LaTeX-project config",
        ):
            LatexProjectIngestionConfig.from_dict({"compile_latex": True})
        with self.assertRaisesRegex(
            LatexProjectValidationError,
            "Unsupported resolution",
        ):
            LatexProjectIngestionConfig.from_dict(
                {"resolution": {"silently_pick_first": True}}
            )

    def test_load_and_save_roundtrip_uses_deterministic_utf8_json(self):
        config = LatexProjectIngestionConfig(
            metadata={"label": "LaTeX – synthetic"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latex_project.json"
            saved = save_latex_project_config(config, path)
            self.assertEqual(saved, path.resolve())
            loaded = load_latex_project_config(path)
            self.assertEqual(loaded, config)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertIn('"schema_version": "1.0"', text)
            self.assertIn("LaTeX – synthetic", text)

    def test_malformed_json_raises_serialization_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latex_project.json"
            path.write_text("{ invalid", encoding="utf-8")
            with self.assertRaises(LatexProjectSerializationError):
                load_latex_project_config(path)

    def test_symlinked_config_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.json"
            real.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")
            with self.assertRaises(LatexProjectValidationError):
                load_latex_project_config(link)


if __name__ == "__main__":
    unittest.main()
