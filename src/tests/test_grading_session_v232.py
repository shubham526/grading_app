"""Regression tests for resumable grading-session checkpoints."""

import json
from pathlib import Path
import tempfile
import unittest

from src.grading_session import (
    GRADING_SESSION_DIRNAME,
    GradingSessionCheckpoint,
    clear_grading_session_checkpoint,
    grading_session_path,
    load_grading_session_checkpoint,
    save_grading_session_checkpoint,
)


class TestGradingSessionCheckpoint(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_preserves_exact_question_and_student(self):
        saved = save_grading_session_checkpoint(
            self.workspace,
            "PS1",
            "Q4",
            "student005",
        )
        loaded = load_grading_session_checkpoint(self.workspace, "PS1")

        self.assertIsInstance(loaded, GradingSessionCheckpoint)
        self.assertEqual(loaded.assessment_id, "PS1")
        self.assertEqual(loaded.question_id, "Q4")
        self.assertEqual(loaded.student_id, "student005")
        self.assertEqual(loaded.saved_at, saved.saved_at)

    def test_checkpoints_are_scoped_per_assessment_in_same_workspace(self):
        save_grading_session_checkpoint(self.workspace, "PS1", "Q4", "alice")
        save_grading_session_checkpoint(self.workspace, "PS2", "Q2", "bob")

        ps1 = load_grading_session_checkpoint(self.workspace, "PS1")
        ps2 = load_grading_session_checkpoint(self.workspace, "PS2")

        self.assertEqual((ps1.question_id, ps1.student_id), ("Q4", "alice"))
        self.assertEqual((ps2.question_id, ps2.student_id), ("Q2", "bob"))
        self.assertNotEqual(
            grading_session_path(self.workspace, "PS1"),
            grading_session_path(self.workspace, "PS2"),
        )

    def test_checkpoint_is_written_under_hidden_workspace_metadata_directory(self):
        save_grading_session_checkpoint(self.workspace, "PS1", "Q1", "alice")
        path = grading_session_path(self.workspace, "PS1")

        self.assertEqual(path.parent.name, GRADING_SESSION_DIRNAME)
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["assessment_id"], "PS1")

    def test_malformed_checkpoint_is_ignored_instead_of_blocking_grading(self):
        path = grading_session_path(self.workspace, "PS1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")

        self.assertIsNone(load_grading_session_checkpoint(self.workspace, "PS1"))

    def test_clear_removes_only_requested_assessment_checkpoint(self):
        save_grading_session_checkpoint(self.workspace, "PS1", "Q1", "alice")
        save_grading_session_checkpoint(self.workspace, "PS2", "Q1", "alice")

        self.assertTrue(clear_grading_session_checkpoint(self.workspace, "PS1"))
        self.assertIsNone(load_grading_session_checkpoint(self.workspace, "PS1"))
        self.assertIsNotNone(load_grading_session_checkpoint(self.workspace, "PS2"))
        self.assertFalse(clear_grading_session_checkpoint(self.workspace, "PS1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
