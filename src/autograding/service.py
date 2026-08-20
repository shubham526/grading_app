"""Instructor-facing autograding orchestration for v2.3.3 Commit 9.

This module is intentionally Qt-free.  It composes the backend layers introduced
in Commits 1-8 into one application service suitable for the desktop UI and
background workers:

    canonical submission -> execution plan -> Docker pytest -> scoring ->
    immutable run persistence

The service never mutates the app's manual rubric/criterion scores.  Programming
autograding results remain separate immutable evidence until a future explicit
merge/publish workflow chooses to use them.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.submissions.repository import SubmissionRepository

from .bundle_store import TestBundleStore
from .errors import AutogradingError
from .execution.docker_pytest_backend import (
    DEFAULT_DOCKER_PYTEST_IMAGE,
    DEFAULT_EXPECTED_PYTEST_VERSION,
    DockerPytestExecutionBackend,
)
from .planner import ExecutionPlan, build_execution_plan
from .repository import AutogradingRunRepository
from .scoring import AutogradingScoringResult, score_pytest_run
from .storage import AutogradingRunReference, StoredAutogradingRun
from .testing.protocol import PytestRunResult
from .testing.pytest_adapter import execute_pytest_plan


AUTOGRADING_SERVICE_SCHEMA_VERSION = "1.0"

GRADE_STATUS_PENDING = "pending"
GRADE_STATUS_RUNNING = "running"
GRADE_STATUS_COMPLETED = "completed"
GRADE_STATUS_REVIEW = "review"
GRADE_STATUS_ERROR = "error"
GRADE_STATUS_CANCELLED = "cancelled"
GRADE_STATUSES = {
    GRADE_STATUS_PENDING,
    GRADE_STATUS_RUNNING,
    GRADE_STATUS_COMPLETED,
    GRADE_STATUS_REVIEW,
    GRADE_STATUS_ERROR,
    GRADE_STATUS_CANCELLED,
}


def _text(value: Any, name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError("%s is required" % name)
    return text


@dataclass(frozen=True)
class AutogradingGradeResult:
    """Complete result of one persisted programming-autograding operation."""

    plan: ExecutionPlan
    pytest_result: PytestRunResult
    scoring_result: AutogradingScoringResult
    stored_run: StoredAutogradingRun

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ExecutionPlan):
            raise TypeError("plan must be an ExecutionPlan")
        if not isinstance(self.pytest_result, PytestRunResult):
            raise TypeError("pytest_result must be a PytestRunResult")
        if not isinstance(self.scoring_result, AutogradingScoringResult):
            raise TypeError("scoring_result must be an AutogradingScoringResult")
        if not isinstance(self.stored_run, StoredAutogradingRun):
            raise TypeError("stored_run must be a StoredAutogradingRun")
        run_id = self.plan.run_id
        if self.pytest_result.backend_record.run_id != run_id:
            raise ValueError("pytest result run_id does not match plan")
        if self.scoring_result.source_run_id != run_id:
            raise ValueError("scoring result run_id does not match plan")
        if self.stored_run.run.run_id != run_id:
            raise ValueError("stored run_id does not match plan")

    @property
    def reference(self) -> AutogradingRunReference:
        return self.stored_run.reference

    @property
    def final_score(self) -> Optional[float]:
        return self.scoring_result.score_summary.final_score

    @property
    def max_score(self) -> float:
        return self.scoring_result.score_summary.max_score

    @property
    def requires_review(self) -> bool:
        return self.scoring_result.score_summary.requires_review


@dataclass(frozen=True)
class BatchStudentResult:
    """One student's outcome within a batch request."""

    student_id: str
    status: str
    grade_result: Optional[AutogradingGradeResult] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        student_id = _text(self.student_id, "student_id")
        status = _text(self.status, "status")
        if status not in GRADE_STATUSES:
            raise ValueError("Unknown batch student status %r" % status)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "status", status)
        if self.grade_result is not None and not isinstance(
            self.grade_result, AutogradingGradeResult
        ):
            raise TypeError("grade_result must be AutogradingGradeResult or None")
        object.__setattr__(
            self,
            "error_type",
            None if self.error_type is None else str(self.error_type).strip() or None,
        )
        object.__setattr__(
            self,
            "error_message",
            None if self.error_message is None else str(self.error_message).strip() or None,
        )


