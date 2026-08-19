"""Error hierarchy for v2.3.3 programming autograding.

The autograding package keeps domain/configuration failures distinct from
execution failures introduced by later commits.  Validation errors inherit from
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


__all__ = [
    "AutogradingError",
    "AutogradingSerializationError",
    "AutogradingValidationError",
    "UnsupportedAutogradingLanguageError",
    "UnsupportedAutogradingRunnerError",
    "UnsupportedAutogradingSchemaError",
]
