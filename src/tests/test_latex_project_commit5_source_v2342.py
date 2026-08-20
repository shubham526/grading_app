from __future__ import annotations

import ast
import unittest
from pathlib import Path


_REPO = Path(__file__).resolve().parents[2]
_WRITTEN_BRIDGE = _REPO / "src" / "submissions" / "latex_project" / "written_bridge.py"
_CANONICAL_BRIDGE = _REPO / "src" / "submissions" / "bridge.py"
_ROUTING = _REPO / "src" / "submissions" / "routing.py"


class TestLatexProjectCommit5SourceV2342(unittest.TestCase):
    def test_changed_production_sources_parse_as_python39_grammar(self):
        for path in (_WRITTEN_BRIDGE, _CANONICAL_BRIDGE, _ROUTING):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))

    def test_written_bridge_has_no_pyqt_or_manual_tex_composer(self):
        source = _WRITTEN_BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("PyQt", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("composition.py", source)
        self.assertNotIn("\\\\input{", source)
        self.assertIn("compile_stored_latex_project_to_pdf", source)
        self.assertIn('"compiled_pdf"', source)

    def test_router_exposes_project_handler_as_supported(self):
        source = _ROUTING.read_text(encoding="utf-8")
        self.assertIn('"handler_available_since": "2.3.4.2"', source)
        self.assertIn("REASON_MULTIPLE_LATEX_PROJECT_ARCHIVES", source)

    def test_commit5_does_not_touch_ui_or_programming_execution(self):
        source = _WRITTEN_BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("autograding", source)
        self.assertNotIn("Docker", source)
        self.assertNotIn("QWidget", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