@dataclass(frozen=True)
class AutogradingBatchResult:
    assessment_id: str
    bundle_id: str
    results: Tuple[BatchStudentResult, ...]
    cancelled: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "bundle_id", _text(self.bundle_id, "bundle_id"))
        results = tuple(self.results or ())
        if any(not isinstance(item, BatchStudentResult) for item in results):
            raise TypeError("results must contain BatchStudentResult objects")
        object.__setattr__(self, "results", results)
        if not isinstance(self.cancelled, bool):
            raise TypeError("cancelled must be boolean")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def completed_count(self) -> int:
        return sum(
            1
            for item in self.results
            if item.status in (GRADE_STATUS_COMPLETED, GRADE_STATUS_REVIEW)
        )

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.results if item.status == GRADE_STATUS_ERROR)


class AutogradingService:
    """Compose planning, execution, scoring, and persistence for one workspace."""

    def __init__(
        self,
        workspace_root: str,
        *,
        evidence_root: Optional[str] = None,
        submission_repository: Optional[SubmissionRepository] = None,
        bundle_store: Optional[TestBundleStore] = None,
        run_repository: Optional[AutogradingRunRepository] = None,
        backend_factory: Callable[..., Any] = DockerPytestExecutionBackend,
        pytest_executor: Callable[[ExecutionPlan, Any], PytestRunResult] = execute_pytest_plan,
        scoring_fn: Callable[[Any, PytestRunResult], AutogradingScoringResult] = score_pytest_run,
        default_image: str = DEFAULT_DOCKER_PYTEST_IMAGE,
        expected_pytest_version: Optional[str] = DEFAULT_EXPECTED_PYTEST_VERSION,
    ) -> None:
        workspace = Path(_text(workspace_root, "workspace_root")).expanduser().resolve()
        self.workspace_root = str(workspace)
        self.evidence_root = str(
            Path(evidence_root).expanduser().resolve()
            if evidence_root
            else (workspace / "submission_evidence")
        )
        self.submission_repository = submission_repository or SubmissionRepository(
            self.evidence_root, create=True
        )
        self.bundle_store = bundle_store or TestBundleStore(self.workspace_root, create=True)
        self.run_repository = run_repository or AutogradingRunRepository(
            self.workspace_root, create=True
        )
        self.backend_factory = backend_factory
        self.pytest_executor = pytest_executor
        self.scoring_fn = scoring_fn
        self.default_image = _text(default_image, "default_image")
        self.expected_pytest_version = (
            None
            if expected_pytest_version is None
            else str(expected_pytest_version).strip() or None
        )

    # ------------------------------------------------------------------
    # Bundle/runtime configuration
    # ------------------------------------------------------------------

    def list_bundles(self, assessment_id: str):
        return self.bundle_store.list_bundle_references(_text(assessment_id, "assessment_id"))

    def import_bundle(
        self,
        assessment_id: str,
        source_dir: str,
        *,
        display_version: Optional[str] = None,
    ):
        assessment_id = _text(assessment_id, "assessment_id")
        return self.bundle_store.import_bundle(
            source_dir,
            expected_assessment_id=assessment_id,
            display_version=display_version,
        )

    def load_bundle(self, assessment_id: str, bundle_id: str):
        return self.bundle_store.load_bundle(
            _text(assessment_id, "assessment_id"),
            _text(bundle_id, "bundle_id"),
            verify_hashes=True,
        )

    def create_backend(self, image: Optional[str] = None):
        runtime_image = str(image or self.default_image).strip()
        kwargs = {"image": runtime_image}
        if self.expected_pytest_version is not None:
            kwargs["expected_pytest_version"] = self.expected_pytest_version
        return self.backend_factory(**kwargs)

    def runtime_availability(self, image: Optional[str] = None):
        backend = self.create_backend(image=image)
        return backend.availability()

    # ------------------------------------------------------------------
    # Planning / eligibility
    # ------------------------------------------------------------------

    def build_plan(
        self,
        assessment_id: str,
        student_id: str,
        bundle_id: str,
        *,
        submission_id: Optional[str] = None,
    ) -> ExecutionPlan:
        return build_execution_plan(
            self.submission_repository,
            self.bundle_store,
            assessment_id=_text(assessment_id, "assessment_id"),
            student_id=_text(student_id, "student_id"),
            bundle_id=_text(bundle_id, "bundle_id"),
            submission_id=submission_id,
        )

    def eligible_active_students(
        self,
        assessment_id: str,
        student_ids: Sequence[str],
        bundle_id: str,
    ) -> Tuple[Tuple[str, ...], Dict[str, str]]:
        """Return students whose active canonical attempt can build a plan.

        This is an execution-free preflight used by the batch dialog.  The plan
        objects themselves are discarded; real grading builds fresh run IDs.
        """

        eligible: List[str] = []
        rejected: Dict[str, str] = {}
        seen = set()
        for raw in tuple(student_ids or ()):
            student_id = str(raw or "").strip()
            if not student_id or student_id in seen:
                continue
            seen.add(student_id)
            try:
                self.build_plan(assessment_id, student_id, bundle_id)
            except Exception as exc:
                rejected[student_id] = str(exc) or type(exc).__name__
            else:
                eligible.append(student_id)
        return tuple(eligible), rejected

    # ------------------------------------------------------------------
    # Execute + score + persist
    # ------------------------------------------------------------------

    def grade_submission(
        self,
        assessment_id: str,
        student_id: str,
        bundle_id: str,
        *,
        submission_id: Optional[str] = None,
        image: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> AutogradingGradeResult:
        plan = self.build_plan(
            assessment_id,
            student_id,
            bundle_id,
            submission_id=submission_id,
        )
        backend = self.create_backend(image=image)
        availability = backend.availability()
        if not availability.available:
            raise AutogradingError(
                "Autograding runtime is unavailable: %s"
                % (availability.reason or "backend unavailable")
            )
        pytest_result = self.pytest_executor(plan, backend)
        scoring_result = self.scoring_fn(plan.config, pytest_result)
        stored = self.run_repository.commit_run(
            plan,
            pytest_result,
            scoring_result,
            metadata=dict(metadata or {}),
        )
        return AutogradingGradeResult(
            plan=plan,
            pytest_result=pytest_result,
            scoring_result=scoring_result,
            stored_run=stored,
        )

    def grade_batch(
        self,
        assessment_id: str,
        student_ids: Sequence[str],
        bundle_id: str,
        *,
        image: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> AutogradingBatchResult:
        assessment_id = _text(assessment_id, "assessment_id")
        bundle_id = _text(bundle_id, "bundle_id")
        ordered = []
        seen = set()
        for raw in tuple(student_ids or ()):
            student_id = str(raw or "").strip()
            if student_id and student_id not in seen:
                ordered.append(student_id)
                seen.add(student_id)

        results: List[BatchStudentResult] = []
        total = len(ordered)
        cancelled = False
        for index, student_id in enumerate(ordered, start=1):
            if cancel_check is not None and cancel_check():
                cancelled = True
                break
            if progress_callback is not None:
                progress_callback(index, total, student_id, GRADE_STATUS_RUNNING)
            try:
                result = self.grade_submission(
                    assessment_id,
                    student_id,
                    bundle_id,
                    image=image,
                    metadata=metadata,
                )
                status = (
                    GRADE_STATUS_REVIEW
                    if result.requires_review
                    else GRADE_STATUS_COMPLETED
                )
                item = BatchStudentResult(
                    student_id=student_id,
                    status=status,
                    grade_result=result,
                )
            except Exception as exc:
                item = BatchStudentResult(
                    student_id=student_id,
                    status=GRADE_STATUS_ERROR,
                    error_type=type(exc).__name__,
                    error_message=str(exc) or type(exc).__name__,
                )
            results.append(item)
            if progress_callback is not None:
                progress_callback(index, total, student_id, item.status)

        if cancelled:
            processed = {item.student_id for item in results}
            for student_id in ordered:
                if student_id not in processed:
                    results.append(
                        BatchStudentResult(
                            student_id=student_id,
                            status=GRADE_STATUS_CANCELLED,
                        )
                    )

        return AutogradingBatchResult(
            assessment_id=assessment_id,
            bundle_id=bundle_id,
            results=tuple(results),
            cancelled=cancelled,
            metadata={"image": str(image or self.default_image)},
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def list_history(self, assessment_id: str, student_id: str):
        return self.run_repository.list_run_references(
            _text(assessment_id, "assessment_id"),
            _text(student_id, "student_id"),
        )

    def list_assessment_history(self, assessment_id: str):
        return self.run_repository.list_assessment_run_references(
            _text(assessment_id, "assessment_id")
        )

    def load_run(self, assessment_id: str, student_id: str, run_id: str):
        return self.run_repository.load_run(
            _text(assessment_id, "assessment_id"),
            _text(student_id, "student_id"),
            _text(run_id, "run_id"),
            verify_hashes=True,
        )


__all__ = [
    "AUTOGRADING_SERVICE_SCHEMA_VERSION",
    "GRADE_STATUS_CANCELLED",
    "GRADE_STATUS_COMPLETED",
    "GRADE_STATUS_ERROR",
    "GRADE_STATUS_PENDING",
    "GRADE_STATUS_REVIEW",
    "GRADE_STATUS_RUNNING",
    "GRADE_STATUSES",
    "AutogradingBatchResult",
    "AutogradingGradeResult",
    "AutogradingService",
    "BatchStudentResult",
]
