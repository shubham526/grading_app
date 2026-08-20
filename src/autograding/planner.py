"""Deterministic execution-plan construction for v2.3.3 Commit 3.

An ``ExecutionPlan`` binds one exact canonical student attempt to one exact
immutable instructor test bundle.  It contains all read-only file inputs and
provenance needed by the execution backend introduced in Commit 4/5, but this
module performs no execution and creates no writable run workspace.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional

from src.submissions.repository import SubmissionRepository

from .bundle_store import TestBundleStore
from .bundles import StoredTestBundle
from .config import AutogradingConfig
from .errors import (
    AutogradingBundleSelectionError,
    ExecutionPlanValidationError,
)
from .ids import generate_autograding_run_id
from .models import AutogradingProvenance, ResourceLimits, TestBundleReference
from .submission_adapter import (
    ProgrammingSubmissionSelection,
    select_programming_submission,
)
from .workspace import (
    ExecutionWorkspaceSpec,
    PlannedWorkspaceFile,
    WORKSPACE_NAMESPACE_GRADER,
)


EXECUTION_PLAN_SCHEMA_VERSION = "1.0"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        raise ExecutionPlanValidationError("%s must not be empty" % name)
    return value


@dataclass(frozen=True)
class ExecutionPlan:
    """Execution-free, hash-complete plan for one future autograding run."""

    run_id: str
    created_at: str
    assessment_id: str
    student_id: str
    submission_id: str
    attempt: Optional[int]
    selected_submission_was_active: bool
    bundle_reference: TestBundleReference
    config: AutogradingConfig
    resource_limits: ResourceLimits
    workspace: ExecutionWorkspaceSpec
    provenance: AutogradingProvenance
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        run_id = _text(self.run_id, "run_id")
        created_at = _text(self.created_at, "created_at")
        assessment_id = _text(self.assessment_id, "assessment_id")
        student_id = _text(self.student_id, "student_id")
        submission_id = _text(self.submission_id, "submission_id")
        attempt = self.attempt
        if attempt is not None:
            if isinstance(attempt, bool):
                raise ExecutionPlanValidationError("attempt must be an integer or None")
            try:
                attempt = int(attempt)
            except (TypeError, ValueError):
                raise ExecutionPlanValidationError("attempt must be an integer or None")
            if attempt <= 0:
                raise ExecutionPlanValidationError("attempt must be positive")
        if not isinstance(self.selected_submission_was_active, bool):
            raise ExecutionPlanValidationError(
                "selected_submission_was_active must be boolean"
            )
        if not isinstance(self.bundle_reference, TestBundleReference):
            raise TypeError("bundle_reference must be a TestBundleReference")
        if not isinstance(self.config, AutogradingConfig):
            raise TypeError("config must be an AutogradingConfig")
        if not isinstance(self.resource_limits, ResourceLimits):
            raise TypeError("resource_limits must be ResourceLimits")
        if not isinstance(self.workspace, ExecutionWorkspaceSpec):
            raise TypeError("workspace must be an ExecutionWorkspaceSpec")
        if not isinstance(self.provenance, AutogradingProvenance):
            raise TypeError("provenance must be AutogradingProvenance")
        if not isinstance(self.metadata, Mapping):
            raise ExecutionPlanValidationError("metadata must be a mapping")

        if self.bundle_reference.assessment_id != assessment_id:
            raise ExecutionPlanValidationError(
                "bundle_reference assessment does not match execution plan"
            )
        if self.config.assessment_id != assessment_id:
            raise ExecutionPlanValidationError(
                "autograder config assessment does not match execution plan"
            )
        if self.resource_limits != self.config.resource_limits:
            raise ExecutionPlanValidationError(
                "resource_limits must match the immutable autograder config"
            )
        if self.provenance.submission_id != submission_id:
            raise ExecutionPlanValidationError(
                "provenance submission_id does not match execution plan"
            )
        if self.provenance.bundle_id != self.bundle_reference.bundle_id:
            raise ExecutionPlanValidationError(
                "provenance bundle_id does not match execution plan"
            )
        if self.provenance.bundle_sha256 != self.bundle_reference.bundle_sha256:
            raise ExecutionPlanValidationError(
                "provenance bundle_sha256 does not match bundle reference"
            )
        if self.provenance.config_sha256 != self.bundle_reference.config_sha256:
            raise ExecutionPlanValidationError(
                "provenance config_sha256 does not match bundle reference"
            )
        if self.provenance.attempt != attempt:
            raise ExecutionPlanValidationError(
                "provenance attempt does not match execution plan"
            )
        if self.provenance.runner_type != self.config.runner_type:
            raise ExecutionPlanValidationError(
                "provenance runner_type does not match autograder config"
            )
        if self.workspace.entrypoint != self.config.entrypoint:
            raise ExecutionPlanValidationError(
                "workspace entrypoint does not match autograder config"
            )
        if self.workspace.entrypoint_file.source_id != self.provenance.artifact_id:
            raise ExecutionPlanValidationError(
                "provenance artifact_id must identify the entrypoint artifact"
            )
        if self.workspace.entrypoint_file.sha256 != self.provenance.submission_sha256:
            raise ExecutionPlanValidationError(
                "provenance submission_sha256 must match entrypoint bytes"
            )

        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "assessment_id", assessment_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "submission_id", submission_id)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def language(self) -> str:
        return self.config.language

    @property
    def runner_type(self) -> str:
        return self.config.runner_type

    @property
    def entrypoint_artifact_id(self) -> str:
        return self.provenance.artifact_id

    @property
    def entrypoint_sha256(self) -> str:
        return self.provenance.submission_sha256

    def to_dict(self, *, include_source_paths: bool = True) -> Dict[str, Any]:
        return {
            "schema_version": EXECUTION_PLAN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "assessment_id": self.assessment_id,
            "student_id": self.student_id,
            "submission_id": self.submission_id,
            "attempt": self.attempt,
            "selected_submission_was_active": self.selected_submission_was_active,
            "bundle_reference": self.bundle_reference.to_dict(),
            "config": self.config.to_dict(),
            "resource_limits": self.resource_limits.to_dict(),
            "workspace": self.workspace.to_dict(
                include_source_paths=include_source_paths
            ),
            "provenance": self.provenance.to_dict(),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionPlan":
        if not isinstance(data, Mapping):
            raise ExecutionPlanValidationError("ExecutionPlan data must be a mapping")
        version = data.get("schema_version")
        if version is not None and str(version) != EXECUTION_PLAN_SCHEMA_VERSION:
            raise ExecutionPlanValidationError(
                "Unsupported execution-plan schema %r; expected %r"
                % (version, EXECUTION_PLAN_SCHEMA_VERSION)
            )
        return cls(
            run_id=data.get("run_id"),
            created_at=data.get("created_at"),
            assessment_id=data.get("assessment_id"),
            student_id=data.get("student_id"),
            submission_id=data.get("submission_id"),
            attempt=data.get("attempt"),
            selected_submission_was_active=data.get(
                "selected_submission_was_active",
                False,
            ),
            bundle_reference=TestBundleReference.from_dict(
                data.get("bundle_reference") or {}
            ),
            config=AutogradingConfig.from_dict(data.get("config") or {}),
            resource_limits=ResourceLimits.from_dict(
                data.get("resource_limits") or {}
            ),
            workspace=ExecutionWorkspaceSpec.from_dict(data.get("workspace") or {}),
            provenance=AutogradingProvenance.from_dict(
                data.get("provenance") or {}
            ),
            metadata=data.get("metadata", {}),
        )


def _grader_workspace_files(bundle: StoredTestBundle) -> tuple:
    files = []
    for item in bundle.files:
        files.append(
            PlannedWorkspaceFile(
                namespace=WORKSPACE_NAMESPACE_GRADER,
                logical_path=item.relative_path,
                source_path=bundle.original_path(item.relative_path),
                sha256=item.sha256,
                size_bytes=item.size_bytes,
                source_id=item.relative_path,
                read_only=True,
                metadata={"role": item.role},
            )
        )
    files.sort(key=lambda value: value.logical_path.casefold())
    return tuple(files)


def _provenance_for_selection(
    selection: ProgrammingSubmissionSelection,
    bundle: StoredTestBundle,
) -> AutogradingProvenance:
    entrypoint = selection.entrypoint_file
    all_artifacts = [
        {
            "artifact_id": item.source_id,
            "logical_path": item.logical_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in selection.files
    ]
    return AutogradingProvenance(
        submission_id=selection.submission.submission_id,
        artifact_id=entrypoint.source_id,
        submission_sha256=entrypoint.sha256,
        bundle_id=bundle.reference.bundle_id,
        bundle_sha256=bundle.reference.bundle_sha256,
        config_sha256=bundle.reference.config_sha256,
        runner_type=bundle.config.runner_type,
        attempt=selection.submission.attempt,
        metadata={
            "assessment_id": selection.submission.assessment_id,
            "student_id": selection.submission.student_id,
            "entrypoint": entrypoint.logical_path,
            "submission_artifacts": all_artifacts,
            "selected_submission_was_active": (
                selection.selected_submission_was_active
            ),
        },
    )


def build_execution_plan_from_bundle(
    repository: SubmissionRepository,
    bundle: StoredTestBundle,
    *,
    student_id: str,
    submission_id: Optional[str] = None,
    verify_submission: bool = True,
    run_id: Optional[str] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> ExecutionPlan:
    """Bind one already-verified immutable bundle to one canonical submission."""

    if not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be a SubmissionRepository")
    if not isinstance(bundle, StoredTestBundle):
        raise TypeError("bundle must be a StoredTestBundle")
    if not isinstance(verify_submission, bool):
        raise TypeError("verify_submission must be a bool")

    selection = select_programming_submission(
        repository,
        bundle.config,
        assessment_id=bundle.reference.assessment_id,
        student_id=student_id,
        submission_id=submission_id,
        verify_artifacts=verify_submission,
    )
    grader_files = _grader_workspace_files(bundle)
    workspace = ExecutionWorkspaceSpec(
        submission_files=selection.files,
        grader_files=grader_files,
        entrypoint=bundle.config.entrypoint,
        metadata={
            "bundle_id": bundle.reference.bundle_id,
            "submission_id": selection.submission.submission_id,
        },
    )
    provenance = _provenance_for_selection(selection, bundle)

    if run_id is None:
        run_id = generate_autograding_run_id()
    now = _utc_now_iso() if now_fn is None else _text(now_fn(), "created_at")

    return ExecutionPlan(
        run_id=run_id,
        created_at=now,
        assessment_id=bundle.reference.assessment_id,
        student_id=selection.submission.student_id,
        submission_id=selection.submission.submission_id,
        attempt=selection.submission.attempt,
        selected_submission_was_active=selection.selected_submission_was_active,
        bundle_reference=bundle.reference,
        config=bundle.config,
        resource_limits=bundle.config.resource_limits,
        workspace=workspace,
        provenance=provenance,
        metadata={
            "submission_source_system": selection.submission.source_system,
            "submission_imported_at": selection.submission.imported_at,
            "submission_submitted_at": selection.submission.submitted_at,
            "verification_performed": selection.verification_performed,
        },
    )


def build_execution_plan(
    repository: SubmissionRepository,
    bundle_store: TestBundleStore,
    *,
    assessment_id: str,
    student_id: str,
    bundle_id: str,
    submission_id: Optional[str] = None,
    verify_submission: bool = True,
    verify_bundle: bool = True,
    run_id: Optional[str] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> ExecutionPlan:
    """Load exact immutable inputs and build one execution-free plan."""

    if not isinstance(repository, SubmissionRepository):
        raise TypeError("repository must be a SubmissionRepository")
    if not isinstance(bundle_store, TestBundleStore):
        raise TypeError("bundle_store must be a TestBundleStore")
    if not isinstance(verify_bundle, bool):
        raise TypeError("verify_bundle must be a bool")

    assessment_id = _text(assessment_id, "assessment_id")
    bundle_id = _text(bundle_id, "bundle_id")
    try:
        bundle = bundle_store.load_bundle(
            assessment_id,
            bundle_id,
            verify_hashes=verify_bundle,
        )
    except KeyError as exc:
        raise AutogradingBundleSelectionError(
            "Unknown autograder bundle %r for assessment %r"
            % (bundle_id, assessment_id)
        ) from exc
    except FileNotFoundError as exc:
        raise AutogradingBundleSelectionError(
            "Autograder bundle %r is missing for assessment %r"
            % (bundle_id, assessment_id)
        ) from exc

    if bundle.reference.assessment_id != assessment_id:
        raise AutogradingBundleSelectionError(
            "Loaded autograder bundle belongs to another assessment"
        )
    return build_execution_plan_from_bundle(
        repository,
        bundle,
        student_id=student_id,
        submission_id=submission_id,
        verify_submission=verify_submission,
        run_id=run_id,
        now_fn=now_fn,
    )


__all__ = [
    "EXECUTION_PLAN_SCHEMA_VERSION",
    "ExecutionPlan",
    "build_execution_plan",
    "build_execution_plan_from_bundle",
]
