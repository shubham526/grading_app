from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import zipfile

from src.submissions.domain import (
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_ZIP,
    VALIDATION_STATUS_INVALID,
    VALIDATION_STATUS_READY,
    CandidateFile,
    ImportCandidate,
)
from src.submissions.latex_project.import_preview import (
    LATEX_PROJECT_ROOT_METADATA_KEY,
    ROOT_SELECTION_DETERMINISTIC,
    ROOT_SELECTION_INSTRUCTOR,
    LATEX_PROJECT_ROOT_METHOD_METADATA_KEY,
    apply_latex_project_preview_validation,
    candidate_latex_project_preview,
    inspect_latex_project_zip,
    latex_project_root_selection_required,
    preflight_latex_project_candidate,
    set_candidate_latex_project_root,
)
from src.submissions.latex_project.models import (
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_INVALID_PROJECT,
    ROOT_RESOLUTION_RESOLVED,
)


class TestLatexProjectImportPreviewV2342(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _zip(self, name, files):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as zipped:
            for relative, text in files.items():
                zipped.writestr(relative, text)
        return path

    def _candidate(self, archive):
        return ImportCandidate(
            candidate_id="cand_1",
            source_system="local_upload",
            proposed_student_id="alice",
            proposed_assessment_id="ps3",
            files=[
                CandidateFile(
                    source_path=str(archive),
                    original_filename=archive.name,
                    artifact_type=ARTIFACT_TYPE_ZIP,
                    role=ARTIFACT_ROLE_SOURCE,
                )
            ],
            validation_status=VALIDATION_STATUS_READY,
        )

    def test_unique_document_is_resolved_without_instructor_prompt(self):
        archive = self._zip(
            "alice.zip",
            {
                "main.tex": (
                    r"\documentclass{article}" "\n"
                    r"\begin{document}Answer\end{document}"
                ),
                "answers/q1.tex": "Question 1 answer",
            },
        )
        candidate = preflight_latex_project_candidate(self._candidate(archive))
        preview = candidate_latex_project_preview(candidate)
        self.assertIsNotNone(preview)
        self.assertEqual(preview.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(preview.root_relative_path, "main.tex")
        self.assertEqual(candidate.metadata[LATEX_PROJECT_ROOT_METADATA_KEY], "main.tex")
        self.assertEqual(
            candidate.metadata[LATEX_PROJECT_ROOT_METHOD_METADATA_KEY],
            ROOT_SELECTION_DETERMINISTIC,
        )
        self.assertFalse(latex_project_root_selection_required(candidate))

    def test_ambiguous_project_requires_explicit_root_choice(self):
        archive = self._zip(
            "alice.zip",
            {
                "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
                "report.tex": r"\documentclass{article}\begin{document}B\end{document}",
            },
        )
        candidate = preflight_latex_project_candidate(self._candidate(archive))
        preview = candidate_latex_project_preview(candidate)
        self.assertEqual(preview.status, ROOT_RESOLUTION_AMBIGUOUS)
        self.assertEqual(set(preview.candidate_paths), {"main.tex", "report.tex"})
        self.assertTrue(latex_project_root_selection_required(candidate))
        self.assertNotIn(LATEX_PROJECT_ROOT_METADATA_KEY, candidate.metadata)

        set_candidate_latex_project_root(candidate, "report.tex")
        self.assertFalse(latex_project_root_selection_required(candidate))
        self.assertEqual(candidate.metadata[LATEX_PROJECT_ROOT_METADATA_KEY], "report.tex")
        self.assertEqual(
            candidate.metadata[LATEX_PROJECT_ROOT_METHOD_METADATA_KEY],
            ROOT_SELECTION_INSTRUCTOR,
        )

    def test_invalid_project_blocks_generic_ready_candidate(self):
        archive = self._zip("alice.zip", {"README.txt": "not latex"})
        candidate = preflight_latex_project_candidate(self._candidate(archive))
        preview = candidate_latex_project_preview(candidate)
        self.assertIn(
            preview.status,
            {ROOT_RESOLUTION_INVALID_PROJECT, "no_root_found"},
        )
        apply_latex_project_preview_validation(candidate)
        self.assertEqual(candidate.validation_status, VALIDATION_STATUS_INVALID)
        self.assertTrue(any(value.startswith("latex_project:") for value in candidate.errors))

    def test_path_traversal_archive_is_rejected_during_preview(self):
        archive = self._zip(
            "evil.zip",
            {
                "../evil.tex": r"\documentclass{article}\begin{document}x\end{document}",
            },
        )
        preview = inspect_latex_project_zip(str(archive))
        self.assertEqual(preview.status, ROOT_RESOLUTION_INVALID_PROJECT)
        self.assertTrue(preview.error_message)

    def test_arbitrary_root_cannot_be_selected(self):
        archive = self._zip(
            "alice.zip",
            {
                "main.tex": r"\documentclass{article}\begin{document}A\end{document}",
                "report.tex": r"\documentclass{article}\begin{document}B\end{document}",
            },
        )
        candidate = preflight_latex_project_candidate(self._candidate(archive))
        with self.assertRaises(ValueError):
            set_candidate_latex_project_root(candidate, "answers/q1.tex")


if __name__ == "__main__":
    unittest.main(verbosity=2)
