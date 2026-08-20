import sys
import unittest

from src.autograding.execution.docker_command import (
    build_docker_create_args,
    run_bounded_command,
    safe_container_name,
)


class TestDockerCommandConstruction(unittest.TestCase):
    def test_container_name_is_sanitized(self):
        self.assertEqual(
            safe_container_name("agrun:abc / weird"),
            "grading-app-agrun-abc-weird",
        )

    def test_create_args_enforce_isolation_and_resource_limits(self):
        args = build_docker_create_args(
            container_name="grading-app-test",
            image_reference="sha256:" + "a" * 64,
            submission_dir="/tmp/submission",
            grader_dir="/tmp/grader",
            output_dir="/tmp/output",
            entrypoint="src/main.py",
            memory_mb=256,
            cpu_count=1,
            pids_limit=64,
        )
        joined = "\n".join(args)
        self.assertIn("--network\nnone", joined)
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop\nALL", joined)
        self.assertIn("--security-opt\nno-new-privileges", joined)
        self.assertIn("--user\n65534:65534", joined)
        self.assertIn("--memory\n256m", joined)
        self.assertIn("--memory-swap\n256m", joined)
        self.assertIn("--cpus\n1.0", joined)
        self.assertIn("--pids-limit\n64", joined)
        self.assertIn("readonly", joined)
        self.assertIn("/workspace/output", joined)
        self.assertIn("/tmp:rw,noexec,nosuid,nodev", joined)
        self.assertEqual(args[-5], "sha256:" + "a" * 64)
        self.assertEqual(args[-1], "/workspace/submission/src/main.py")

    def test_create_args_reject_parent_entrypoint(self):
        with self.assertRaises(ValueError):
            build_docker_create_args(
                container_name="x",
                image_reference="img",
                submission_dir="/tmp/s",
                grader_dir="/tmp/g",
                output_dir="/tmp/o",
                entrypoint="../escape.py",
                memory_mb=None,
                cpu_count=None,
                pids_limit=None,
            )

    def test_bounded_runner_truncates_without_blocking(self):
        result = run_bounded_command(
            (sys.executable, "-c", "import sys; sys.stdout.write('x'*10000); sys.stderr.write('y'*10000)"),
            timeout_seconds=5,
            stdout_max_bytes=128,
            stderr_max_bytes=64,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.encode("utf-8")), 128)
        self.assertEqual(len(result.stderr.encode("utf-8")), 64)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)

    def test_bounded_runner_enforces_timeout(self):
        result = run_bounded_command(
            (sys.executable, "-c", "import time; time.sleep(5)"),
            timeout_seconds=0.1,
            stdout_max_bytes=64,
            stderr_max_bytes=64,
        )
        self.assertTrue(result.timed_out)


if __name__ == "__main__":
    unittest.main()
