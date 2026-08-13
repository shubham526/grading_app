"""Pure/headless tests for the Commit-5 submission controller."""

import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import importlib.util

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from src.submissions import FULL_SUBMISSION, ParsedSubmission

# Load the Qt-free controller directly from its file.  Importing
# ``src.ui.submission_controller`` through the package would execute the
# legacy ``src.ui.__init__`` first, which imports the PyQt main window and
# defeats this test's headless contract.
_CONTROLLER_PATH = Path(_REPO_ROOT) / "src" / "ui" / "submission_controller.py"
_SPEC = importlib.util.spec_from_file_location(
    "grading_app_submission_controller_testmod",
    _CONTROLLER_PATH,
)
_CONTROLLER_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_CONTROLLER_MODULE)
SubmissionController = _CONTROLLER_MODULE.SubmissionController
DEFAULT_EVIDENCE_DIRNAME = _CONTROLLER_MODULE.DEFAULT_EVIDENCE_DIRNAME


def _parsed(student_id="alice", *, answer="answer", mode="latex", accommodation=False):
    return ParsedSubmission(
        student_id=student_id,
        source_used="pdf" if accommodation else "latex",
        raw_text=answer,
        answers_by_question={"Q1": answer},
        files={"pdf" if accommodation else "latex": f"/{student_id}/source"},
        warnings=[],
        metadata={"question_split_status": "success"},
        submission_mode=mode,
        accommodation_mode=accommodation,
    )


class TestSubmissionControllerConfiguration(unittest.TestCase):

    def test_assessment_dir_maps_to_submission_evidence_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = SubmissionController()
            root = controller.set_assessments_dir(tmp)
            self.assertEqual(
                root,
                str((Path(tmp).resolve() / DEFAULT_EVIDENCE_DIRNAME)),
            )
            self.assertFalse(Path(root).exists(), "configuration should not create evidence eagerly")

    def test_question_ids_are_deduplicated_in_order(self):
        controller = SubmissionController(question_ids=["Q1", "Q2", "Q1", "", "Q3"])
        self.assertEqual(controller.question_ids, ("Q1", "Q2", "Q3"))

    def test_clear_keeps_configuration_by_default(self):
        controller = SubmissionController(question_ids=["Q1"], evidence_root="/tmp/evidence")
        controller.register_submission(_parsed())
        controller.activate_student("alice", load_persisted=False)
        controller.set_current_question("Q1")

        controller.clear()

        self.assertEqual(controller.question_ids, ("Q1",))
        self.assertTrue(controller.evidence_root.endswith("/tmp/evidence"))
        self.assertIsNone(controller.current_submission)
        self.assertEqual(controller.submissions, {})


class TestSubmissionControllerRegistration(unittest.TestCase):

    def test_register_and_activate_normalizes_student_id(self):
        parsed = _parsed("alice")
        controller = SubmissionController()
        controller.register_submission(parsed, student_id=" Alice ")
        active = controller.activate_student("ALICE", load_persisted=False)
        self.assertIs(active, parsed)
        self.assertEqual(controller.current_student_id, "alice")

    def test_registration_key_must_match_parsed_student(self):
        controller = SubmissionController()
        with self.assertRaises(ValueError):
            controller.register_submission(_parsed("alice"), student_id="bob")

    def test_replace_false_rejects_existing_submission(self):
        controller = SubmissionController()
        controller.register_submission(_parsed("alice"))
        with self.assertRaises(ValueError):
            controller.register_submission(_parsed("alice", answer="new"), replace=False)

    def test_batch_registration_remembers_submission_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = SubmissionController()
            result = controller.register_submissions(
                {"alice": _parsed("alice"), "bob": _parsed("bob")},
                submissions_dir=tmp,
            )
            self.assertEqual(set(result), {"alice", "bob"})
            self.assertEqual(controller.submissions_dir, str(Path(tmp).resolve()))


class TestSubmissionControllerPersistentLoading(unittest.TestCase):

    def test_activate_student_lazily_loads_persisted_evidence(self):
        persisted = _parsed("alice", answer="cached")
        loader = Mock(return_value=persisted)
        controller = SubmissionController(
            evidence_root="/tmp/evidence",
            load_persisted_fn=loader,
        )

        result = controller.activate_student("alice", load_persisted=True)

        self.assertIs(result, persisted)
        loader.assert_called_once_with(
            str(Path("/tmp/evidence").resolve()),
            "alice",
            verify_hashes=True,
        )
        self.assertIs(controller.current_submission, persisted)

    def test_missing_persisted_evidence_is_normal_optional_state(self):
        loader = Mock(side_effect=FileNotFoundError("missing"))
        controller = SubmissionController(
            evidence_root="/tmp/evidence",
            load_persisted_fn=loader,
        )
        self.assertIsNone(controller.activate_student("alice", load_persisted=True))
        self.assertEqual(controller.current_student_id, "alice")


class TestSubmissionControllerAnswers(unittest.TestCase):

    def test_current_answer_tracks_question(self):
        parsed = _parsed("alice")
        parsed.answers_by_question = {"Q1": "one", "Q2": "two"}
        controller = SubmissionController()
        controller.register_submission(parsed)
        controller.activate_student("alice", load_persisted=False)
        controller.set_current_question("Q2")
        self.assertEqual(controller.current_answer(), "two")

    def test_full_submission_fallback_is_explicit(self):
        parsed = _parsed("alice")
        parsed.answers_by_question = {FULL_SUBMISSION: "whole file"}
        controller = SubmissionController()
        controller.register_submission(parsed)
        controller.activate_student("alice", load_persisted=False)
        controller.set_current_question("Q1")

        self.assertIsNone(controller.current_answer())
        self.assertEqual(
            controller.current_answer(allow_full_submission_fallback=True),
            "whole file",
        )


