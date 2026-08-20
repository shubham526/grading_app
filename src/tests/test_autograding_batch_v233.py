import tempfile
import unittest
from pathlib import Path

from src.submissions.domain import ARTIFACT_ROLE_PRIMARY, ARTIFACT_TYPE_PYTHON, CandidateFile
from src.tests.autograding_v233_persistence_support import make_pytest_result
from src.tests.autograding_v233_service_support import ASSESSMENT_ID, STUDENT_ID, prepare_service


class TestAutogradingBatchService(unittest.TestCase):
    def _add_student(self, service, base, student_id):
        root = Path(base) / ("submission_" + student_id)
        root.mkdir(parents=True, exist_ok=True)
        main = root / "main.py"
        helper = root / "helpers.py"
        main.write_text("VALUE = 2\n", encoding="utf-8")
        helper.write_text("def helper():\n    return 2\n", encoding="utf-8")
        service.submission_repository.create_submission(
            assessment_id=ASSESSMENT_ID,
            student_id=student_id,
            files=[
                CandidateFile(str(main), "main.py", ARTIFACT_TYPE_PYTHON, ARTIFACT_ROLE_PRIMARY),
                CandidateFile(str(helper), "helpers.py", ARTIFACT_TYPE_PYTHON, ARTIFACT_ROLE_PRIMARY),
            ],
            make_active=True,
        )

    def test_batch_grades_multiple_students_and_persists_each(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            self._add_student(service, td, "bob")
            result = service.grade_batch(
                ASSESSMENT_ID,
                [STUDENT_ID, "bob"],
                bundle.reference.bundle_id,
            )
            self.assertFalse(result.cancelled)
            self.assertEqual(result.completed_count, 2)
            self.assertEqual(result.error_count, 0)
            self.assertEqual(len(service.list_history(ASSESSMENT_ID, STUDENT_ID)), 1)
            self.assertEqual(len(service.list_history(ASSESSMENT_ID, "bob")), 1)

    def test_batch_continues_after_student_error(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            self._add_student(service, td, "bob")
            result = service.grade_batch(
                ASSESSMENT_ID,
                ["missing", "bob"],
                bundle.reference.bundle_id,
            )
            self.assertEqual(result.error_count, 1)
            self.assertEqual(result.completed_count, 1)
            by_id = {item.student_id: item for item in result.results}
            self.assertEqual(by_id["missing"].status, "error")
            self.assertEqual(by_id["bob"].status, "completed")

    def test_cooperative_cancel_marks_remaining_students_cancelled(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            self._add_student(service, td, "bob")
            checks = {"count": 0}

            def cancel_check():
                checks["count"] += 1
                return checks["count"] > 1

            result = service.grade_batch(
                ASSESSMENT_ID,
                [STUDENT_ID, "bob"],
                bundle.reference.bundle_id,
                cancel_check=cancel_check,
            )
            self.assertTrue(result.cancelled)
            by_id = {item.student_id: item for item in result.results}
            self.assertEqual(by_id[STUDENT_ID].status, "completed")
            self.assertEqual(by_id["bob"].status, "cancelled")
            self.assertEqual(len(service.list_history(ASSESSMENT_ID, "bob")), 0)

    def test_progress_callback_reports_running_and_terminal_status(self):
        with tempfile.TemporaryDirectory() as td:
            service, bundle, _submission, _factory = prepare_service(td)
            events = []
            service.grade_batch(
                ASSESSMENT_ID,
                [STUDENT_ID],
                bundle.reference.bundle_id,
                progress_callback=lambda *args: events.append(args),
            )
            self.assertEqual(events[0][3], "running")
            self.assertEqual(events[-1][3], "completed")
            self.assertEqual(events[-1][2], STUDENT_ID)


if __name__ == "__main__":
    unittest.main()
