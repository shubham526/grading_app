"""Source-level invariants for v2.3.4.2 Commit 8 hardening."""

from pathlib import Path
import unittest


SRC_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent


class TestLatexProjectCommit8SourceV2342(unittest.TestCase):
    def test_v2342_tests_do_not_depend_on_repository_root_fixture_directory(self):
        offenders = []
        for path in sorted(TEST_ROOT.glob("test_*_v2342.py")):
            if "_source_" in path.name:
                continue
            source = path.read_text(encoding="utf-8")
            if ' / "fixtures"' in source or "/fixtures/" in source:
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_v233_release_acceptance_is_now_self_contained(self):
        path = TEST_ROOT / "test_autograding_release_acceptance_v233.py"
        source = path.read_text(encoding="utf-8")
        self.assertNotIn(' / "fixtures" / "v2.3.3_autograding_acceptance"', source)
        self.assertIn("write_release_fixture", source)
        self.assertIn("TemporaryDirectory", source)

    def test_commit8_hardening_delta_remains_test_only(self):
        commit8_paths = (
            "tests/test_autograding_release_acceptance_v233.py",
            "tests/autograding_v233_release_fixture_support.py",
            "tests/latex_project_v2342_hardening_support.py",
            "tests/test_latex_project_edge_cases_v2342.py",
            "tests/test_latex_project_compilation_hardening_v2342.py",
            "tests/test_latex_project_regression_boundaries_v2342.py",
            "tests/test_latex_project_commit8_source_v2342.py",
        )
        self.assertTrue(all(value.startswith("tests/") for value in commit8_paths))

    def test_project_compiler_still_forces_no_shell_escape(self):
        compiler = (SRC_ROOT / "submissions" / "compiler.py").read_text(encoding="utf-8")
        self.assertIn('"-no-shell-escape"', compiler)
        self.assertIn('"shell_escape": "f"', compiler)
        self.assertIn('"openin_any": "p"', compiler)
        self.assertIn('"openout_any": "p"', compiler)

    def test_programming_mode_production_files_are_not_latex_project_dependencies(self):
        latex_dir = SRC_ROOT / "submissions" / "latex_project"
        for path in sorted(latex_dir.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("src.autograding", source, path.name)
            self.assertNotIn("from ..autograding", source, path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
