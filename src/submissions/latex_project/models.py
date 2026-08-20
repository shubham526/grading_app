"""Domain contracts for v2.3.4.2 Overleaf / LaTeX Project ZIP ingestion.

The objects in this module describe archive provenance, extracted project-file
metadata, root-document resolution, import candidates, and diagnostics.  They
do not open ZIP files, extract bytes, compile LaTeX, execute subprocesses, or
depend on desktop UI libraries.  Later v2.3.4.2 commits consume these contracts.

All persisted paths are project-relative POSIX-style paths.  Absolute host
paths are deliberately excluded from portable provenance.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import re
import uuid
from pathlib import PurePosixPath
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .errors import (
    LatexProjectSerializationError,
    LatexProjectValidationError,
    UnsupportedLatexProjectSchemaError,
)


LATEX_PROJECT_DOMAIN_SCHEMA_VERSION = "1.0"

ARCHIVE_VALIDATION_PENDING = "pending"
ARCHIVE_VALIDATION_VALID = "valid"
ARCHIVE_VALIDATION_INVALID = "invalid"
ARCHIVE_VALIDATION_REJECTED = "rejected"
ARCHIVE_VALIDATION_STATUSES = (
    ARCHIVE_VALIDATION_PENDING,
    ARCHIVE_VALIDATION_VALID,
    ARCHIVE_VALIDATION_INVALID,
    ARCHIVE_VALIDATION_REJECTED,
)

ROOT_RESOLUTION_PENDING = "pending"
ROOT_RESOLUTION_RESOLVED = "resolved"
ROOT_RESOLUTION_AMBIGUOUS = "ambiguous"
ROOT_RESOLUTION_NO_ROOT_FOUND = "no_root_found"
ROOT_RESOLUTION_INVALID_PROJECT = "invalid_project"
ROOT_RESOLUTION_STATUSES = (
    ROOT_RESOLUTION_PENDING,
    ROOT_RESOLUTION_RESOLVED,
    ROOT_RESOLUTION_AMBIGUOUS,
    ROOT_RESOLUTION_NO_ROOT_FOUND,
    ROOT_RESOLUTION_INVALID_PROJECT,
)

ROOT_METHOD_NONE = "none"
ROOT_METHOD_UNIQUE_DOCUMENT = "unique_document"
ROOT_METHOD_PREFERRED_NAME = "preferred_name"
ROOT_METHOD_INSTRUCTOR_SELECTED = "instructor_selected"
ROOT_RESOLUTION_METHODS = (
    ROOT_METHOD_NONE,
    ROOT_METHOD_UNIQUE_DOCUMENT,
    ROOT_METHOD_PREFERRED_NAME,
    ROOT_METHOD_INSTRUCTOR_SELECTED,
)

FILE_ROLE_ROOT = "root"
FILE_ROLE_TEX_SOURCE = "tex_source"
FILE_ROLE_BIBLIOGRAPHY = "bibliography"
FILE_ROLE_FIGURE = "figure"
FILE_ROLE_STYLE = "style"
FILE_ROLE_DATA = "data"
FILE_ROLE_OTHER = "other"
FILE_ROLES = (
    FILE_ROLE_ROOT,
    FILE_ROLE_TEX_SOURCE,
    FILE_ROLE_BIBLIOGRAPHY,
    FILE_ROLE_FIGURE,
    FILE_ROLE_STYLE,
    FILE_ROLE_DATA,
    FILE_ROLE_OTHER,
)

DIAGNOSTIC_INFO = "info"
DIAGNOSTIC_WARNING = "warning"
DIAGNOSTIC_BLOCKING = "blocking"
DIAGNOSTIC_SEVERITIES = (
    DIAGNOSTIC_INFO,
    DIAGNOSTIC_WARNING,
    DIAGNOSTIC_BLOCKING,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _text(value, name):
    value = "" if value is None else str(value).strip()
    if not value:
        raise LatexProjectValidationError("%s must not be empty" % name)
    return value


def _optional_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _metadata(value, name="metadata"):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LatexProjectValidationError("%s must be a mapping" % name)
    return deepcopy(dict(value))


def _int(value, name, minimum=None):
    if isinstance(value, bool):
        raise LatexProjectValidationError("%s must be an integer, not boolean" % name)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise LatexProjectValidationError("%s must be an integer" % name)
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = float(number)
    if numeric_value != float(number):
        raise LatexProjectValidationError("%s must be an integer" % name)
    if minimum is not None and number < minimum:
        raise LatexProjectValidationError(
            "%s must be at least %s" % (name, minimum)
        )
    return number


def _optional_int(value, name, minimum=None):
    if value is None:
        return None
    return _int(value, name, minimum=minimum)


def _sha256(value, name="sha256", required=True):
    if value is None or not str(value).strip():
        if required:
            raise LatexProjectValidationError("%s is required" % name)
        return None
    digest = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise LatexProjectValidationError(
            "%s must be a 64-character hexadecimal SHA-256 digest" % name
        )
    return digest


def normalize_project_relative_path(value, name="relative_path"):
    """Return one safe, portable, POSIX-style project-relative path.

    This is a domain-level normalization rule, not archive extraction.  Commit
    2 performs member-type checks and verifies that extraction cannot escape a
    disposable project root.
    """

    raw = _text(value, name)
    if "\x00" in raw:
        raise LatexProjectValidationError("%s must not contain NUL bytes" % name)
    raw = raw.replace("\\", "/")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise LatexProjectValidationError("%s must be a relative path" % name)
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise LatexProjectValidationError("%s must be a relative path" % name)
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        raise LatexProjectValidationError(
            "%s must not contain parent traversal" % name
        )
    normalized = "/".join(parts)
    if normalized.startswith("/"):
        raise LatexProjectValidationError("%s must be a relative path" % name)
    return normalized


def _path_tuple(values, name, allow_empty=True):
    if values is None:
        values = ()
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Sequence):
        raise LatexProjectValidationError(
            "%s must be an ordered sequence of paths" % name
        )
    result = []
    seen = set()
    for raw in values:
        value = normalize_project_relative_path(raw, "%s entry" % name)
        if value in seen:
            raise LatexProjectValidationError(
                "%s contains duplicate path %r" % (name, value)
            )
        seen.add(value)
        result.append(value)
    if not allow_empty and not result:
        raise LatexProjectValidationError("%s must not be empty" % name)
    return tuple(result)


def _status(value, allowed, name):
    value = _text(value, name).lower()
    if value not in allowed:
        raise LatexProjectValidationError(
            "%s must be one of: %s" % (name, ", ".join(allowed))
        )
    return value


def _schema_checked(data):
    if not isinstance(data, Mapping):
        raise LatexProjectSerializationError("serialized data must be a mapping")
    version = data.get("schema_version", LATEX_PROJECT_DOMAIN_SCHEMA_VERSION)
    if str(version) not in ("1", LATEX_PROJECT_DOMAIN_SCHEMA_VERSION):
        raise UnsupportedLatexProjectSchemaError(
            "Unsupported LaTeX-project domain schema %r; expected %r"
            % (version, LATEX_PROJECT_DOMAIN_SCHEMA_VERSION)
        )
    return data


def _new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex)


def generate_latex_project_id():
    """Return a new opaque LaTeX-project ID."""
    return _new_id("lproj")


def generate_latex_project_candidate_id():
    """Return a new opaque LaTeX-project import-candidate ID."""
    return _new_id("lpcand")


@dataclass(frozen=True)
class LatexProjectDiagnostic:
    """One portable diagnostic emitted while ingesting or resolving a project."""

    code: str
    message: str
    severity: str = DIAGNOSTIC_WARNING
    relative_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(self, "message", _text(self.message, "message"))
        object.__setattr__(
            self,
            "severity",
            _status(self.severity, DIAGNOSTIC_SEVERITIES, "severity"),
        )
        relative_path = self.relative_path
        if relative_path is not None:
            relative_path = normalize_project_relative_path(
                relative_path,
                "relative_path",
            )
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "relative_path": self.relative_path,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise LatexProjectSerializationError(
                "LatexProjectDiagnostic data must be a mapping"
            )
        return cls(
            code=data.get("code"),
            message=data.get("message"),
            severity=data.get("severity", DIAGNOSTIC_WARNING),
            relative_path=data.get("relative_path"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class LatexProjectFile:
    """Metadata for one regular file in an extracted LaTeX project manifest."""

    relative_path: str
    size_bytes: int
    sha256: str
    role: str = FILE_ROLE_OTHER
    media_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self,
            "relative_path",
            normalize_project_relative_path(self.relative_path),
        )
        object.__setattr__(
            self,
            "size_bytes",
            _int(self.size_bytes, "size_bytes", minimum=0),
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256))
        object.__setattr__(self, "role", _status(self.role, FILE_ROLES, "role"))
        object.__setattr__(self, "media_type", _optional_text(self.media_type))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "role": self.role,
            "media_type": self.media_type,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise LatexProjectSerializationError(
                "LatexProjectFile data must be a mapping"
            )
        return cls(
            relative_path=data.get("relative_path"),
            size_bytes=data.get("size_bytes"),
            sha256=data.get("sha256"),
            role=data.get("role", FILE_ROLE_OTHER),
            media_type=data.get("media_type"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class LatexProjectManifest:
    """Deterministic manifest metadata for safely extracted regular files."""

    project_id: str
    files: Tuple[LatexProjectFile, ...]
    total_uncompressed_bytes: int
    manifest_sha256: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        project_id = _text(self.project_id, "project_id")
        values = []
        for value in self.files or ():
            if isinstance(value, LatexProjectFile):
                item = value
            elif isinstance(value, Mapping):
                item = LatexProjectFile.from_dict(value)
            else:
                raise LatexProjectValidationError(
                    "files must contain LatexProjectFile objects or mappings"
                )
            values.append(item)
        paths = [item.relative_path for item in values]
        if len(paths) != len(set(paths)):
            raise LatexProjectValidationError(
                "files contains duplicate relative paths"
            )
        expected_total = sum(item.size_bytes for item in values)
        total = _int(
            self.total_uncompressed_bytes,
            "total_uncompressed_bytes",
            minimum=0,
        )
        if total != expected_total:
            raise LatexProjectValidationError(
                "total_uncompressed_bytes does not match manifest file sizes"
            )
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "files", tuple(values))
        object.__setattr__(self, "total_uncompressed_bytes", total)
        object.__setattr__(
            self,
            "manifest_sha256",
            _sha256(self.manifest_sha256, "manifest_sha256", required=False),
        )
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @property
    def file_count(self):
        return len(self.files)

    def file_by_path(self, relative_path):
        normalized = normalize_project_relative_path(relative_path)
        for item in self.files:
            if item.relative_path == normalized:
                return item
        return None

    def to_dict(self):
        return {
            "schema_version": LATEX_PROJECT_DOMAIN_SCHEMA_VERSION,
            "project_id": self.project_id,
            "files": [item.to_dict() for item in self.files],
            "file_count": self.file_count,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "manifest_sha256": self.manifest_sha256,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        data = _schema_checked(data)
        files = tuple(
            LatexProjectFile.from_dict(item)
            if isinstance(item, Mapping)
            else item
            for item in (data.get("files") or ())
        )
        declared_count = data.get("file_count")
        if declared_count is not None and _int(
            declared_count,
            "file_count",
            minimum=0,
        ) != len(files):
            raise LatexProjectSerializationError(
                "file_count does not match serialized files"
            )
        return cls(
            project_id=data.get("project_id"),
            files=files,
            total_uncompressed_bytes=data.get("total_uncompressed_bytes", 0),
            manifest_sha256=data.get("manifest_sha256"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class LatexProjectArchive:
    """Portable provenance for the student's original immutable ZIP artifact."""

    project_id: str
    source_artifact_id: str
    original_filename: str
    archive_sha256: str
    archive_size_bytes: int
    validation_status: str = ARCHIVE_VALIDATION_PENDING
    imported_at: Optional[str] = None
    diagnostics: Tuple[LatexProjectDiagnostic, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "project_id", _text(self.project_id, "project_id"))
        object.__setattr__(
            self,
            "source_artifact_id",
            _text(self.source_artifact_id, "source_artifact_id"),
        )
        object.__setattr__(
            self,
            "original_filename",
            _text(self.original_filename, "original_filename"),
        )
        object.__setattr__(
            self,
            "archive_sha256",
            _sha256(self.archive_sha256, "archive_sha256"),
        )
        object.__setattr__(
            self,
            "archive_size_bytes",
            _int(self.archive_size_bytes, "archive_size_bytes", minimum=0),
        )
        object.__setattr__(
            self,
            "validation_status",
            _status(
                self.validation_status,
                ARCHIVE_VALIDATION_STATUSES,
                "validation_status",
            ),
        )
        object.__setattr__(self, "imported_at", _optional_text(self.imported_at))
        diagnostics = []
        for value in self.diagnostics or ():
            if isinstance(value, LatexProjectDiagnostic):
                diagnostics.append(value)
            elif isinstance(value, Mapping):
                diagnostics.append(LatexProjectDiagnostic.from_dict(value))
            else:
                raise LatexProjectValidationError(
                    "diagnostics must contain LatexProjectDiagnostic objects or mappings"
                )
        object.__setattr__(self, "diagnostics", tuple(diagnostics))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @property
    def has_blocking_diagnostics(self):
        return any(
            item.severity == DIAGNOSTIC_BLOCKING for item in self.diagnostics
        )

    def to_dict(self):
        return {
            "schema_version": LATEX_PROJECT_DOMAIN_SCHEMA_VERSION,
            "project_id": self.project_id,
            "source_artifact_id": self.source_artifact_id,
            "original_filename": self.original_filename,
            "archive_sha256": self.archive_sha256,
            "archive_size_bytes": self.archive_size_bytes,
            "validation_status": self.validation_status,
            "imported_at": self.imported_at,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        data = _schema_checked(data)
        return cls(
            project_id=data.get("project_id"),
            source_artifact_id=data.get("source_artifact_id"),
            original_filename=data.get("original_filename"),
            archive_sha256=data.get("archive_sha256"),
            archive_size_bytes=data.get("archive_size_bytes"),
            validation_status=data.get(
                "validation_status",
                ARCHIVE_VALIDATION_PENDING,
            ),
            imported_at=data.get("imported_at"),
            diagnostics=tuple(data.get("diagnostics") or ()),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class LatexProjectResolution:
    """Result contract for deterministic or instructor-confirmed root selection."""

    status: str
    root_relative_path: Optional[str] = None
    candidate_paths: Tuple[str, ...] = field(default_factory=tuple)
    resolution_method: str = ROOT_METHOD_NONE
    diagnostics: Tuple[LatexProjectDiagnostic, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        status = _status(self.status, ROOT_RESOLUTION_STATUSES, "status")
        method = _status(
            self.resolution_method,
            ROOT_RESOLUTION_METHODS,
            "resolution_method",
        )
        root = self.root_relative_path
        if root is not None:
            root = normalize_project_relative_path(root, "root_relative_path")
        candidates = _path_tuple(self.candidate_paths, "candidate_paths")

        if status == ROOT_RESOLUTION_RESOLVED:
            if root is None:
                raise LatexProjectValidationError(
                    "resolved root status requires root_relative_path"
                )
            if method == ROOT_METHOD_NONE:
                raise LatexProjectValidationError(
                    "resolved root status requires a resolution_method"
                )
            if candidates and root not in candidates:
                raise LatexProjectValidationError(
                    "resolved root_relative_path must be one of candidate_paths"
                )
        else:
            if root is not None:
                raise LatexProjectValidationError(
                    "unresolved root status must not declare root_relative_path"
                )
            if method != ROOT_METHOD_NONE:
                raise LatexProjectValidationError(
                    "unresolved root status must use resolution_method='none'"
                )
        if status == ROOT_RESOLUTION_AMBIGUOUS and len(candidates) < 2:
            raise LatexProjectValidationError(
                "ambiguous root status requires at least two candidate_paths"
            )

        diagnostics = []
        for value in self.diagnostics or ():
            if isinstance(value, LatexProjectDiagnostic):
                diagnostics.append(value)
            elif isinstance(value, Mapping):
                diagnostics.append(LatexProjectDiagnostic.from_dict(value))
            else:
                raise LatexProjectValidationError(
                    "diagnostics must contain LatexProjectDiagnostic objects or mappings"
                )

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "root_relative_path", root)
        object.__setattr__(self, "candidate_paths", candidates)
        object.__setattr__(self, "resolution_method", method)
        object.__setattr__(self, "diagnostics", tuple(diagnostics))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @property
    def requires_instructor_selection(self):
        return self.status == ROOT_RESOLUTION_AMBIGUOUS

    def to_dict(self):
        return {
            "schema_version": LATEX_PROJECT_DOMAIN_SCHEMA_VERSION,
            "status": self.status,
            "root_relative_path": self.root_relative_path,
            "candidate_paths": list(self.candidate_paths),
            "resolution_method": self.resolution_method,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        data = _schema_checked(data)
        return cls(
            status=data.get("status"),
            root_relative_path=data.get("root_relative_path"),
            candidate_paths=tuple(data.get("candidate_paths") or ()),
            resolution_method=data.get("resolution_method", ROOT_METHOD_NONE),
            diagnostics=tuple(data.get("diagnostics") or ()),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class LatexProjectImportCandidate:
    """One ZIP candidate mapped into shared assessment/student identity state."""

    candidate_id: str
    assessment_id: str
    archive_filename: str
    archive_size_bytes: int
    student_id: Optional[str] = None
    submission_id: Optional[str] = None
    attempt: Optional[int] = None
    source_artifact_id: Optional[str] = None
    rendered_artifact_id: Optional[str] = None
    archive_sha256: Optional[str] = None
    project_id: Optional[str] = None
    validation_status: str = ARCHIVE_VALIDATION_PENDING
    resolution: LatexProjectResolution = field(
        default_factory=lambda: LatexProjectResolution(
            status=ROOT_RESOLUTION_PENDING
        )
    )
    diagnostics: Tuple[LatexProjectDiagnostic, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id"),
        )
        object.__setattr__(
            self,
            "assessment_id",
            _text(self.assessment_id, "assessment_id"),
        )
        object.__setattr__(
            self,
            "archive_filename",
            _text(self.archive_filename, "archive_filename"),
        )
        object.__setattr__(
            self,
            "archive_size_bytes",
            _int(self.archive_size_bytes, "archive_size_bytes", minimum=0),
        )
        object.__setattr__(self, "student_id", _optional_text(self.student_id))
        object.__setattr__(
            self,
            "submission_id",
            _optional_text(self.submission_id),
        )
        object.__setattr__(
            self,
            "attempt",
            _optional_int(self.attempt, "attempt", minimum=1),
        )
        object.__setattr__(
            self,
            "source_artifact_id",
            _optional_text(self.source_artifact_id),
        )
        object.__setattr__(
            self,
            "rendered_artifact_id",
            _optional_text(self.rendered_artifact_id),
        )
        object.__setattr__(
            self,
            "archive_sha256",
            _sha256(self.archive_sha256, "archive_sha256", required=False),
        )
        object.__setattr__(self, "project_id", _optional_text(self.project_id))
        object.__setattr__(
            self,
            "validation_status",
            _status(
                self.validation_status,
                ARCHIVE_VALIDATION_STATUSES,
                "validation_status",
            ),
        )

        resolution = self.resolution
        if isinstance(resolution, Mapping):
            resolution = LatexProjectResolution.from_dict(resolution)
        if not isinstance(resolution, LatexProjectResolution):
            raise LatexProjectValidationError(
                "resolution must be LatexProjectResolution or a mapping"
            )
        object.__setattr__(self, "resolution", resolution)

        diagnostics = []
        for value in self.diagnostics or ():
            if isinstance(value, LatexProjectDiagnostic):
                diagnostics.append(value)
            elif isinstance(value, Mapping):
                diagnostics.append(LatexProjectDiagnostic.from_dict(value))
            else:
                raise LatexProjectValidationError(
                    "diagnostics must contain LatexProjectDiagnostic objects or mappings"
                )
        object.__setattr__(self, "diagnostics", tuple(diagnostics))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @property
    def mapped(self):
        return self.student_id is not None

    @property
    def committed_identity_available(self):
        return (
            self.submission_id is not None
            and self.attempt is not None
            and self.source_artifact_id is not None
        )

    def to_dict(self):
        return {
            "schema_version": LATEX_PROJECT_DOMAIN_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "assessment_id": self.assessment_id,
            "archive_filename": self.archive_filename,
            "archive_size_bytes": self.archive_size_bytes,
            "student_id": self.student_id,
            "submission_id": self.submission_id,
            "attempt": self.attempt,
            "source_artifact_id": self.source_artifact_id,
            "rendered_artifact_id": self.rendered_artifact_id,
            "archive_sha256": self.archive_sha256,
            "project_id": self.project_id,
            "validation_status": self.validation_status,
            "resolution": self.resolution.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        data = _schema_checked(data)
        return cls(
            candidate_id=data.get("candidate_id"),
            assessment_id=data.get("assessment_id"),
            archive_filename=data.get("archive_filename"),
            archive_size_bytes=data.get("archive_size_bytes"),
            student_id=data.get("student_id"),
            submission_id=data.get("submission_id"),
            attempt=data.get("attempt"),
            source_artifact_id=data.get("source_artifact_id"),
            rendered_artifact_id=data.get("rendered_artifact_id"),
            archive_sha256=data.get("archive_sha256"),
            project_id=data.get("project_id"),
            validation_status=data.get(
                "validation_status",
                ARCHIVE_VALIDATION_PENDING,
            ),
            resolution=data.get(
                "resolution",
                {"status": ROOT_RESOLUTION_PENDING},
            ),
            diagnostics=tuple(data.get("diagnostics") or ()),
            metadata=data.get("metadata", {}),
        )


__all__ = [
    "ARCHIVE_VALIDATION_INVALID",
    "ARCHIVE_VALIDATION_PENDING",
    "ARCHIVE_VALIDATION_REJECTED",
    "ARCHIVE_VALIDATION_STATUSES",
    "ARCHIVE_VALIDATION_VALID",
    "DIAGNOSTIC_BLOCKING",
    "DIAGNOSTIC_INFO",
    "DIAGNOSTIC_SEVERITIES",
    "DIAGNOSTIC_WARNING",
    "FILE_ROLE_BIBLIOGRAPHY",
    "FILE_ROLE_DATA",
    "FILE_ROLE_FIGURE",
    "FILE_ROLE_OTHER",
    "FILE_ROLE_ROOT",
    "FILE_ROLE_STYLE",
    "FILE_ROLE_TEX_SOURCE",
    "FILE_ROLES",
    "LATEX_PROJECT_DOMAIN_SCHEMA_VERSION",
    "LatexProjectArchive",
    "LatexProjectDiagnostic",
    "LatexProjectFile",
    "LatexProjectImportCandidate",
    "LatexProjectManifest",
    "LatexProjectResolution",
    "ROOT_METHOD_INSTRUCTOR_SELECTED",
    "ROOT_METHOD_NONE",
    "ROOT_METHOD_PREFERRED_NAME",
    "ROOT_METHOD_UNIQUE_DOCUMENT",
    "ROOT_RESOLUTION_AMBIGUOUS",
    "ROOT_RESOLUTION_INVALID_PROJECT",
    "ROOT_RESOLUTION_METHODS",
    "ROOT_RESOLUTION_NO_ROOT_FOUND",
    "ROOT_RESOLUTION_PENDING",
    "ROOT_RESOLUTION_RESOLVED",
    "ROOT_RESOLUTION_STATUSES",
    "generate_latex_project_candidate_id",
    "generate_latex_project_id",
    "normalize_project_relative_path",
]
