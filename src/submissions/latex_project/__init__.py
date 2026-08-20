"""Backend contracts for Overleaf / multi-file LaTeX project ingestion.

v2.3.4.2 Commit 1 is deliberately execution-free: this package currently
contains only validated domain/configuration models.  Safe ZIP inspection and
extraction arrive in Commit 2.
"""

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
    LatexProjectError,
    LatexProjectSerializationError,
    LatexProjectValidationError,
    UnsupportedLatexProjectSchemaError,
)
from .models import *  # re-export stable domain constants/value objects
from .models import __all__ as _model_all


__all__ = list(_model_all) + [
    "DEFAULT_IGNORED_DIRECTORY_NAMES",
    "DEFAULT_IGNORED_METADATA_NAMES",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_FILE_COUNT",
    "DEFAULT_MAX_INCLUDE_DEPTH",
    "DEFAULT_MAX_MEMBER_BYTES",
    "DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES",
    "DEFAULT_PREFERRED_ROOT_NAMES",
    "LATEX_PROJECT_CONFIG_SCHEMA_VERSION",
    "LatexProjectError",
    "LatexProjectIngestionConfig",
    "LatexProjectSafetyLimits",
    "LatexProjectSerializationError",
    "LatexProjectValidationError",
    "UnsupportedLatexProjectSchemaError",
    "load_latex_project_config",
    "save_latex_project_config",
]
