"""Programming Submission & Autograding backend for the Rubric Grading Tool.

v2.3.3 Commit 1 defines only dependency-free domain/configuration contracts.
It does **not** execute student code, import Docker/pytest, or depend on PyQt.
"""

from .config import (
    AUTOGRADING_CONFIG_SCHEMA_VERSION,
    DEFAULT_REPORTING_POLICY,
    SCORING_METHOD_EQUAL_WITHIN_GROUP,
    SCORING_METHOD_EXPLICIT_TEST_POINTS,
    SUPPORTED_AUTOGRADING_LANGUAGES,
    SUPPORTED_AUTOGRADING_RUNNERS,
    SUPPORTED_SCORING_METHODS,
    AutogradingConfig,
    load_autograding_config,
    save_autograding_config,
)
from .errors import (
    AutogradingError,
    AutogradingSerializationError,
    AutogradingValidationError,
    UnsupportedAutogradingLanguageError,
    UnsupportedAutogradingRunnerError,
    UnsupportedAutogradingSchemaError,
)
from .ids import (
    generate_autograding_run_id,
    generate_test_bundle_id,
)
from .models import *  # re-export stable domain constants and value objects
from .models import __all__ as _model_all


__all__ = list(_model_all) + [
    "AUTOGRADING_CONFIG_SCHEMA_VERSION",
    "AutogradingConfig",
    "AutogradingError",
    "AutogradingSerializationError",
    "AutogradingValidationError",
    "DEFAULT_REPORTING_POLICY",
    "SCORING_METHOD_EQUAL_WITHIN_GROUP",
    "SCORING_METHOD_EXPLICIT_TEST_POINTS",
    "SUPPORTED_AUTOGRADING_LANGUAGES",
    "SUPPORTED_AUTOGRADING_RUNNERS",
    "SUPPORTED_SCORING_METHODS",
    "UnsupportedAutogradingLanguageError",
    "UnsupportedAutogradingRunnerError",
    "UnsupportedAutogradingSchemaError",
    "generate_autograding_run_id",
    "generate_test_bundle_id",
    "load_autograding_config",
    "save_autograding_config",
]
