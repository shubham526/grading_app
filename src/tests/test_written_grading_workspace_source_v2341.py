"""Source guards for the v2.3.4.1 written workspace extraction."""

import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE = _ROOT / "ui/workspaces/written_grading_workspace.py"
_MAIN_WINDOW = _ROOT / "ui/main_window.py"


class TestWrittenGradingWorkspaceSourceV2341(unittest.TestCase):
    def test_workspace_is_presentation_only(self):
        source = _WORKSPACE.read_text(encoding="utf-8")
        self.assertIn("class WrittenGradingWorkspace", source)
        self.assertNotIn("SubmissionRepository", source)
        self.assertNotIn("AutogradingService", source)
        self.assertNotIn("load_rubric_from_file", source)
        self.assertNotIn("save_assessment", source)
        self.assertIn("layout.addWidget(self._legacy_root)", source)

    def test_main_window_keeps_legacy_root_only_as_compatibility_alias(self):
        source = _MAIN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("self.written_workspace = None", source)
        self.assertIn("WrittenGradingWorkspace(written_widget, self)", source)
        self.assertIn("target = self.written_workspace", source)
        self.assertIn("return self.written_workspace.legacy_layout()", source)

    def test_python39_grammar(self):
        for path in (_WORKSPACE, _MAIN_WINDOW):
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=(3, 9),
            )


if __name__ == "__main__":
    unittest.main()
