"""Structural tests for Commit-5 responsive layout and preference persistence."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
_SOURCE = _PATH.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _class():
    return next(
        node for node in _TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "RubricGrader"
    )


def _method(name):
    return next(
        node for node in _class().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _segment(name):
    return ast.get_source_segment(_SOURCE, _method(name)) or ""


class TestMainWindowLayoutState(unittest.TestCase):

    def test_default_window_is_resizable_with_practical_minimum(self):
        init = _segment("__init__")
        self.assertIn("setMinimumSize(900, 600)", init)
        self.assertIn("resize(1400, 900)", init)

    def test_outer_workspace_is_vertical_splitter(self):
        source = _segment("init_ui")
        self.assertIn("self.workspace_splitter = QSplitter(Qt.Vertical)", source)
        self.assertIn("self.workspace_splitter.addWidget(self.submission_workspace)", source)
        self.assertIn("self.workspace_splitter.addWidget(self.grading_workspace)", source)
        self.assertIn("self.workspace_splitter.setChildrenCollapsible(False)", source)

    def test_grading_area_retains_independent_summary_splitter(self):
        source = _segment("init_ui")
        self.assertIn("self.main_splitter = QSplitter(Qt.Vertical)", source)
        self.assertIn("self.main_splitter.addWidget(self.scroll_area)", source)
        self.assertIn("self.main_splitter.addWidget(self.summary_container)", source)

    def test_submission_workspace_owns_independent_horizontal_splitter(self):
        workspace_path = _REPO_ROOT / "src" / "ui" / "widgets" / "submission_workspace.py"
        workspace_source = workspace_path.read_text(encoding="utf-8")
        self.assertIn("self.splitter = QSplitter(Qt.Horizontal", workspace_source)
        self.assertIn("toggle_document_panel", workspace_source)
        self.assertIn("toggle_text_panel", workspace_source)

    def test_ui_preferences_save_geometry_and_all_three_splitter_states(self):
        source = _segment("_save_ui_preferences")
        self.assertIn("saveGeometry()", source)
        self.assertIn("workspace_splitter.saveState()", source)
        self.assertIn("main_splitter.saveState()", source)
        self.assertIn("submission_workspace.splitter.saveState()", source)
        self.assertIn("isMaximized()", source)

    def test_ui_preferences_restore_geometry_and_all_three_splitter_states(self):
        source = _segment("_restore_ui_preferences")
        self.assertIn("restoreGeometry", source)
        self.assertIn("workspace_splitter.restoreState", source)
        self.assertIn("main_splitter.restoreState", source)
        self.assertIn("submission_workspace.splitter.restoreState", source)
        self.assertIn("Qt.WindowMaximized", source)

    def test_preferences_are_restored_after_widgets_exist(self):
        init = _segment("__init__")
        self.assertLess(init.index("self.init_ui()"), init.index("self._restore_ui_preferences()"))

    def test_close_path_persists_layout_and_cancels_background_requests(self):
        finalize = _segment("_finalize_window_close")
        self.assertIn("_save_ui_preferences()", finalize)
        self.assertIn("worker.cancel()", finalize)
        close = _segment("closeEvent")
        self.assertIn("_finalize_window_close", close)

    def test_question_mode_navigation_uses_two_row_layout(self):
        source = _segment("init_ui")
        self.assertIn("question_row = QHBoxLayout()", source)
        self.assertIn("student_row = QHBoxLayout()", source)
        self.assertIn("question_mode_controls.setMinimumHeight(92)", source)
        self.assertNotIn("question_mode_layout.addLayout(action_row)", source)
        self.assertIn("student_row.addWidget(self.save_question_btn)", source)

    def test_question_mode_layout_is_remeasured_after_becoming_visible(self):
        source = _segment("apply_current_workflow_view")
        self.assertIn("QTimer.singleShot(0, self._stabilize_question_mode_layout)", source)
        stabilizer = _segment("_stabilize_question_mode_layout")
        self.assertIn("adjustSize()", stabilizer)
        self.assertIn("sizeHint().height()", stabilizer)

    def test_vertical_splitters_cannot_accidentally_collapse_primary_workspaces(self):
        source = _segment("init_ui")
        self.assertIn("self.workspace_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("self.main_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("initially_collapsed=True", source)

    def test_restored_zero_sized_splitters_are_normalized(self):
        restore = _segment("_restore_ui_preferences")
        self.assertIn("_ensure_usable_splitter_sizes", restore)
        normalize = _segment("_normalize_splitter_sizes")
        self.assertIn("splitter.setSizes", normalize)
        self.assertIn("minimums", normalize)

    def test_primary_toolbar_groups_reports_and_settings_in_menus(self):
        source = _segment("init_ui")
        self.assertIn("self.reports_menu_button", source)
        self.assertIn("self.settings_menu_button", source)
        self.assertIn("QToolButton.InstantPopup", source)
        self.assertIn("Submission & AI Settings", source)


    def test_submission_gets_priority_in_default_vertical_split(self):
        source = _segment("init_ui")
        self.assertIn("self.submission_workspace.setMinimumHeight(320)", source)
        self.assertIn("self.workspace_splitter.setStretchFactor(0, 6)", source)
        self.assertIn("self.workspace_splitter.setStretchFactor(1, 4)", source)
        self.assertIn("self.workspace_splitter.setSizes([520, 320])", source)
        self.assertIn("self.workspace_splitter.setHandleWidth(10)", source)

    def test_grading_summary_is_collapsible_and_collapsed_by_default(self):
        source = _segment("init_ui")
        self.assertIn(
            'CardWidget("Grading", collapsible=True, initially_collapsed=True)',
            source,
        )

    def test_layout_preferences_include_compact_top_sections(self):
        save = _segment("_save_ui_preferences")
        restore = _segment("_restore_ui_preferences")
        self.assertIn("_UI_GRADING_CARD_COLLAPSED_KEY", save)
        self.assertIn("_UI_ATTEMPTED_QUESTIONS_VISIBLE_KEY", save)
        self.assertIn("grading_card_collapsed", restore)
        self.assertIn("attempted_questions_visible", restore)

    def test_focus_mode_hides_grading_and_restores_splitter(self):
        source = _segment("_on_submission_focus_requested")
        self.assertIn("self.grading_workspace.setVisible(False)", source)
        self.assertIn("self.grading_workspace.setVisible(True)", source)
        self.assertIn("self._workspace_sizes_before_focus", source)
        self.assertIn("self.workspace_splitter.setSizes(sizes)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
