import hashlib
from pathlib import Path
import tempfile
import unittest

from src.submissions.latex_project.config import LatexProjectIngestionConfig
from src.submissions.latex_project.discovery import discover_latex_project
from src.submissions.latex_project.models import (
    FILE_ROLE_TEX_SOURCE,
    ROOT_METHOD_INSTRUCTOR_SELECTED,
    ROOT_METHOD_UNIQUE_DOCUMENT,
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_INVALID_PROJECT,
    ROOT_RESOLUTION_NO_ROOT_FOUND,
    ROOT_RESOLUTION_RESOLVED,
    LatexProjectFile,
    LatexProjectManifest,
)
from src.submissions.latex_project.resolution import (
    resolve_latex_project_root,
    select_latex_project_root,
)


def _discover(root, sources):
    root = Path(root)
    entries = []
    for relative, text in sources.items():
        data = text.encode("utf-8")
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append(
            LatexProjectFile(
                relative_path=relative,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                role=FILE_ROLE_TEX_SOURCE,
            )
        )
    manifest = LatexProjectManifest(
        project_id="lproj-resolution-test",
        files=tuple(entries),
        total_uncompressed_bytes=sum(item.size_bytes for item in entries),
    )
    return discover_latex_project(root, manifest)


def _doc(body="Hello"):
    return "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n" % body


class TestLatexProjectResolutionV2342(unittest.TestCase):
    def test_unique_complete_document_resolves_deterministically(self):
        with tempfile.TemporaryDirectory() as td:
            discovery = _discover(td, {
                "submission.tex": _doc(),
                "section.tex": "body only\n",
            })
            result = resolve_latex_project_root(discovery)
        self.assertEqual(result.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(result.root_relative_path, "submission.tex")
        self.assertEqual(result.resolution_method, ROOT_METHOD_UNIQUE_DOCUMENT)

    def test_main_tex_and_report_tex_remain_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            discovery = _discover(td, {
                "main.tex": _doc("main"),
                "report.tex": _doc("report"),
            })
            result = resolve_latex_project_root(discovery)
        self.assertEqual(result.status, ROOT_RESOLUTION_AMBIGUOUS)
        self.assertIsNone(result.root_relative_path)
        self.assertEqual(result.metadata["preferred_name_hints"], ["main.tex"])

    def test_custom_preferred_names_are_hints_not_automatic_selection(self):
        with tempfile.TemporaryDirectory() as td:
            discovery = _discover(td, {
                "paper.tex": _doc("paper"),
                "report.tex": _doc("report"),
            })
            config = LatexProjectIngestionConfig(
                preferred_root_names=("report.tex", "paper.tex")
            )
            result = resolve_latex_project_root(discovery, config=config)
        self.assertEqual(result.status, ROOT_RESOLUTION_AMBIGUOUS)
        self.assertIsNone(result.root_relative_path)
        self.assertEqual(
            result.metadata["preferred_name_hints"],
            ["report.tex", "paper.tex"],
        )

    def test_duplicate_main_basenames_do_not_get_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            discovery = _discover(td, {
                "a/main.tex": _doc("a"),
                "b/main.tex": _doc("b"),
            })
            result = resolve_latex_project_root(discovery)
        self.assertEqual(result.status, ROOT_RESOLUTION_AMBIGUOUS)

    def test_instructor_can_resolve_only_an_ambiguous_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            discovery = _discover(td, {
                "paper.tex": _doc("paper"),
                "report.tex": _doc("report"),
                "notes.tex": "notes\n",
            })
            automatic = resolve_latex_project_root(discovery)
            selected = select_latex_project_root(discovery, "report.tex")
        self.assertEqual(automatic.status, ROOT_RESOLUTION_AMBIGUOUS)
        self.assertEqual(selected.status, ROOT_RESOLUTION_RESOLVED)
        self.assertEqual(selected.root_relative_path, "report.tex")
        self.assertEqual(selected.resolution_method, ROOT_METHOD_INSTRUCTOR_SELECTED)
        self.assertIn("root_selected_by_instructor", [d.code for d in selected.diagnostics])
        with self.assertRaises(ValueError):
            select_latex_project_root(discovery, "notes.tex")

    def test_no_complete_document_is_blocking_no_root(self):
        with tempfile.TemporaryDirectory() as td:
            discovery = _discover(td, {
                "main.tex": "\\input{section}\n",
                "section.tex": "answer\n",
            })
            result = resolve_latex_project_root(discovery)
        self.assertEqual(result.status, ROOT_RESOLUTION_NO_ROOT_FOUND)
        self.assertIn("no_complete_root_document", [d.code for d in result.diagnostics])

    def test_no_readable_tex_is_invalid_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = b"plain text"
            (root / "README.txt").write_bytes(data)
            manifest = LatexProjectManifest(
                project_id="lproj-invalid",
                files=(LatexProjectFile(
                    relative_path="README.txt",
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                ),),
                total_uncompressed_bytes=len(data),
            )
            discovery = discover_latex_project(td, manifest)
            result = resolve_latex_project_root(discovery)
        self.assertEqual(result.status, ROOT_RESOLUTION_INVALID_PROJECT)
        self.assertIn("invalid_project_no_readable_tex", [d.code for d in result.diagnostics])


if __name__ == "__main__":
    unittest.main(verbosity=2)
