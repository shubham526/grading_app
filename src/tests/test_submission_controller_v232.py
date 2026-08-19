"""Tests for v2.3.2 Commit 6 canonical SubmissionController integration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from src.submissions import (
    CandidateFile,
    ParsedSubmission,
    SubmissionRepository,
    parse_submission,
)
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    SOURCE_SYSTEM_LOCAL_UPLOAD,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTROLLER_PATH = _REPO_ROOT / "src" / "ui" / "submission_controller.py"
_SPEC = importlib.util.spec_from_file_location(
    "submission_controller_v232_under_test",
    _CONTROLLER_PATH,
)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
SubmissionController = _MODULE.SubmissionController


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _candidate(path: Path, *, artifact_type: str = ARTIFACT_TYPE_TEX) -> CandidateFile:
    return CandidateFile(
        source_path=str(path),
        original_filename=path.name,
        artifact_type=artifact_type,
        role=ARTIFACT_ROLE_PRIMARY,
    )


def _parsed(student_id: str, answer: str = "A") -> ParsedSubmission:
    return ParsedSubmission(
        student_id=student_id,
        source_used="latex",
        raw_text=answer,
        answers_by_question={"Q1": answer},
        files={},
    )


class TestCommit6ControllerConfiguration(unittest.TestCase):

    def test_repository_is_lazy_and_assessment_id_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "submission_evidence"
            controller = SubmissionController(evidence_root=str(root))

            self.assertFalse(root.exists())
            self.assertIsNone(controller.submission_repository)
            self.assertIsNone(controller.assessment_id)

            self.assertEqual(controller.set_assessment_id(" PS1 "), "PS1")
            self.assertEqual(controller.assessment_id, "PS1")
            self.assertFalse(root.exists())


    def test_changing_assessment_clears_student_parsed_cache(self):
        controller = SubmissionController()
        controller.set_assessment_id("PS1")
        controller.register_submission(_parsed("alice", "PS1 answer"))
        controller.activate_student("alice", load_persisted=False)
        self.assertIsNotNone(controller.current_submission)

        controller.set_assessment_id("PS2")

        self.assertIsNone(controller.current_submission)
        self.assertIsNone(
            controller.submission_for_student("alice", load_persisted=False)
        )

    def test_clear_without_configuration_removes_canonical_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = SubmissionController(
                evidence_root=str(Path(tmp) / "evidence"),
                question_ids=["Q1"],
            )
            controller.set_assessment_id("PS1")
            controller.clear(keep_configuration=False)

            self.assertIsNone(controller.evidence_root)
            self.assertIsNone(controller.assessment_id)
            self.assertIsNone(controller.submission_repository)
            self.assertEqual(controller.question_ids, ())


class TestCommit6CanonicalHistory(unittest.TestCase):

    def test_history_and_active_id_come_from_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            repo = SubmissionRepository(str(root))
            first_path = _write(Path(tmp) / "alice_v1.tex", "Question 1\nA")
            second_path = _write(Path(tmp) / "alice_v2.tex", "Question 1\nB")

            first = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(first_path)],
            )
            second = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(second_path)],
            )

            controller = SubmissionController(evidence_root=str(root))
            controller.set_assessment_id("PS1")

            history = controller.submission_history_for_student("Alice")

            self.assertEqual([item.submission_id for item in history], [first.submission_id, second.submission_id])
            self.assertFalse(history[0].is_active_attempt)
            self.assertTrue(history[1].is_active_attempt)
            self.assertEqual(
                controller.active_submission_id_for_student("alice"),
                second.submission_id,
            )

    def test_current_canonical_submission_tracks_active_student(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            repo = SubmissionRepository(str(root))
            tex = _write(Path(tmp) / "alice.tex", "Question 1\nA")
            submission = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(tex)],
            )

            controller = SubmissionController(evidence_root=str(root))
            controller.set_assessment_id("PS1")
            controller.activate_student("alice", load_persisted=False)

            current = controller.current_canonical_submission
            self.assertIsNotNone(current)
            self.assertEqual(current.submission_id, submission.submission_id)


class TestCommit6AttemptActivation(unittest.TestCase):

    def test_activate_submission_parses_before_switching_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            repo = SubmissionRepository(str(root))
            first_path = _write(Path(tmp) / "alice_v1.tex", "Question 1\nA")
            second_path = _write(Path(tmp) / "alice_v2.tex", "Question 1\nB")
            first = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(first_path)],
            )
            second = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(second_path)],
            )

            parser = Mock(return_value=_parsed("alice", "attempt one"))
            persist_link = Mock(return_value={})
            controller = SubmissionController(
                evidence_root=str(root),
                question_ids=["Q1"],
                parse_canonical_fn=parser,
                persist_canonical_link_fn=persist_link,
            )
            controller.set_assessment_id("PS1")

            parsed = controller.activate_submission("alice", first.submission_id)

            self.assertEqual(parsed.get_answer("Q1"), "attempt one")
            self.assertEqual(
                repo.get_active_submission("PS1", "alice").submission_id,
                first.submission_id,
            )
            self.assertEqual(controller.current_student_id, "alice")
            self.assertIs(controller.current_submission, parsed)
            self.assertEqual(
                parsed.metadata["canonical_submission"]["submission_id"],
                first.submission_id,
            )

            args, kwargs = parser.call_args
            self.assertEqual(args[0].submission_id, first.submission_id)
            self.assertEqual(args[2], ("Q1",))
            self.assertTrue(kwargs["verify_artifacts"])
            self.assertEqual(kwargs["evidence_dir"], str(root.resolve()))
            persist_link.assert_called()

            # Confirm the old active attempt really was different before switching.
            self.assertNotEqual(first.submission_id, second.submission_id)

    def test_parse_failure_does_not_change_repository_active_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            repo = SubmissionRepository(str(root))
            first_path = _write(Path(tmp) / "alice_v1.tex", "Question 1\nA")
            second_path = _write(Path(tmp) / "alice_v2.tex", "Question 1\nB")
            first = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(first_path)],
            )
            second = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(second_path)],
            )

            parser = Mock(side_effect=RuntimeError("parse failed"))
            controller = SubmissionController(
                evidence_root=str(root),
                parse_canonical_fn=parser,
            )
            controller.set_assessment_id("PS1")

            with self.assertRaises(RuntimeError):
                controller.activate_submission("alice", first.submission_id)

            active = repo.get_active_submission("PS1", "alice")
            self.assertEqual(active.submission_id, second.submission_id)

    def test_set_active_without_parse_clears_stale_parsed_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            repo = SubmissionRepository(str(root))
            first_path = _write(Path(tmp) / "alice_v1.tex", "Question 1\nA")
            second_path = _write(Path(tmp) / "alice_v2.tex", "Question 1\nB")
            first = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(first_path)],
            )
            second = repo.create_submission(
                assessment_id="PS1",
                student_id="alice",
                files=[_candidate(second_path)],
            )

            parsed = _parsed("alice", "B")
            parsed.metadata["canonical_submission"] = {
                "submission_id": second.submission_id,
                "assessment_id": "PS1",
                "student_id": "alice",
            }

            controller = SubmissionController(evidence_root=str(root))
            controller.set_assessment_id("PS1")
            controller.register_submission(parsed)

            controller.set_active_canonical_submission("alice", first.submission_id)

            self.assertIsNone(
                controller.submission_for_student("alice", load_persisted=False)
            )
            self.assertEqual(
                repo.get_active_submission("PS1", "alice").submission_id,
                first.submission_id,
            )


class TestCommit6LegacyMigrationOnLoad(unittest.TestCase):

    def test_loading_v22_evidence_migrates_and_persists_canonical_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            tex = root / "alice.tex"
            tex.write_text("Question 1\nA", encoding="utf-8")

            original = parse_submission(
                str(tex),
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )
            self.assertEqual(original.get_answer("Q1"), "A")

            controller = SubmissionController(
                evidence_root=str(evidence),
                question_ids=["Q1"],
            )
            controller.set_assessment_id("PS1")

            loaded = controller.activate_student("alice", load_persisted=True)

            self.assertIsNotNone(loaded)
            link = loaded.metadata.get("canonical_submission", {})
            self.assertTrue(link.get("submission_id"))
            self.assertEqual(link.get("assessment_id"), "PS1")
            self.assertEqual(link.get("attempt"), 1)

            history = controller.submission_history_for_student("alice")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].submission_id, link["submission_id"])

            # Restart: the legacy evidence now recovers the same canonical ID.
            restarted = SubmissionController(
                evidence_root=str(evidence),
                question_ids=["Q1"],
            )
            restarted.set_assessment_id("PS1")
            loaded_again = restarted.activate_student("alice", load_persisted=True)
            self.assertEqual(
                loaded_again.metadata["canonical_submission"]["submission_id"],
                link["submission_id"],
            )
            self.assertEqual(
                len(restarted.submission_history_for_student("alice")),
                1,
            )


    def test_switching_assessment_does_not_migrate_or_display_linked_legacy_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            tex = root / "alice_PS1.tex"
            tex.write_text("Question 1\nPS1 answer", encoding="utf-8")

            repository = SubmissionRepository(str(evidence))
            ps1 = repository.create_submission(
                assessment_id="PS1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                files=[_candidate(tex)],
            )
            # Canonical parsing persists the v2.2 compatibility bundle plus an
            # explicit PS1 canonical linkage in the student-only evidence path.
            from src.submissions import parse_canonical_submission
            parse_canonical_submission(
                ps1,
                repository,
                ["Q1"],
                compile_pdf=False,
                evidence_dir=str(evidence),
            )

            controller = SubmissionController(
                evidence_root=str(evidence),
                question_ids=["Q1"],
            )
            controller.set_assessment_id("PS1")
            loaded_ps1 = controller.activate_student("alice", load_persisted=True)
            self.assertIsNotNone(loaded_ps1)
            self.assertEqual(
                loaded_ps1.metadata["canonical_submission"]["assessment_id"],
                "PS1",
            )

            controller.set_assessment_id("PS2")
            loaded_ps2 = controller.activate_student("alice", load_persisted=True)

            self.assertIsNone(loaded_ps2)
            self.assertIsNone(controller.current_submission)
            self.assertEqual(repository.list_submissions("PS2", "alice"), [])

    def test_unsupported_future_artifact_is_valid_canonical_state_but_not_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            repo = SubmissionRepository(str(root))
            code = _write(Path(tmp) / "main.py", "print('hello')\n")
            submission = repo.create_submission(
                assessment_id="LAB1",
                student_id="alice",
                source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
                files=[_candidate(code, artifact_type=ARTIFACT_TYPE_PYTHON)],
            )

            controller = SubmissionController(evidence_root=str(root))
            controller.set_assessment_id("LAB1")

            parsed = controller.activate_student("alice", load_persisted=True)

            self.assertIsNone(parsed)
            current = controller.current_canonical_submission
            self.assertIsNotNone(current)
            self.assertEqual(current.submission_id, submission.submission_id)


class TestCommit6AssessmentRestore(unittest.TestCase):

    def test_fallback_assessment_json_restores_canonical_identity(self):
        loader = Mock(side_effect=FileNotFoundError("missing"))
        controller = SubmissionController(load_persisted_fn=loader)
        assessment = {
            "student_id": "alice",
            "assessment_id": "PS1",
            "submission_meta": {
                "student_id": "alice",
                "assessment_id": "PS1",
                "submission_id": "sub_saved",
                "attempt": 2,
                "source_system": "local_upload",
                "artifact_ids": ["art_1"],
                "source_used": "latex",
                "submission_mode": "latex",
            },
            "extracted_answers": {"Q1": "saved"},
        }

        parsed = controller.restore_from_assessment(assessment)

        self.assertIsNotNone(parsed)
        self.assertEqual(controller.assessment_id, "PS1")
        self.assertEqual(
            parsed.metadata["canonical_submission"]["submission_id"],
            "sub_saved",
        )
        self.assertEqual(parsed.get_answer("Q1"), "saved")


class TestCommit6MainWindowWiring(unittest.TestCase):

    def test_submission_context_sets_stable_assessment_id(self):
        source = (_REPO_ROOT / "src" / "ui" / "main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "self.submission_controller.set_assessment_id(assessment_id)",
            source,
        )
        self.assertIn('rubric.get("assessment_id")', source)
        self.assertIn('rubric.get("assignment_id")', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
