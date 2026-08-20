"""Programming Submission & Autograding backend for the Rubric Grading Tool.

v2.3.3 Commits 1-2 provide dependency-free domain/configuration contracts plus
validated, immutable instructor test-bundle ingestion/storage.  They do **not**
execute student code, import Docker/pytest, or depend on PyQt.
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
from .bundle_store import (
    AUTOGRADING_DIRECTORY,
    BUNDLES_DIRECTORY,
    BUNDLE_INDEX_FILENAME,
    BUNDLE_INDEX_SCHEMA_VERSION,
    BUNDLE_MANIFEST_FILENAME,
    BUNDLE_ORIGINALS_DIRECTORY,
    TestBundleStore,
)
from .bundles import (
    BundleFile,
    BundleImportResult,
    StoredTestBundle,
    TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION,
    TEST_BUNDLE_MANIFEST_SCHEMA_VERSION,
    ValidatedTestBundle,
    validate_test_bundle,
)
from .errors import (
    AutogradingBundleError,
    AutogradingBundleIntegrityError,
    AutogradingBundleStorageError,
    AutogradingBundleValidationError,
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
from .validation import (
    ALLOWED_TOP_LEVEL_ENTRIES,
    AUTOGRADER_CONFIG_FILENAME,
    DEFAULT_MAX_BUNDLE_FILE_BYTES,
    DEFAULT_MAX_BUNDLE_FILES,
    DEFAULT_MAX_BUNDLE_TOTAL_BYTES,
    IGNORED_BUNDLE_METADATA_FILENAMES,
    REQUIREMENTS_FILENAME,
    SUPPORT_DIRECTORY,
    TESTS_DIRECTORY,
    discover_test_function_names,
    normalize_bundle_relative_path,
    validate_declared_test_ids,
    validate_requirements_text,
)
from .models import *  # re-export stable domain constants and value objects
from .models import __all__ as _model_all


__all__ = list(_model_all) + [
    "ALLOWED_TOP_LEVEL_ENTRIES",
    "AUTOGRADER_CONFIG_FILENAME",
    "AUTOGRADING_DIRECTORY",
    "AutogradingBundleError",
    "AutogradingBundleIntegrityError",
    "AutogradingBundleStorageError",
    "AutogradingBundleValidationError",
    "BUNDLES_DIRECTORY",
    "BUNDLE_INDEX_FILENAME",
    "BUNDLE_INDEX_SCHEMA_VERSION",
    "BUNDLE_MANIFEST_FILENAME",
    "BUNDLE_ORIGINALS_DIRECTORY",
    "BundleFile",
    "BundleImportResult",
    "DEFAULT_MAX_BUNDLE_FILE_BYTES",
    "DEFAULT_MAX_BUNDLE_FILES",
    "DEFAULT_MAX_BUNDLE_TOTAL_BYTES",
    "IGNORED_BUNDLE_METADATA_FILENAMES",
    "REQUIREMENTS_FILENAME",
    "StoredTestBundle",
    "SUPPORT_DIRECTORY",
    "TESTS_DIRECTORY",
    "TEST_BUNDLE_FINGERPRINT_SCHEMA_VERSION",
    "TEST_BUNDLE_MANIFEST_SCHEMA_VERSION",
    "TestBundleStore",
    "ValidatedTestBundle",
    "discover_test_function_names",
    "normalize_bundle_relative_path",
    "validate_declared_test_ids",
    "validate_requirements_text",
    "validate_test_bundle",
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
