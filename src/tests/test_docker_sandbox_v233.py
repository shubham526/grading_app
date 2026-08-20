from pathlib import Path
import os
import tempfile
import unittest

from src.autograding.errors import DockerSandboxError
from src.autograding.execution.sandbox import SandboxMaterializer
from src.tests.autograding_v233_execution_support import build_test_execution_plan


class TestDockerSandboxMaterialization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_materializes_exact_submission_and_grader_bytes(self):
        plan = build_test_execution_plan(self.root / "plan")
        materializer = SandboxMaterializer(parent_dir=str(self.root))
        sandbox = materializer.materialize(plan)
        self.addCleanup(materializer.cleanup)
        self.assertEqual(
            (sandbox.submission_dir / "main.py").read_bytes(),
            Path(plan.workspace.submission_files[0].source_path).read_bytes(),
        )
        self.assertEqual(
            (sandbox.grader_dir / "tests/test_fixture.py").read_bytes(),
            Path(plan.workspace.grader_files[0].source_path).read_bytes(),
        )
        self.assertTrue(sandbox.output_dir.is_dir())

    def test_staged_inputs_are_read_only(self):
        plan = build_test_execution_plan(self.root / "plan")
        materializer = SandboxMaterializer(parent_dir=str(self.root))
        sandbox = materializer.materialize(plan)
        self.addCleanup(materializer.cleanup)
        mode = os.stat(sandbox.submission_dir / "main.py").st_mode & 0o777
        self.assertEqual(mode, 0o444)

    def test_hash_mutation_after_planning_is_rejected(self):
        plan = build_test_execution_plan(self.root / "plan")
        Path(plan.workspace.submission_files[0].source_path).write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(DockerSandboxError, "hash|size"):
            SandboxMaterializer(parent_dir=str(self.root)).materialize(plan)

    def test_symlink_swap_after_planning_is_rejected(self):
        plan = build_test_execution_plan(self.root / "plan")
        source = Path(plan.workspace.submission_files[0].source_path)
        replacement = source.with_name("replacement.py")
        replacement.write_bytes(source.read_bytes())
        source.unlink()
        try:
            source.symlink_to(replacement)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(DockerSandboxError, "Symlinked"):
            SandboxMaterializer(parent_dir=str(self.root)).materialize(plan)

    def test_cleanup_removes_staging_root(self):
        plan = build_test_execution_plan(self.root / "plan")
        materializer = SandboxMaterializer(parent_dir=str(self.root))
        sandbox = materializer.materialize(plan)
        staging = sandbox.root
        self.assertTrue(staging.exists())
        materializer.cleanup()
        self.assertFalse(staging.exists())

    def test_materialization_never_executes_sources(self):
        plan_root = self.root / "plan"
        plan = build_test_execution_plan(plan_root)
        materializer = SandboxMaterializer(parent_dir=str(self.root))
        materializer.materialize(plan)
        materializer.cleanup()
        self.assertFalse(plan_root.joinpath("STUDENT_CODE_WAS_EXECUTED").exists())
        self.assertFalse(plan_root.joinpath("GRADER_CODE_WAS_EXECUTED").exists())


if __name__ == "__main__":
    unittest.main()
