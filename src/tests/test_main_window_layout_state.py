"""Structural tests for Commit-5 responsive Gradescope-style layout."""

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

    def test_upper_context_and_work_area_use_vertical_splitter(self):
        source = _segment("init_ui")
        self.assertIn("self.session_workspace_splitter = PersistentGripSplitter(Qt.Vertical)", source)
        self.assertIn("self.session_workspace_splitter.addWidget(self.session_scroll)", source)
        self.assertIn("self.session_workspace_splitter.addWidget(self.workspace_host)", source)
        self.assertIn("self.session_workspace_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("self.session_workspace_splitter.setHandleWidth(12)", source)
        self.assertIn("self.session_workspace_splitter.setSizes([235, 665])", source)

    def test_upper_context_is_scrollable_when_compressed(self):
        source = _segment("init_ui")
        self.assertIn("self.session_scroll = QScrollArea()", source)
        self.assertIn("self.session_scroll.setWidgetResizable(True)", source)
        self.assertIn("self.session_scroll.setWidget(self.session_panel)", source)

    def test_primary_workspace_is_horizontal_submission_and_grading_split(self):
        source = _segment("init_ui")
        self.assertIn("self.workspace_splitter = PersistentGripSplitter(Qt.Horizontal)", source)
        self.assertIn("self.workspace_splitter.addWidget(self.submission_workspace)", source)
        self.assertIn("self.workspace_splitter.addWidget(self.grading_workspace)", source)
        self.assertIn("self.workspace_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("self.workspace_splitter.setHandleWidth(12)", source)

    def test_splitters_use_persistent_custom_grip_handle(self):
        self.assertIn("class GripSplitterHandle(QSplitterHandle)", _SOURCE)
        self.assertIn("class PersistentGripSplitter(QSplitter)", _SOURCE)
        self.assertIn('self.setToolTip("Drag to resize")', _SOURCE)
        self.assertIn('QColor("#667085")', _SOURCE)
        self.assertIn("createHandle", _SOURCE)

    def test_submission_and_grading_have_useful_minimum_widths(self):
        source = _segment("init_ui")
        self.assertIn("self.submission_workspace.setMinimumWidth(460)", source)
        self.assertIn("self.grading_workspace.setMinimumWidth(420)", source)
        self.assertIn("self.workspace_splitter.setSizes([760, 640])", source)

    def test_grading_area_retains_independent_vertical_summary_splitter(self):
        source = _segment("init_ui")
        self.assertIn("self.main_splitter = PersistentGripSplitter(Qt.Vertical)", source)
        self.assertIn("self.main_splitter.addWidget(self.scroll_area)", source)
        self.assertIn("self.main_splitter.addWidget(self.summary_container)", source)
        self.assertIn("self.main_splitter.setChildrenCollapsible(False)", source)

    def test_question_summary_still_exists_and_is_collapsible(self):
        source = _segment("init_ui")
        self.assertIn('"Question Scores Summary", collapsible=True, initially_collapsed=True', source)
        self.assertIn("self.question_summary_layout", source)

    def test_question_summary_show_hide_resizes_summary_pane(self):
        source = _segment("_on_question_summary_collapsed_changed")
        self.assertIn("summary_height = 58", source)
        self.assertIn("summary_height = min(280, max(190, total // 3))", source)
        self.assertIn("splitter.setSizes([criteria_height, summary_height])", source)
        init = _segment("init_ui")
        self.assertIn("question_summary_card.collapsed_changed.connect", init)

    def test_grading_pane_has_compact_question_aware_heading(self):
        source = _segment("init_ui")
        self.assertIn('self.grading_pane_title = QLabel("Grading"', source)
        notify = _segment("_notify_submission_context_changed")
        self.assertIn('self.grading_pane_title.setText(f"Grading — {self.current_question_id}")', notify)

    def test_submission_workspace_no_longer_persists_internal_text_splitter(self):
        workspace_source = (_REPO_ROOT / "src" / "ui" / "widgets" / "submission_workspace.py").read_text(encoding="utf-8")
        self.assertNotIn("self.splitter = QSplitter", workspace_source)
        self.assertNotIn("SubmissionTextPanel", workspace_source)

    def test_ui_preferences_save_all_three_splitter_states(self):
        source = _segment("_save_ui_preferences")
        self.assertIn("saveGeometry()", source)
        self.assertIn("session_workspace_splitter.saveState()", source)
        self.assertIn("workspace_splitter.saveState()", source)
        self.assertIn("main_splitter.saveState()", source)
        self.assertIn("question_summary_card.is_collapsed()", source)
        self.assertIn("isMaximized()", source)

    def test_restore_enforces_splitter_orientations_after_saved_state(self):
        source = _segment("_restore_ui_preferences")
        self.assertIn("session_workspace_splitter.restoreState", source)
        self.assertIn("workspace_splitter.restoreState", source)
        self.assertIn("main_splitter.restoreState", source)
        self.assertIn("self.session_workspace_splitter.setOrientation(Qt.Vertical)", source)
        self.assertIn("self.workspace_splitter.setOrientation(Qt.Horizontal)", source)
        self.assertIn("self.main_splitter.setOrientation(Qt.Vertical)", source)

    def test_workspace_uses_versioned_settings_key_to_ignore_legacy_orientation(self):
        self.assertIn('_UI_WORKSPACE_SPLITTER_KEY = "workspace_splitter_horizontal_v2"', _SOURCE)
        self.assertIn('_UI_SESSION_SPLITTER_KEY = "session_workspace_splitter_v2"', _SOURCE)

    def test_preferences_are_restored_after_widgets_exist(self):
        init = _segment("__init__")
        self.assertLess(init.index("self.init_ui()"), init.index("self._restore_ui_preferences()"))

    def test_close_path_reattaches_popout_then_persists(self):
        finalize = _segment("_finalize_window_close")
        self.assertIn("_reattach_grading_workspace", finalize)
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

    def test_restored_bad_splitter_sizes_are_normalized_for_both_axes(self):
        ensure = _segment("_ensure_usable_splitter_sizes")
        self.assertIn("minimums=(140, 320)", ensure)
        self.assertIn("fallback=(235, 665)", ensure)
        self.assertIn("minimums=(460, 420)", ensure)
        self.assertIn("fallback=(760, 640)", ensure)

    def test_primary_toolbar_groups_reports_and_settings_in_menus(self):
        source = _segment("init_ui")
        self.assertIn("self.reports_menu_button", source)
        self.assertIn("self.settings_menu_button", source)
        self.assertIn("QToolButton.InstantPopup", source)
        self.assertIn("Submission & AI Settings", source)

    def test_grading_summary_is_collapsible_and_collapsed_by_default(self):
        source = _segment("init_ui")
        self.assertIn(
            'CardWidget("Grading", collapsible=True, initially_collapsed=True)',
            source,
        )

    def test_focus_mode_temporarily_hides_context_and_right_grading_pane(self):
        source = _segment("_on_submission_focus_requested")
        self.assertIn("self.session_scroll.setVisible(False)", source)
        self.assertIn("self.grading_workspace.setVisible(False)", source)
        self.assertIn("self.session_scroll.setVisible(True)", source)
        self.assertIn("self.grading_workspace.setVisible(True)", source)
        self.assertIn("self._session_sizes_before_focus", source)

    def test_popout_reparents_exact_horizontal_workspace_not_a_copy(self):
        popout = _segment("_pop_out_grading_workspace")
        self.assertIn("self.workspace_host_layout.removeWidget(self.workspace_splitter)", popout)
        self.assertIn("self.workspace_splitter.setParent(dialog)", popout)
        self.assertIn("dialog_layout.addWidget(self.workspace_splitter, 1)", popout)
        self.assertNotIn("SubmissionWorkspace(dialog", popout)
        reattach = _segment("_reattach_grading_workspace")
        self.assertIn("self.workspace_splitter.setParent(self.workspace_host)", reattach)
        self.assertIn("self.workspace_host_layout.insertWidget(0, self.workspace_splitter)", reattach)

    def test_popout_has_navigation_save_and_reattach_controls(self):
        popout = _segment("_pop_out_grading_workspace")
        for label in ("Previous Question", "Next Question", "Previous Student", "Next Student", "Save", "Reattach"):
            self.assertIn(label, popout)
        self.assertIn("save_and_next_student", popout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
