"""Structural integration tests for the final Commit-5 main-window wiring.

These tests intentionally parse source rather than constructing the full desktop
window.  That keeps business-architecture checks independent from Qt display
availability while the dedicated widget tests exercise real Qt widgets.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_WINDOW = _REPO_ROOT / "src" / "ui" / "main_window.py"
_SOURCE = _MAIN_WINDOW.read_text(encoding="utf-8")


def _tree():
    return ast.parse(_SOURCE)


def _rubric_grader_class():
    for node in _tree().body:
        if isinstance(node, ast.ClassDef) and node.name == "RubricGrader":
            return node
    raise AssertionError("RubricGrader class not found")


def _method(name):
    for node in _rubric_grader_class().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"RubricGrader.{name} not found")


def _segment(name):
    return ast.get_source_segment(_SOURCE, _method(name)) or ""


def _called_attribute_names(node):
    return [
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    ]


class TestMainWindowSubmissionArchitecture(unittest.TestCase):

    def test_main_window_uses_controller_workspace_and_worker_layer(self):
        self.assertIn(
            "from src.ui.submission_controller import SubmissionController",
            _SOURCE,
        )
        self.assertIn(
            "from src.ui.widgets.submission_workspace import SubmissionWorkspace",
            _SOURCE,
        )
        self.assertIn(
            "from src.ui.workers.submission_worker import (",
            _SOURCE,
        )
        init = _method("__init__")
        called_names = {
            child.func.id
            for child in ast.walk(init)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        self.assertIn("SubmissionController", called_names)
        self.assertIn("load_submission_settings", called_names)

    def test_main_window_does_not_bypass_submission_backend_layers(self):
        forbidden = (
            "parse_submissions_folder(",
            "parse_pdf_accommodation(",
            "load_persisted_submission(",
            "OllamaTranscriptionBackend(",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, _SOURCE)

    def test_question_mode_student_load_synchronizes_submission_context(self):
        calls = _called_attribute_names(_method("load_question_mode_student"))
        self.assertIn("_sync_submission_context", calls)

    def test_question_navigation_updates_submission_question_context(self):
        for method_name in ("on_question_combo_changed", "navigate_question"):
            source = _segment(method_name)
            with self.subTest(method=method_name):
                self.assertIn("submission_controller.set_current_question", source)
                self.assertIn("_notify_submission_context_changed", source)

    def test_student_centric_workflow_clears_question_specific_evidence_context(self):
        source = _segment("apply_current_workflow_view")
        self.assertIn("submission_controller.set_current_question(None)", source)
        self.assertIn("_sync_submission_context(load_persisted=True)", source)

    def test_all_three_save_paths_attach_optional_submission_fields(self):
        # Question-level and autosave paths merge submission fields directly.
        for method_name in (
            "save_current_question",
            "auto_save_assessment",
        ):
            calls = _called_attribute_names(_method(method_name))
            with self.subTest(method=method_name):
                self.assertIn("_merge_current_submission_into_assessment", calls)

        # Full Save Assessment now delegates snapshot construction so its behavior
        # stays identical in student- and question-centric workflows.
        save_calls = _called_attribute_names(_method("save_assessment"))
        self.assertIn("_build_complete_current_assessment", save_calls)
        builder_calls = _called_attribute_names(_method("_build_complete_current_assessment"))
        self.assertIn("_merge_current_submission_into_assessment", builder_calls)

    def test_submission_merge_helper_cannot_touch_scoring_fields(self):
        source = _segment("_merge_current_submission_into_assessment")
        self.assertIn("submission_controller.merge_submission_fields", source)
        for scoring_field in (
            "points_awarded",
            "points_possible",
            "selected",
            "counted",
        ):
            self.assertNotIn(scoring_field, source)

    def test_explicit_pdf_flow_contains_no_reason_or_diagnosis_capture(self):
        source = _segment("add_pdf_accommodation").lower()
        self.assertIn("pdf accommodation", source)
        self.assertIn("authoritative evidence", source)
        self.assertNotIn("diagnosis", source)
        self.assertNotIn("medical reason", source)
        self.assertNotIn("accommodation reason", source)

    def test_manual_student_entry_refreshes_submission_context(self):
        source = _segment("_on_manual_student_context_changed")
        self.assertIn("STUDENT_CENTRIC", source)
        self.assertIn("_sync_submission_context", source)

    def test_student_centric_roster_context_prefers_stable_student_id(self):
        source = _segment("_active_submission_student_id")
        self.assertIn("_current_student_record", source)
        self.assertIn("record.student_id", source)
        self.assertIn("STUDENT_CENTRIC", source)

    def test_roster_and_assessment_folder_immediately_refresh_student_centric_evidence(self):
        for method_name in ("load_roster", "load_assessment_folder"):
            source = _segment(method_name)
            with self.subTest(method=method_name):
                self.assertIn("_sync_student_centric_record_context", source)

    def test_student_centric_sync_helper_does_not_modify_scores(self):
        source = _segment("_sync_student_centric_record_context")
        self.assertIn("_sync_submission_context", source)
        for scoring_field in ("points_awarded", "points_possible", "selected", "counted"):
            self.assertNotIn(scoring_field, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
