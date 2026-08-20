"""Static safety/compatibility gates for v2.3.4.2 Commit 2."""

import ast
from pathlib import Path
import re
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "submissions" / "latex_project"
_PRODUCTION = [
    _PACKAGE / "errors.py",
    _PACKAGE / "models.py",
    _PACKAGE / "config.py",
    _PACKAGE / "archive.py",
    _PACKAGE / "storage.py",
    _PACKAGE / "__init__.py",
]


class TestLatexProjectCommit2SourceV2342(unittest.TestCase):
    def test_changed_package_remains_python39_grammar_compatible(self):
        for path in _PRODUCTION:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=(3, 9))

    def test_archive_layer_never_uses_zipfile_extract_helpers(self):
        source = (_PACKAGE / "archive.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\.extract(?:all)?\s*\(", source))

    def test_commit2_has_no_execution_or_latex_compilation_surface(self):
        joined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (_PACKAGE / "archive.py", _PACKAGE / "storage.py")
        ).lower()
        for forbidden in (
            "import subprocess",
            "from subprocess",
            "os.system(",
            "popen(",
            "shell=true",
            "pdflatex",
            "xelatex",
            "lualatex",
            "shell-escape",
        ):
            self.assertNotIn(forbidden, joined)

    def test_safety_rules_are_not_exposed_as_allow_unsafe_flags(self):
        joined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (_PACKAGE / "config.py", _PACKAGE / "archive.py")
        ).lower()
        for forbidden in (
            "allow_symlink",
            "allow_links",
            "allow_path_traversal",
            "allow_absolute_paths",
            "unsafe_extract",
        ):
            self.assertNotIn(forbidden, joined)

    def test_new_tests_use_temporary_data_not_repository_root_fixtures(self):
        for name in (
            "test_latex_project_archive_v2342.py",
            "test_latex_project_storage_v2342.py",
        ):
            source = (_ROOT / "tests" / name).read_text(encoding="utf-8")
            self.assertIn("TemporaryDirectory", source)
            self.assertNotIn(' / "fixtures"', source)
            self.assertNotIn("/fixtures/", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
