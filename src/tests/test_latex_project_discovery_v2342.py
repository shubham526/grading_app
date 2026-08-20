import hashlib
from pathlib import Path
import tempfile
import unittest

from src.submissions.latex_project.discovery import discover_latex_project
from src.submissions.latex_project.models import (
    FILE_ROLE_BIBLIOGRAPHY,
    FILE_ROLE_FIGURE,
    FILE_ROLE_OTHER,
    FILE_ROLE_TEX_SOURCE,
    LatexProjectFile,
    LatexProjectManifest,
)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _project(root, files):
    root = Path(root)
    entries = []
    for relative, value in files.items():
        data = value if isinstance(value, bytes) else value.encode("utf-8")
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        suffix = Path(relative).suffix.lower()
        if suffix == ".tex":
            role = FILE_ROLE_TEX_SOURCE
        elif suffix == ".bib":
            role = FILE_ROLE_BIBLIOGRAPHY
        elif suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
            role = FILE_ROLE_FIGURE
        else:
            role = FILE_ROLE_OTHER
        entries.append(
            LatexProjectFile(
                relative_path=relative,
                size_bytes=len(data),
                sha256=_sha(data),
                role=role,
            )
        )
    return LatexProjectManifest(
        project_id="lproj-discovery-test",
        files=tuple(entries),
        total_uncompressed_bytes=sum(item.size_bytes for item in entries),
    )


class TestLatexProjectDiscoveryV2342(unittest.TestCase):
    def test_discovers_document_candidates_and_project_assets(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {
                "main.tex": r"""\documentclass{article}
\begin{document}
\input{sections/q1}
\include{sections/q2.tex}
\end{document}
""",
                "sections/q1.tex": "Question one.\n",
                "sections/q2.tex": "Question two.\n",
                "orphan.tex": "Unused notes.\n",
                "refs.bib": "@book{x,title={X}}\n",
                "figures/a.pdf": b"%PDF-synthetic",
                "notes.txt": "synthetic\n",
            })
            result = discover_latex_project(td, manifest)

        self.assertEqual(result.document_candidate_paths, ("main.tex",))
        self.assertEqual(
            result.included_tex_paths,
            ("sections/q1.tex", "sections/q2.tex"),
        )
        self.assertEqual(result.orphan_tex_paths, ("orphan.tex",))
        self.assertEqual(result.bibliography_paths, ("refs.bib",))
        self.assertEqual(result.figure_paths, ("figures/a.pdf",))
        self.assertEqual(result.other_paths, ("notes.txt",))
        main = result.source_by_path("main.tex")
        self.assertTrue(main.has_documentclass)
        self.assertTrue(main.has_begin_document)
        self.assertEqual(len(main.references), 2)
        self.assertTrue(all(item.exists for item in main.references))

    def test_commented_document_markers_and_inputs_do_not_count(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {
                "notes.tex": r"""% \documentclass{article}
% \begin{document}
% \input{hidden}
Literal escaped percent \% still here.
""",
                "hidden.tex": "text\n",
            })
            result = discover_latex_project(td, manifest)

        self.assertEqual(result.document_candidate_paths, ())
        notes = result.source_by_path("notes.tex")
        self.assertFalse(notes.has_documentclass)
        self.assertFalse(notes.has_begin_document)
        self.assertEqual(notes.references, ())

    def test_missing_static_include_is_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {
                "main.tex": r"""\documentclass{article}
\begin{document}
\input{sections/missing}
\end{document}
""",
            })
            result = discover_latex_project(td, manifest)

        self.assertIn("missing_include_reference", [d.code for d in result.diagnostics])
        reference = result.source_by_path("main.tex").references[0]
        self.assertEqual(reference.resolved_relative_path, "sections/missing.tex")
        self.assertFalse(reference.exists)
        self.assertFalse(reference.dynamic)

    def test_dynamic_include_is_recorded_without_macro_expansion(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {
                "main.tex": r"""\documentclass{article}
\newcommand{\partfile}{sections/q1}
\begin{document}
\input{\partfile}
\end{document}
""",
                "sections/q1.tex": "text\n",
            })
            result = discover_latex_project(td, manifest)

        reference = result.source_by_path("main.tex").references[0]
        self.assertTrue(reference.dynamic)
        self.assertIsNone(reference.resolved_relative_path)
        self.assertIn("dynamic_include_reference", [d.code for d in result.diagnostics])

    def test_parent_reference_inside_project_is_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {
                "main.tex": r"""\documentclass{article}
\begin{document}\input{sections/q1}\end{document}
""",
                "sections/q1.tex": r"\input{../shared}",
                "shared.tex": "shared text\n",
            })
            result = discover_latex_project(td, manifest)

        ref = result.source_by_path("sections/q1.tex").references[0]
        self.assertEqual(ref.resolved_relative_path, "shared.tex")
        self.assertTrue(ref.exists)
        self.assertNotIn(
            "include_reference_outside_project",
            [d.code for d in result.diagnostics],
        )

    def test_reference_outside_project_is_never_resolved_to_host_path(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {
                "main.tex": r"""\documentclass{article}
\begin{document}\input{../secret}\end{document}
""",
            })
            result = discover_latex_project(td, manifest)

        ref = result.source_by_path("main.tex").references[0]
        self.assertIsNone(ref.resolved_relative_path)
        self.assertFalse(ref.exists)
        self.assertIn(
            "include_reference_outside_project",
            [d.code for d in result.diagnostics],
        )

    def test_non_utf8_tex_is_not_guessed_as_root(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {"main.tex": b"\xff\xfe\x00\x00"})
            result = discover_latex_project(td, manifest)

        self.assertEqual(result.tex_sources, ())
        self.assertIn("tex_source_not_utf8", [d.code for d in result.diagnostics])

    def test_no_tex_project_emits_blocking_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _project(td, {"README.txt": "nothing to grade\n"})
            result = discover_latex_project(td, manifest)

        self.assertEqual(result.tex_sources, ())
        diagnostic = next(d for d in result.diagnostics if d.code == "no_tex_sources")
        self.assertEqual(diagnostic.severity, "blocking")


if __name__ == "__main__":
    unittest.main(verbosity=2)
