"""
Canonical submission-domain models for the Rubric Grading Tool.

v2.3.2 adds a source-agnostic identity/provenance layer underneath the
existing v2.2 parsing pipeline. These objects describe what a student
submitted; they do not parse answers, score work, touch the filesystem, or
depend on PyQt.

``Submission`` / ``ArtifactFile`` are therefore deliberately separate from
``ParsedSubmission`` in ``submissions.models``. The latter remains the
grading-facing representation of extracted content.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import re
import uuid
from typing import Any, Dict, List, Mapping, Optional


SUBMISSION_DOMAIN_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Source systems
# ---------------------------------------------------------------------------

SOURCE_SYSTEM_LOCAL_UPLOAD = "local_upload"
SOURCE_SYSTEM_LEGACY_LOCAL = "legacy_local"
SOURCE_SYSTEM_CANVAS = "canvas"
SOURCE_SYSTEM_GIT = "git"
SOURCE_SYSTEM_EXTERNAL_IMPORT = "external_import"

# ---------------------------------------------------------------------------
# Submission statuses
# ---------------------------------------------------------------------------

SUBMISSION_STATUS_IMPORTED = "imported"
SUBMISSION_STATUS_ACTIVE = "active"
SUBMISSION_STATUS_SUPERSEDED = "superseded"
SUBMISSION_STATUS_INVALID = "invalid"
SUBMISSION_STATUS_WITHDRAWN = "withdrawn"

# ---------------------------------------------------------------------------
# Artifact roles
# ---------------------------------------------------------------------------

ARTIFACT_ROLE_PRIMARY = "primary"
ARTIFACT_ROLE_RENDERED = "rendered"
ARTIFACT_ROLE_SOURCE = "source"
ARTIFACT_ROLE_ATTACHMENT = "attachment"
ARTIFACT_ROLE_SUPPORTING = "supporting"
ARTIFACT_ROLE_DERIVED = "derived"

# ---------------------------------------------------------------------------
# Artifact types
# ---------------------------------------------------------------------------

ARTIFACT_TYPE_PDF = "pdf"
ARTIFACT_TYPE_TEX = "tex"
ARTIFACT_TYPE_LATEX_PROJECT_ZIP = "latex_project_zip"
ARTIFACT_TYPE_PYTHON = "python"
ARTIFACT_TYPE_ZIP = "zip"
ARTIFACT_TYPE_DOCX = "docx"
ARTIFACT_TYPE_TEXT = "text"
ARTIFACT_TYPE_IMAGE = "image"
ARTIFACT_TYPE_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Import matching states
# ---------------------------------------------------------------------------

MATCH_STATUS_MATCHED = "matched"
MATCH_STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
MATCH_STATUS_AMBIGUOUS = "ambiguous"
MATCH_STATUS_UNMATCHED = "unmatched"
MATCH_STATUS_IGNORED = "ignored"

# ---------------------------------------------------------------------------
# Import validation states
# ---------------------------------------------------------------------------

VALIDATION_STATUS_PENDING = "pending"
VALIDATION_STATUS_READY = "ready"
VALIDATION_STATUS_NEEDS_MAPPING = "needs_mapping"
VALIDATION_STATUS_DUPLICATE = "duplicate"
VALIDATION_STATUS_UNSUPPORTED = "unsupported"
VALIDATION_STATUS_INVALID = "invalid"
VALIDATION_STATUS_ERROR = "error"

# ---------------------------------------------------------------------------
# Import batch states
# ---------------------------------------------------------------------------

IMPORT_BATCH_STATUS_PREPARING = "preparing"
IMPORT_BATCH_STATUS_READY = "ready"
IMPORT_BATCH_STATUS_COMMITTING = "committing"
IMPORT_BATCH_STATUS_COMPLETED = "completed"
IMPORT_BATCH_STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
IMPORT_BATCH_STATUS_CANCELLED = "cancelled"
IMPORT_BATCH_STATUS_FAILED = "failed"


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Internal validation / serialization helpers
# ---------------------------------------------------------------------------

def _text(value: Any, name: str) -> str:
    """Return a stripped non-empty string."""
    value = "" if value is None else str(value).strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _optional_text(value: Any) -> Optional[str]:
    """Return a stripped string or ``None`` for an empty value."""
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def _metadata(
    value: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return an independent JSON-friendly metadata dictionary."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")

    return deepcopy(dict(value))


def _sha256(
    value: Any,
    *,
    required: bool = True,
) -> Optional[str]:
    """Validate and normalize a SHA-256 hexadecimal digest."""
    if value is None or not str(value).strip():
        if required:
            raise ValueError("sha256 is required")
        return None

    value = str(value).strip().lower()

    if not _SHA256_RE.fullmatch(value):
        raise ValueError(
            "sha256 must be a 64-character hexadecimal digest"
        )

    return value


def _schema_checked(
    data: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate the optional serialized domain schema marker."""
    if not isinstance(data, Mapping):
        raise TypeError(
            "serialized domain data must be a mapping"
        )

    version = data.get("schema_version")

    if (
        version is not None
        and str(version) != SUBMISSION_DOMAIN_SCHEMA_VERSION
    ):
        raise ValueError(
            f"Unsupported submission-domain schema {version!r}; "
            f"expected {SUBMISSION_DOMAIN_SCHEMA_VERSION!r}"
        )

    return data


