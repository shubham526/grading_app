import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "autograding" / "runtime" / "pytest_runner.py"


class TestPytestRuntimeRunner(unittest.TestCase):
    def setUp(self):
        # The production Commit-6 runner executes inside the dedicated Docker
        # image, which always contains the pinned pytest runtime.  These four
        # tests additionally exercise that same script with the instructor's
        # host Python.  pytest is therefore optional on the host: skip this
        # compatibility check cleanly when it is not installed rather than
        # turning an optional development dependency into an app dependency.
        if importlib.util.find_spec("pytest") is None:
            self.skipTest("host Python does not have pytest installed; Docker runtime tests cover production pytest execution")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.submission = self.root / "submission"
        self.grader = self.root / "grader"
        self.tests = self.grader / "tests"
        self.output = self.root / "output"
        self.submission.mkdir()
        self.tests.mkdir(parents=True)
        self.output.mkdir()

    def run_runner(self, config):
        config_path = self.root / "config.json"
        output_path = self.output / "results.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--config", str(config_path),
                "--output", str(output_path),
                "--submission-root", str(self.submission),
                "--grader-root", str(self.grader),
            ],
            cwd=str(self.submission),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        if not output_path.exists():
            self.fail(
                "pytest_runner.py exited before writing its structured protocol.\n"
                "returncode=%r\nstdout:\n%s\nstderr:\n%s"
                % (result.returncode, result.stdout, result.stderr)
            )
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        return result, payload

    def test_public_and_hidden_results_are_machine_readable(self):
        (self.submission / "main.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
        (self.tests / "test_main.py").write_text(
            "from main import add\n"
            "def test_public():\n    print('hello')\n    assert add(1,2)==3\n"
            "def test_hidden():\n    assert add(1,2)==4\n",
            encoding="utf-8",
        )
        config = {
            "schema_version": "1.0",
            "tests": [
                {"test_id": "pub", "selector": "tests/test_main.py::test_public", "visibility": "public", "display_name": "Public", "timeout_seconds": 1},
                {"test_id": "hid", "selector": "tests/test_main.py::test_hidden", "visibility": "hidden", "display_name": "Hidden", "timeout_seconds": 1},
            ],
        }
        result, payload = self.run_runner(config)
        self.assertEqual(result.returncode, 1)
        by_id = {item["test_id"]: item for item in payload["tests"]}
        self.assertEqual(by_id["pub"]["status"], "passed")
        self.assertEqual(by_id["pub"]["stdout"], "hello\n")
        self.assertEqual(by_id["hid"]["status"], "failed")
        self.assertIn("assert", by_id["hid"]["traceback"])

    def test_configured_per_test_timeout_is_reported(self):
        (self.submission / "main.py").write_text("x=1\n", encoding="utf-8")
        (self.tests / "test_slow.py").write_text(
            "import time\ndef test_slow():\n    time.sleep(2)\n",
            encoding="utf-8",
        )
        config = {
            "schema_version": "1.0",
            "tests": [
                {"test_id": "slow", "selector": "tests/test_slow.py::test_slow", "visibility": "hidden", "display_name": "Slow", "timeout_seconds": 0.05},
            ],
        }
        result, payload = self.run_runner(config)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["tests"][0]["status"], "timeout")
        self.assertIn("timeout", payload["tests"][0]["message"].lower())

    def test_student_syntax_error_is_detected_before_test_collection(self):
        (self.submission / "main.py").write_text("def broken(:\n", encoding="utf-8")
        (self.tests / "test_main.py").write_text("def test_basic():\n    assert True\n", encoding="utf-8")
        config = {
            "schema_version": "1.0",
            "tests": [
                {"test_id": "basic", "selector": "tests/test_main.py::test_basic", "visibility": "public", "display_name": "Basic", "timeout_seconds": 1},
            ],
        }
        result, payload = self.run_runner(config)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(payload["student_preflight_errors"])
        self.assertEqual(payload["tests"][0]["status"], "error")
        self.assertIn("syntax", payload["tests"][0]["message"].lower())

    def test_parametrized_function_is_aggregated_under_one_stable_test_id(self):
        (self.submission / "main.py").write_text("x=1\n", encoding="utf-8")
        (self.tests / "test_param.py").write_text(
            "import pytest\n"
            "@pytest.mark.parametrize('value',[1,2,3])\n"
            "def test_values(value):\n    assert value < 3\n",
            encoding="utf-8",
        )
        config = {
            "schema_version": "1.0",
            "tests": [
                {"test_id": "values", "selector": "tests/test_param.py::test_values", "visibility": "public", "display_name": "Values", "timeout_seconds": 1},
            ],
        }
        result, payload = self.run_runner(config)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(payload["tests"]), 1)
        self.assertEqual(payload["tests"][0]["item_count"], 3)
        self.assertEqual(payload["tests"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
