"""Static Commit-6 UI/worker contract gates for environments without PyQt5."""

import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_DIALOG = _ROOT / "ui" / "dialogs" / "submission_import_dialog.py"
_ROOT_DIALOG = _ROOT / "ui" / "dialogs" / "latex_project_root_dialog.py"
_WORKER = _ROOT / "ui" / "workers" / "submission_import_worker.py"
_PREVIEW = _ROOT / "submissions" / "latex_project" / "import_preview.py"
_LATEX_INIT = _ROOT / "submissions" / "latex_project" / "__init__.py"


class TestLatexProjectImportUiSourceV2342(unittest.TestCase):
    def test_commit6_sources_remain_python39_compatible(self):
        for path in (_DIALOG, _ROOT_DIALOG, _WORKER, _PREVIEW, _LATEX_INIT):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))

    def test_preview_is_execution_free_and_uses_safe_project_services(self):
        source = _PREVIEW.read_text(encoding="utf-8")
        self.assertIn("LatexProjectArchiveStore", source)
        self.assertIn("discover_latex_project", source)
        self.assertIn("resolve_latex_project_root", source)
        for forbidden in ("subprocess", "pdflatex", "compile_tex_to_pdf", "os.system"):
            self.assertNotIn(forbidden, source)

    def test_import_dialog_requests_root_only_for_ambiguous_projects(self):
        source = _DIALOG.read_text(encoding="utf-8")
        self.assertIn("LatexProjectRootSelectionDialog", source)
        self.assertIn("latex_project_root_selection_required", source)
        self.assertIn("_resolve_latex_project_roots", source)
        self.assertIn("set_candidate_latex_project_root", source)
        self.assertIn("*.zip", source)
        self.assertIn("The app will not guess", _ROOT_DIALOG.read_text(encoding="utf-8"))

    def test_worker_preflights_then_passes_selected_root_to_canonical_bridge(self):
        source = _WORKER.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("preflight_latex_project_candidates"), 3)
        self.assertIn("LATEX_PROJECT_ROOT_METADATA_KEY", source)
        self.assertIn("latex_project_root=selected_root", source)
        self.assertIn("LatexProjectRootResolutionRequiredError", source)
        self.assertIn('"root_resolution_required"', source)

    def test_commit6_does_not_bypass_canonical_importer_or_written_bridge(self):
        dialog = _DIALOG.read_text(encoding="utf-8")
        worker = _WORKER.read_text(encoding="utf-8")
        self.assertIn("SubmissionImporter", dialog)
        self.assertIn("SubmissionImporter", worker)
        self.assertIn("parse_canonical_submission", worker)
        self.assertNotIn("compile_tex_to_pdf", dialog)
        self.assertNotIn("compile_tex_to_pdf", worker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
