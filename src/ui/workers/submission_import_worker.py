"""Background worker for canonical submission import and LaTeX ZIP preflight.

The worker keeps discovery, hashing, safe project preview, canonical file copying,
and optional parsing/compilation of newly active supported submissions off the Qt
GUI thread. It does not mutate ``SubmissionController`` state. The main-window/UI
thread registers returned ``Submission`` / ``ParsedSubmission`` objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import threading
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from src.submissions import (
    ExplicitAccommodationRequiredError,
    ImportBatch,
    ImportCommitResult,
    ImportCandidate,
    LocalFileSourceAdapter,
    Submission,
    SubmissionHandlerUnavailableError,
    SubmissionImporter,
    SubmissionRepository,
    generate_import_batch_id,
    parse_canonical_submission,
    route_submission,
)
from src.submissions.latex_project import (
    LATEX_PROJECT_ROOT_METADATA_KEY,
    LatexProjectRootResolutionRequiredError,
    apply_latex_project_preview_validation,
    preflight_latex_project_candidates,
)


class SubmissionImportOperation(str, Enum):
    """Supported canonical-import background operations."""

    DISCOVER_FILES = "discover_files"
    DISCOVER_DIRECTORY = "discover_directory"
    COMMIT = "commit"


def new_import_request_id() -> str:
    return uuid.uuid4().hex


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_operation(value: Any) -> SubmissionImportOperation:
    if isinstance(value, SubmissionImportOperation):
        return value
    try:
        return SubmissionImportOperation(str(value))
    except ValueError as exc:
        choices = ", ".join(item.value for item in SubmissionImportOperation)
        raise ValueError(
            f"Unknown submission import operation {value!r}; expected one of: {choices}"
        ) from exc


class SubmissionImportWorkerSignals(QObject):
    """Signals emitted by :class:`SubmissionImportWorker`."""

    started = pyqtSignal(str, str)
    progress = pyqtSignal(str, str, str)
    completed = pyqtSignal(str, str, object)
    failed = pyqtSignal(str, str, str, str)
    cancelled = pyqtSignal(str, str)
    finished = pyqtSignal(str, str)


class SubmissionImportWorker(QRunnable):
    """Run one source-discovery or canonical-commit operation in a thread pool."""

    def __init__(
        self,
        repository: SubmissionRepository,
        assessment_id: str,
        roster: Sequence[Any],
        operation: Any,
        *,
        request_id: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__()
        if not isinstance(repository, SubmissionRepository):
            raise TypeError("repository must be SubmissionRepository")
        assessment_id = str(assessment_id or "").strip()
        if not assessment_id:
            raise ValueError("assessment_id is required")

        self.repository = repository
        self.assessment_id = assessment_id
        self.roster = list(roster)
        self.operation = _normalize_operation(operation)
        self.request_id = str(request_id or new_import_request_id())
        self.parameters: Dict[str, Any] = dict(parameters or {})
        self.signals = SubmissionImportWorkerSignals()
        self._cancel_event = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _emit_progress(self, message: str) -> None:
        self.signals.progress.emit(
            self.request_id,
            self.operation.value,
            str(message),
        )

    @pyqtSlot()
    def run(self) -> None:
        operation = self.operation.value
        self.signals.started.emit(self.request_id, operation)
        try:
            if self.is_cancelled:
                self.signals.cancelled.emit(self.request_id, operation)
                return

            payload = self._execute()

            if self.is_cancelled:
                self.signals.cancelled.emit(self.request_id, operation)
                return

            self.signals.completed.emit(self.request_id, operation, payload)
        except Exception as exc:
            self.signals.failed.emit(
                self.request_id,
                operation,
                type(exc).__name__,
                str(exc) or type(exc).__name__,
            )
        finally:
            self.signals.finished.emit(self.request_id, operation)

    def _execute(self) -> Any:
        if self.operation == SubmissionImportOperation.DISCOVER_FILES:
            return self._discover_files()
        if self.operation == SubmissionImportOperation.DISCOVER_DIRECTORY:
            return self._discover_directory()
        if self.operation == SubmissionImportOperation.COMMIT:
            return self._commit()
        raise AssertionError(f"Unhandled import operation: {self.operation!r}")

    def _importer(self) -> SubmissionImporter:
        return SubmissionImporter(
            self.repository,
            assessment_id=self.assessment_id,
            roster=self.roster,
        )

    def _discover_files(self) -> Dict[str, Any]:
        file_paths = self.parameters.get("file_paths") or []
        if isinstance(file_paths, (str, bytes)) or not file_paths:
            raise ValueError("file_paths must be a non-empty sequence")
        self._emit_progress("Inspecting selected files and computing hashes…")
        adapter = LocalFileSourceAdapter.from_files(list(file_paths))
        raw_candidates = adapter.discover(assessment_id=self.assessment_id)
        if self.is_cancelled:
            return {"raw_candidates": [], "candidates": []}
        self._emit_progress("Safely inspecting LaTeX project ZIPs…")
        raw_candidates = preflight_latex_project_candidates(raw_candidates)
        if self.is_cancelled:
            return {"raw_candidates": [], "candidates": []}
        self._emit_progress("Matching submissions to the roster…")
        prepared = [
            apply_latex_project_preview_validation(item)
            for item in self._importer().prepare_candidates(raw_candidates)
        ]
        return {
            "raw_candidates": raw_candidates,
            "candidates": prepared,
            "source_kind": "files",
        }

    def _discover_directory(self) -> Dict[str, Any]:
        directory = str(self.parameters.get("directory") or "").strip()
        if not directory:
            raise ValueError("directory is required")
        include_subdirs = bool(
            self.parameters.get("include_student_subdirectories", True)
        )
        self._emit_progress("Scanning the submission folder and computing hashes…")
        adapter = LocalFileSourceAdapter.from_directory(
            directory,
            include_student_subdirectories=include_subdirs,
        )
        raw_candidates = adapter.discover(assessment_id=self.assessment_id)
        if self.is_cancelled:
            return {"raw_candidates": [], "candidates": []}
        self._emit_progress("Safely inspecting LaTeX project ZIPs…")
        raw_candidates = preflight_latex_project_candidates(raw_candidates)
        if self.is_cancelled:
            return {"raw_candidates": [], "candidates": []}
        self._emit_progress("Matching submissions to the roster…")
        prepared = [
            apply_latex_project_preview_validation(item)
            for item in self._importer().prepare_candidates(raw_candidates)
        ]
        return {
            "raw_candidates": raw_candidates,
            "candidates": prepared,
            "source_kind": "directory",
            "directory": directory,
        }

    def _commit(self) -> Dict[str, Any]:
        candidates = self.parameters.get("candidates") or []
        if not isinstance(candidates, (list, tuple)):
            raise TypeError("candidates must be a list or tuple")
        candidates = list(candidates)
        if not all(isinstance(item, ImportCandidate) for item in candidates):
            raise TypeError("every candidate must be ImportCandidate")

        force_duplicate_ids: Set[str] = {
            str(value)
            for value in (self.parameters.get("force_duplicate_ids") or [])
        }
        make_active = bool(self.parameters.get("make_active", True))
        created_by = self.parameters.get("created_by")
        question_ids = self.parameters.get("question_ids")
        evidence_dir = self.parameters.get("evidence_dir")
        compile_pdf = bool(self.parameters.get("compile_pdf", True))

        importer = self._importer()
        started_at = _utc_now_iso()
        submissions: List[Submission] = []
        skipped: List[str] = []
        errors: Dict[str, str] = {}
        processed_ids: Set[str] = set()

        all_source_paths: List[str] = []
        for candidate in candidates:
            for candidate_file in candidate.files:
                all_source_paths.append(candidate_file.source_path)
        adapter = (
            LocalFileSourceAdapter.from_files(all_source_paths)
            if all_source_paths
            else None
        )

        total = len(candidates)
        for index, candidate in enumerate(candidates, start=1):
            if self.is_cancelled:
                break
            self._emit_progress(
                f"Importing submission {index} of {total}: "
                f"{candidate.proposed_student_id or candidate.candidate_id}"
            )
            try:
                submission = importer.commit_candidate(
                    candidate,
                    adapter=adapter,
                    make_active=make_active,
                    force_duplicate=(candidate.candidate_id in force_duplicate_ids),
                )
                submissions.append(submission)
            except ValueError as exc:
                # Unready candidates that reached this worker are explicit user
                # selections; record the reason rather than hiding them.
                errors[candidate.candidate_id] = str(exc)
            except Exception as exc:
                errors[candidate.candidate_id] = str(exc)
            finally:
                processed_ids.add(candidate.candidate_id)

        if self.is_cancelled:
            skipped.extend(
                candidate.candidate_id
                for candidate in candidates
                if candidate.candidate_id not in processed_ids
            )

        status = "completed" if not errors else "completed_with_errors"
        batch = ImportBatch(
            import_batch_id=generate_import_batch_id(),
            source_system=(
                candidates[0].source_system if candidates else "local_upload"
            ),
            started_at=started_at,
            completed_at=_utc_now_iso(),
            created_by=(str(created_by).strip() if created_by else None),
            candidate_count=len(candidates),
            imported_count=len(submissions),
            skipped_count=len(skipped),
            error_count=len(errors),
            status=status,
            metadata={
                "assessment_id": self.assessment_id,
                "submission_ids": [item.submission_id for item in submissions],
            },
        )
        commit_result = ImportCommitResult(
            batch=batch,
            submissions=submissions,
            skipped_candidate_ids=skipped,
            errors=errors,
        )

        # Parse only the final active committed attempt for each student.  This
        # avoids repeatedly compiling intermediate attempts in a batch and keeps
        # controller mutation on the GUI thread.
        parsed_by_student: Dict[str, Any] = {}
        parse_errors: Dict[str, str] = {}
        handler_pending: Dict[str, str] = {}
        root_resolution_required: Dict[str, Dict[str, Any]] = {}

        affected_students = sorted({item.student_id for item in submissions})
        for student_id in affected_students:
            if self.is_cancelled:
                break
            active = self.repository.get_active_submission(
                self.assessment_id,
                student_id,
            )
            if active is None:
                continue

            decision = route_submission(active)
            if not decision.supported:
                handler_pending[student_id] = decision.reason or decision.route
                continue
            if decision.requires_explicit_accommodation:
                # The separate existing Add PDF Accommodation workflow remains
                # the explicit authorization path for PDF-only submissions.
                handler_pending[student_id] = "explicit_pdf_accommodation_required"
                continue

            self._emit_progress(f"Preparing grading evidence for {student_id}…")
            try:
                selected_root = str(
                    active.metadata.get(LATEX_PROJECT_ROOT_METADATA_KEY) or ""
                ).strip() or None
                parsed_by_student[student_id] = parse_canonical_submission(
                    active,
                    self.repository,
                    question_ids,
                    compile_pdf=compile_pdf,
                    latex_project_root=selected_root,
                    accommodation_mode=False,
                    evidence_dir=(str(evidence_dir) if evidence_dir else None),
                )
            except LatexProjectRootResolutionRequiredError as exc:
                root_resolution_required[student_id] = {
                    "submission_id": active.submission_id,
                    "candidate_paths": list(exc.resolution.candidate_paths),
                    "status": exc.resolution.status,
                    "message": str(exc),
                }
            except (SubmissionHandlerUnavailableError, ExplicitAccommodationRequiredError) as exc:
                handler_pending[student_id] = str(exc)
            except Exception as exc:
                # Canonical import remains successful even if the optional
                # grading-facing parser cannot prepare derived evidence.
                parse_errors[student_id] = str(exc)

        return {
            "commit_result": commit_result,
            "parsed_by_student": parsed_by_student,
            "parse_errors": parse_errors,
            "handler_pending": handler_pending,
            "root_resolution_required": root_resolution_required,
        }


__all__ = [
    "SubmissionImportOperation",
    "SubmissionImportWorker",
    "SubmissionImportWorkerSignals",
    "new_import_request_id",
]
