import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.similarity.report import generate_similarity_report
from src.similarity.sources import (
    SOURCE_ASSESSMENT_FOLDER,
    SOURCE_LOADED,
    SOURCE_SUBMISSIONS_FOLDER,
    collect_loaded_similarity_submissions,
    collect_similarity_assessment_folder,
    collect_similarity_source,
    collect_similarity_submissions_folder,
    infer_similarity_question_ids,
)
from src.submissions import FULL_SUBMISSION
from src.submissions.models import ParsedSubmission
from src.ui.submission_controller import SubmissionController


def parsed(student_id, answers, *, warnings=None, files=None, evidence=None):
    return ParsedSubmission(
        student_id=student_id,
        source_used="latex",
        raw_text="\n".join(answers.values()),
        answers_by_question=dict(answers),
        files=dict(files or {}),
        warnings=list(warnings or []),
        metadata={"evidence": dict(evidence or {})},
    )


def assessment(student_id, answers, *, evidence_dir=None, file_hashes=None):
    meta = {
        "student_id": student_id,
        "source_used": "latex",
        "submission_mode": "latex",
        "accommodation_mode": False,
        "files": {"latex": f"/missing/{student_id}.tex"},
        "file_hashes": dict(file_hashes or {}),
        "warnings": [],
    }
    if evidence_dir is not None:
        meta["evidence_dir"] = str(evidence_dir)

    return {
        "student_id": student_id,
        "student_name": student_id.title(),
        "criteria": [{"id": "C1", "points_awarded": 5}],
        "submission_meta": meta,
        "extracted_answers": dict(answers),
    }


class TestQuestionInference(unittest.TestCase):
    def test_preferred_question_order_wins(self):
        submissions = {
            "alice": parsed("alice", {"Q2": "two", "Q1": "one"}),
        }
        self.assertEqual(
            infer_similarity_question_ids(submissions, ["Q2", "Q1", "Q2"]),
            ["Q2", "Q1"],
        )

    def test_questions_are_inferred_from_loaded_answers(self):
        submissions = {
            "alice": parsed("alice", {"Q2": "two"}),
            "bob": parsed("bob", {"Q1": "one", FULL_SUBMISSION: "whole"}),
        }
        self.assertEqual(
            infer_similarity_question_ids(submissions),
            ["Q1", "Q2"],
        )


class TestLoadedSource(unittest.TestCase):
    def test_loaded_parsed_submissions_are_reused_without_copying(self):
        alice = parsed("alice", {"Q1": "answer"})
        result = collect_loaded_similarity_submissions(
            {"alice": alice},
            question_ids=["Q1"],
        )
        self.assertEqual(result.source_type, SOURCE_LOADED)
        self.assertIs(result.submissions["alice"], alice)
        self.assertEqual(result.question_ids, ["Q1"])

    def test_loaded_source_accepts_controller_snapshot(self):
        controller = SubmissionController(question_ids=["Q1"])
        alice = parsed("alice", {"Q1": "one"})
        bob = parsed("bob", {"Q1": "two"})
        controller.register_submissions({"alice": alice, "bob": bob})

        result = collect_loaded_similarity_submissions(
            controller.submissions,
            question_ids=controller.question_ids,
        )
        self.assertEqual(result.student_ids, ["alice", "bob"])
        self.assertIs(result.submissions["alice"], alice)

    def test_mapping_key_mismatch_is_warned_and_internal_id_is_used(self):
        alice = parsed("alice", {"Q1": "answer"})
        result = collect_loaded_similarity_submissions({"wrong": alice})
        self.assertEqual(result.student_ids, ["alice"])
        self.assertTrue(
            any(w.startswith("student_id_key_mismatch:") for w in result.warnings)
        )

    def test_duplicate_internal_student_id_is_not_silently_overwritten(self):
        first = parsed("alice", {"Q1": "first"})
        second = parsed("ALICE", {"Q1": "second"})
        result = collect_loaded_similarity_submissions(
            {"a": first, "b": second}
        )
        self.assertEqual(result.student_ids, ["alice"])
        self.assertIs(result.submissions["alice"], first)
        self.assertTrue(
            any(w.startswith("duplicate_student_id:") for w in result.warnings)
        )

    def test_empty_loaded_source_is_valid_with_warning(self):
        result = collect_loaded_similarity_submissions({})
        self.assertEqual(result.submissions, {})
        self.assertIn("no_loaded_submissions", result.warnings)

    def test_existing_submission_warning_is_propagated(self):
        result = collect_loaded_similarity_submissions(
            {
                "alice": parsed(
                    "alice",
                    {"Q1": "answer"},
                    warnings=["missing_answer_for_Q2"],
                )
            }
        )
        self.assertIn(
            "submission_warning:alice:missing_answer_for_Q2",
            result.warnings,
        )


