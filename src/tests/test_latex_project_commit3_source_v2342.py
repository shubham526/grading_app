import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION = (
    _ROOT / "submissions" / "latex_project" / "discovery.py",
    _ROOT / "submissions" / "latex_project" / "resolution.py",
)


class TestLatexProjectCommit3SourceV2342(unittest.TestCase):
    def test_changed_production_files_parse_with_python39_grammar(self):
        for path in _PRODUCTION:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=(3, 9))

    def test_discovery_and_resolution_are_execution_free_and_ui_free(self):
        forbidden = (
            "subprocess",
            "os.system",
            "os.popen",
            "shell=True",
            "ZipFile(",
            ".extract(",
            "extractall",
            "pdflatex",
            "xelatex",
            "lualatex",
            "PyQt",
            "PySide",
        )
        for path in _PRODUCTION:
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source, "%s contains %r" % (path.name, token))

    def test_commit3_does_not_depend_on_repository_root_fixture_data(self):
        for path in _PRODUCTION:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("fixtures/", source)
            self.assertNotIn('"fixtures"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
