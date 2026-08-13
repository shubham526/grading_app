"""Regression tests for issues found during the Commit-5 hands-on UI pass."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
_STYLE_PATH = _REPO_ROOT / "src" / "utils" / "styles.py"
_CONFIG_PATH = _REPO_ROOT / "src" / "ui" / "dialogs" / "config.py"

_MAIN_SOURCE = _MAIN_PATH.read_text(encoding="utf-8")
_MAIN_TREE = ast.parse(_MAIN_SOURCE)


def _class():
    return next(
        node for node in _MAIN_TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "RubricGrader"
    )


def _method(name):
    return next(
        node for node in _class().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _segment(name):
    return ast.get_source_segment(_MAIN_SOURCE, _method(name)) or ""


class TestManualAcceptanceRegressions(unittest.TestCase):

    def test_empty_assessment_workspace_is_non_modal(self):
        source = _segment("load_assessment_folder")
        self.assertNotIn("No Existing Assessments", source)
        self.assertNotIn("QMessageBox.information", source)
        self.assertIn("Assessment workspace ready", source)
        self.assertIn("load a roster or submissions to begin", source)

    def test_question_mode_controls_use_two_compact_rows(self):
        source = _segment("init_ui")
        self.assertIn("question_row = QHBoxLayout()", source)
        self.assertIn("student_row = QHBoxLayout()", source)
        self.assertIn("question_mode_layout.addLayout(question_row)", source)
        self.assertIn("question_mode_layout.addLayout(student_row)", source)
        self.assertNotIn("question_mode_layout.addLayout(action_row)", source)

    def test_question_mode_actions_share_student_row(self):
        source = _segment("init_ui")
        self.assertIn("student_row.addWidget(self.save_question_btn)", source)
        self.assertIn("student_row.addWidget(self.save_next_student_btn)", source)
        self.assertIn("student_row.addWidget(self.mark_question_complete_btn)", source)
        self.assertIn('QPushButton("Save + Next")', source)
        self.assertIn('QPushButton("Mark Complete")', source)

    def test_question_mode_card_uses_size_hint_stabilization(self):
        source = _segment("apply_current_workflow_view")
        self.assertIn("self.question_mode_controls.setMinimumHeight(92)", source)
        self.assertIn("self.workflow_card.setMinimumHeight(206)", source)
        self.assertIn("central_layout.invalidate()", source)
        self.assertIn("central_layout.activate()", source)
        self.assertIn("QTimer.singleShot(0, self._stabilize_question_mode_layout)", source)

        stabilizer = _segment("_stabilize_question_mode_layout")
        self.assertIn("self.question_mode_controls.sizeHint().height()", stabilizer)
        self.assertIn("self.workflow_card.sizeHint().height()", stabilizer)

    def test_question_mode_has_gap_before_questions_attempted_group(self):
        source = _segment("init_ui")
        self.assertIn("main_layout.addSpacing(6)", source)

    def test_light_theme_forces_fusion_and_legible_editors(self):
        source = _STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn('QStyleFactory.create("Fusion")', source)
        self.assertIn("background-color: #FFFFFF", source)
        self.assertIn("color: #1F2937", source)

    def test_visible_arrow_widgets_paint_their_own_indicators(self):
        source = _STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn("class VisibleArrowComboBox", source)
        self.assertIn("class VisibleArrowSpinBox", source)
        self.assertGreaterEqual(source.count("painter.drawPolygon"), 3)

    def test_config_dialog_uses_visible_arrow_controls(self):
        source = _CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn("VisibleArrowComboBox", source)
        self.assertIn("VisibleArrowSpinBox", source)
        self.assertIn("QAbstractSpinBox.UpDownArrows", source)

    def test_main_workflow_uses_visible_arrow_combos(self):
        source = _segment("init_ui")
        self.assertIn("self.workflow_mode_combo = VisibleArrowComboBox()", source)
        self.assertIn("self.question_combo = VisibleArrowComboBox()", source)
        self.assertIn("self.student_combo = VisibleArrowComboBox()", source)

    def test_config_initial_fixed_total_matches_question_count_times_points(self):
        source = _CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn("self.update_fixed_total()", source)
        self.assertIn("self.questions_to_count.value() * self.points_per_question.value()", source)


    def test_grades_and_evidence_folder_label_is_unambiguous(self):
        source = _segment("init_ui")
        self.assertIn('QPushButton("Grades & Evidence Folder")', source)
        self.assertIn("assessment JSON files and persistent submission evidence", source)

    def test_small_rubric_clamps_stale_generic_fixed_total(self):
        source = _segment("load_rubric")
        self.assertIn('question_count = max(1, len(self.question_groups))', source)
        self.assertIn('self.grading_config["questions_to_count"] = question_count', source)
        self.assertIn('question_count * self.grading_config["points_per_question"]', source)

    def test_attempted_questions_are_opt_in_from_compact_context(self):
        source = _segment("init_ui")
        self.assertIn('self.attempted_questions_button.setText("Attempted Questions")', source)
        self.assertIn("self.attempted_questions_button.setChecked(False)", source)
        toggle = _segment("_set_questions_attempted_visible")
        self.assertIn("question_selection_group.setVisible", toggle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
