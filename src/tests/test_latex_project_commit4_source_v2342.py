"""Source/architecture gates for corrected v2.3.4.2 Commit 4."""

import ast
from pathlib import Path
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPILER = _REPO_ROOT / "src" / "submissions" / "compiler.py"
_PROJECT_COMPILATION = (
    _REPO_ROOT / "src" / "submissions" / "latex_project" / "compilation.py"
)
_PROJECT_STORAGE = (
    _REPO_ROOT / "src" / "submissions" / "latex_project" / "storage.py"
)


class TestLatexProjectCommit4SourceV2342(unittest.TestCase):
    def test_changed_production_files_parse_with_python39_grammar(self):
        for path in (_COMPILER, _PROJECT_COMPILATION, _PROJECT_STORAGE):
            with self.subTest(path=path.name):
                ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                    feature_version=(3, 9),
                )

    def test_project_compilation_delegates_to_existing_latex_compiler(self):
        source = _PROJECT_COMPILATION.read_text(encoding="utf-8")
        self.assertIn("compile_tex_to_pdf(", source)
        self.assertIn("source_root=str(extracted_root)", source)
        self.assertIn("allowed_source_paths=allowed_paths", source)

    def test_commit4_does_not_implement_manual_input_include_composition(self):
        source = _PROJECT_COMPILATION.read_text(encoding="utf-8")
        forbidden = (
            "ComposedLatexDocument",
            "compose_latex",
            "composition_output_limit_exceeded",
            "latex_include_cycle",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_commit4_adds_no_pyqt_or_written_ui_dependency(self):
        source = _PROJECT_COMPILATION.read_text(encoding="utf-8")
        self.assertNotIn("PyQt", source)
        self.assertNotIn("main_window", source)
        self.assertNotIn("WrittenGradingWorkspace", source)

    def test_compiler_retains_no_shell_escape_and_restricted_tex_io(self):
        source = _COMPILER.read_text(encoding="utf-8")
        self.assertIn('"-no-shell-escape"', source)
        self.assertIn('"openin_any": "p"', source)
        self.assertIn('"openout_any": "p"', source)

    def test_new_commit4_tests_do_not_depend_on_repository_root_fixtures(self):
        for path in (
            _REPO_ROOT / "src" / "tests" / "test_latex_project_compilation_v2342.py",
            _REPO_ROOT / "src" / "tests" / "test_latex_compiler_project_root_v2342.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('/ "fixtures" /', source)
            self.assertIn("TemporaryDirectory", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
