import unittest

from src.autograding.errors import ExecutionBackendContractError
from src.autograding.execution import BackendAvailability, probe_backends
from src.tests.autograding_v233_execution_support import FakeExecutionBackend


class TestBackendAvailability(unittest.TestCase):
    def test_available_roundtrip(self):
        value = BackendAvailability(
            backend="docker",
            available=True,
            checked_at="2026-08-19T20:10:00Z",
            details={"version": "test"},
        )
        self.assertEqual(BackendAvailability.from_dict(value.to_dict()), value)

    def test_unavailable_requires_reason(self):
        with self.assertRaisesRegex(ExecutionBackendContractError, "reason"):
            BackendAvailability(backend="docker", available=False)

    def test_available_may_include_diagnostic_reason_without_becoming_unavailable(self):
        value = BackendAvailability(
            backend="docker",
            available=True,
            reason="using cached runtime",
        )
        self.assertTrue(value.available)
        self.assertEqual(value.reason, "using cached runtime")

    def test_available_must_be_bool(self):
        with self.assertRaisesRegex(ExecutionBackendContractError, "boolean"):
            BackendAvailability(backend="docker", available=1)

    def test_unknown_schema_is_rejected(self):
        with self.assertRaisesRegex(ExecutionBackendContractError, "Unsupported"):
            BackendAvailability.from_dict(
                {
                    "schema_version": "999",
                    "backend": "docker",
                    "available": True,
                }
            )

    def test_probe_backends_preserves_order(self):
        first = FakeExecutionBackend(backend_name="first")
        second = FakeExecutionBackend(
            backend_name="second",
            available=False,
            availability_reason="not installed",
        )
        results = probe_backends([first, second])
        self.assertEqual([item.backend for item in results], ["first", "second"])
        self.assertTrue(results[0].available)
        self.assertFalse(results[1].available)

    def test_probe_backends_rejects_invalid_objects(self):
        with self.assertRaisesRegex(ExecutionBackendContractError, "probe_availability"):
            probe_backends([object()])

    def test_probe_backends_rejects_invalid_return_type(self):
        class Bad:
            def probe_availability(self):
                return True

        with self.assertRaisesRegex(ExecutionBackendContractError, "BackendAvailability"):
            probe_backends([Bad()])


if __name__ == "__main__":
    unittest.main()
