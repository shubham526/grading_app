from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestLatexProjectDiagnosticsUiSourceV2342(unittest.TestCase):
    def test_commit7_ui_sources_are_python39_compatible(self):
        for relative in (
            "ui/dialogs/latex_project_diagnostics_dialog.py",
            "ui/dialogs/submission_import_dialog.py",
            "ui/workers/submission_import_worker.py",
            "ui/main_window.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            ast.parse(source, filename=relative, feature_version=(3, 9))

    def test_diagnostics_dialog_exposes_logs_project_and_recovery_actions(self):
        source = (ROOT / "ui/dialogs/latex_project_diagnostics_dialog.py").read_text(encoding="utf-8")
        self.assertIn("View Compilation Log", source)
        self.assertIn("Open Source Project", source)
        self.assertIn("Retry Compilation", source)
        self.assertIn("Choose Different Root", source)
        self.assertIn("Recovery is blocked", source)

    def test_worker_has_explicit_verified_recovery_operation(self):
        source = (ROOT / "ui/workers/submission_import_worker.py").read_text(encoding="utf-8")
        self.assertIn('RECOVER_LATEX_PROJECT = "recover_latex_project"', source)
        self.assertIn("latex_project_force_recompile=True", source)
        self.assertIn("latex_project_diagnostics", source)
        self.assertIn("LatexProjectIntegrityError", source)

    def test_import_dialog_routes_recovery_without_reimporting_original_zip(self):
        source = (ROOT / "ui/dialogs/submission_import_dialog.py").read_text(encoding="utf-8")
        self.assertIn("_start_latex_project_recovery", source)
        self.assertIn("RECOVER_LATEX_PROJECT", source)
        self.assertIn("evidence_recovered", source)
        self.assertIn("LatexProjectDiagnosticsDialog", source)

    def test_main_window_registers_recovered_evidence_on_ui_thread(self):
        source = (ROOT / "ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("dialog.evidence_recovered.connect", source)
        self.assertIn("def _on_canonical_evidence_recovered", source)
        self.assertIn("register_canonical_submission", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
