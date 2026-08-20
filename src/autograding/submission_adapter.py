"""Bridge canonical v2.3.2 Python submissions into autograding planning.

Commit 3 consumes immutable ``Submission`` / ``ArtifactFile`` records and an
``AutogradingConfig``.  It verifies the exact canonical bytes, applies the
assignment's required-file contract, and produces an execution-free selection
snapshot.  Historical attempts may be selected explicitly without mutating the
repository's active-attempt pointer.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from src.submissions.domain import (
    ARTIFACT_TYPE_PYTHON,
    SUBMISSION_STATUS_INVALID,
    SUBMISSION_STATUS_WITHDRAWN,
    ArtifactFile,
    Submission,
)
from src.submissions.repository import SubmissionRepository
from src.submissions.routing import (
    HANDLER_PROGRAMMING,
    ROUTE_PROGRAMMING_PYTHON,
    route_submission,
)

from .config import AutogradingConfig
from .errors import (
    CanonicalSubmissionIntegrityError,
    NoCanonicalSubmissionError,
    ProgrammingSubmissionContractError,
)
from .workspace import (
    PlannedWorkspaceFile,
    WORKSPACE_NAMESPACE_SUBMISSION,
    normalize_workspace_relative_path,
)


PROGRAMMING_PATH_METADATA_KEY = "programming_relative_path"


def _text(value: Any, name: str) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        raise ProgrammingSubmissionContractError("%s must not be empty" % name)
    return value


def _artifact_logical_path(artifact: ArtifactFile) -> str:
    raw = None
    if isinstance(artifact.metadata, Mapping):
        raw = artifact.metadata.get(PROGRAMMING_PATH_METADATA_KEY)
    if raw is None or not str(raw).strip():
        raw = artifact.original_filename
    logical = normalize_workspace_relative_path(raw, "programming artifact path")
    if not logical.casefold().endswith(".py"):
        raise ProgrammingSubmissionContractError(
            "Canonical Python artifact %s does not map to a .py logical path: %s"
            % (artifact.artifact_id, logical)
        )
    return logical


@dataclass(frozen=True)
class ProgrammingSubmissionSelection:
    """Exact canonical Python attempt selected for one future grading run."""

    submission: Submission
    files: Tuple[PlannedWorkspaceFile, ...]
    entrypoint_artifact_id: str
    selected_submission_was_active: bool
    verification_performed: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.submission, Submission):
            raise TypeError("submission must be a Submission")
        files = tuple(self.files or ())
        if not files or any(not isinstance(item, PlannedWorkspaceFile) for item in files):
            raise ProgrammingSubmissionContractError(
                "files must contain at least one PlannedWorkspaceFile"
            )
        if any(item.namespace != WORKSPACE_NAMESPACE_SUBMISSION for item in files):
            raise ProgrammingSubmissionContractError(
                "programming selection files must use submission namespace"
            )
        artifact_ids = [item.source_id for item in files]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ProgrammingSubmissionContractError(
                "programming selection contains duplicate artifact IDs"
            )
        entrypoint_artifact_id = _text(
            self.entrypoint_artifact_id,
            "entrypoint_artifact_id",
        )
        if entrypoint_artifact_id not in artifact_ids:
            raise ProgrammingSubmissionContractError(
                "entrypoint_artifact_id is not present in programming files"
            )
        if not isinstance(self.selected_submission_was_active, bool):
            raise ProgrammingSubmissionContractError(
                "selected_submission_was_active must be boolean"
            )
        if not isinstance(self.verification_performed, bool):
            raise ProgrammingSubmissionContractError(
                "verification_performed must be boolean"
            )
        if not isinstance(self.metadata, Mapping):
            raise ProgrammingSubmissionContractError("metadata must be a mapping")

        object.__setattr__(self, "files", files)
        object.__setattr__(self, "entrypoint_artifact_id", entrypoint_artifact_id)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def entrypoint_file(self) -> PlannedWorkspaceFile:
        for item in self.files:
            if item.source_id == self.entrypoint_artifact_id:
                return item
        raise ProgrammingSubmissionContractError("entrypoint artifact is missing")


def _load_submission(
    repository: SubmissionRepository,
    *,
    assessment_id: str,
    student_id: str,
    submission_id: Optional[str],
) -> Submission:
    if submission_id is None:
        submission = repository.get_active_submission(assessment_id, student_id)
        if submission is None:
            raise NoCanonicalSubmissionError(
                "No active canonical submission exists for assessment %r and student %r"
                % (assessment_id, student_id)
            )
        return submission

    try:
        return repository.get_submission(
            _text(submission_id, "submission_id"),
            assessment_id=assessment_id,
            student_id=student_id,
        )
    except KeyError as exc:
        raise NoCanonicalSubmissionError(
            "Canonical submission %r does not exist for assessment %r and student %r"
            % (submission_id, assessment_id, student_id)
        ) from exc


def _verify_submission_or_raise(
    repository: SubmissionRepository,
    submission: Submission,
) -> None:
    verification = repository.verify_submission(submission)
    if verification.get("ok"):
        return
    failures = []
    for artifact_id, result in verification.get("artifacts", {}).items():
        if not result.get("ok"):
            failures.append(str(artifact_id))
    raise CanonicalSubmissionIntegrityError(
        "Canonical programming submission failed size/SHA-256 verification: %s"
        % (", ".join(failures) if failures else "unknown artifact")
    )


def select_programming_submission(
    repository: SubmissionRepository,
    config: AutogradingConfig,
    *,
    assessment_id: str,
    student_id: str,
    submission_id: Optional[str] = None,
    verify_artifacts: bool = True,
) -> ProgrammingSubmissionSelection:
    """Select and validate one canonical Python attempt without executing it.

    ``submission_id=None`` follows the repository's active-attempt pointer.
    Supplying a submission ID grades that immutable historical attempt exactly
    and does not mutate the active pointer.
    """

    if not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be a SubmissionRepository")
    if not isinstance(config, AutogradingConfig):
        raise TypeError("config must be an AutogradingConfig")
    if not isinstance(verify_artifacts, bool):
        raise TypeError("verify_artifacts must be a bool")

    assessment_id = _text(assessment_id, "assessment_id")
    student_id = _text(student_id, "student_id")
    if config.assessment_id != assessment_id:
        raise ProgrammingSubmissionContractError(
            "Autograder config assessment_id %r does not match requested assessment %r"
            % (config.assessment_id, assessment_id)
        )

    submission = _load_submission(
        repository,
        assessment_id=assessment_id,
        student_id=student_id,
        submission_id=submission_id,
    )
    if submission.assessment_id != assessment_id or submission.student_id != student_id:
        raise ProgrammingSubmissionContractError(
            "Canonical submission identity does not match requested assessment/student"
        )
    if submission.status in {SUBMISSION_STATUS_INVALID, SUBMISSION_STATUS_WITHDRAWN}:
        raise ProgrammingSubmissionContractError(
            "Canonical submission status %r cannot be autograded" % submission.status
        )

    decision = route_submission(submission)
    if (
        decision.route != ROUTE_PROGRAMMING_PYTHON
        or decision.handler != HANDLER_PROGRAMMING
        or not decision.supported
    ):
        raise ProgrammingSubmissionContractError(
            "Canonical submission is not an available Python programming route: "
            "%s (%s)" % (decision.route, decision.reason or "unsupported")
        )

    if verify_artifacts:
        _verify_submission_or_raise(repository, submission)

    python_artifacts = [
        artifact
        for artifact in submission.artifacts
        if artifact.artifact_type == ARTIFACT_TYPE_PYTHON
    ]
    if not python_artifacts:
        raise ProgrammingSubmissionContractError(
            "Programming submission contains no canonical Python artifacts"
        )

    planned_files = []
    logical_to_artifact = {}
    folded_paths = {}
    for artifact in python_artifacts:
        logical_path = _artifact_logical_path(artifact)
        folded = logical_path.casefold()
        if folded in folded_paths:
            raise ProgrammingSubmissionContractError(
                "Programming artifacts have a case-insensitive path collision: %r and %r"
                % (folded_paths[folded], logical_path)
            )
        folded_paths[folded] = logical_path
        canonical_path = repository.artifact_path(submission, artifact)
        planned = PlannedWorkspaceFile(
            namespace=WORKSPACE_NAMESPACE_SUBMISSION,
            logical_path=logical_path,
            source_path=canonical_path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            source_id=artifact.artifact_id,
            read_only=True,
            metadata={
                "artifact_type": artifact.artifact_type,
                "role": artifact.role,
                "original_filename": artifact.original_filename,
            },
        )
        planned_files.append(planned)
        logical_to_artifact[logical_path] = artifact

    missing = [
        path for path in config.required_files if path not in logical_to_artifact
    ]
    if missing:
        raise ProgrammingSubmissionContractError(
            "Programming submission is missing required canonical file(s): %s"
            % ", ".join(missing)
        )

    entrypoint_artifact = logical_to_artifact.get(config.entrypoint)
    if entrypoint_artifact is None:
        # Normally covered by required_files because Commit 1 inserts the
        # entrypoint there, but keeping this explicit protects serialized/legacy
        # configs and gives a sharper diagnostic.
        raise ProgrammingSubmissionContractError(
            "Programming entrypoint %r is not present in canonical artifacts"
            % config.entrypoint
        )

    planned_files.sort(key=lambda item: (item.logical_path.casefold(), item.source_id))
    return ProgrammingSubmissionSelection(
        submission=submission,
        files=tuple(planned_files),
        entrypoint_artifact_id=entrypoint_artifact.artifact_id,
        selected_submission_was_active=bool(submission.is_active_attempt),
        verification_performed=verify_artifacts,
        metadata={
            "route": decision.route,
            "handler": decision.handler,
            "required_files": list(config.required_files),
            "entrypoint": config.entrypoint,
        },
    )


__all__ = [
    "PROGRAMMING_PATH_METADATA_KEY",
    "ProgrammingSubmissionSelection",
    "select_programming_submission",
]
