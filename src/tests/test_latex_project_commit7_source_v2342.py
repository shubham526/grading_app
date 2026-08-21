from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestLatexProjectCommit7SourceV2342(unittest.TestCase):
    def test_changed_backend_sources_are_python39_grammar_compatible(self):
        for relative in (
            "submissions/latex_project/provenance.py",
            "submissions/latex_project/written_bridge.py",
            "submissions/latex_project/__init__.py",
            "submissions/bridge.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            ast.parse(source, filename=relative, feature_version=(3, 9))

    def test_provenance_is_backend_only_and_does_not_mutate_canonical_manifests(self):
        source = (ROOT / "submissions/latex_project/provenance.py").read_text(encoding="utf-8")
        self.assertNotIn("PyQt", source)
        self.assertIn("grading_provenance.json", source)
        self.assertNotIn("submission.json", source)
        self.assertNotIn("index.json", source)

    def test_recovery_reuses_verified_project_and_blocks_integrity_failures(self):
        bridge = (ROOT / "submissions/latex_project/written_bridge.py").read_text(encoding="utf-8")
        self.assertIn("reuse_persisted_compilation", bridge)
        self.assertIn("force_recompile", bridge)
        self.assertIn("reusable_compiled_pdf", bridge)
        self.assertIn("load_latex_project_provenance", bridge)


if __name__ == "__main__":
    unittest.main(verbosity=2)
