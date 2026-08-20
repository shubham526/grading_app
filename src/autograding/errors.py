"""Error hierarchy for v2.3.3 programming autograding.

The autograding package keeps domain/configuration and instructor-bundle failures
distinct from execution failures introduced by later commits. Validation errors inherit from
``ValueError`` so callers may handle them alongside ordinary schema errors,
while still being able to catch the autograding-specific base class.
"""


class AutogradingError(Exception):
    """Base class for errors owned by the autograding subsystem."""


class AutogradingValidationError(AutogradingError, ValueError):
    """Raised when an autograding domain object or config is invalid."""


class AutogradingSerializationError(AutogradingError, ValueError):
    """Raised when serialized autograding data cannot be decoded safely."""


class UnsupportedAutogradingSchemaError(AutogradingValidationError):
    """Raised when serialized data uses an unsupported schema version."""


class UnsupportedAutogradingLanguageError(AutogradingValidationError):
    """Raised when a configuration names an unsupported programming language."""


class UnsupportedAutogradingRunnerError(AutogradingValidationError):
    """Raised when a configuration names an unsupported test runner."""




class AutogradingPlanningError(AutogradingError, ValueError):
    """Base class for canonical-submission / execution-plan preparation failures."""


class NoCanonicalSubmissionError(AutogradingPlanningError):
    """Raised when the requested student/assessment has no selectable submission."""


class ProgrammingSubmissionContractError(AutogradingPlanningError):
    """Raised when canonical programming artifacts do not satisfy the grader contract."""


class CanonicalSubmissionIntegrityError(AutogradingPlanningError):
    """Raised when immutable canonical student bytes fail size/hash verification."""


class AutogradingBundleSelectionError(AutogradingPlanningError):
    """Raised when an immutable instructor bundle cannot be selected for planning."""


class ExecutionPlanValidationError(AutogradingPlanningError):
    """Raised when a transient execution plan/workspace contract is inconsistent."""


class AutogradingBundleError(AutogradingError):
    """Base class for instructor test-bundle ingestion/storage failures."""


class AutogradingBundleValidationError(AutogradingBundleError, AutogradingValidationError):
    """Raised when a source test bundle violates the accepted static contract."""


class AutogradingBundleIntegrityError(AutogradingBundleError, ValueError):
    """Raised when committed bundle bytes/manifests fail integrity verification."""


class AutogradingBundleStorageError(AutogradingBundleError):
    """Raised when immutable bundle storage cannot complete safely."""


__all__ = [
    "AutogradingBundleError",
    "AutogradingBundleIntegrityError",
    "AutogradingBundleSelectionError",
    "AutogradingBundleStorageError",
    "AutogradingBundleValidationError",
    "AutogradingError",
    "AutogradingPlanningError",
    "AutogradingSerializationError",
    "AutogradingValidationError",
    "CanonicalSubmissionIntegrityError",
    "ExecutionPlanValidationError",
    "NoCanonicalSubmissionError",
    "ProgrammingSubmissionContractError",
    "UnsupportedAutogradingLanguageError",
    "UnsupportedAutogradingRunnerError",
    "UnsupportedAutogradingSchemaError",
]
