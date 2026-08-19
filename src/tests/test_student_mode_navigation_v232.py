"""Regression coverage for v2.3.2 Student-by-student roster navigation."""

import ast
from pathlib import Path
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PATH = _REPO_ROOT / "src" / "ui" / "main_window.py"
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


class TestStudentModeNavigationV232(unittest.TestCase):

    def test_student_navigation_controls_are_shared_by_both_workflows(self):
        source = _segment("init_ui")
        self.assertIn("self.student_navigation_controls = QWidget()", source)
        self.assertIn("self.student_combo = VisibleArrowComboBox()", source)
        self.assertIn('self.prev_student_btn = QPushButton("‹")', source)
        self.assertIn('self.next_student_btn = QPushButton("›")', source)
        self.assertIn("workflow_layout.addWidget(self.student_navigation_controls)", source)

    def test_student_mode_has_full_assessment_save_and_next_action(self):
        source = _segment("init_ui")
        self.assertIn('self.save_next_assessment_btn = QPushButton("Save + Next Student")', source)
        self.assertIn(
            "self.save_next_assessment_btn.clicked.connect(self.save_and_next_student_assessment)",
            source,
        )
        method = _segment("save_and_next_student_assessment")
        self.assertIn("self.save_assessment(show_success=False)", method)
        self.assertIn("self._move_student_after_save(1)", method)

    def test_student_mode_loader_restores_whole_assessment_and_submission_evidence(self):
        source = _segment("load_student_mode_student")
        self.assertIn("self._read_assessment_file(record.assessment_path)", source)
        self.assertIn("self._apply_assessment_to_widgets", source)
        self.assertIn("show_all_criteria(self)", source)
        self.assertIn("self._sync_submission_context(existing, load_persisted=True)", source)
        self.assertIn("self.student_mode_dirty = False", source)

    def test_combo_navigation_works_in_student_mode_and_saves_dirty_progress(self):
        source = _segment("on_student_combo_changed")
        self.assertNotIn("self.workflow_mode != QUESTION_CENTRIC", source)
        self.assertIn("elif self.student_mode_dirty and not self.save_assessment(show_success=False)", source)
        self.assertIn("self.load_student_mode_student(new_index)", source)

    def test_previous_next_navigation_works_in_student_mode_and_saves_dirty_progress(self):
        source = _segment("navigate_student")
        self.assertNotIn("self.workflow_mode != QUESTION_CENTRIC", source)
        self.assertIn("elif self.student_mode_dirty and not self.save_assessment(show_success=False)", source)
        self.assertIn("self.load_student_mode_student(target)", source)

    def test_student_mode_changes_are_tracked_as_dirty(self):
        self.assertIn("self.student_mode_dirty = True", _segment("on_criterion_points_changed"))
        self.assertIn("self.student_mode_dirty = True", _segment("on_criterion_content_changed"))
        self.assertIn("self.student_mode_dirty = True", _segment("on_question_selection_changed"))

    def test_full_save_allows_incomplete_progress_in_both_workflows(self):
        source = _segment("_build_complete_current_assessment")
        self.assertIn("get_assessment_data(self, validate=False)", source)
        self.assertIn('assessment_data["student_id"] = record.student_id', source)

    def test_student_mode_close_prompts_to_persist_dirty_assessment(self):
        source = _segment("closeEvent")
        self.assertIn("self.workflow_mode == STUDENT_CENTRIC and self.student_mode_dirty", source)
        self.assertIn("self.save_assessment(show_success=False)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