class TestSubmissionsFolderSource(unittest.TestCase):
    def test_folder_source_delegates_to_v22_parser_without_compilation_or_persistence(self):
        parser = Mock(
            return_value={
                "alice": parsed("alice", {"Q1": "one"}),
                "bob": parsed("bob", {"Q1": "two"}),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_similarity_submissions_folder(
                tmp,
                question_ids=["Q1"],
                parse_folder_fn=parser,
            )
            resolved = str(Path(tmp).resolve())

        parser.assert_called_once_with(
            resolved,
            ["Q1"],
            compile_pdf=False,
            evidence_dir=None,
        )
        self.assertEqual(result.source_type, SOURCE_SUBMISSIONS_FOLDER)
        self.assertEqual(result.student_ids, ["alice", "bob"])
        self.assertEqual(result.question_ids, ["Q1"])

    def test_real_v22_parser_handles_normal_latex_folder_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for student, q1, q2 in [
                ("alice", "The runtime is linear.", "Proof by induction."),
                ("bob", "The runtime is linear.", "A different proof."),
            ]:
                student_dir = root / student
                student_dir.mkdir()
                (student_dir / "main.tex").write_text(
                    "\\documentclass{article}\n"
                    "\\begin{document}\n"
                    f"Question 1\n{q1}\n"
                    f"Question 2\n{q2}\n"
                    "\\end{document}\n",
                    encoding="utf-8",
                )

            result = collect_similarity_submissions_folder(
                str(root),
                question_ids=["Q1", "Q2"],
            )

        self.assertEqual(result.student_ids, ["alice", "bob"])
        self.assertEqual(
            result.submissions["alice"].answers_by_question["Q1"],
            "The runtime is linear.",
        )
        self.assertNotIn("compiled_pdf", result.submissions["alice"].files)

    def test_empty_normal_folder_is_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_similarity_submissions_folder(tmp)
        self.assertEqual(result.submissions, {})
        self.assertIn("no_normal_latex_submissions_found", result.warnings)


class TestAssessmentFolderSource(unittest.TestCase):
    def test_saved_assessment_json_is_loaded_as_similarity_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alice.json").write_text(
                json.dumps(assessment("alice", {"Q1": "one"})),
                encoding="utf-8",
            )
            (root / "bob.json").write_text(
                json.dumps(assessment("bob", {"Q1": "two"})),
                encoding="utf-8",
            )

            result = collect_similarity_assessment_folder(
                str(root),
                question_ids=["Q1"],
            )

        self.assertEqual(result.source_type, SOURCE_ASSESSMENT_FOLDER)
        self.assertEqual(result.student_ids, ["alice", "bob"])
        self.assertEqual(
            result.submissions["alice"]["extracted_answers"]["Q1"],
            "one",
        )

    def test_non_assessment_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "semester_report.json").write_text(
                json.dumps({"report_type": "semester_abet"}),
                encoding="utf-8",
            )
            (root / "alice.json").write_text(
                json.dumps(assessment("alice", {"Q1": "one"})),
                encoding="utf-8",
            )
            result = collect_similarity_assessment_folder(str(root))

        self.assertEqual(result.student_ids, ["alice"])
        self.assertFalse(
            any("semester_report.json" in warning for warning in result.warnings)
        )

    def test_malformed_json_warns_and_valid_students_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{ not valid json", encoding="utf-8")
            (root / "alice.json").write_text(
                json.dumps(assessment("alice", {"Q1": "one"})),
                encoding="utf-8",
            )

            result = collect_similarity_assessment_folder(str(root))

        self.assertEqual(result.student_ids, ["alice"])
        self.assertTrue(
            any(w.startswith("assessment_file_unreadable:bad.json") for w in result.warnings)
        )

    def test_assessment_without_submission_evidence_is_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alice.json").write_text(
                json.dumps(
                    {
                        "student_id": "alice",
                        "criteria": [{"id": "C1", "points_awarded": 5}],
                    }
                ),
                encoding="utf-8",
            )
            result = collect_similarity_assessment_folder(str(root))

        self.assertEqual(result.submissions, {})
        self.assertTrue(
            any(
                w.startswith("assessment_missing_submission_evidence:alice.json")
                for w in result.warnings
            )
        )
        self.assertIn("no_assessments_with_submission_evidence", result.warnings)

    def test_persisted_evidence_is_preferred_when_available(self):
        persisted = parsed("alice", {"Q1": "persisted answer"})
        loader = Mock(return_value=persisted)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_student = root / "submission_evidence" / "alice"
            payload = assessment(
                "alice",
                {"Q1": "assessment copy"},
                evidence_dir=evidence_student,
            )
            (root / "alice.json").write_text(json.dumps(payload), encoding="utf-8")

            result = collect_similarity_assessment_folder(
                str(root),
                load_persisted_fn=loader,
            )

        self.assertIs(result.submissions["alice"], persisted)
        loader.assert_called_once()
        args, kwargs = loader.call_args
        self.assertEqual(
            args[0],
            str((root / "submission_evidence").resolve()),
        )
        self.assertEqual(args[1], "alice")
        self.assertTrue(kwargs["verify_hashes"])

    def test_missing_persisted_bundle_falls_back_to_assessment_json(self):
        loader = Mock(side_effect=FileNotFoundError("missing"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_student = root / "submission_evidence" / "alice"
            payload = assessment(
                "alice",
                {"Q1": "saved fallback answer"},
                evidence_dir=evidence_student,
            )
            (root / "alice.json").write_text(json.dumps(payload), encoding="utf-8")

            result = collect_similarity_assessment_folder(
                str(root),
                load_persisted_fn=loader,
            )

        self.assertEqual(
            result.submissions["alice"]["extracted_answers"]["Q1"],
            "saved fallback answer",
        )
        self.assertTrue(
            any(w.startswith("persisted_evidence_unavailable:") for w in result.warnings)
        )

    def test_stored_hashes_survive_assessment_source_and_drive_exact_match(self):
        shared_hash = "f" * 64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alice.json").write_text(
                json.dumps(
                    assessment(
                        "alice",
                        {"Q1": "different answer alpha"},
                        file_hashes={"latex_sha256": shared_hash},
                    )
                ),
                encoding="utf-8",
            )
            (root / "bob.json").write_text(
                json.dumps(
                    assessment(
                        "bob",
                        {"Q1": "different answer beta"},
                        file_hashes={"latex_sha256": shared_hash},
                    )
                ),
                encoding="utf-8",
            )
            source = collect_similarity_assessment_folder(
                str(root),
                question_ids=["Q1"],
            )
            report = generate_similarity_report(
                source.submissions,
                "PS3",
                source.question_ids,
            )

        self.assertEqual(len(report.pairs), 1)
        self.assertTrue(report.pairs[0].exact_file_match)
        self.assertEqual(report.pairs[0].flag_level, "exact")


class TestSourceDispatcher(unittest.TestCase):
    def test_loaded_dispatch(self):
        result = collect_similarity_source(
            SOURCE_LOADED,
            loaded_submissions={"alice": parsed("alice", {"Q1": "one"})},
            question_ids=["Q1"],
        )
        self.assertEqual(result.student_ids, ["alice"])

    def test_submissions_folder_dispatch(self):
        parser = Mock(return_value={"alice": parsed("alice", {"Q1": "one"})})
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_similarity_source(
                SOURCE_SUBMISSIONS_FOLDER,
                path=tmp,
                question_ids=["Q1"],
                parse_folder_fn=parser,
            )
        self.assertEqual(result.student_ids, ["alice"])

    def test_assessment_folder_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alice.json").write_text(
                json.dumps(assessment("alice", {"Q1": "one"})),
                encoding="utf-8",
            )
            result = collect_similarity_source(
                SOURCE_ASSESSMENT_FOLDER,
                path=str(root),
                question_ids=["Q1"],
            )
        self.assertEqual(result.student_ids, ["alice"])

    def test_folder_sources_require_path(self):
        with self.assertRaises(ValueError):
            collect_similarity_source(SOURCE_SUBMISSIONS_FOLDER)
        with self.assertRaises(ValueError):
            collect_similarity_source(SOURCE_ASSESSMENT_FOLDER)

    def test_unknown_source_type_is_rejected(self):
        with self.assertRaises(ValueError):
            collect_similarity_source("mystery")


if __name__ == "__main__":
    unittest.main()
