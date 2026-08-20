import unittest

from src.autograding.execution.docker_command import build_docker_create_args_for_command


class TestDockerPytestCommand(unittest.TestCase):
    def test_explicit_pytest_command_keeps_commit5_isolation_controls(self):
        args = build_docker_create_args_for_command(
            container_name="grading-app-pytest",
            image_reference="sha256:" + "a" * 64,
            submission_dir="/tmp/submission",
            grader_dir="/tmp/grader",
            output_dir="/tmp/output",
            runtime_dir="/tmp/runtime",
            command=("python", "-B", "-u", "/workspace/runtime/pytest_runner.py"),
            memory_mb=256,
            cpu_count=1,
            pids_limit=64,
        )
        joined = "\n".join(args)
        self.assertIn("--network\nnone", joined)
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop\nALL", joined)
        self.assertIn("--security-opt\nno-new-privileges", joined)
        self.assertIn("dst=/workspace/runtime,readonly", joined)
        self.assertIn("dst=/workspace/submission,readonly", joined)
        self.assertIn("dst=/workspace/grader,readonly", joined)
        self.assertIn("dst=/workspace/output", joined)
        self.assertEqual(args[-4:], ("python", "-B", "-u", "/workspace/runtime/pytest_runner.py"))

    def test_empty_container_command_is_rejected(self):
        with self.assertRaises(ValueError):
            build_docker_create_args_for_command(
                container_name="x",
                image_reference="img",
                submission_dir="/tmp/s",
                grader_dir="/tmp/g",
                output_dir="/tmp/o",
                runtime_dir="/tmp/r",
                command=(),
                memory_mb=None,
                cpu_count=None,
                pids_limit=None,
            )


if __name__ == "__main__":
    unittest.main()
