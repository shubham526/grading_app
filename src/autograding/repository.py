"""Immutable autograding-run repository for v2.3.3 Commit 8.

Every execution attempt is committed as a new immutable run directory.  The
per-student index is the only mutable history structure; reruns are never
silently deduplicated or overwritten.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Mapping, Optional

from src.submissions.file_store import (
    atomic_write_json,
    atomic_write_text,
    compute_file_sha256,
    read_json_object,
    reject_symlink,
    safe_path_component,
)

from .bundle_store import AUTOGRADING_DIRECTORY, TestBundleStore
from .errors import (
    AutogradingBundleIntegrityError,
    AutogradingRunIntegrityError,
    AutogradingRunStorageError,
)
from .models import (
    EXECUTION_STATUS_CANCELLED,
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INFRASTRUCTURE_ERROR,
    EXECUTION_STATUS_TIMEOUT,
    REVIEW_STATUS_FLAGGED,
    REVIEW_STATUS_UNREVIEWED,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_COMPLETED_WITH_FAILURES,
    RUN_STATUS_CONTAINER_ERROR,
    RUN_STATUS_GRADER_ERROR,
    RUN_STATUS_RUNTIME_ERROR,
    RUN_STATUS_SYNTAX_ERROR,
    RUN_STATUS_TEST_COLLECTION_ERROR,
    RUN_STATUS_TIMEOUT,
    TEST_STATUS_ERROR,
    TEST_STATUS_FAILED,
    TEST_STATUS_INFRASTRUCTURE_ERROR,
    TEST_STATUS_SKIPPED,
    TEST_STATUS_TIMEOUT,
    AutogradingProvenance,
    AutogradingRun,
)
from .planner import ExecutionPlan
from .scoring import AutogradingScoringResult
from .storage import (
    AUTOGRADING_RUN_EVIDENCE_DIRECTORY,
    AUTOGRADING_RUN_INDEX_SCHEMA_VERSION,
    AUTOGRADING_RUN_MANIFEST_FILENAME,
    AUTOGRADING_RUN_PLAN_FILENAME,
    AUTOGRADING_RUN_PYTEST_FILENAME,
    AUTOGRADING_RUN_SCORING_FILENAME,
    AUTOGRADING_RUN_STDERR_FILENAME,
    AUTOGRADING_RUN_STDOUT_FILENAME,
    AUTOGRADING_RUN_STORAGE_SCHEMA_VERSION,
    AutogradingRunReference,
    RunFileRecord,
    RUN_FILE_ROLE_PLAN,
    RUN_FILE_ROLE_PYTEST,
    RUN_FILE_ROLE_SCORING,
    RUN_FILE_ROLE_STDERR,
    RUN_FILE_ROLE_STDOUT,
    StoredAutogradingRun,
)
from .testing.protocol import PytestRunResult
from .validation import reject_symlink_chain


RUNS_DIRECTORY = "runs"
RUN_INDEX_FILENAME = "index.json"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value, name):
    value = "" if value is None else str(value).strip()
    if not value:
        raise AutogradingRunStorageError("%s must not be empty" % name)
    return value


def _contains_key(value, key):
    if isinstance(value, Mapping):
        if key in value:
            return True
        return any(_contains_key(item, key) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, key) for item in value)
    return False


def _run_status(pytest_result):
    execution = pytest_result.execution_result
    if execution.status == EXECUTION_STATUS_TIMEOUT:
        return RUN_STATUS_TIMEOUT
    if execution.status == EXECUTION_STATUS_INFRASTRUCTURE_ERROR:
        return RUN_STATUS_CONTAINER_ERROR
    if execution.status == EXECUTION_STATUS_CANCELLED:
        return RUN_STATUS_CANCELLED
    if execution.status == EXECUTION_STATUS_ERROR:
        return RUN_STATUS_RUNTIME_ERROR
    if pytest_result.student_preflight_errors:
        return RUN_STATUS_SYNTAX_ERROR
    if pytest_result.collection_errors or pytest_result.selection_errors:
        return RUN_STATUS_TEST_COLLECTION_ERROR
    if any(item.status == TEST_STATUS_INFRASTRUCTURE_ERROR for item in pytest_result.test_results):
        return RUN_STATUS_GRADER_ERROR
    failure_statuses = {
        TEST_STATUS_FAILED,
        TEST_STATUS_ERROR,
        TEST_STATUS_TIMEOUT,
        TEST_STATUS_SKIPPED,
    }
    if any(item.status in failure_statuses for item in pytest_result.test_results):
        return RUN_STATUS_COMPLETED_WITH_FAILURES
    return RUN_STATUS_COMPLETED


def _runtime_provenance(plan, pytest_result):
    environment = pytest_result.backend_record.environment
    metadata = deepcopy(plan.provenance.metadata)
    metadata.update(
        {
            "execution_backend": pytest_result.backend_record.backend_name,
            "environment": environment.to_dict(),
            "pytest_version": pytest_result.pytest_version,
            "pytest_exit_code": pytest_result.pytest_exit_code,
            "plan_created_at": plan.created_at,
            "selected_submission_was_active": plan.selected_submission_was_active,
        }
    )
    return AutogradingProvenance(
        submission_id=plan.provenance.submission_id,
        artifact_id=plan.provenance.artifact_id,
        submission_sha256=plan.provenance.submission_sha256,
        bundle_id=plan.provenance.bundle_id,
        bundle_sha256=plan.provenance.bundle_sha256,
        config_sha256=plan.provenance.config_sha256,
        runner_type=plan.provenance.runner_type,
        attempt=plan.provenance.attempt,
        environment_id=environment.environment_id,
        runner_version=pytest_result.pytest_version,
        metadata=metadata,
    )


def build_autograding_run_record(plan, pytest_result, scoring_result, metadata=None):
    """Build the immutable domain run snapshot that Commit 8 persists."""

    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be an ExecutionPlan")
    if not isinstance(pytest_result, PytestRunResult):
        raise TypeError("pytest_result must be a PytestRunResult")
    if not isinstance(scoring_result, AutogradingScoringResult):
        raise TypeError("scoring_result must be an AutogradingScoringResult")

    run_id = plan.run_id
    if pytest_result.backend_record.run_id != run_id:
        raise AutogradingRunStorageError("pytest result run_id does not match execution plan")
    if scoring_result.source_run_id != run_id:
        raise AutogradingRunStorageError("scoring result run_id does not match execution plan")

    config_ids = tuple(item.test_id for item in plan.config.tests)
    pytest_ids = tuple(item.test_id for item in pytest_result.test_results)
    scored_ids = tuple(item.test_id for item in scoring_result.test_results)
    if set(pytest_ids) != set(config_ids):
        raise AutogradingRunStorageError("pytest results do not match configured test IDs")
    if scored_ids != config_ids:
        raise AutogradingRunStorageError(
            "scored test results must preserve instructor configuration order"
        )
    pytest_by_id = {item.test_id: item for item in pytest_result.test_results}
    for scored in scoring_result.test_results:
        runtime = pytest_by_id[scored.test_id]
        if scored.status != runtime.status:
            raise AutogradingRunStorageError(
                "scoring result changed runtime status for %s" % scored.test_id
            )

    if abs(float(scoring_result.score_summary.max_score) - float(plan.config.max_points)) > 1e-9:
        raise AutogradingRunStorageError("score max does not match immutable autograder config")

    requires_review = bool(scoring_result.score_summary.requires_review)
    run_metadata = deepcopy(dict(metadata or {}))
    run_metadata.update(
        {
            "bundle_reference": plan.bundle_reference.to_dict(),
            "environment": pytest_result.backend_record.environment.to_dict(),
            "backend_name": pytest_result.backend_record.backend_name,
            "pytest_exit_code": pytest_result.pytest_exit_code,
            "pytest_version": pytest_result.pytest_version,
            "scoring_method": scoring_result.scoring_method,
            "selected_submission_was_active": plan.selected_submission_was_active,
        }
    )

    execution = pytest_result.execution_result
    return AutogradingRun(
        grading_run_id=run_id,
        assessment_id=plan.assessment_id,
        student_id=plan.student_id,
        submission_id=plan.submission_id,
        created_at=plan.created_at,
        provenance=_runtime_provenance(plan, pytest_result),
        status=_run_status(pytest_result),
        attempt=plan.attempt,
        review_status=(REVIEW_STATUS_FLAGGED if requires_review else REVIEW_STATUS_UNREVIEWED),
        started_at=execution.started_at,
        finished_at=execution.finished_at or pytest_result.backend_record.recorded_at,
        duration_ms=execution.duration_ms,
        execution_result=execution,
        test_results=scoring_result.test_results,
        score_summary=scoring_result.score_summary,
        requires_review=requires_review,
        review_reason=scoring_result.score_summary.review_reason,
        metadata=run_metadata,
    )


class AutogradingRunRepository:
    """Workspace-scoped immutable repository for autograding run history."""

    def __init__(self, workspace_root, create=True, now_fn=None):
        if not workspace_root:
            raise AutogradingRunStorageError("workspace_root is required")
        requested = Path(workspace_root).expanduser()
        reject_symlink_chain(requested, "assessment workspace")
        reject_symlink(requested, "assessment workspace")
        self._workspace_root = requested.resolve()
        self._root = self._workspace_root / AUTOGRADING_DIRECTORY
        self._lock = threading.RLock()
        self._now_fn = now_fn or _utc_now_iso
        reject_symlink(self._root, "autograding storage root")
        if create:
            self._workspace_root.mkdir(parents=True, exist_ok=True)
            self._root.mkdir(parents=True, exist_ok=True)

    @property
    def workspace_root(self):
        return str(self._workspace_root)

    @property
    def root(self):
        return str(self._root)

    def _assessment_dir(self, assessment_id, create=False):
        assessment_id = _text(assessment_id, "assessment_id")
        path = self._root / safe_path_component(assessment_id)
        reject_symlink(path, "autograding assessment directory")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _runs_root(self, assessment_id, create=False):
        path = self._assessment_dir(assessment_id, create=create) / RUNS_DIRECTORY
        reject_symlink(path, "autograding runs directory")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _student_dir(self, assessment_id, student_id, create=False):
        student_id = _text(student_id, "student_id")
        path = self._runs_root(assessment_id, create=create) / safe_path_component(student_id)
        reject_symlink(path, "autograding student-run directory")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self, assessment_id, student_id):
        return self._student_dir(assessment_id, student_id, create=False) / RUN_INDEX_FILENAME

    def _run_dir(self, assessment_id, student_id, run_id):
        return self._student_dir(assessment_id, student_id, create=False) / safe_path_component(
            _text(run_id, "run_id")
        )

    def _default_index(self, assessment_id, student_id):
        return {
            "schema_version": AUTOGRADING_RUN_INDEX_SCHEMA_VERSION,
            "assessment_id": assessment_id,
            "student_id": student_id,
            "runs": [],
        }

    def _load_index(self, assessment_id, student_id, allow_missing=True):
        assessment_id = _text(assessment_id, "assessment_id")
        student_id = _text(student_id, "student_id")
        path = self._index_path(assessment_id, student_id)
        try:
            reject_symlink_chain(path, "autograding run index", anchor=self._root)
        except Exception as exc:
            raise AutogradingRunIntegrityError(str(exc))
        if not path.exists():
            if allow_missing:
                return self._default_index(assessment_id, student_id)
            raise FileNotFoundError(str(path))
        try:
            data = read_json_object(path)
        except Exception as exc:
            raise AutogradingRunIntegrityError("Could not read run index: %s" % exc)
        if str(data.get("schema_version", "")) != AUTOGRADING_RUN_INDEX_SCHEMA_VERSION:
            raise AutogradingRunIntegrityError("Unsupported autograding run index schema")
        if str(data.get("assessment_id", "")) != assessment_id:
            raise AutogradingRunIntegrityError("Run index assessment mismatch")
        if str(data.get("student_id", "")) != student_id:
            raise AutogradingRunIntegrityError("Run index student mismatch")
        entries = data.get("runs")
        if not isinstance(entries, list):
            raise AutogradingRunIntegrityError("Run index runs must be a list")
        seen = set()
        for entry in entries:
            try:
                ref = AutogradingRunReference.from_dict(entry)
            except Exception as exc:
                raise AutogradingRunIntegrityError("Invalid run index entry: %s" % exc)
            if ref.assessment_id != assessment_id or ref.student_id != student_id:
                raise AutogradingRunIntegrityError("Run index contains cross-student/assessment entry")
            if ref.run_id in seen:
                raise AutogradingRunIntegrityError("Duplicate run_id in run index: %s" % ref.run_id)
            seen.add(ref.run_id)
        return deepcopy(data)

    def _write_index(self, assessment_id, student_id, index):
        student_dir = self._student_dir(assessment_id, student_id, create=True)
        payload = deepcopy(dict(index))
        payload["schema_version"] = AUTOGRADING_RUN_INDEX_SCHEMA_VERSION
        payload["assessment_id"] = assessment_id
        payload["student_id"] = student_id
        payload["runs"] = sorted(
            list(payload.get("runs") or ()),
            key=lambda item: (str(item.get("created_at", "")), str(item.get("run_id", ""))),
        )
        try:
            atomic_write_json(student_dir / RUN_INDEX_FILENAME, payload, overwrite=True)
        except Exception as exc:
            raise AutogradingRunStorageError("Could not write autograding run index: %s" % exc)

    def list_run_references(self, assessment_id, student_id):
        with self._lock:
            index = self._load_index(assessment_id, student_id, allow_missing=True)
            return tuple(AutogradingRunReference.from_dict(item) for item in index["runs"])

    def list_assessment_run_references(self, assessment_id):
        assessment_id = _text(assessment_id, "assessment_id")
        runs_root = self._runs_root(assessment_id, create=False)
        if not runs_root.exists():
            return tuple()
        try:
            reject_symlink_chain(runs_root, "autograding runs directory", anchor=self._root)
        except Exception as exc:
            raise AutogradingRunIntegrityError(str(exc))
        references = []
        for child in sorted(runs_root.iterdir(), key=lambda p: p.name.casefold()):
            if child.is_symlink():
                raise AutogradingRunIntegrityError("Symlink found in autograding run history")
            if not child.is_dir():
                raise AutogradingRunIntegrityError("Unexpected file in runs root: %s" % child)
            index_path = child / RUN_INDEX_FILENAME
            if not index_path.exists():
                continue
            data = read_json_object(index_path)
            student_id = str(data.get("student_id", "")).strip()
            if not student_id:
                raise AutogradingRunIntegrityError("Run index is missing student_id")
            references.extend(self.list_run_references(assessment_id, student_id))
        return tuple(sorted(references, key=lambda item: (item.created_at, item.student_id, item.run_id)))

    def latest_run_reference(self, assessment_id, student_id):
        refs = self.list_run_references(assessment_id, student_id)
        return refs[-1] if refs else None

    def _write_json_component(self, staging, relative_path, payload, role):
        path = staging / relative_path
        try:
            atomic_write_json(path, payload, overwrite=False)
            try:
                path.chmod(0o444)
            except OSError:
                pass
            return RunFileRecord(
                relative_path=relative_path,
                role=role,
                size_bytes=path.stat().st_size,
                sha256=compute_file_sha256(str(path)),
            )
        except Exception as exc:
            raise AutogradingRunStorageError("Could not persist %s: %s" % (role, exc))

    def _write_text_component(self, staging, relative_path, text, role):
        path = staging / relative_path
        try:
            atomic_write_text(path, text or "", overwrite=False)
            try:
                path.chmod(0o444)
            except OSError:
                pass
            return RunFileRecord(
                relative_path=relative_path,
                role=role,
                size_bytes=path.stat().st_size,
                sha256=compute_file_sha256(str(path)),
            )
        except Exception as exc:
            raise AutogradingRunStorageError("Could not persist %s: %s" % (role, exc))

    def _reference_for(self, run, manifest_path):
        environment = run.metadata.get("environment") or {}
        digest = environment.get("container_image_digest") if isinstance(environment, Mapping) else None
        summary = run.score_summary
        return AutogradingRunReference(
            run_id=run.run_id,
            assessment_id=run.assessment_id,
            student_id=run.student_id,
            submission_id=run.submission_id,
            bundle_id=run.provenance.bundle_id,
            created_at=run.created_at,
            status=run.status,
            manifest_sha256=compute_file_sha256(str(manifest_path)),
            manifest_size_bytes=manifest_path.stat().st_size,
            attempt=run.attempt,
            finished_at=run.finished_at,
            final_score=(summary.final_score if summary is not None else None),
            max_score=(summary.max_score if summary is not None else None),
            requires_review=run.requires_review,
            review_status=run.review_status,
            environment_id=run.provenance.environment_id,
            container_image_digest=digest,
            metadata={
                "runner_type": run.provenance.runner_type,
                "runner_version": run.provenance.runner_version,
            },
        )

    def commit_run(self, plan, pytest_result, scoring_result, metadata=None):
        """Atomically commit a new immutable historical run.

        The same submission/bundle combination may be committed repeatedly as
        long as each execution has its own run_id.  Reruns are evidence, not
        duplicates.
        """

        run = build_autograding_run_record(plan, pytest_result, scoring_result, metadata=metadata)
        with self._lock:
            # Reverify the immutable instructor bundle immediately before storing
            # provenance, so the historical record never points at already-corrupt
            # grader bytes.
            bundle_store = TestBundleStore(self._workspace_root, create=False)
            try:
                bundle = bundle_store.load_bundle(
                    plan.assessment_id,
                    plan.bundle_reference.bundle_id,
                    verify_hashes=True,
                )
            except Exception as exc:
                raise AutogradingRunStorageError(
                    "Cannot persist run because its test bundle is unavailable or corrupt: %s" % exc
                )
            if bundle.reference != plan.bundle_reference:
                raise AutogradingRunStorageError("Execution plan bundle reference changed before persistence")

            student_dir = self._student_dir(run.assessment_id, run.student_id, create=True)
            final_dir = student_dir / safe_path_component(run.run_id)
            if final_dir.exists() or final_dir.is_symlink():
                raise AutogradingRunStorageError(
                    "Autograding run_id already exists and cannot be overwritten: %s" % run.run_id
                )

            index = self._load_index(run.assessment_id, run.student_id, allow_missing=True)
            if any(str(item.get("run_id")) == run.run_id for item in index["runs"]):
                raise AutogradingRunStorageError("run_id already exists in history index")

            staging = Path(tempfile.mkdtemp(prefix=".run-staging-", dir=str(student_dir)))
            renamed = False
            try:
                plan_snapshot = plan.to_dict(include_source_paths=False)
                if _contains_key(plan_snapshot, "source_path"):
                    raise AutogradingRunStorageError(
                        "portable execution plan unexpectedly contains host source_path values"
                    )

                files = []
                files.append(
                    self._write_json_component(
                        staging,
                        AUTOGRADING_RUN_PLAN_FILENAME,
                        plan_snapshot,
                        RUN_FILE_ROLE_PLAN,
                    )
                )
                files.append(
                    self._write_json_component(
                        staging,
                        AUTOGRADING_RUN_PYTEST_FILENAME,
                        pytest_result.to_dict(),
                        RUN_FILE_ROLE_PYTEST,
                    )
                )
                files.append(
                    self._write_json_component(
                        staging,
                        AUTOGRADING_RUN_SCORING_FILENAME,
                        scoring_result.to_dict(),
                        RUN_FILE_ROLE_SCORING,
                    )
                )
                files.append(
                    self._write_text_component(
                        staging,
                        "%s/%s" % (
                            AUTOGRADING_RUN_EVIDENCE_DIRECTORY,
                            AUTOGRADING_RUN_STDOUT_FILENAME,
                        ),
                        pytest_result.execution_result.stdout,
                        RUN_FILE_ROLE_STDOUT,
                    )
                )
                files.append(
                    self._write_text_component(
                        staging,
                        "%s/%s" % (
                            AUTOGRADING_RUN_EVIDENCE_DIRECTORY,
                            AUTOGRADING_RUN_STDERR_FILENAME,
                        ),
                        pytest_result.execution_result.stderr,
                        RUN_FILE_ROLE_STDERR,
                    )
                )

                manifest = {
                    "schema_version": AUTOGRADING_RUN_STORAGE_SCHEMA_VERSION,
                    "run": run.to_dict(),
                    "files": [item.to_dict() for item in files],
                    "metadata": {
                        "portable_plan": True,
                        "source_paths_persisted": False,
                        "committed_at": _text(self._now_fn(), "committed_at"),
                    },
                }
                manifest_path = staging / AUTOGRADING_RUN_MANIFEST_FILENAME
                atomic_write_json(manifest_path, manifest, overwrite=False)
                try:
                    manifest_path.chmod(0o444)
                except OSError:
                    pass

                staging.rename(final_dir)
                renamed = True
                manifest_path = final_dir / AUTOGRADING_RUN_MANIFEST_FILENAME
                reference = self._reference_for(run, manifest_path)
                index["runs"].append(reference.to_dict())
                self._write_index(run.assessment_id, run.student_id, index)
            except Exception:
                if renamed and final_dir.exists():
                    shutil.rmtree(final_dir, ignore_errors=True)
                raise
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)

            return self.load_run(run.assessment_id, run.student_id, run.run_id, verify_hashes=True)

    def _reference_from_index(self, assessment_id, student_id, run_id):
        index = self._load_index(assessment_id, student_id, allow_missing=False)
        for item in index["runs"]:
            ref = AutogradingRunReference.from_dict(item)
            if ref.run_id == run_id:
                return ref
        raise KeyError(run_id)

    def _load_manifest(self, assessment_id, student_id, run_id):
        run_dir = self._run_dir(assessment_id, student_id, run_id)
        manifest_path = run_dir / AUTOGRADING_RUN_MANIFEST_FILENAME
        try:
            reject_symlink_chain(manifest_path, "autograding run manifest", anchor=self._root)
        except Exception as exc:
            raise AutogradingRunIntegrityError(str(exc))
        if not manifest_path.exists():
            raise FileNotFoundError(str(manifest_path))
        try:
            manifest = read_json_object(manifest_path)
        except Exception as exc:
            raise AutogradingRunIntegrityError("Could not read run manifest: %s" % exc)
        if str(manifest.get("schema_version", "")) != AUTOGRADING_RUN_STORAGE_SCHEMA_VERSION:
            raise AutogradingRunIntegrityError("Unsupported autograding run manifest schema")
        return run_dir, manifest_path, manifest

    def _load_component_json(self, run_dir, record):
        path = run_dir / record.relative_path
        try:
            return read_json_object(path)
        except Exception as exc:
            raise AutogradingRunIntegrityError(
                "Could not read %s component: %s" % (record.role, exc)
            )

    def load_run(self, assessment_id, student_id, run_id, verify_hashes=True):
        assessment_id = _text(assessment_id, "assessment_id")
        student_id = _text(student_id, "student_id")
        run_id = _text(run_id, "run_id")
        with self._lock:
            reference = self._reference_from_index(assessment_id, student_id, run_id)
            run_dir, manifest_path, manifest = self._load_manifest(assessment_id, student_id, run_id)

            actual_manifest_size = manifest_path.stat().st_size
            actual_manifest_hash = compute_file_sha256(str(manifest_path))
            if actual_manifest_size != reference.manifest_size_bytes:
                raise AutogradingRunIntegrityError("Run manifest size does not match history index")
            if actual_manifest_hash != reference.manifest_sha256:
                raise AutogradingRunIntegrityError("Run manifest hash does not match history index")

            run_data = manifest.get("run")
            if not isinstance(run_data, Mapping):
                raise AutogradingRunIntegrityError("Run manifest run must be an object")
            try:
                run = AutogradingRun.from_dict(run_data)
            except Exception as exc:
                raise AutogradingRunIntegrityError("Invalid stored AutogradingRun: %s" % exc)
            if (
                run.run_id != reference.run_id
                or run.assessment_id != reference.assessment_id
                or run.student_id != reference.student_id
                or run.submission_id != reference.submission_id
                or run.provenance.bundle_id != reference.bundle_id
            ):
                raise AutogradingRunIntegrityError("Run manifest identity does not match history index")
            summary = run.score_summary
            expected_final = summary.final_score if summary is not None else None
            expected_max = summary.max_score if summary is not None else None
            environment = run.metadata.get("environment") or {}
            expected_digest = (
                environment.get("container_image_digest")
                if isinstance(environment, Mapping)
                else None
            )
            indexed_fields_match = (
                reference.attempt == run.attempt
                and reference.created_at == run.created_at
                and reference.finished_at == run.finished_at
                and reference.status == run.status
                and reference.requires_review == run.requires_review
                and reference.review_status == run.review_status
                and reference.environment_id == run.provenance.environment_id
                and reference.container_image_digest == expected_digest
                and reference.final_score == expected_final
                and reference.max_score == expected_max
            )
            if not indexed_fields_match:
                raise AutogradingRunIntegrityError(
                    "Run history index summary does not match immutable run manifest"
                )

            try:
                files = tuple(RunFileRecord.from_dict(item) for item in (manifest.get("files") or ()))
            except Exception as exc:
                raise AutogradingRunIntegrityError("Invalid run file manifest: %s" % exc)
            by_role = {item.role: item for item in files}
            required_roles = {
                RUN_FILE_ROLE_PLAN,
                RUN_FILE_ROLE_PYTEST,
                RUN_FILE_ROLE_SCORING,
                RUN_FILE_ROLE_STDOUT,
                RUN_FILE_ROLE_STDERR,
            }
            if set(by_role) != required_roles:
                raise AutogradingRunIntegrityError("Run manifest does not contain the required component roles")

            if verify_hashes:
                self._verify_files(run_dir, files)

            plan_snapshot = self._load_component_json(run_dir, by_role[RUN_FILE_ROLE_PLAN])
            if _contains_key(plan_snapshot, "source_path"):
                raise AutogradingRunIntegrityError("Stored portable plan leaks host source_path values")
            try:
                pytest_result = PytestRunResult.from_dict(
                    self._load_component_json(run_dir, by_role[RUN_FILE_ROLE_PYTEST])
                )
                scoring_result = AutogradingScoringResult.from_dict(
                    self._load_component_json(run_dir, by_role[RUN_FILE_ROLE_SCORING])
                )
            except Exception as exc:
                raise AutogradingRunIntegrityError("Stored structured result is invalid: %s" % exc)

            stored = StoredAutogradingRun(
                reference=reference,
                run=run,
                plan_snapshot=plan_snapshot,
                pytest_result=pytest_result,
                scoring_result=scoring_result,
                files=files,
                run_dir=str(run_dir),
                metadata=manifest.get("metadata", {}),
            )
            self._verify_consistency(stored)
            self._verify_evidence_files(stored)
            return stored

    def _verify_files(self, run_dir, files):
        expected = {AUTOGRADING_RUN_MANIFEST_FILENAME}
        for item in files:
            path = run_dir / item.relative_path
            try:
                reject_symlink_chain(path, "stored autograding run file", anchor=run_dir)
            except Exception as exc:
                raise AutogradingRunIntegrityError(str(exc))
            if path.is_symlink() or not path.is_file():
                raise AutogradingRunIntegrityError("Stored run file is missing or symlinked: %s" % path)
            if path.stat().st_size != item.size_bytes:
                raise AutogradingRunIntegrityError("Stored run file size mismatch: %s" % item.relative_path)
            if compute_file_sha256(str(path)) != item.sha256:
                raise AutogradingRunIntegrityError("Stored run file hash mismatch: %s" % item.relative_path)
            expected.add(item.relative_path)

        actual = set()
        for path in run_dir.rglob("*"):
            if path.is_symlink():
                raise AutogradingRunIntegrityError("Symlink found in immutable run directory: %s" % path)
            if path.is_file():
                actual.add(path.relative_to(run_dir).as_posix())
            elif not path.is_dir():
                raise AutogradingRunIntegrityError("Non-regular entry found in run directory: %s" % path)
        if actual != expected:
            raise AutogradingRunIntegrityError(
                "Stored run directory does not match manifest; extra=%r missing=%r"
                % (sorted(actual - expected), sorted(expected - actual))
            )

    def _verify_consistency(self, stored):
        run = stored.run
        pytest_result = stored.pytest_result
        scoring = stored.scoring_result
        plan = stored.plan_snapshot
        if str(plan.get("run_id", "")) != run.run_id:
            raise AutogradingRunIntegrityError("Stored execution plan run_id mismatch")
        if str(plan.get("assessment_id", "")) != run.assessment_id:
            raise AutogradingRunIntegrityError("Stored execution plan assessment mismatch")
        if str(plan.get("student_id", "")) != run.student_id:
            raise AutogradingRunIntegrityError("Stored execution plan student mismatch")
        if str(plan.get("submission_id", "")) != run.submission_id:
            raise AutogradingRunIntegrityError("Stored execution plan submission mismatch")
        bundle_ref = plan.get("bundle_reference") or {}
        if str(bundle_ref.get("bundle_id", "")) != run.provenance.bundle_id:
            raise AutogradingRunIntegrityError("Stored execution plan bundle mismatch")
        if str(bundle_ref.get("bundle_sha256", "")) != run.provenance.bundle_sha256:
            raise AutogradingRunIntegrityError("Stored execution plan bundle hash mismatch")
        if str(bundle_ref.get("config_sha256", "")) != run.provenance.config_sha256:
            raise AutogradingRunIntegrityError("Stored execution plan config hash mismatch")
        if pytest_result.backend_record.run_id != run.run_id:
            raise AutogradingRunIntegrityError("Stored pytest run_id mismatch")
        if scoring.source_run_id != run.run_id:
            raise AutogradingRunIntegrityError("Stored scoring run_id mismatch")
        if pytest_result.execution_result != run.execution_result:
            raise AutogradingRunIntegrityError("Stored execution result differs across run/protocol files")
        if scoring.test_results != run.test_results:
            raise AutogradingRunIntegrityError("Stored scored test results differ from domain run")
        if scoring.score_summary != run.score_summary:
            raise AutogradingRunIntegrityError("Stored score summary differs from domain run")
        environment = pytest_result.backend_record.environment
        if run.provenance.environment_id != environment.environment_id:
            raise AutogradingRunIntegrityError("Stored environment provenance mismatch")
        if run.provenance.runner_version != pytest_result.pytest_version:
            raise AutogradingRunIntegrityError("Stored runner version provenance mismatch")

    def _verify_evidence_files(self, stored):
        stdout_record = stored.file_by_role(RUN_FILE_ROLE_STDOUT)
        stderr_record = stored.file_by_role(RUN_FILE_ROLE_STDERR)
        stdout_path = Path(stored.run_dir) / stdout_record.relative_path
        stderr_path = Path(stored.run_dir) / stderr_record.relative_path
        try:
            stdout = stdout_path.read_text(encoding="utf-8")
            stderr = stderr_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise AutogradingRunIntegrityError("Could not read execution evidence text: %s" % exc)
        if stdout != stored.run.execution_result.stdout:
            raise AutogradingRunIntegrityError("Execution stdout evidence differs from run record")
        if stderr != stored.run.execution_result.stderr:
            raise AutogradingRunIntegrityError("Execution stderr evidence differs from run record")

    def verify_run(self, stored):
        if not isinstance(stored, StoredAutogradingRun):
            raise TypeError("stored must be a StoredAutogradingRun")
        reloaded = self.load_run(
            stored.reference.assessment_id,
            stored.reference.student_id,
            stored.reference.run_id,
            verify_hashes=True,
        )
        if reloaded.reference != stored.reference:
            raise AutogradingRunIntegrityError("Reloaded run reference differs from supplied record")
        return True


__all__ = [
    "AutogradingRunRepository",
    "RUNS_DIRECTORY",
    "RUN_INDEX_FILENAME",
    "build_autograding_run_record",
]
