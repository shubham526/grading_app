"""Backend support for Overleaf / multi-file LaTeX project ingestion.

v2.3.4.2 Commit 2 adds bounded, execution-free ZIP inspection/extraction and
transactional immutable project storage.  Root-document discovery, multi-file
composition, canonical submission bridging, and Written-mode UI arrive in
later commits.
"""

from .archive import (
    LatexArchiveExtractionSummary,
    compute_manifest_sha256,
    safe_extract_latex_project_zip,
)
from .config import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    DEFAULT_IGNORED_METADATA_NAMES,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_FILE_COUNT,
    DEFAULT_MAX_INCLUDE_DEPTH,
    DEFAULT_MAX_MEMBER_BYTES,
    DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES,
    DEFAULT_PREFERRED_ROOT_NAMES,
    LATEX_PROJECT_CONFIG_SCHEMA_VERSION,
    LatexProjectIngestionConfig,
    LatexProjectSafetyLimits,
    load_latex_project_config,
    save_latex_project_config,
)
from .errors import (
    LatexProjectArchiveError,
    LatexProjectArchiveRejectedError,
    LatexProjectError,
    LatexProjectIntegrityError,
    LatexProjectSerializationError,
    LatexProjectStorageError,
    LatexProjectValidationError,
    UnsupportedLatexProjectSchemaError,
)
from .models import *  # re-export stable domain constants/value objects
from .models import __all__ as _model_all
from .storage import (
    ARCHIVE_METADATA_FILENAME,
    EXTRACTED_DIRNAME,
    MANIFEST_FILENAME,
    ORIGINAL_ARCHIVE_FILENAME,
    ORIGINAL_DIRNAME,
    LatexProjectArchiveStore,
    StoredLatexProject,
)


__all__ = list(_model_all) + [
    "ARCHIVE_METADATA_FILENAME",
    "DEFAULT_IGNORED_DIRECTORY_NAMES",
    "DEFAULT_IGNORED_METADATA_NAMES",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_FILE_COUNT",
    "DEFAULT_MAX_INCLUDE_DEPTH",
    "DEFAULT_MAX_MEMBER_BYTES",
    "DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES",
    "DEFAULT_PREFERRED_ROOT_NAMES",
    "EXTRACTED_DIRNAME",
    "LATEX_PROJECT_CONFIG_SCHEMA_VERSION",
    "LatexArchiveExtractionSummary",
    "LatexProjectArchiveError",
    "LatexProjectArchiveRejectedError",
    "LatexProjectArchiveStore",
    "LatexProjectError",
    "LatexProjectIngestionConfig",
    "LatexProjectIntegrityError",
    "LatexProjectSafetyLimits",
    "LatexProjectSerializationError",
    "LatexProjectStorageError",
    "LatexProjectValidationError",
    "MANIFEST_FILENAME",
    "ORIGINAL_ARCHIVE_FILENAME",
    "ORIGINAL_DIRNAME",
    "StoredLatexProject",
    "UnsupportedLatexProjectSchemaError",
    "compute_manifest_sha256",
    "load_latex_project_config",
    "safe_extract_latex_project_zip",
    "save_latex_project_config",
]