class TestSubmissionControllerAssessmentBridge(unittest.TestCase):

    def test_merge_submission_fields_does_not_mutate_grading_data(self):
        parsed = _parsed("alice", answer="student answer")
        fields_fn = Mock(return_value={
            "submission_meta": {"student_id": "alice", "source_used": "latex"},
            "extracted_answers": {"Q1": "student answer"},
        })
        controller = SubmissionController(assessment_fields_fn=fields_fn)
        controller.register_submission(parsed)
        controller.activate_student("alice", load_persisted=False)

        original = {
            "student_id": "alice",
            "criteria": [{"id": "C1", "points_awarded": 7}],
            "total_awarded": 7,
        }
        untouched = deepcopy(original)
        merged = controller.merge_submission_fields(original)

        self.assertEqual(original, untouched)
        self.assertEqual(merged["criteria"], original["criteria"])
        self.assertEqual(merged["total_awarded"], 7)
        self.assertEqual(merged["extracted_answers"]["Q1"], "student answer")
        fields_fn.assert_called_once_with(parsed)

    def test_merge_without_loaded_submission_leaves_assessment_unchanged(self):
        controller = SubmissionController()
        assessment = {"criteria": [{"id": "C1", "points_awarded": 3}]}
        merged = controller.merge_submission_fields(assessment, student_id="alice")
        self.assertEqual(merged, assessment)
        self.assertIsNot(merged, assessment)

    def test_restore_prefers_persisted_evidence_dir_from_assessment(self):
        persisted = _parsed("alice", answer="persisted")
        loader = Mock(return_value=persisted)
        controller = SubmissionController(load_persisted_fn=loader)
        with tempfile.TemporaryDirectory() as tmp:
            student_dir = Path(tmp) / "alice"
            assessment = {
                "student_id": "alice",
                "submission_meta": {
                    "student_id": "alice",
                    "evidence_dir": str(student_dir),
                    "source_used": "latex",
                    "submission_mode": "latex",
                },
                "extracted_answers": {"Q1": "assessment copy"},
            }
            result = controller.restore_from_assessment(assessment)

        self.assertIs(result, persisted)
        loader.assert_called_once_with(str(Path(tmp).resolve()), "alice", verify_hashes=True)
        self.assertEqual(controller.current_student_id, "alice")

    def test_restore_falls_back_to_assessment_json_when_bundle_missing(self):
        loader = Mock(side_effect=FileNotFoundError("missing"))
        controller = SubmissionController(load_persisted_fn=loader)
        with tempfile.TemporaryDirectory() as tmp:
            assessment = {
                "student_id": "alice",
                "submission_meta": {
                    "student_id": "alice",
                    "evidence_dir": str(Path(tmp) / "alice"),
                    "source_used": "pdf",
                    "submission_mode": "pdf_accommodation",
                    "accommodation_mode": True,
                    "files": {"pdf": "/missing/original.pdf"},
                    "warnings": ["pdf_may_be_image_only"],
                },
                "extracted_answers": {"Q1": "saved answer"},
            }
            result = controller.restore_from_assessment(assessment)

        self.assertIsNotNone(result)
        self.assertEqual(result.get_answer("Q1"), "saved answer")
        self.assertTrue(result.accommodation_mode)
        self.assertIn("persisted_evidence_unavailable", result.warnings)
        self.assertTrue(result.metadata["evidence"]["loaded_from_assessment_json"])


class TestSubmissionControllerParseDelegation(unittest.TestCase):

    def test_normal_parse_uses_controller_questions_and_evidence_root(self):
        parser = Mock(return_value={"alice": _parsed("alice")})
        controller = SubmissionController(
            question_ids=["Q1", "Q2"],
            evidence_root="/tmp/evidence",
            parse_folder_fn=parser,
        )
        result = controller.parse_normal_submissions("/tmp/submissions")
        self.assertIn("alice", result)
        parser.assert_called_once_with(
            "/tmp/submissions",
            ("Q1", "Q2"),
            compile_pdf=True,
            compilation_dir=None,
            compiler_options=None,
            evidence_dir=str(Path("/tmp/evidence").resolve()),
        )

    def test_pdf_parse_requires_explicit_student_and_does_not_auto_register(self):
        parsed = _parsed(
            "alice",
            answer="handwriting",
            mode="pdf_accommodation",
            accommodation=True,
        )
        parser = Mock(return_value=parsed)
        controller = SubmissionController(
            question_ids=["Q1"],
            evidence_root="/tmp/evidence",
            parse_pdf_fn=parser,
        )
        result = controller.parse_pdf_accommodation("alice", "/tmp/a.pdf")

        self.assertIs(result, parsed)
        self.assertEqual(controller.submissions, {})
        args, kwargs = parser.call_args
        self.assertEqual(args, ("/tmp/a.pdf", ("Q1",)))
        self.assertEqual(kwargs["student_id"], "alice")
        self.assertFalse(kwargs["transcribe_handwriting"])
        self.assertEqual(kwargs["evidence_dir"], str(Path("/tmp/evidence").resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
