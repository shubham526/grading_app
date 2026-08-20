"""Immutable autograding-run storage records for v2.3.3 Commit 8.

This module defines the serialized run-history contract.  It does not execute
student code, invoke pytest, or compute scores.  Repository code writes these
records atomically after Commit 6/7 have produced a structured execution result
and deterministic score.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import AutogradingRunIntegrityError, AutogradingRunStorageError
from .models import AutogradingRun
from .scoring import AutogradingScoringResult
from .testing.protocol import PytestRunResult


AUTOGRADING_RUN_STORAGE_SCHEMA_VERSION = "1.0"
AUTOGRADING_RUN_INDEX_SCHEMA_VERSION = "1.0"
AUTOGRADING_RUN_MANIFEST_FILENAME = "run.json"
AUTOGRADING_RUN_PLAN_FILENAME = "plan.json"
AUTOGRADING_RUN_PYTEST_FILENAME = "pytest_results.json"
AUTOGRADING_RUN_SCORING_FILENAME = "scoring.json"
AUTOGRADING_RUN_EVIDENCE_DIRECTORY = "evidence"
AUTOGRADING_RUN_STDOUT_FILENAME = "execution_stdout.txt"
AUTOGRADING_RUN_STDERR_FILENAME = "execution_stderr.txt"

RUN_FILE_ROLE_PLAN = "execution_plan"
RUN_FILE_ROLE_PYTEST = "pytest_results"
RUN_FILE_ROLE_SCORING = "scoring_result"
RUN_FILE_ROLE_STDOUT = "execution_stdout"
RUN_FILE_ROLE_STDERR = "execution_stderr"
RUN_FILE_ROLES = (
    RUN_FILE_ROLE_PLAN,
    RUN_FILE_ROLE_PYTEST,
    RUN_FILE_ROLE_SCORING,
    RUN_FILE_ROLE_STDOUT,
    RUN_FILE_ROLE_STDERR,
)


def _text(value, name):
    value = "" if value is None else str(value).strip()
    if not value:
        raise AutogradingRunStorageError("%s must not be empty" % name)
    return value


def _optional_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _nonnegative_int(value, name):
    if isinstance(value, bool):
        raise AutogradingRunStorageError("%s must be an integer" % name)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AutogradingRunStorageError("%s must be an integer" % name)
    if number < 0:
        raise AutogradingRunStorageError("%s must be non-negative" % name)
    return number


def _optional_float(value, name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise AutogradingRunStorageError("%s must be numeric" % name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AutogradingRunStorageError("%s must be numeric" % name)
    return number


def _sha256(value, name):
    digest = _text(value, name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise AutogradingRunStorageError(
            "%s must be a 64-character hexadecimal SHA-256 digest" % name
        )
    return digest


@dataclass(frozen=True)
class RunFileRecord:
    """One immutable companion file named by a run manifest."""

    relative_path: str
    role: str
    size_bytes: int
    sha256: str

    def __post_init__(self):
        path = _text(self.relative_path, "relative_path").replace("\\", "/")
        if path.startswith("/") or path in (".", "..") or ".." in path.split("/"):
            raise AutogradingRunStorageError("relative_path must remain inside the run directory")
        role = _text(self.role, "role")
        if role not in RUN_FILE_ROLES:
            raise AutogradingRunStorageError(
                "role must be one of: %s" % ", ".join(RUN_FILE_ROLES)
            )
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "size_bytes", _nonnegative_int(self.size_bytes, "size_bytes"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))

    def to_dict(self):
        return {
            "relative_path": self.relative_path,
            "role": self.role,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingRunStorageError("RunFileRecord data must be a mapping")
        return cls(
            relative_path=data.get("relative_path"),
            role=data.get("role"),
            size_bytes=data.get("size_bytes"),
            sha256=data.get("sha256"),
        )


@dataclass(frozen=True)
class AutogradingRunReference:
    """Compact immutable history-index reference for one committed run."""

    run_id: str
    assessment_id: str
    student_id: str
    submission_id: str
    bundle_id: str
    created_at: str
    status: str
    manifest_sha256: str
    manifest_size_bytes: int
    attempt: Optional[int] = None
    finished_at: Optional[str] = None
    final_score: Optional[float] = None
    max_score: Optional[float] = None
    requires_review: bool = False
    review_status: str = "unreviewed"
    environment_id: Optional[str] = None
    container_image_digest: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in (
            "run_id",
            "assessment_id",
            "student_id",
            "submission_id",
            "bundle_id",
            "created_at",
            "status",
            "review_status",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "manifest_sha256", _sha256(self.manifest_sha256, "manifest_sha256"))
        object.__setattr__(
            self,
            "manifest_size_bytes",
            _nonnegative_int(self.manifest_size_bytes, "manifest_size_bytes"),
        )
        if self.attempt is not None:
            attempt = _nonnegative_int(self.attempt, "attempt")
            if attempt < 1:
                raise AutogradingRunStorageError("attempt must be positive")
            object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "finished_at", _optional_text(self.finished_at))
        object.__setattr__(self, "final_score", _optional_float(self.final_score, "final_score"))
        object.__setattr__(self, "max_score", _optional_float(self.max_score, "max_score"))
        if not isinstance(self.requires_review, bool):
            raise AutogradingRunStorageError("requires_review must be boolean")
        object.__setattr__(self, "environment_id", _optional_text(self.environment_id))
        object.__setattr__(
            self,
            "container_image_digest",
            _optional_text(self.container_image_digest),
        )
        if not isinstance(self.metadata, Mapping):
            raise AutogradingRunStorageError("metadata must be a mapping")
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def grading_run_id(self):
        return self.run_id

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "assessment_id": self.assessment_id,
            "student_id": self.student_id,
            "submission_id": self.submission_id,
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "status": self.status,
            "manifest_sha256": self.manifest_sha256,
            "manifest_size_bytes": self.manifest_size_bytes,
            "attempt": self.attempt,
            "finished_at": self.finished_at,
            "final_score": self.final_score,
            "max_score": self.max_score,
            "requires_review": self.requires_review,
            "review_status": self.review_status,
            "environment_id": self.environment_id,
            "container_image_digest": self.container_image_digest,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingRunStorageError("AutogradingRunReference data must be a mapping")
        return cls(
            run_id=data.get("run_id") or data.get("grading_run_id"),
            assessment_id=data.get("assessment_id"),
            student_id=data.get("student_id"),
            submission_id=data.get("submission_id"),
            bundle_id=data.get("bundle_id"),
            created_at=data.get("created_at"),
            status=data.get("status"),
            manifest_sha256=data.get("manifest_sha256"),
            manifest_size_bytes=data.get("manifest_size_bytes", 0),
            attempt=data.get("attempt"),
            finished_at=data.get("finished_at"),
            final_score=data.get("final_score"),
            max_score=data.get("max_score"),
            requires_review=data.get("requires_review", False),
            review_status=data.get("review_status", "unreviewed"),
            environment_id=data.get("environment_id"),
            container_image_digest=data.get("container_image_digest"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class StoredAutogradingRun:
    """Fully reconstructed immutable run plus storage/protocol snapshots."""

    reference: AutogradingRunReference
    run: AutogradingRun
    plan_snapshot: Dict[str, Any]
    pytest_result: PytestRunResult
    scoring_result: AutogradingScoringResult
    files: Tuple[RunFileRecord, ...]
    run_dir: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.reference, AutogradingRunReference):
            raise AutogradingRunIntegrityError("reference must be AutogradingRunReference")
        if not isinstance(self.run, AutogradingRun):
            raise AutogradingRunIntegrityError("run must be AutogradingRun")
        if self.run.run_id != self.reference.run_id:
            raise AutogradingRunIntegrityError("stored run/reference run_id mismatch")
        if not isinstance(self.plan_snapshot, Mapping):
            raise AutogradingRunIntegrityError("plan_snapshot must be a mapping")
        if not isinstance(self.pytest_result, PytestRunResult):
            raise AutogradingRunIntegrityError("pytest_result must be PytestRunResult")
        if not isinstance(self.scoring_result, AutogradingScoringResult):
            raise AutogradingRunIntegrityError("scoring_result must be AutogradingScoringResult")
        files = tuple(self.files or ())
        if any(not isinstance(item, RunFileRecord) for item in files):
            raise AutogradingRunIntegrityError("files must contain RunFileRecord values")
        paths = [item.relative_path.casefold() for item in files]
        if len(paths) != len(set(paths)):
            raise AutogradingRunIntegrityError("run manifest contains duplicate file paths")
        roles = [item.role for item in files]
        if len(roles) != len(set(roles)):
            raise AutogradingRunIntegrityError("run manifest contains duplicate file roles")
        object.__setattr__(self, "plan_snapshot", deepcopy(dict(self.plan_snapshot)))
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "run_dir", _text(self.run_dir, "run_dir"))
        if not isinstance(self.metadata, Mapping):
            raise AutogradingRunIntegrityError("metadata must be a mapping")
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def file_by_role(self, role):
        for item in self.files:
            if item.role == role:
                return item
        return None


__all__ = [
    "AUTOGRADING_RUN_EVIDENCE_DIRECTORY",
    "AUTOGRADING_RUN_INDEX_SCHEMA_VERSION",
    "AUTOGRADING_RUN_MANIFEST_FILENAME",
    "AUTOGRADING_RUN_PLAN_FILENAME",
    "AUTOGRADING_RUN_PYTEST_FILENAME",
    "AUTOGRADING_RUN_SCORING_FILENAME",
    "AUTOGRADING_RUN_STDERR_FILENAME",
    "AUTOGRADING_RUN_STDOUT_FILENAME",
    "AUTOGRADING_RUN_STORAGE_SCHEMA_VERSION",
    "AutogradingRunReference",
    "RunFileRecord",
    "RUN_FILE_ROLE_PLAN",
    "RUN_FILE_ROLE_PYTEST",
    "RUN_FILE_ROLE_SCORING",
    "RUN_FILE_ROLE_STDERR",
    "RUN_FILE_ROLE_STDOUT",
    "RUN_FILE_ROLES",
    "StoredAutogradingRun",
]
