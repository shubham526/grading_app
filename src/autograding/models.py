"""Domain models for v2.3.3 Programming Submission & Autograding.

Commit 1 is deliberately execution-free.  These objects define stable,
JSON-serializable contracts for configuration, planning, execution evidence,
per-test results, scores, provenance, and historical grading runs.  Later
commits may *produce* these records, but they should not need to redesign them.

The module has no PyQt, Docker, pytest, or third-party dependencies and remains
compatible with Python 3.9.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .errors import (
    AutogradingSerializationError,
    AutogradingValidationError,
    UnsupportedAutogradingSchemaError,
)


AUTOGRADING_DOMAIN_SCHEMA_VERSION = "1.0"

# Test visibility.  Hidden is the secure default for instructor-authored tests.
TEST_VISIBILITY_PUBLIC = "public"
TEST_VISIBILITY_HIDDEN = "hidden"
TEST_VISIBILITIES = (
    TEST_VISIBILITY_PUBLIC,
    TEST_VISIBILITY_HIDDEN,
)

# Normalized per-test states.  Keep student failures separate from grader/
# infrastructure failures so later scoring cannot silently convert the latter
# into student zeros.
TEST_STATUS_PENDING = "pending"
TEST_STATUS_PASSED = "passed"
TEST_STATUS_FAILED = "failed"
TEST_STATUS_ERROR = "error"
TEST_STATUS_TIMEOUT = "timeout"
TEST_STATUS_SKIPPED = "skipped"
TEST_STATUS_XFAIL = "xfail"
TEST_STATUS_XPASS = "xpass"
TEST_STATUS_INFRASTRUCTURE_ERROR = "infrastructure_error"
TEST_STATUSES = (
    TEST_STATUS_PENDING,
    TEST_STATUS_PASSED,
    TEST_STATUS_FAILED,
    TEST_STATUS_ERROR,
    TEST_STATUS_TIMEOUT,
    TEST_STATUS_SKIPPED,
    TEST_STATUS_XFAIL,
    TEST_STATUS_XPASS,
    TEST_STATUS_INFRASTRUCTURE_ERROR,
)

# Process/execution states.  The execution backend is introduced later.
EXECUTION_STATUS_PENDING = "pending"
EXECUTION_STATUS_RUNNING = "running"
EXECUTION_STATUS_COMPLETED = "completed"
EXECUTION_STATUS_ERROR = "error"
EXECUTION_STATUS_TIMEOUT = "timeout"
EXECUTION_STATUS_CANCELLED = "cancelled"
EXECUTION_STATUS_INFRASTRUCTURE_ERROR = "infrastructure_error"
EXECUTION_STATUSES = (
    EXECUTION_STATUS_PENDING,
    EXECUTION_STATUS_RUNNING,
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    EXECUTION_STATUS_CANCELLED,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
)

# Detailed top-level grading-run states.  These mirror the design specification
# and intentionally preserve more detail than the future compact UI labels.
RUN_STATUS_QUEUED = "queued"
RUN_STATUS_PREPARING = "preparing"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_COMPLETED_WITH_FAILURES = "completed_with_failures"
RUN_STATUS_VALIDATION_ERROR = "validation_error"
RUN_STATUS_MISSING_FILE = "missing_file"
RUN_STATUS_IMPORT_ERROR = "import_error"
RUN_STATUS_SYNTAX_ERROR = "syntax_error"
RUN_STATUS_TEST_COLLECTION_ERROR = "test_collection_error"
RUN_STATUS_RUNTIME_ERROR = "runtime_error"
RUN_STATUS_TIMEOUT = "timeout"
RUN_STATUS_MEMORY_LIMIT = "memory_limit"
RUN_STATUS_PROCESS_LIMIT = "process_limit"
RUN_STATUS_CONTAINER_ERROR = "container_error"
RUN_STATUS_ENVIRONMENT_ERROR = "environment_error"
RUN_STATUS_GRADER_ERROR = "grader_error"
RUN_STATUS_CANCELLED = "cancelled"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUSES = (
    RUN_STATUS_QUEUED,
    RUN_STATUS_PREPARING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_COMPLETED_WITH_FAILURES,
    RUN_STATUS_VALIDATION_ERROR,
    RUN_STATUS_MISSING_FILE,
    RUN_STATUS_IMPORT_ERROR,
    RUN_STATUS_SYNTAX_ERROR,
    RUN_STATUS_TEST_COLLECTION_ERROR,
    RUN_STATUS_RUNTIME_ERROR,
    RUN_STATUS_TIMEOUT,
    RUN_STATUS_MEMORY_LIMIT,
    RUN_STATUS_PROCESS_LIMIT,
    RUN_STATUS_CONTAINER_ERROR,
    RUN_STATUS_ENVIRONMENT_ERROR,
    RUN_STATUS_GRADER_ERROR,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_INTERRUPTED,
)

REVIEW_STATUS_UNREVIEWED = "unreviewed"
REVIEW_STATUS_FLAGGED = "flagged"
REVIEW_STATUS_REVIEWED = "reviewed"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUSES = (
    REVIEW_STATUS_UNREVIEWED,
    REVIEW_STATUS_FLAGGED,
    REVIEW_STATUS_REVIEWED,
    REVIEW_STATUS_APPROVED,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_DIGEST_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


def _text(value, name):
    value = "" if value is None else str(value).strip()
    if not value:
        raise AutogradingValidationError("%s must not be empty" % name)
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
        raise AutogradingValidationError("%s must be a mapping" % name)
    return deepcopy(dict(value))


def _string_tuple(values, name, allow_empty=True):
    if values is None:
        values = ()
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Sequence):
        raise AutogradingValidationError("%s must be an ordered sequence of strings" % name)
    result = []
    seen = set()
    for raw in values:
        value = _text(raw, name)
        if value in seen:
            raise AutogradingValidationError(
                "%s contains duplicate value %r" % (name, value)
            )
        seen.add(value)
        result.append(value)
    if not allow_empty and not result:
        raise AutogradingValidationError("%s must not be empty" % name)
    return tuple(result)


def _finite_float(value, name, minimum=None, strictly_positive=False):
    if isinstance(value, bool):
        raise AutogradingValidationError("%s must be numeric, not boolean" % name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AutogradingValidationError("%s must be numeric" % name)
    if not math.isfinite(number):
        raise AutogradingValidationError("%s must be finite" % name)
    if strictly_positive and number <= 0:
        raise AutogradingValidationError("%s must be greater than zero" % name)
    if minimum is not None and number < minimum:
        raise AutogradingValidationError(
            "%s must be at least %s" % (name, minimum)
        )
    return number


def _optional_float(value, name, minimum=None, strictly_positive=False):
    if value is None:
        return None
    return _finite_float(
        value,
        name,
        minimum=minimum,
        strictly_positive=strictly_positive,
    )


def _int(value, name, minimum=None):
    if isinstance(value, bool):
        raise AutogradingValidationError("%s must be an integer, not boolean" % name)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AutogradingValidationError("%s must be an integer" % name)
    # Reject 3.2 becoming 3 through int().
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = float(number)
    if numeric_value != float(number):
        raise AutogradingValidationError("%s must be an integer" % name)
    if minimum is not None and number < minimum:
        raise AutogradingValidationError(
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
            raise AutogradingValidationError("%s is required" % name)
        return None
    digest = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise AutogradingValidationError(
            "%s must be a 64-character hexadecimal SHA-256 digest" % name
        )
    return digest


def _sha256_digest(value, name="digest", required=False):
    if value is None or not str(value).strip():
        if required:
            raise AutogradingValidationError("%s is required" % name)
        return None
    raw = str(value).strip().lower()
    match = _SHA256_DIGEST_RE.fullmatch(raw)
    if not match:
        raise AutogradingValidationError(
            "%s must be a SHA-256 digest (64 hex characters, optionally prefixed by sha256:)"
            % name
        )
    return "sha256:%s" % match.group(1)


def _choice(value, name, allowed):
    value = _text(value, name).lower()
    if value not in allowed:
        raise AutogradingValidationError(
            "%s must be one of: %s" % (name, ", ".join(allowed))
        )
    return value


def _validate_schema(data):
    if not isinstance(data, Mapping):
        raise AutogradingSerializationError(
            "serialized autograding data must be a mapping"
        )
    version = data.get("schema_version")
    if version is not None and str(version) != AUTOGRADING_DOMAIN_SCHEMA_VERSION:
        raise UnsupportedAutogradingSchemaError(
            "Unsupported autograding-domain schema %r; expected %r"
            % (version, AUTOGRADING_DOMAIN_SCHEMA_VERSION)
        )
    return data


@dataclass(frozen=True)
class ResourceLimits:
    """Resource/output limits requested for one isolated grading run."""

    wall_timeout_seconds: float = 15.0
    memory_mb: Optional[int] = 512
    cpu_count: Optional[float] = 1.0
    pids_limit: Optional[int] = 128
    stdout_max_bytes: int = 1024 * 1024
    stderr_max_bytes: int = 1024 * 1024
    network_enabled: bool = False

    def __post_init__(self):
        object.__setattr__(
            self,
            "wall_timeout_seconds",
            _finite_float(
                self.wall_timeout_seconds,
                "wall_timeout_seconds",
                strictly_positive=True,
            ),
        )
        object.__setattr__(
            self,
            "memory_mb",
            _optional_int(self.memory_mb, "memory_mb", minimum=1),
        )
        object.__setattr__(
            self,
            "cpu_count",
            _optional_float(
                self.cpu_count,
                "cpu_count",
                strictly_positive=True,
            ),
        )
        object.__setattr__(
            self,
            "pids_limit",
            _optional_int(self.pids_limit, "pids_limit", minimum=1),
        )
        object.__setattr__(
            self,
            "stdout_max_bytes",
            _int(self.stdout_max_bytes, "stdout_max_bytes", minimum=1),
        )
        object.__setattr__(
            self,
            "stderr_max_bytes",
            _int(self.stderr_max_bytes, "stderr_max_bytes", minimum=1),
        )
        if not isinstance(self.network_enabled, bool):
            raise AutogradingValidationError("network_enabled must be boolean")

    def to_dict(self):
        return {
            "wall_timeout_seconds": self.wall_timeout_seconds,
            "memory_mb": self.memory_mb,
            "cpu_count": self.cpu_count,
            "pids_limit": self.pids_limit,
            "stdout_max_bytes": self.stdout_max_bytes,
            "stderr_max_bytes": self.stderr_max_bytes,
            "network_enabled": self.network_enabled,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("ResourceLimits data must be a mapping")
        return cls(
            wall_timeout_seconds=data.get("wall_timeout_seconds", 15.0),
            memory_mb=data.get("memory_mb", 512),
            cpu_count=data.get("cpu_count", 1.0),
            pids_limit=data.get("pids_limit", 128),
            stdout_max_bytes=data.get("stdout_max_bytes", 1024 * 1024),
            stderr_max_bytes=data.get("stderr_max_bytes", 1024 * 1024),
            network_enabled=data.get("network_enabled", False),
        )


@dataclass(frozen=True)
class TestDefinition:
    """Stable instructor-declared identity and scoring metadata for one test."""

    test_id: str
    name: str
    group_id: Optional[str] = None
    visibility: str = TEST_VISIBILITY_HIDDEN
    points: Optional[float] = None
    timeout_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "test_id", _text(self.test_id, "test_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "group_id", _optional_text(self.group_id))
        object.__setattr__(
            self,
            "visibility",
            _choice(self.visibility, "visibility", TEST_VISIBILITIES),
        )
        object.__setattr__(
            self,
            "points",
            _optional_float(self.points, "points", minimum=0.0),
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            _optional_float(
                self.timeout_seconds,
                "timeout_seconds",
                strictly_positive=True,
            ),
        )
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "test_id": self.test_id,
            "name": self.name,
            "group_id": self.group_id,
            "visibility": self.visibility,
            "points": self.points,
            "timeout_seconds": self.timeout_seconds,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("TestDefinition data must be a mapping")
        return cls(
            test_id=data.get("test_id"),
            name=data.get("name") or data.get("test_id"),
            group_id=data.get("group_id"),
            visibility=data.get("visibility", TEST_VISIBILITY_HIDDEN),
            points=data.get("points"),
            timeout_seconds=data.get("timeout_seconds"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class TestGroup:
    """One stable scoring/reporting group in a programming assessment."""

    group_id: str
    name: str
    points: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "group_id", _text(self.group_id, "group_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self,
            "points",
            _finite_float(self.points, "points", minimum=0.0),
        )
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "group_id": self.group_id,
            "name": self.name,
            "points": self.points,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("TestGroup data must be a mapping")
        return cls(
            group_id=data.get("group_id"),
            name=data.get("name") or data.get("group_id"),
            points=data.get("points", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class TestBundleReference:
    """Immutable provenance reference to a committed instructor test bundle."""

    bundle_id: str
    assessment_id: str
    bundle_sha256: str
    config_sha256: str
    imported_at: str
    display_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "bundle_id", _text(self.bundle_id, "bundle_id"))
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        object.__setattr__(
            self,
            "bundle_sha256",
            _sha256(self.bundle_sha256, "bundle_sha256"),
        )
        object.__setattr__(
            self,
            "config_sha256",
            _sha256(self.config_sha256, "config_sha256"),
        )
        object.__setattr__(self, "imported_at", _text(self.imported_at, "imported_at"))
        object.__setattr__(self, "display_version", _optional_text(self.display_version))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "bundle_id": self.bundle_id,
            "assessment_id": self.assessment_id,
            "bundle_sha256": self.bundle_sha256,
            "config_sha256": self.config_sha256,
            "imported_at": self.imported_at,
            "display_version": self.display_version,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("TestBundleReference data must be a mapping")
        return cls(
            bundle_id=data.get("bundle_id"),
            assessment_id=data.get("assessment_id"),
            bundle_sha256=data.get("bundle_sha256"),
            config_sha256=data.get("config_sha256"),
            imported_at=data.get("imported_at"),
            display_version=data.get("display_version"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ExecutionEnvironment:
    """Reproducibility identity for the runtime that executed a grading run."""

    environment_id: str
    backend: str
    language: str
    interpreter_version: Optional[str] = None
    container_image: Optional[str] = None
    container_image_digest: Optional[str] = None
    dependency_lock_sha256: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "environment_id", _text(self.environment_id, "environment_id"))
        object.__setattr__(self, "backend", _text(self.backend, "backend"))
        object.__setattr__(self, "language", _text(self.language, "language").lower())
        object.__setattr__(self, "interpreter_version", _optional_text(self.interpreter_version))
        object.__setattr__(self, "container_image", _optional_text(self.container_image))
        object.__setattr__(
            self,
            "container_image_digest",
            _sha256_digest(
                self.container_image_digest,
                "container_image_digest",
                required=False,
            ),
        )
        object.__setattr__(
            self,
            "dependency_lock_sha256",
            _sha256(
                self.dependency_lock_sha256,
                "dependency_lock_sha256",
                required=False,
            ),
        )
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "environment_id": self.environment_id,
            "backend": self.backend,
            "language": self.language,
            "interpreter_version": self.interpreter_version,
            "container_image": self.container_image,
            "container_image_digest": self.container_image_digest,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("ExecutionEnvironment data must be a mapping")
        return cls(
            environment_id=data.get("environment_id"),
            backend=data.get("backend"),
            language=data.get("language"),
            interpreter_version=data.get("interpreter_version"),
            container_image=data.get("container_image"),
            container_image_digest=data.get("container_image_digest"),
            dependency_lock_sha256=data.get("dependency_lock_sha256"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Normalized process-level result independent of any concrete backend."""

    status: str
    exit_code: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "status", _choice(self.status, "status", EXECUTION_STATUSES))
        object.__setattr__(self, "exit_code", _optional_int(self.exit_code, "exit_code"))
        object.__setattr__(self, "started_at", _optional_text(self.started_at))
        object.__setattr__(self, "finished_at", _optional_text(self.finished_at))
        object.__setattr__(self, "duration_ms", _optional_int(self.duration_ms, "duration_ms", minimum=0))
        object.__setattr__(self, "stdout", "" if self.stdout is None else str(self.stdout))
        object.__setattr__(self, "stderr", "" if self.stderr is None else str(self.stderr))
        if not isinstance(self.stdout_truncated, bool):
            raise AutogradingValidationError("stdout_truncated must be boolean")
        if not isinstance(self.stderr_truncated, bool):
            raise AutogradingValidationError("stderr_truncated must be boolean")
        object.__setattr__(self, "error_message", _optional_text(self.error_message))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "error_message": self.error_message,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("ExecutionResult data must be a mapping")
        return cls(
            status=data.get("status"),
            exit_code=data.get("exit_code"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_ms=data.get("duration_ms"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            stdout_truncated=data.get("stdout_truncated", False),
            stderr_truncated=data.get("stderr_truncated", False),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class TestResult:
    """Normalized result for one stable test identity."""

    test_id: str
    status: str
    visibility: str = TEST_VISIBILITY_HIDDEN
    group_id: Optional[str] = None
    display_name: Optional[str] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None
    traceback: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    points_possible: Optional[float] = None
    points_awarded: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "test_id", _text(self.test_id, "test_id"))
        object.__setattr__(self, "status", _choice(self.status, "status", TEST_STATUSES))
        object.__setattr__(
            self,
            "visibility",
            _choice(self.visibility, "visibility", TEST_VISIBILITIES),
        )
        object.__setattr__(self, "group_id", _optional_text(self.group_id))
        object.__setattr__(self, "display_name", _optional_text(self.display_name))
        object.__setattr__(self, "duration_ms", _optional_int(self.duration_ms, "duration_ms", minimum=0))
        object.__setattr__(self, "message", _optional_text(self.message))
        object.__setattr__(self, "traceback", _optional_text(self.traceback))
        object.__setattr__(self, "stdout", "" if self.stdout is None else str(self.stdout))
        object.__setattr__(self, "stderr", "" if self.stderr is None else str(self.stderr))
        possible = _optional_float(self.points_possible, "points_possible", minimum=0.0)
        awarded = _optional_float(self.points_awarded, "points_awarded", minimum=0.0)
        if awarded is not None and possible is None:
            raise AutogradingValidationError(
                "points_awarded requires points_possible"
            )
        if awarded is not None and possible is not None and awarded > possible + 1e-9:
            raise AutogradingValidationError(
                "points_awarded must not exceed points_possible"
            )
        object.__setattr__(self, "points_possible", possible)
        object.__setattr__(self, "points_awarded", awarded)
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "test_id": self.test_id,
            "status": self.status,
            "visibility": self.visibility,
            "group_id": self.group_id,
            "display_name": self.display_name,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "traceback": self.traceback,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "points_possible": self.points_possible,
            "points_awarded": self.points_awarded,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("TestResult data must be a mapping")
        return cls(
            test_id=data.get("test_id"),
            status=data.get("status"),
            visibility=data.get("visibility", TEST_VISIBILITY_HIDDEN),
            group_id=data.get("group_id"),
            display_name=data.get("display_name"),
            duration_ms=data.get("duration_ms"),
            message=data.get("message"),
            traceback=data.get("traceback"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            points_possible=data.get("points_possible"),
            points_awarded=data.get("points_awarded"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class TestGroupResult:
    """Score/result summary for one configured test group."""

    group_id: str
    name: str
    points_possible: float
    points_awarded: Optional[float] = None
    test_ids: Tuple[str, ...] = field(default_factory=tuple)
    requires_review: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "group_id", _text(self.group_id, "group_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        possible = _finite_float(self.points_possible, "points_possible", minimum=0.0)
        awarded = _optional_float(self.points_awarded, "points_awarded", minimum=0.0)
        if awarded is not None and awarded > possible + 1e-9:
            raise AutogradingValidationError(
                "points_awarded must not exceed points_possible"
            )
        object.__setattr__(self, "points_possible", possible)
        object.__setattr__(self, "points_awarded", awarded)
        object.__setattr__(self, "test_ids", _string_tuple(self.test_ids, "test_ids"))
        if not isinstance(self.requires_review, bool):
            raise AutogradingValidationError("requires_review must be boolean")
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "group_id": self.group_id,
            "name": self.name,
            "points_possible": self.points_possible,
            "points_awarded": self.points_awarded,
            "test_ids": list(self.test_ids),
            "requires_review": self.requires_review,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("TestGroupResult data must be a mapping")
        return cls(
            group_id=data.get("group_id"),
            name=data.get("name") or data.get("group_id"),
            points_possible=data.get("points_possible", 0.0),
            points_awarded=data.get("points_awarded"),
            test_ids=tuple(data.get("test_ids") or ()),
            requires_review=data.get("requires_review", False),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ScoreSummary:
    """Assessment-level deterministic score plus explicit review state."""

    max_score: float
    raw_score: Optional[float] = None
    final_score: Optional[float] = None
    requires_review: bool = False
    review_reason: Optional[str] = None
    group_results: Tuple[TestGroupResult, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        maximum = _finite_float(self.max_score, "max_score", strictly_positive=True)
        raw = _optional_float(self.raw_score, "raw_score", minimum=0.0)
        final = _optional_float(self.final_score, "final_score", minimum=0.0)
        if raw is not None and raw > maximum + 1e-9:
            raise AutogradingValidationError("raw_score must not exceed max_score")
        if final is not None and final > maximum + 1e-9:
            raise AutogradingValidationError("final_score must not exceed max_score")
        if not isinstance(self.requires_review, bool):
            raise AutogradingValidationError("requires_review must be boolean")
        groups = tuple(self.group_results or ())
        if any(not isinstance(item, TestGroupResult) for item in groups):
            raise AutogradingValidationError(
                "group_results must contain TestGroupResult objects"
            )
        ids = [item.group_id for item in groups]
        if len(ids) != len(set(ids)):
            raise AutogradingValidationError("group_results contains duplicate group_id values")
        object.__setattr__(self, "max_score", maximum)
        object.__setattr__(self, "raw_score", raw)
        object.__setattr__(self, "final_score", final)
        object.__setattr__(self, "review_reason", _optional_text(self.review_reason))
        object.__setattr__(self, "group_results", groups)
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "max_score": self.max_score,
            "raw_score": self.raw_score,
            "final_score": self.final_score,
            "requires_review": self.requires_review,
            "review_reason": self.review_reason,
            "group_results": [item.to_dict() for item in self.group_results],
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("ScoreSummary data must be a mapping")
        return cls(
            max_score=data.get("max_score"),
            raw_score=data.get("raw_score"),
            final_score=data.get("final_score"),
            requires_review=data.get("requires_review", False),
            review_reason=data.get("review_reason"),
            group_results=tuple(
                TestGroupResult.from_dict(item)
                for item in (data.get("group_results") or ())
            ),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class AutogradingProvenance:
    """Immutable lineage tying a grading run to exact submission/test bytes."""

    submission_id: str
    artifact_id: str
    submission_sha256: str
    bundle_id: str
    bundle_sha256: str
    config_sha256: str
    runner_type: str
    attempt: Optional[int] = None
    environment_id: Optional[str] = None
    runner_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "submission_id", _text(self.submission_id, "submission_id"))
        object.__setattr__(self, "artifact_id", _text(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self,
            "submission_sha256",
            _sha256(self.submission_sha256, "submission_sha256"),
        )
        object.__setattr__(self, "bundle_id", _text(self.bundle_id, "bundle_id"))
        object.__setattr__(
            self,
            "bundle_sha256",
            _sha256(self.bundle_sha256, "bundle_sha256"),
        )
        object.__setattr__(
            self,
            "config_sha256",
            _sha256(self.config_sha256, "config_sha256"),
        )
        object.__setattr__(self, "runner_type", _text(self.runner_type, "runner_type").lower())
        attempt = _optional_int(self.attempt, "attempt", minimum=1)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "environment_id", _optional_text(self.environment_id))
        object.__setattr__(self, "runner_version", _optional_text(self.runner_version))
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "submission_id": self.submission_id,
            "artifact_id": self.artifact_id,
            "submission_sha256": self.submission_sha256,
            "bundle_id": self.bundle_id,
            "bundle_sha256": self.bundle_sha256,
            "config_sha256": self.config_sha256,
            "runner_type": self.runner_type,
            "attempt": self.attempt,
            "environment_id": self.environment_id,
            "runner_version": self.runner_version,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError("AutogradingProvenance data must be a mapping")
        return cls(
            submission_id=data.get("submission_id"),
            artifact_id=data.get("artifact_id"),
            submission_sha256=data.get("submission_sha256"),
            bundle_id=data.get("bundle_id"),
            bundle_sha256=data.get("bundle_sha256"),
            config_sha256=data.get("config_sha256"),
            runner_type=data.get("runner_type"),
            attempt=data.get("attempt"),
            environment_id=data.get("environment_id"),
            runner_version=data.get("runner_version"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AutogradingRun:
    """Historical grading-run record.

    The top-level object is mutable because later service/repository commits will
    transition a run through queued/running/completed states.  Its nested
    provenance/result value objects are immutable snapshots.
    """

    grading_run_id: str
    assessment_id: str
    student_id: str
    submission_id: str
    created_at: str
    provenance: AutogradingProvenance
    status: str = RUN_STATUS_QUEUED
    attempt: Optional[int] = None
    review_status: str = REVIEW_STATUS_UNREVIEWED
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    execution_result: Optional[ExecutionResult] = None
    test_results: Tuple[TestResult, ...] = field(default_factory=tuple)
    score_summary: Optional[ScoreSummary] = None
    requires_review: bool = False
    review_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.grading_run_id = _text(self.grading_run_id, "grading_run_id")
        self.assessment_id = _text(self.assessment_id, "assessment_id")
        self.student_id = _text(self.student_id, "student_id")
        self.submission_id = _text(self.submission_id, "submission_id")
        self.created_at = _text(self.created_at, "created_at")
        if not isinstance(self.provenance, AutogradingProvenance):
            raise AutogradingValidationError(
                "provenance must be an AutogradingProvenance"
            )
        if self.provenance.submission_id != self.submission_id:
            raise AutogradingValidationError(
                "provenance submission_id does not match run submission_id"
            )
        self.status = _choice(self.status, "status", RUN_STATUSES)
        self.attempt = _optional_int(self.attempt, "attempt", minimum=1)
        if (
            self.attempt is not None
            and self.provenance.attempt is not None
            and self.attempt != self.provenance.attempt
        ):
            raise AutogradingValidationError(
                "run attempt does not match provenance attempt"
            )
        self.review_status = _choice(
            self.review_status,
            "review_status",
            REVIEW_STATUSES,
        )
        self.started_at = _optional_text(self.started_at)
        self.finished_at = _optional_text(self.finished_at)
        self.duration_ms = _optional_int(self.duration_ms, "duration_ms", minimum=0)
        if self.execution_result is not None and not isinstance(
            self.execution_result, ExecutionResult
        ):
            raise AutogradingValidationError(
                "execution_result must be an ExecutionResult or None"
            )
        self.test_results = tuple(self.test_results or ())
        if any(not isinstance(item, TestResult) for item in self.test_results):
            raise AutogradingValidationError(
                "test_results must contain TestResult objects"
            )
        test_ids = [item.test_id for item in self.test_results]
        if len(test_ids) != len(set(test_ids)):
            raise AutogradingValidationError(
                "test_results contains duplicate test_id values"
            )
        if self.score_summary is not None and not isinstance(
            self.score_summary, ScoreSummary
        ):
            raise AutogradingValidationError(
                "score_summary must be a ScoreSummary or None"
            )
        if not isinstance(self.requires_review, bool):
            raise AutogradingValidationError("requires_review must be boolean")
        self.review_reason = _optional_text(self.review_reason)
        self.metadata = _metadata(self.metadata)

    @property
    def run_id(self):
        """Compatibility/readability alias for ``grading_run_id``."""

        return self.grading_run_id

    def to_dict(self):
        return {
            "schema_version": AUTOGRADING_DOMAIN_SCHEMA_VERSION,
            "grading_run_id": self.grading_run_id,
            "assessment_id": self.assessment_id,
            "student_id": self.student_id,
            "submission_id": self.submission_id,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
            "status": self.status,
            "attempt": self.attempt,
            "review_status": self.review_status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "execution_result": (
                self.execution_result.to_dict()
                if self.execution_result is not None
                else None
            ),
            "test_results": [item.to_dict() for item in self.test_results],
            "score_summary": (
                self.score_summary.to_dict()
                if self.score_summary is not None
                else None
            ),
            "requires_review": self.requires_review,
            "review_reason": self.review_reason,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        data = _validate_schema(data)
        provenance_data = data.get("provenance")
        if not isinstance(provenance_data, Mapping):
            raise AutogradingSerializationError(
                "AutogradingRun provenance must be a mapping"
            )
        execution_data = data.get("execution_result")
        score_data = data.get("score_summary")
        return cls(
            grading_run_id=data.get("grading_run_id") or data.get("run_id"),
            assessment_id=data.get("assessment_id"),
            student_id=data.get("student_id"),
            submission_id=data.get("submission_id"),
            created_at=data.get("created_at"),
            provenance=AutogradingProvenance.from_dict(provenance_data),
            status=data.get("status", RUN_STATUS_QUEUED),
            attempt=data.get("attempt"),
            review_status=data.get("review_status", REVIEW_STATUS_UNREVIEWED),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_ms=data.get("duration_ms"),
            execution_result=(
                ExecutionResult.from_dict(execution_data)
                if isinstance(execution_data, Mapping)
                else None
            ),
            test_results=tuple(
                TestResult.from_dict(item)
                for item in (data.get("test_results") or ())
            ),
            score_summary=(
                ScoreSummary.from_dict(score_data)
                if isinstance(score_data, Mapping)
                else None
            ),
            requires_review=data.get("requires_review", False),
            review_reason=data.get("review_reason"),
            metadata=data.get("metadata", {}),
        )


__all__ = [name for name in globals() if name.startswith(("AUTOGRADING_", "EXECUTION_", "REVIEW_", "RUN_", "TEST_"))] + [
    "AutogradingProvenance",
    "AutogradingRun",
    "ExecutionEnvironment",
    "ExecutionResult",
    "ResourceLimits",
    "ScoreSummary",
    "TestBundleReference",
    "TestDefinition",
    "TestGroup",
    "TestGroupResult",
    "TestResult",
]
