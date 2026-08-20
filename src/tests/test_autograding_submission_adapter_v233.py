import tempfile
import unittest
from pathlib import Path

from src.autograding.config import AutogradingConfig
from src.autograding.errors import (
    CanonicalSubmissionIntegrityError,
    NoCanonicalSubmissionError,
    ProgrammingSubmissionContractError,
)
from src.autograding.submission_adapter import select_programming_submission
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    CandidateFile,
)
from src.submissions.routing import HANDLER_PROGRAMMING, ROUTE_PROGRAMMING_PYTHON, route_submission

from src.tests.autograding_v233_test_support import (
    create_python_submission,
    make_submission_repository,
)


def config(assessment_id="LAB1", required_files=("helpers.py",)):
    return AutogradingConfig.from_dict(
        {
            "schema_version": "1.0",
            "assessment_id": assessment_id,
            "entrypoint": "main.py",
            "required_files": list(required_files),
            "max_points": 1,
            "tests": [{"test_id": "test_basic", "points": 1}],
        }
    )


class TestProgrammingSubmissionAdapter(unittest.TestCase):
    def test_active_multifile_python_submission_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            submission = create_python_submission(repo, root / "incoming")
            selection = select_programming_submission(
                repo,
                config(),
                assessment_id="LAB1",
                student_id="alice",
            )

        self.assertEqual(selection.submission.submission_id, submission.submission_id)
        self.assertTrue(selection.selected_submission_was_active)
        self.assertTrue(selection.verification_performed)
        self.assertEqual(
            [item.logical_path for item in selection.files],
            ["helpers.py", "main.py"],
        )
        self.assertEqual(selection.entrypoint_file.logical_path, "main.py")

    def test_v233_router_marks_python_handler_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            submission = create_python_submission(repo, root / "incoming")
            decision = route_submission(submission)
        self.assertEqual(decision.route, ROUTE_PROGRAMMING_PYTHON)
        self.assertEqual(decision.handler, HANDLER_PROGRAMMING)
        self.assertTrue(decision.supported)
        self.assertIsNone(decision.reason)

    def test_no_active_submission_has_specific_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_submission_repository(Path(tmp) / "evidence")
            with self.assertRaises(NoCanonicalSubmissionError):
                select_programming_submission(
                    repo,
                    config(),
                    assessment_id="LAB1",
                    student_id="alice",
                )

    def test_config_assessment_mismatch_is_rejected_before_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_submission_repository(Path(tmp) / "evidence")
            with self.assertRaisesRegex(ProgrammingSubmissionContractError, "does not match"):
                select_programming_submission(
                    repo,
                    config("LAB2"),
                    assessment_id="LAB1",
                    student_id="alice",
                )

    def test_missing_required_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            create_python_submission(
                repo,
                root / "incoming",
                files={"main.py": "print('ok')\n"},
            )
            with self.assertRaisesRegex(ProgrammingSubmissionContractError, "missing required"):
                select_programming_submission(
                    repo,
                    config(required_files=("helpers.py",)),
                    assessment_id="LAB1",
                    student_id="alice",
                )

    def test_written_submission_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            tex = root / "alice.tex"
            tex.write_text("not python", encoding="utf-8")
            repo.create_submission(
                assessment_id="LAB1",
                student_id="alice",
                files=[
                    CandidateFile(
                        source_path=str(tex),
                        original_filename="alice.tex",
                        artifact_type=ARTIFACT_TYPE_TEX,
                        role=ARTIFACT_ROLE_PRIMARY,
                    )
                ],
            )
            with self.assertRaisesRegex(ProgrammingSubmissionContractError, "not an available Python"):
                select_programming_submission(
                    repo,
                    config(required_files=()),
                    assessment_id="LAB1",
                    student_id="alice",
                )

    def test_canonical_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            submission = create_python_submission(repo, root / "incoming")
            entry = next(a for a in submission.artifacts if a.original_filename == "main.py")
            canonical = Path(repo.artifact_path(submission, entry))
            canonical.write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(CanonicalSubmissionIntegrityError):
                select_programming_submission(
                    repo,
                    config(),
                    assessment_id="LAB1",
                    student_id="alice",
                )

    def test_explicit_programming_relative_path_supports_nested_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            create_python_submission(
                repo,
                root / "incoming",
                files={"student_entry.py": "x=1\n", "student_helper.py": "y=2\n"},
                programming_paths={
                    "student_entry.py": "src/main.py",
                    "student_helper.py": "src/helpers.py",
                },
            )
            cfg = AutogradingConfig.from_dict(
                {
                    "assessment_id": "LAB1",
                    "entrypoint": "src/main.py",
                    "required_files": ["src/helpers.py"],
                    "max_points": 1,
                    "tests": [{"test_id": "test_basic", "points": 1}],
                }
            )
            selection = select_programming_submission(
                repo,
                cfg,
                assessment_id="LAB1",
                student_id="alice",
            )
        self.assertEqual(selection.entrypoint_file.logical_path, "src/main.py")

    def test_case_insensitive_programming_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_submission_repository(root / "evidence")
            create_python_submission(
                repo,
                root / "incoming",
                files={"one.py": "x=1\n", "two.py": "x=2\n"},
                programming_paths={"one.py": "Main.py", "two.py": "main.py"},
            )
            with self.assertRaisesRegex(ProgrammingSubmissionContractError, "collision"):
                select_programming_submission(
                    repo,
                    config(required_files=()),
                    assessment_id="LAB1",
                    student_id="alice",
                )

    def test_selection_does_not_execute_student_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / "EXECUTED.txt"
            repo = make_submission_repository(root / "evidence")
            create_python_submission(
                repo,
                root / "incoming",
                files={
                    "main.py": "from pathlib import Path\nPath(%r).write_text('bad')\n" % str(sentinel),
                    "helpers.py": "raise RuntimeError('must not import')\n",
                },
            )
            select_programming_submission(
                repo,
                config(),
                assessment_id="LAB1",
                student_id="alice",
            )
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
