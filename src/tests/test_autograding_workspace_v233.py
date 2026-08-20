import tempfile
import unittest
from pathlib import Path

from src.autograding.errors import ExecutionPlanValidationError
from src.autograding.workspace import (
    ExecutionWorkspaceSpec,
    PlannedWorkspaceFile,
    WORKSPACE_NAMESPACE_GRADER,
    WORKSPACE_NAMESPACE_SUBMISSION,
    normalize_workspace_relative_path,
)


class TestExecutionWorkspacePlanning(unittest.TestCase):
    def _file(self, root, name, namespace, logical_path, source_id):
        path = Path(root) / name
        path.write_bytes(b"abc")
        import hashlib
        return PlannedWorkspaceFile(
            namespace=namespace,
            logical_path=logical_path,
            source_path=str(path),
            sha256=hashlib.sha256(b"abc").hexdigest(),
            size_bytes=3,
            source_id=source_id,
        )

    def test_normalizes_portable_relative_paths(self):
        self.assertEqual(normalize_workspace_relative_path("src\\main.py"), "src/main.py")
        with self.assertRaises(ExecutionPlanValidationError):
            normalize_workspace_relative_path("../main.py")
        with self.assertRaises(ExecutionPlanValidationError):
            normalize_workspace_relative_path("C:\\temp\\main.py")

    def test_workspace_has_separate_submission_and_grader_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            student = self._file(tmp, "student.py", WORKSPACE_NAMESPACE_SUBMISSION, "main.py", "art1")
            grader = self._file(tmp, "grader.py", WORKSPACE_NAMESPACE_GRADER, "tests/test.py", "tests/test.py")
            spec = ExecutionWorkspaceSpec(
                submission_files=(student,),
                grader_files=(grader,),
                entrypoint="main.py",
            )
        self.assertEqual(student.destination_relative_path, "submission/main.py")
        self.assertEqual(grader.destination_relative_path, "grader/tests/test.py")
        self.assertEqual(spec.output_directory, "output")

    def test_missing_entrypoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            student = self._file(tmp, "student.py", WORKSPACE_NAMESPACE_SUBMISSION, "helper.py", "art1")
            grader = self._file(tmp, "grader.py", WORKSPACE_NAMESPACE_GRADER, "tests/test.py", "tests/test.py")
            with self.assertRaisesRegex(ExecutionPlanValidationError, "entrypoint"):
                ExecutionWorkspaceSpec(
                    submission_files=(student,),
                    grader_files=(grader,),
                    entrypoint="main.py",
                )

    def test_case_insensitive_collision_is_rejected_even_on_case_sensitive_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = self._file(tmp, "one.py", WORKSPACE_NAMESPACE_SUBMISSION, "Main.py", "art1")
            two = self._file(tmp, "two.py", WORKSPACE_NAMESPACE_SUBMISSION, "main.py", "art2")
            grader = self._file(tmp, "grader.py", WORKSPACE_NAMESPACE_GRADER, "tests/test.py", "tests/test.py")
            with self.assertRaisesRegex(ExecutionPlanValidationError, "collision"):
                ExecutionWorkspaceSpec(
                    submission_files=(one, two),
                    grader_files=(grader,),
                    entrypoint="Main.py",
                )

    def test_source_size_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "student.py"
            path.write_bytes(b"abcd")
            with self.assertRaisesRegex(ExecutionPlanValidationError, "size changed"):
                PlannedWorkspaceFile(
                    namespace=WORKSPACE_NAMESPACE_SUBMISSION,
                    logical_path="main.py",
                    source_path=str(path),
                    sha256="a" * 64,
                    size_bytes=3,
                    source_id="art1",
                )


if __name__ == "__main__":
    unittest.main()
