"""Structured pytest result protocol for v2.3.3 Commit 6."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from ..errors import PytestResultProtocolError
from ..execution.result_protocol import BackendExecutionRecord
from ..models import ExecutionResult, TestResult


PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION = "1.0"
PYTEST_RESULT_FILENAME = "pytest_results.json"
PYTEST_RUNTIME_CONFIG_FILENAME = "pytest_run_config.json"
DEFAULT_PYTEST_PROTOCOL_MAX_BYTES = 16 * 1024 * 1024


def _nonnegative_int(value, name):
    if isinstance(value, bool):
        raise PytestResultProtocolError("%s must be an integer" % name)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PytestResultProtocolError("%s must be an integer" % name) from exc
    if number < 0:
        raise PytestResultProtocolError("%s must be non-negative" % name)
    return number


@dataclass(frozen=True)
class PytestRunResult:
    """Host-side structured result for one pytest execution.

    Commit 6 intentionally contains no score.  ``test_results`` describe test
    outcomes only; Commit 7 turns those outcomes into deterministic points.
    """

    backend_record: BackendExecutionRecord
    test_results: Tuple[TestResult, ...]
    pytest_exit_code: Optional[int]
    pytest_version: Optional[str]
    collected_count: int = 0
    selected_count: int = 0
    deselected_count: int = 0
    collection_errors: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    selection_errors: Tuple[str, ...] = field(default_factory=tuple)
    student_preflight_errors: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    requires_review: bool = False
    review_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.backend_record, BackendExecutionRecord):
            raise TypeError("backend_record must be a BackendExecutionRecord")
        results = tuple(self.test_results or ())
        if any(not isinstance(item, TestResult) for item in results):
            raise TypeError("test_results must contain TestResult objects")
        ids = [item.test_id for item in results]
        if len(ids) != len(set(ids)):
            raise PytestResultProtocolError("test_results contains duplicate test_id values")
        object.__setattr__(self, "test_results", results)
        if self.pytest_exit_code is not None:
            if isinstance(self.pytest_exit_code, bool):
                raise PytestResultProtocolError("pytest_exit_code must be an integer")
            object.__setattr__(self, "pytest_exit_code", int(self.pytest_exit_code))
        object.__setattr__(
            self,
            "pytest_version",
            None if self.pytest_version is None else str(self.pytest_version).strip() or None,
        )
        for name in ("collected_count", "selected_count", "deselected_count"):
            object.__setattr__(self, name, _nonnegative_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "collection_errors",
            tuple(deepcopy(dict(item)) for item in (self.collection_errors or ())),
        )
        object.__setattr__(
            self,
            "selection_errors",
            tuple(str(item) for item in (self.selection_errors or ())),
        )
        object.__setattr__(
            self,
            "student_preflight_errors",
            tuple(deepcopy(dict(item)) for item in (self.student_preflight_errors or ())),
        )
        if not isinstance(self.requires_review, bool):
            raise PytestResultProtocolError("requires_review must be boolean")
        object.__setattr__(
            self,
            "review_reason",
            None if self.review_reason is None else str(self.review_reason).strip() or None,
        )
        if not isinstance(self.metadata, Mapping):
            raise PytestResultProtocolError("metadata must be a mapping")
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def execution_result(self) -> ExecutionResult:
        return self.backend_record.result

    @property
    def all_tests_passed(self) -> bool:
        return bool(self.test_results) and all(item.status == "passed" for item in self.test_results)

    def test_by_id(self, test_id):
        target = str(test_id or "").strip()
        for item in self.test_results:
            if item.test_id == target:
                return item
        return None

    def to_dict(self):
        return {
            "schema_version": PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION,
            "backend_record": self.backend_record.to_dict(),
            "test_results": [item.to_dict() for item in self.test_results],
            "pytest_exit_code": self.pytest_exit_code,
            "pytest_version": self.pytest_version,
            "collected_count": self.collected_count,
            "selected_count": self.selected_count,
            "deselected_count": self.deselected_count,
            "collection_errors": [deepcopy(item) for item in self.collection_errors],
            "selection_errors": list(self.selection_errors),
            "student_preflight_errors": [
                deepcopy(item) for item in self.student_preflight_errors
            ],
            "requires_review": self.requires_review,
            "review_reason": self.review_reason,
            "metadata": deepcopy(self.metadata),
        }


    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise PytestResultProtocolError("PytestRunResult data must be a mapping")
        version = data.get("schema_version")
        if version is not None and str(version) != PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION:
            raise PytestResultProtocolError(
                "Unsupported PytestRunResult schema %r; expected %r"
                % (version, PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION)
            )
        backend_data = data.get("backend_record")
        if not isinstance(backend_data, Mapping):
            raise PytestResultProtocolError("backend_record must be a mapping")
        return cls(
            backend_record=BackendExecutionRecord.from_dict(backend_data),
            test_results=tuple(
                TestResult.from_dict(item) for item in (data.get("test_results") or ())
            ),
            pytest_exit_code=data.get("pytest_exit_code"),
            pytest_version=data.get("pytest_version"),
            collected_count=data.get("collected_count", 0),
            selected_count=data.get("selected_count", 0),
            deselected_count=data.get("deselected_count", 0),
            collection_errors=tuple(data.get("collection_errors") or ()),
            selection_errors=tuple(data.get("selection_errors") or ()),
            student_preflight_errors=tuple(data.get("student_preflight_errors") or ()),
            requires_review=data.get("requires_review", False),
            review_reason=data.get("review_reason"),
            metadata=data.get("metadata", {}),
        )


__all__ = [
    "DEFAULT_PYTEST_PROTOCOL_MAX_BYTES",
    "PYTEST_RESULT_FILENAME",
    "PYTEST_RESULT_PROTOCOL_SCHEMA_VERSION",
    "PYTEST_RUNTIME_CONFIG_FILENAME",
    "PytestRunResult",
]
