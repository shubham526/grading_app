"""Backend support for Overleaf / multi-file LaTeX project ingestion.

v2.3.4.2 Commit 5 extends the existing restricted LaTeX-to-PDF compiler to
whole safely extracted Overleaf projects. Project discovery/root resolution
remain separate from compilation. Canonical submission bridging now adapts
compiled projects into the existing Written ``ParsedSubmission`` contract;
ZIP import UI arrives in a later commit.
"""

from .archive import (
    LatexArchiveExtractionSummary,
    compute_manifest_sha256,
    safe_extract_latex_project_zip,
)
from .compilation import (
    LatexProjectCompilation,
    compile_stored_latex_project_to_pdf,
)
from .discovery import (
    LatexProjectDiscovery,
    LatexProjectReference,
    LatexTexSourceInfo,
    discover_latex_project,
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
from .resolution import (
    resolve_latex_project_root,
    select_latex_project_root,
)
from .written_bridge import (
    LATEX_PROJECT_COMPILED_DIRNAME,
    LATEX_PROJECT_DERIVED_DIRNAME,
    LatexProjectCompilationFailedError,
    LatexProjectPreparedContext,
    LatexProjectRootResolutionRequiredError,
    LatexProjectWrittenBridgeError,
    parse_canonical_latex_project,
    prepare_canonical_latex_project,
)
from .storage import (
    ARCHIVE_METADATA_FILENAME,
    EXTRACTED_DIRNAME,
    MANIFEST_FILENAME,
    ORIGINAL_ARCHIVE_FILENAME,
    ORIGINAL_DIRNAME,
    LatexProjectArchiveStore,
    StoredLatexProject,
    verify_stored_latex_project,
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
    "LatexProjectDiscovery",
    "LatexProjectReference",
    "LatexTexSourceInfo",
    "LatexProjectArchiveError",
    "LatexProjectArchiveRejectedError",
    "LatexProjectArchiveStore",
    "LatexProjectCompilation",
    "LATEX_PROJECT_COMPILED_DIRNAME",
    "LATEX_PROJECT_DERIVED_DIRNAME",
    "LatexProjectCompilationFailedError",
    "LatexProjectPreparedContext",
    "LatexProjectRootResolutionRequiredError",
    "LatexProjectWrittenBridgeError",
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
    "compile_stored_latex_project_to_pdf",
    "parse_canonical_latex_project",
    "prepare_canonical_latex_project",
    "compute_manifest_sha256",
    "discover_latex_project",
    "resolve_latex_project_root",
    "select_latex_project_root",
    "load_latex_project_config",
    "safe_extract_latex_project_zip",
    "save_latex_project_config",
    "verify_stored_latex_project",
]
