"""Source-contract checks for v2.3.4.2 Commit 1."""

import ast
from pathlib import Path
import unittest


_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "submissions" / "latex_project"
_PRODUCTION_FILES = (
    _PACKAGE_ROOT / "__init__.py",
    _PACKAGE_ROOT / "errors.py",
    _PACKAGE_ROOT / "models.py",
    _PACKAGE_ROOT / "config.py",
)


class TestLatexProjectCommit1SourceV2342(unittest.TestCase):

    def test_commit1_production_sources_parse_as_python39_grammar(self):
        for path in _PRODUCTION_FILES:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(path), feature_version=(3, 9))

    def test_commit1_domain_and_config_have_no_pyqt_dependency(self):
        for path in _PRODUCTION_FILES:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("PyQt", source)

    def test_commit1_does_not_extract_compile_or_execute_student_content(self):
        forbidden_imports = (
            "import zipfile",
            "from zipfile",
            "import subprocess",
            "from subprocess",
            "import docker",
            "from docker",
        )
        forbidden_calls = (
            "extractall(",
            "Popen(",
            "subprocess.run(",
            "pdflatex",
            "xelatex",
            "lualatex",
            "shell=True",
        )
        for path in _PRODUCTION_FILES:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                for fragment in forbidden_imports + forbidden_calls:
                    self.assertNotIn(fragment, source)

    def test_safety_invariants_are_not_exposed_as_disable_switches(self):
        config_source = (_PACKAGE_ROOT / "config.py").read_text(encoding="utf-8")
        for unsafe_switch in (
            "allow_path_traversal",
            "allow_absolute_paths",
            "allow_symlinks",
            "allow_hardlinks",
            "allow_special_files",
            "enable_shell_escape",
            "compile_latex",
        ):
            self.assertNotIn(unsafe_switch, config_source)


if __name__ == "__main__":
    unittest.main()
