"""Source-level regression coverage for question-mode save/resume UX."""

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


class TestQuestionModeSaveResumeV232(unittest.TestCase):

    def test_save_assessment_no_longer_routes_to_question_only_save(self):
        source = _segment("save_assessment")
        self.assertNotIn("save_current_question", source)
        self.assertIn("_build_complete_current_assessment", source)
        self.assertIn("_current_assessment_save_path", source)
        self.assertIn("_write_complete_assessment", source)

    def test_question_mode_full_snapshot_allows_incomplete_progress(self):
        source = _segment("_build_complete_current_assessment")
        self.assertIn("validate=(self.workflow_mode != QUESTION_CENTRIC)", source)
        self.assertIn("update_grading_progress_metadata", source)
        self.assertIn("question_id=self.current_question_id", source)

    def test_save_assessment_as_is_explicit_and_uses_file_chooser(self):
        source = _segment("save_assessment_as")
        self.assertIn('"Save Assessment As"', source)
        self.assertIn("QFileDialog.getSaveFileName", source)
        self.assertIn("_write_complete_assessment", source)

    def test_question_controls_are_unambiguous(self):
        self.assertIn('QPushButton("Save Question")', _SOURCE)
        self.assertIn('QPushButton("Save Assessment As…")', _SOURCE)
        self.assertIn('QPushButton("Save Assessment")', _SOURCE)

    def test_question_save_and_navigation_update_resume_checkpoint(self):
        self.assertIn("_write_grading_session_checkpoint()", _segment("save_current_question"))
        self.assertIn("_write_grading_session_checkpoint()", _segment("on_student_combo_changed"))
        self.assertIn("_write_grading_session_checkpoint()", _segment("navigate_student"))
        self.assertIn("_write_grading_session_checkpoint()", _segment("on_question_combo_changed"))
        self.assertIn("_write_grading_session_checkpoint()", _segment("navigate_question"))

    def test_resume_restores_workflow_question_and_student(self):
        source = _segment("_restore_grading_session_checkpoint")
        self.assertIn("self.workflow_mode = QUESTION_CENTRIC", source)
        self.assertIn("self.current_question_id = checkpoint.question_id", source)
        self.assertIn("self.current_student_index = student_index", source)
        self.assertIn("self.apply_current_workflow_view()", source)

    def test_resume_is_offered_after_each_required_context_source_can_finish_loading(self):
        self.assertIn("_maybe_offer_resume_grading_session()", _segment("load_rubric"))
        self.assertIn("_maybe_offer_resume_grading_session()", _segment("load_assessment_folder"))
        self.assertIn("_maybe_offer_resume_grading_session()", _segment("load_roster"))


    def test_auto_resume_waits_for_roster_but_manual_question_mode_can_resume_without_one(self):
        offer = _segment("_maybe_offer_resume_grading_session")
        workflow = _segment("on_workflow_mode_changed")
        self.assertIn("not allow_without_roster and not self.roster_records", offer)
        self.assertIn("allow_without_roster=True", workflow)

    def test_tools_menu_exposes_manual_resume_action(self):
        self.assertIn('"Resume Grading Session"', _SOURCE)
        self.assertIn("self.resume_grading_session_action.triggered.connect", _SOURCE)

    def test_full_save_clears_question_dirty_state_only_after_successful_write(self):
        source = _segment("_write_complete_assessment")
        write_pos = source.index("json.dump")
        clear_pos = source.index("self.question_mode_dirty = False")
        self.assertLess(write_pos, clear_pos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
