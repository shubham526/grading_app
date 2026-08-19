"""Source-level regression tests for the final v2.3.2 grading-window polish."""

import ast
from pathlib import Path
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
_STYLE_PATH = _REPO_ROOT / "src" / "utils" / "styles.py"
_SOURCE = _MAIN_PATH.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _class_node():
    return next(
        node for node in _TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "RubricGrader"
    )


def _method(name):
    return next(
        node for node in _class_node().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _segment(name):
    return ast.get_source_segment(_SOURCE, _method(name)) or ""


class TestUiPolishV232(unittest.TestCase):

    def test_primary_toolbar_has_only_two_large_routine_actions(self):
        source = _segment("init_ui")
        self.assertIn('self.load_btn = QPushButton("Load Rubric")', source)
        self.assertIn('self.import_submissions_btn = QPushButton("Import Submissions")', source)
        for old_button in (
            'QPushButton("Load Submissions")',
            'QPushButton("Load Reference Solution")',
            'QPushButton("Add PDF Accommodation")',
            'QPushButton("Grades + Evidence Folder")',
            'QPushButton("Load Roster")',
            'QPushButton("Analytics")',
        ):
            self.assertNotIn(old_button, source)

    def test_setup_menu_contains_workspace_roster_reference_and_pdf_accommodation(self):
        source = _segment("init_ui")
        self.assertIn('"Choose Workspace…"', source)
        self.assertIn('"Load Roster…"', source)
        self.assertIn('"Load Reference Solution…"', source)
        self.assertIn('"Add PDF Accommodation…"', source)
        self.assertIn("self.setup_menu_button", source)

    def test_analytics_is_grouped_with_reports(self):
        source = _segment("init_ui")
        self.assertIn('self.analytics_btn = QAction(qta.icon(\'fa5s.chart-bar\'), "Analytics", self)', source)
        self.assertIn("reports_menu.addAction(self.analytics_btn)", source)

    def test_legacy_latex_loader_is_not_primary_toolbar_action(self):
        source = _segment("init_ui")
        self.assertIn('legacy_menu = QMenu("Legacy", self)', source)
        self.assertIn('"Load LaTeX Submissions (v2.2)…"', source)
        self.assertIn("tools_menu.addMenu(legacy_menu)", source)

    def test_assessment_context_is_one_compact_strip(self):
        source = _segment("init_ui")
        self.assertIn('self.info_widget.setObjectName("assessmentContextStrip")', source)
        self.assertIn('assessment_caption = QLabel("Assessment")', source)
        self.assertIn('workspace_caption = QLabel("Workspace")', source)
        self.assertNotIn('student_label = QLabel("Student")', source)

    def test_workspace_path_is_compacted_but_full_value_is_tooltip(self):
        source = _segment("_set_assessment_workspace_path")
        self.assertIn('display = f"…/{parent}/{base}"', source)
        self.assertIn("self.assessment_folder_label.setToolTip(absolute)", source)

    def test_grading_configuration_summary_is_inline_in_context(self):
        source = _segment("init_ui")
        self.assertIn('self.config_info.setObjectName("gradingSummaryLabel")', source)
        self.assertIn("workflow_top.addWidget(self.config_info, 1)", source)
        self.assertNotIn('CardWidget("Grading", collapsible=True', source)

    def test_save_as_moves_to_small_more_save_menu(self):
        source = _segment("init_ui")
        self.assertIn('self.save_assessment_as_action = QAction(', source)
        self.assertIn('"Save Assessment As…"', source)
        self.assertIn("self.save_assessment_menu_button", source)
        self.assertNotIn('QPushButton("Save Assessment As…")', source)

    def test_top_context_allocates_more_room_to_grading_workspace(self):
        source = _segment("init_ui")
        self.assertIn("self.session_workspace_splitter.setSizes([185, 715])", source)
        ensure = _segment("_ensure_usable_splitter_sizes")
        self.assertIn("minimums=(120, 320)", ensure)
        self.assertIn("fallback=(185, 715)", ensure)

    def test_styles_include_compact_toolbar_and_context_strip_rules(self):
        styles = _STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn('QToolButton[toolbarMenu="true"]', styles)
        self.assertIn("QFrame#assessmentContextStrip", styles)
        self.assertIn("QLabel#gradingSummaryLabel", styles)


if __name__ == "__main__":
    unittest.main(verbosity=2)
