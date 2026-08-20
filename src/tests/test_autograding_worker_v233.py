import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "ui/workers/autograding_worker.py"


class TestAutogradingWorkerSource(unittest.TestCase):
    def test_worker_has_grade_one_and_batch_operations(self):
        text = WORKER.read_text(encoding="utf-8")
        self.assertIn('GRADE_ONE = "grade_one"', text)
        self.assertIn('GRADE_BATCH = "grade_batch"', text)
        self.assertIn("service.grade_submission", text)
        self.assertIn("service.grade_batch", text)

    def test_worker_cancellation_is_cooperative(self):
        text = WORKER.read_text(encoding="utf-8")
        self.assertIn("threading.Event", text)
        self.assertIn("cancel_check=lambda: self.is_cancelled", text)
        self.assertIn("currently running Docker container", text)

    def test_worker_is_python39_compatible(self):
        ast.parse(WORKER.read_text(encoding="utf-8"), filename=str(WORKER), feature_version=(3, 9))

    @unittest.skipUnless(importlib.util.find_spec("PyQt5") is not None, "PyQt5 not installed")
    def test_worker_imports_when_qt_is_available(self):
        from src.ui.workers.autograding_worker import AutogradingOperation
        self.assertEqual(AutogradingOperation.GRADE_ONE.value, "grade_one")


if __name__ == "__main__":
    unittest.main()
