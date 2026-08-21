"""Release-level acceptance guards for v2.3.4.2 LaTeX-project ZIP ingestion.

The detailed archive, discovery, compilation, recovery, and GUI-source tests
live in the permanent ``*_v2342`` suite.  This module protects the final
release contract itself: package version, Written-only UI wiring, release
documentation, and one restart-safe canonical ZIP -> compiled PDF flow.

The end-to-end compilation case is skipped only when ``pdflatex`` is not
installed in the executing environment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import src
from src.submissions.bridge import parse_canonical_submission
from src.submissions.domain import (
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_ZIP,
    CandidateFile,
)
from src.submissions.repository import SubmissionRepository


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "docs"
_IMPORT_DIALOG = _REPO_ROOT / "src/ui/dialogs/submission_import_dialog.py"
_ROOT_DIALOG = _REPO_ROOT / "src/ui/dialogs/latex_project_root_dialog.py"
_DIAGNOSTICS_DIALOG = _REPO_ROOT / "src/ui/dialogs/latex_project_diagnostics_dialog.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TestLatexProjectReleaseAcceptanceV2342(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(src.__version__, "2.3.4.2")

    def test_written_zip_ui_and_recovery_contract_is_present(self):
        importer = _IMPORT_DIALOG.read_text(encoding="utf-8")
        root_dialog = _ROOT_DIALOG.read_text(encoding="utf-8")
        diagnostics = _DIAGNOSTICS_DIALOG.read_text(encoding="utf-8")

        self.assertIn('return "Choose project root"', importer)
        self.assertIn("LatexProjectRootSelectionDialog", importer)
        self.assertIn("LatexProjectDiagnosticsDialog", importer)
        self.assertIn("latex_project_root_selection_required", importer)
        self.assertIn("Select LaTeX Project Root", root_dialog)
        self.assertIn("Multiple LaTeX entry points found", root_dialog)
        self.assertIn("Use Selected File", root_dialog)
        self.assertIn("LaTeX Project Diagnostics", diagnostics)
        self.assertIn("View Compilation Log", diagnostics)
        self.assertIn("Open Source Project", diagnostics)
        self.assertIn("Retry Compilation", diagnostics)
        self.assertIn("Choose Different Root", diagnostics)

    def test_release_documentation_exists_and_describes_current_contract(self):
        expected = (
            _DOCS / "latex_project_ingestion.md",
            _DOCS / "written_submission_import.md",
            _DOCS / "v2.3.4.2_manual_acceptance.md",
            _DOCS / "releases/v2.3.4.2.md",
        )
        for path in expected:
            self.assertTrue(path.is_file(), str(path))

        ingestion = expected[0].read_text(encoding="utf-8")
        written = expected[1].read_text(encoding="utf-8")
        acceptance = expected[2].read_text(encoding="utf-8")
        release = expected[3].read_text(encoding="utf-8")

        self.assertIn("Overleaf", ingestion)
        self.assertIn("-no-shell-escape", ingestion)
        self.assertIn("not an OS/container sandbox", ingestion)
        self.assertIn("immutable", ingestion.lower())
        self.assertIn(".zip", written)
        self.assertIn("Choose project root", written)
        self.assertIn("compiled PDF", written)
        self.assertIn("Assessment Home", acceptance)
        self.assertIn("restart", acceptance.lower())
        self.assertIn("integrity", acceptance.lower())
        self.assertIn("2.3.4.2", release)
        self.assertIn("Overleaf / LaTeX Project ZIP Ingestion", release)

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex is not installed")
    def test_canonical_multifile_zip_compiles_and_reopens_with_same_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_zip = root / "alice_PS3.zip"
            with zipfile.ZipFile(
                source_zip,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.writestr(
                    "main.tex",
                    "\\documentclass{article}\n"
                    "\\input{macros}\n"
                    "\\begin{document}\n"
                    "\\input{answers/q1}\n"
                    "\\input{answers/q2}\n"
                    "\\end{document}\n",
                )
                archive.writestr(
                    "macros.tex",
                    "\\newcommand{\\fixtureanswer}[1]{\\textbf{#1}}\n",
                )
                archive.writestr(
                    "answers/q1.tex",
                    "\\section*{Question 1}\n"
                    "\\fixtureanswer{Canonical project answer one.}\n",
                )
                archive.writestr(
                    "answers/q2.tex",
                    "\\section*{Question 2}\n"
                    "\\fixtureanswer{Canonical project answer two.}\n",
                )
                archive.writestr(
                    "references.bib",
                    "@misc{fixture,title={Release Fixture},year={2026}}\n",
                )
                archive.writestr(
                    "figures/runtime_plot.pdf",
                    b"%PDF-1.4\n% preserved synthetic unreferenced figure\n",
                )

            original_sha = _sha256(source_zip)
            evidence_root = root / "submission_evidence"
            repository = SubmissionRepository(str(evidence_root))
            submission = repository.create_submission(
                assessment_id="PS3_RELEASE_ACCEPTANCE",
                student_id="alice",
                files=[
                    CandidateFile(
                        source_path=str(source_zip),
                        original_filename=source_zip.name,
                        artifact_type=ARTIFACT_TYPE_ZIP,
                        role=ARTIFACT_ROLE_SOURCE,
                    )
                ],
            )

            parsed = parse_canonical_submission(
                submission,
                repository,
                ["Q1", "Q2"],
                evidence_dir=str(root / "parsed"),
            )

            compiled_pdf = Path(parsed.files["compiled_pdf"])
            self.assertTrue(compiled_pdf.is_file())
            self.assertTrue(compiled_pdf.read_bytes().startswith(b"%PDF-"))
            self.assertEqual(parsed.metadata["canonical_source"], "latex_project")
            project_metadata = parsed.metadata["latex_project"]
            self.assertEqual(project_metadata["root_relative_path"], "main.tex")
            self.assertEqual(project_metadata["compilation_attempt_count"], 1)
            self.assertTrue(project_metadata["compiled_pdf_sha256"])
            self.assertIn("Q1", parsed.answers_by_question)
            self.assertIn("Q2", parsed.answers_by_question)

            canonical_zip = Path(parsed.files["latex_project_zip"])
            self.assertTrue(canonical_zip.is_file())
            self.assertEqual(_sha256(canonical_zip), original_sha)
            self.assertTrue(repository.verify_submission(submission)["ok"])

            first_pdf_sha = project_metadata["compiled_pdf_sha256"]
            first_provenance = Path(project_metadata["provenance_state_path"])
            self.assertTrue(first_provenance.is_file())

            reopened_repository = SubmissionRepository(str(evidence_root))
            reopened = reopened_repository.get_active_submission(
                "PS3_RELEASE_ACCEPTANCE",
                "alice",
            )
            self.assertIsNotNone(reopened)
            self.assertEqual(reopened.submission_id, submission.submission_id)

            reparsed = parse_canonical_submission(
                reopened,
                reopened_repository,
                ["Q1", "Q2"],
                evidence_dir=str(root / "reparsed"),
            )
            reopened_project = reparsed.metadata["latex_project"]
            self.assertEqual(reopened_project["root_relative_path"], "main.tex")
            self.assertEqual(reopened_project["compilation_attempt_count"], 1)
            self.assertEqual(reopened_project["compiled_pdf_sha256"], first_pdf_sha)
            self.assertEqual(
                Path(reopened_project["provenance_state_path"]),
                first_provenance,
            )
            self.assertTrue(Path(reparsed.files["compiled_pdf"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