def _serialized(value: Any) -> Dict[str, Any]:
    """Return a JSON-friendly dataclass representation with schema version."""
    payload = asdict(value)
    payload["schema_version"] = SUBMISSION_DOMAIN_SCHEMA_VERSION
    return payload


# ---------------------------------------------------------------------------
# Opaque internal ID helpers
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def generate_submission_id() -> str:
    """Return a new opaque canonical submission ID."""
    return _new_id("sub")


def generate_artifact_id() -> str:
    """Return a new opaque canonical artifact ID."""
    return _new_id("art")


def generate_derived_artifact_id() -> str:
    """Return a new opaque derived-artifact ID."""
    return _new_id("drv")


def generate_import_batch_id() -> str:
    """Return a new opaque import-batch ID."""
    return _new_id("imp")


def generate_candidate_id() -> str:
    """Return a new opaque import-candidate ID."""
    return _new_id("cand")


# ---------------------------------------------------------------------------
# External provenance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExternalReference:
    """
    Typed provenance reference to an entity in an external system.

    External identifiers are supporting provenance only. They never replace
    grading-app internal IDs such as ``student_id``, ``assessment_id`` or
    ``submission_id``.

    Examples:

        system="canvas"
        entity_type="assignment"
        external_id="3889170"

    or:

        system="canvas"
        entity_type="file"
        external_id="82177342"
    """

    system: str
    entity_type: str
    external_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "system",
            _text(self.system, "system"),
        )
        object.__setattr__(
            self,
            "entity_type",
            _text(self.entity_type, "entity_type"),
        )
        object.__setattr__(
            self,
            "external_id",
            _text(self.external_id, "external_id"),
        )
        object.__setattr__(
            self,
            "metadata",
            _metadata(self.metadata),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ExternalReference":
        """Construct an external reference from serialized data."""
        if not isinstance(data, Mapping):
            raise TypeError(
                "ExternalReference data must be a mapping"
            )

        return cls(
            system=data.get("system"),
            entity_type=data.get("entity_type"),
            external_id=data.get("external_id"),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Canonical artifacts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactFile:
    """
    One committed original file belonging to a canonical submission.

    This object represents an artifact after it has been committed to canonical
    storage. Therefore its stable relative path, byte size and SHA-256 digest
    are required.

    Commit 2 introduces the repository responsible for actually copying and
    preserving those bytes.
    """

    artifact_id: str
    submission_id: str

    role: str
    artifact_type: str

    original_filename: str
    stored_relative_path: str

    size_bytes: int
    sha256: str

    mime_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_id",
            _text(self.artifact_id, "artifact_id"),
        )
        object.__setattr__(
            self,
            "submission_id",
            _text(self.submission_id, "submission_id"),
        )
        object.__setattr__(
            self,
            "role",
            _text(self.role, "role"),
        )
        object.__setattr__(
            self,
            "artifact_type",
            _text(self.artifact_type, "artifact_type"),
        )
        object.__setattr__(
            self,
            "original_filename",
            _text(self.original_filename, "original_filename"),
        )
        object.__setattr__(
            self,
            "stored_relative_path",
            _text(
                self.stored_relative_path,
                "stored_relative_path",
            ),
        )

        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
        ):
            raise TypeError(
                "size_bytes must be an integer"
            )

        if self.size_bytes < 0:
            raise ValueError(
                "size_bytes must be non-negative"
            )

        object.__setattr__(
            self,
            "sha256",
            _sha256(self.sha256),
        )
        object.__setattr__(
            self,
            "mime_type",
            _optional_text(self.mime_type),
        )
        object.__setattr__(
            self,
            "metadata",
            _metadata(self.metadata),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ArtifactFile":
        """Construct a canonical artifact from serialized data."""
        if not isinstance(data, Mapping):
            raise TypeError(
                "ArtifactFile data must be a mapping"
            )

        return cls(
            artifact_id=data.get("artifact_id"),
            submission_id=data.get("submission_id"),
            role=data.get("role"),
            artifact_type=data.get("artifact_type"),
            original_filename=data.get("original_filename"),
            stored_relative_path=data.get(
                "stored_relative_path"
            ),
            size_bytes=data.get("size_bytes"),
            sha256=data.get("sha256"),
            mime_type=data.get("mime_type"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class DerivedArtifact:
    """
    Artifact produced from one or more immutable source artifacts.

    Examples include:

    * parsed question-answer JSON;
    * normalized text;
    * locally compiled validation PDFs;
    * extracted project manifests.

    Derived artifacts preserve lineage back to the canonical source artifacts.
    """

    derived_artifact_id: str
    source_artifact_ids: List[str]

    kind: str

    generator: str
    generator_version: str
    created_at: str

    stored_relative_path: Optional[str] = None
    sha256: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "derived_artifact_id",
            _text(
                self.derived_artifact_id,
                "derived_artifact_id",
            ),
        )

        if not isinstance(
            self.source_artifact_ids,
            (list, tuple),
        ):
            raise TypeError(
                "source_artifact_ids must be a list or tuple"
            )

        source_ids = [
            _text(value, "source_artifact_id")
            for value in self.source_artifact_ids
        ]

        if not source_ids:
            raise ValueError(
                "source_artifact_ids must contain at least one ID"
            )

        if len(source_ids) != len(set(source_ids)):
            raise ValueError(
                "source_artifact_ids must not contain duplicates"
            )

        object.__setattr__(
            self,
            "source_artifact_ids",
            source_ids,
        )
        object.__setattr__(
            self,
            "kind",
            _text(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "generator",
            _text(self.generator, "generator"),
        )
        object.__setattr__(
            self,
            "generator_version",
            _text(
                self.generator_version,
                "generator_version",
            ),
        )
        object.__setattr__(
            self,
            "created_at",
            _text(self.created_at, "created_at"),
        )
        object.__setattr__(
            self,
            "stored_relative_path",
            _optional_text(self.stored_relative_path),
        )
        object.__setattr__(
            self,
            "sha256",
            _sha256(
                self.sha256,
                required=False,
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _metadata(self.metadata),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a versioned JSON-friendly representation."""
        return _serialized(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "DerivedArtifact":
        """Construct a derived artifact from serialized data."""
        data = _schema_checked(data)

        return cls(
            derived_artifact_id=data.get(
                "derived_artifact_id"
            ),
            source_artifact_ids=list(
                data.get("source_artifact_ids") or []
            ),
            kind=data.get("kind"),
            generator=data.get("generator"),
            generator_version=data.get(
                "generator_version"
            ),
            created_at=data.get("created_at"),
            stored_relative_path=data.get(
                "stored_relative_path"
            ),
            sha256=data.get("sha256"),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Canonical logical submission
# ---------------------------------------------------------------------------

@dataclass
class Submission:
    """
    Canonical logical submission/attempt for one student and assessment.

    A submission is not synonymous with one file. A single logical attempt may
    contain, for example:

        rendered PDF + LaTeX source ZIP

    or later:

        main.py + helpers.py

    The repository introduced in Commit 2 will own persistence and active
    attempt indexing.
    """

    submission_id: str
    assessment_id: str
    student_id: str

    source_system: str
    imported_at: str

    attempt: Optional[int] = None
    is_active_attempt: bool = True

    submitted_at: Optional[str] = None

    status: str = SUBMISSION_STATUS_IMPORTED

    artifacts: List[ArtifactFile] = field(
        default_factory=list
    )
    external_refs: List[ExternalReference] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.submission_id = _text(
            self.submission_id,
            "submission_id",
        )
        self.assessment_id = _text(
            self.assessment_id,
            "assessment_id",
        )
        self.student_id = _text(
            self.student_id,
            "student_id",
        )
        self.source_system = _text(
            self.source_system,
            "source_system",
        )
        self.imported_at = _text(
            self.imported_at,
            "imported_at",
        )

        self.submitted_at = _optional_text(
            self.submitted_at
        )

        self.status = _text(
            self.status,
            "status",
        )

        if self.attempt is not None:
            if (
                isinstance(self.attempt, bool)
                or not isinstance(self.attempt, int)
            ):
                raise TypeError(
                    "attempt must be an integer or None"
                )

            if self.attempt <= 0:
                raise ValueError(
                    "attempt must be positive"
                )

        if not isinstance(
            self.is_active_attempt,
            bool,
        ):
            raise TypeError(
                "is_active_attempt must be a bool"
            )

        if not isinstance(
            self.artifacts,
            (list, tuple),
        ):
            raise TypeError(
                "artifacts must be a list or tuple"
            )

        artifacts = [
            item
            if isinstance(item, ArtifactFile)
            else ArtifactFile.from_dict(item)
            for item in self.artifacts
        ]

        if any(
            item.submission_id != self.submission_id
            for item in artifacts
        ):
            raise ValueError(
                "every artifact must reference "
                "its parent submission_id"
            )

        artifact_ids = [
            item.artifact_id
            for item in artifacts
        ]

        if len(artifact_ids) != len(
            set(artifact_ids)
        ):
            raise ValueError(
                "artifact_id values must be unique "
                "within a submission"
            )

        self.artifacts = artifacts

        if not isinstance(
            self.external_refs,
            (list, tuple),
        ):
            raise TypeError(
                "external_refs must be a list or tuple"
            )

        refs = [
            item
            if isinstance(item, ExternalReference)
            else ExternalReference.from_dict(item)
            for item in self.external_refs
        ]

        ref_keys = [
            (
                item.system,
                item.entity_type,
                item.external_id,
            )
            for item in refs
        ]

        if len(ref_keys) != len(set(ref_keys)):
            raise ValueError(
                "external references must be unique "
                "within a submission"
            )

        self.external_refs = refs
        self.metadata = _metadata(self.metadata)

    def artifact_by_id(
        self,
        artifact_id: str,
    ) -> Optional[ArtifactFile]:
        """Return one artifact by stable internal ID."""
        target = str(artifact_id).strip()

        return next(
            (
                item
                for item in self.artifacts
                if item.artifact_id == target
            ),
            None,
        )

    def artifacts_by_type(
        self,
        artifact_type: str,
    ) -> List[ArtifactFile]:
        """Return all artifacts of a particular canonical type."""
        target = str(artifact_type).strip()

        return [
            item
            for item in self.artifacts
            if item.artifact_type == target
        ]

    def artifacts_by_role(
        self,
        role: str,
    ) -> List[ArtifactFile]:
        """Return all artifacts having a particular logical role."""
        target = str(role).strip()

        return [
            item
            for item in self.artifacts
            if item.role == target
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Return a versioned JSON-friendly representation."""
        return _serialized(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "Submission":
        """Construct a canonical submission from serialized data."""
        data = _schema_checked(data)

        return cls(
            submission_id=data.get(
                "submission_id"
            ),
            assessment_id=data.get(
                "assessment_id"
            ),
            student_id=data.get(
                "student_id"
            ),
            source_system=data.get(
                "source_system"
            ),
            imported_at=data.get(
                "imported_at"
            ),
            attempt=data.get(
                "attempt"
            ),
            is_active_attempt=data.get(
                "is_active_attempt",
                True,
            ),
            submitted_at=data.get(
                "submitted_at"
            ),
            status=data.get(
                "status",
                SUBMISSION_STATUS_IMPORTED,
            ),
            artifacts=[
                ArtifactFile.from_dict(item)
                for item in data.get(
                    "artifacts",
                    [],
                )
            ],
            external_refs=[
                ExternalReference.from_dict(item)
                for item in data.get(
                    "external_refs",
                    [],
                )
            ],
            metadata=data.get(
                "metadata",
                {},
            ),
        )


# ---------------------------------------------------------------------------
# Import discovery / preview domain objects
# ---------------------------------------------------------------------------

@dataclass
class CandidateFile:
    """
    File discovered for import but not yet committed to canonical storage.

    ``sha256`` and ``size_bytes`` are optional because discovery may occur
    before Commit 2/3 performs hashing and persistence.
    """

    source_path: str
    original_filename: str

    artifact_type: str = ARTIFACT_TYPE_UNKNOWN
    role: str = ARTIFACT_ROLE_PRIMARY

    size_bytes: Optional[int] = None
    sha256: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.source_path = _text(
            self.source_path,
            "source_path",
        )
        self.original_filename = _text(
            self.original_filename,
            "original_filename",
        )
        self.artifact_type = _text(
            self.artifact_type,
            "artifact_type",
        )
        self.role = _text(
            self.role,
            "role",
        )

        if self.size_bytes is not None:
            if (
                isinstance(self.size_bytes, bool)
                or not isinstance(
                    self.size_bytes,
                    int,
                )
            ):
                raise TypeError(
                    "size_bytes must be "
                    "an integer or None"
                )

            if self.size_bytes < 0:
                raise ValueError(
                    "size_bytes must be non-negative"
                )

        self.sha256 = _sha256(
            self.sha256,
            required=False,
        )

        self.metadata = _metadata(
            self.metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "CandidateFile":
        """Construct a candidate file from serialized data."""
        if not isinstance(data, Mapping):
            raise TypeError(
                "CandidateFile data must be a mapping"
            )

        return cls(
            source_path=data.get(
                "source_path"
            ),
            original_filename=data.get(
                "original_filename"
            ),
            artifact_type=data.get(
                "artifact_type",
                ARTIFACT_TYPE_UNKNOWN,
            ),
            role=data.get(
                "role",
                ARTIFACT_ROLE_PRIMARY,
            ),
            size_bytes=data.get(
                "size_bytes"
            ),
            sha256=data.get(
                "sha256"
            ),
            metadata=data.get(
                "metadata",
                {},
            ),
        )


@dataclass
class ImportCandidate:
    """
    One proposed logical submission shown in import preview before commit.

    Commit 3 will add the source adapters and importer that produce and consume
    these objects.
    """

    candidate_id: str
    source_system: str

    source_locator: Optional[str] = None

    proposed_student_id: Optional[str] = None
    proposed_assessment_id: Optional[str] = None
    proposed_attempt: Optional[int] = None

    files: List[CandidateFile] = field(
        default_factory=list
    )

    match_status: str = MATCH_STATUS_UNMATCHED
    validation_status: str = VALIDATION_STATUS_PENDING

    warnings: List[str] = field(
        default_factory=list
    )
    errors: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.candidate_id = _text(
            self.candidate_id,
            "candidate_id",
        )
        self.source_system = _text(
            self.source_system,
            "source_system",
        )

        self.source_locator = _optional_text(
            self.source_locator
        )
        self.proposed_student_id = _optional_text(
            self.proposed_student_id
        )
        self.proposed_assessment_id = _optional_text(
            self.proposed_assessment_id
        )

        if self.proposed_attempt is not None:
            if (
                isinstance(self.proposed_attempt, bool)
                or not isinstance(
                    self.proposed_attempt,
                    int,
                )
            ):
                raise TypeError(
                    "proposed_attempt must be "
                    "an integer or None"
                )

            if self.proposed_attempt <= 0:
                raise ValueError(
                    "proposed_attempt must be positive"
                )

        if not isinstance(
            self.files,
            (list, tuple),
        ):
            raise TypeError(
                "files must be a list or tuple"
            )

        self.files = [
            item
            if isinstance(item, CandidateFile)
            else CandidateFile.from_dict(item)
            for item in self.files
        ]

        self.match_status = _text(
            self.match_status,
            "match_status",
        )

        self.validation_status = _text(
            self.validation_status,
            "validation_status",
        )

        if not isinstance(
            self.warnings,
            (list, tuple),
        ):
            raise TypeError(
                "warnings must be a list or tuple"
            )

        if not isinstance(
            self.errors,
            (list, tuple),
        ):
            raise TypeError(
                "errors must be a list or tuple"
            )

        self.warnings = [
            str(item)
            for item in self.warnings
        ]

        self.errors = [
            str(item)
            for item in self.errors
        ]

        self.metadata = _metadata(
            self.metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a versioned JSON-friendly representation."""
        return _serialized(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ImportCandidate":
        """Construct an import candidate from serialized data."""
        data = _schema_checked(data)

        return cls(
            candidate_id=data.get(
                "candidate_id"
            ),
            source_system=data.get(
                "source_system"
            ),
            source_locator=data.get(
                "source_locator"
            ),
            proposed_student_id=data.get(
                "proposed_student_id"
            ),
            proposed_assessment_id=data.get(
                "proposed_assessment_id"
            ),
            proposed_attempt=data.get(
                "proposed_attempt"
            ),
            files=[
                CandidateFile.from_dict(item)
                for item in data.get(
                    "files",
                    [],
                )
            ],
            match_status=data.get(
                "match_status",
                MATCH_STATUS_UNMATCHED,
            ),
            validation_status=data.get(
                "validation_status",
                VALIDATION_STATUS_PENDING,
            ),
            warnings=list(
                data.get(
                    "warnings",
                    [],
                )
            ),
            errors=list(
                data.get(
                    "errors",
                    [],
                )
            ),
            metadata=data.get(
                "metadata",
                {},
            ),
        )


@dataclass
class ImportBatch:
    """
    Audit-friendly summary/state for one future import operation.

    Commit 3 will add the importer that mutates these counts and statuses.
    """

    import_batch_id: str
    source_system: str
    started_at: str

    completed_at: Optional[str] = None
    created_by: Optional[str] = None

    candidate_count: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0

    status: str = IMPORT_BATCH_STATUS_PREPARING

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.import_batch_id = _text(
            self.import_batch_id,
            "import_batch_id",
        )
        self.source_system = _text(
            self.source_system,
            "source_system",
        )
        self.started_at = _text(
            self.started_at,
            "started_at",
        )

        self.completed_at = _optional_text(
            self.completed_at
        )
        self.created_by = _optional_text(
            self.created_by
        )

        self.status = _text(
            self.status,
            "status",
        )

        self.metadata = _metadata(
            self.metadata
        )

        for name in (
            "candidate_count",
            "imported_count",
            "skipped_count",
            "error_count",
        ):
            value = getattr(
                self,
                name,
            )

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
            ):
                raise TypeError(
                    f"{name} must be an integer"
                )

            if value < 0:
                raise ValueError(
                    f"{name} must be non-negative"
                )

        if (
            self.imported_count
            + self.skipped_count
            + self.error_count
            > self.candidate_count
        ):
            raise ValueError(
                "processed candidate counts must not "
                "exceed candidate_count"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a versioned JSON-friendly representation."""
        return _serialized(self)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ImportBatch":
        """Construct an import batch from serialized data."""
        data = _schema_checked(data)

        return cls(
            import_batch_id=data.get(
                "import_batch_id"
            ),
            source_system=data.get(
                "source_system"
            ),
            started_at=data.get(
                "started_at"
            ),
            completed_at=data.get(
                "completed_at"
            ),
            created_by=data.get(
                "created_by"
            ),
            candidate_count=data.get(
                "candidate_count",
                0,
            ),
            imported_count=data.get(
                "imported_count",
                0,
            ),
            skipped_count=data.get(
                "skipped_count",
                0,
            ),
            error_count=data.get(
                "error_count",
                0,
            ),
            status=data.get(
                "status",
                IMPORT_BATCH_STATUS_PREPARING,
            ),
            metadata=data.get(
                "metadata",
                {},
            ),
        )


__all__ = [
    name
    for name in globals()
    if (
        name.startswith(
            (
                "ARTIFACT_",
                "IMPORT_BATCH_",
                "MATCH_",
                "SOURCE_SYSTEM_",
                "SUBMISSION_",
                "VALIDATION_",
            )
        )
        or name
        in {
            "ArtifactFile",
            "CandidateFile",
            "DerivedArtifact",
            "ExternalReference",
            "ImportBatch",
            "ImportCandidate",
            "Submission",
            "generate_artifact_id",
            "generate_candidate_id",
            "generate_derived_artifact_id",
            "generate_import_batch_id",
            "generate_submission_id",
        }
    )
]
