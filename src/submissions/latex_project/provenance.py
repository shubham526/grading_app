"""Persistent provenance and recovery state for canonical LaTeX projects.

The original ZIP, extracted source manifest, and canonical submission manifest
remain immutable.  This module stores *derived* grading state alongside the
verified project so root choices, compiler attempts, logs, and rendered-PDF
hashes survive application restarts without mutating authoritative evidence.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..file_store import (
    atomic_write_json,
    atomic_write_text,
    compute_file_sha256,
    read_json_object,
    reject_symlink,
)
from ..models import CompilationResult
from .errors import LatexProjectIntegrityError, LatexProjectSerializationError
from .models import LatexProjectResolution, normalize_project_relative_path
from .storage import StoredLatexProject


LATEX_PROJECT_PROVENANCE_SCHEMA_VERSION = "1.0"
LATEX_PROJECT_PROVENANCE_FILENAME = "grading_provenance.json"
LATEX_PROJECT_LOGS_DIRNAME = "logs"

PROJECT_STATUS_ROOT_RESOLVED = "root_resolved"
PROJECT_STATUS_COMPILED = "compiled"
PROJECT_STATUS_COMPILATION_FAILED = "compilation_failed"
PROJECT_STATUS_INTEGRITY_FAILED = "integrity_failed"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("%s must not be empty" % name)
    return text


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_relative_path(value: Any, name: str) -> Optional[str]:
    text = _optional_text(value)
    if text is None:
        return None
    return normalize_project_relative_path(text, name)


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError("%s must be bool" % name)
    return value


@dataclass(frozen=True)
class LatexProjectCompilationAttempt:
    """One persisted compiler attempt for a verified project/root."""

    attempt_number: int
    started_at: str
    completed_at: str
    root_relative_path: str
    root_resolution_method: str
    compiler_options: Dict[str, Any]
    success: bool
    engine: str
    return_code: Optional[int] = None
    passes_completed: int = 0
    duration_seconds: float = 0.0
    warnings: Tuple[str, ...] = ()
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    compiled_pdf_relative_path: Optional[str] = None
    compiled_pdf_sha256: Optional[str] = None
    compilation_log_relative_path: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.attempt_number, bool) or self.attempt_number <= 0:
            raise ValueError("attempt_number must be a positive integer")
        _text(self.started_at, "started_at")
        _text(self.completed_at, "completed_at")
        object.__setattr__(
            self,
            "root_relative_path",
            normalize_project_relative_path(self.root_relative_path, "root_relative_path"),
        )
        _text(self.root_resolution_method, "root_resolution_method")
        _text(self.engine, "engine")
        if not isinstance(self.success, bool):
            raise TypeError("success must be bool")
        if self.compiled_pdf_relative_path is not None:
            object.__setattr__(
                self,
                "compiled_pdf_relative_path",
                normalize_project_relative_path(
                    self.compiled_pdf_relative_path, "compiled_pdf_relative_path"
                ),
            )
        if self.compilation_log_relative_path is not None:
            object.__setattr__(
                self,
                "compilation_log_relative_path",
                normalize_project_relative_path(
                    self.compilation_log_relative_path, "compilation_log_relative_path"
                ),
            )
        if self.success:
            if not self.compiled_pdf_relative_path or not self.compiled_pdf_sha256:
                raise ValueError("successful attempt requires compiled PDF provenance")
        if self.compiled_pdf_sha256 is not None:
            digest = str(self.compiled_pdf_sha256).strip().lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("compiled_pdf_sha256 must be a SHA-256 hex digest")
            object.__setattr__(self, "compiled_pdf_sha256", digest)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "root_relative_path": self.root_relative_path,
            "root_resolution_method": self.root_resolution_method,
            "compiler_options": deepcopy(self.compiler_options),
            "success": self.success,
            "engine": self.engine,
            "return_code": self.return_code,
            "passes_completed": self.passes_completed,
            "duration_seconds": self.duration_seconds,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "compiled_pdf_relative_path": self.compiled_pdf_relative_path,
            "compiled_pdf_sha256": self.compiled_pdf_sha256,
            "compilation_log_relative_path": self.compilation_log_relative_path,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LatexProjectCompilationAttempt":
        if not isinstance(data, Mapping):
            raise TypeError("compilation attempt must be a mapping")
        return cls(
            attempt_number=int(data.get("attempt_number") or 0),
            started_at=_text(data.get("started_at"), "started_at"),
            completed_at=_text(data.get("completed_at"), "completed_at"),
            root_relative_path=_text(data.get("root_relative_path"), "root_relative_path"),
            root_resolution_method=_text(
                data.get("root_resolution_method"), "root_resolution_method"
            ),
            compiler_options=deepcopy(dict(data.get("compiler_options") or {})),
            success=_bool(data.get("success"), "success"),
            engine=_text(data.get("engine"), "engine"),
            return_code=data.get("return_code"),
            passes_completed=int(data.get("passes_completed") or 0),
            duration_seconds=float(data.get("duration_seconds") or 0.0),
            warnings=tuple(str(v) for v in (data.get("warnings") or ())),
            error_code=_optional_text(data.get("error_code")),
            error_message=_optional_text(data.get("error_message")),
            compiled_pdf_relative_path=_optional_relative_path(
                data.get("compiled_pdf_relative_path"), "compiled_pdf_relative_path"
            ),
            compiled_pdf_sha256=_optional_text(data.get("compiled_pdf_sha256")),
            compilation_log_relative_path=_optional_relative_path(
                data.get("compilation_log_relative_path"), "compilation_log_relative_path"
            ),
        )


@dataclass(frozen=True)
class LatexProjectProvenanceState:
    """Restart-safe mutable state derived from immutable canonical evidence."""

    submission_id: str
    source_artifact_id: str
    project_id: str
    archive_sha256: str
    manifest_sha256: str
    root_relative_path: Optional[str] = None
    root_resolution_method: Optional[str] = None
    candidate_paths: Tuple[str, ...] = ()
    updated_at: str = field(default_factory=_utc_now_iso)
    compilation_attempts: Tuple[LatexProjectCompilationAttempt, ...] = ()
    schema_version: str = LATEX_PROJECT_PROVENANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LATEX_PROJECT_PROVENANCE_SCHEMA_VERSION:
            raise ValueError("unsupported LaTeX-project provenance schema")
        for name in (
            "submission_id",
            "source_artifact_id",
            "project_id",
            "archive_sha256",
            "manifest_sha256",
            "updated_at",
        ):
            _text(getattr(self, name), name)
        for name in ("archive_sha256", "manifest_sha256"):
            digest = str(getattr(self, name)).strip().lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("%s must be a SHA-256 hex digest" % name)
            object.__setattr__(self, name, digest)
        if (self.root_relative_path is None) != (self.root_resolution_method is None):
            raise ValueError("root path and resolution method must be present together")
        if self.root_relative_path is not None:
            object.__setattr__(
                self,
                "root_relative_path",
                normalize_project_relative_path(
                    self.root_relative_path, "root_relative_path"
                ),
            )
        object.__setattr__(
            self,
            "candidate_paths",
            tuple(
                normalize_project_relative_path(path, "candidate_path")
                for path in self.candidate_paths
            ),
        )
        seen = set()
        for attempt in self.compilation_attempts:
            if not isinstance(attempt, LatexProjectCompilationAttempt):
                raise TypeError("compilation_attempts must contain attempt records")
            if attempt.attempt_number in seen:
                raise ValueError("duplicate compilation attempt number")
            seen.add(attempt.attempt_number)

    @property
    def latest_attempt(self) -> Optional[LatexProjectCompilationAttempt]:
        return self.compilation_attempts[-1] if self.compilation_attempts else None

    @property
    def status(self) -> str:
        latest = self.latest_attempt
        if latest is None:
            return PROJECT_STATUS_ROOT_RESOLVED
        return PROJECT_STATUS_COMPILED if latest.success else PROJECT_STATUS_COMPILATION_FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "submission_id": self.submission_id,
            "source_artifact_id": self.source_artifact_id,
            "project_id": self.project_id,
            "archive_sha256": self.archive_sha256,
            "manifest_sha256": self.manifest_sha256,
            "root_relative_path": self.root_relative_path,
            "root_resolution_method": self.root_resolution_method,
            "candidate_paths": list(self.candidate_paths),
            "updated_at": self.updated_at,
            "status": self.status,
            "compilation_attempts": [item.to_dict() for item in self.compilation_attempts],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LatexProjectProvenanceState":
        if not isinstance(data, Mapping):
            raise TypeError("LaTeX-project provenance must be a mapping")
        schema = str(data.get("schema_version") or "").strip()
        if schema != LATEX_PROJECT_PROVENANCE_SCHEMA_VERSION:
            raise LatexProjectSerializationError(
                "Unsupported LaTeX-project provenance schema %r" % schema
            )
        try:
            return cls(
                schema_version=schema,
                submission_id=_text(data.get("submission_id"), "submission_id"),
                source_artifact_id=_text(
                    data.get("source_artifact_id"), "source_artifact_id"
                ),
                project_id=_text(data.get("project_id"), "project_id"),
                archive_sha256=_text(data.get("archive_sha256"), "archive_sha256"),
                manifest_sha256=_text(data.get("manifest_sha256"), "manifest_sha256"),
                root_relative_path=_optional_relative_path(
                    data.get("root_relative_path"), "root_relative_path"
                ),
                root_resolution_method=_optional_text(
                    data.get("root_resolution_method")
                ),
                candidate_paths=tuple(
                    normalize_project_relative_path(v, "candidate_path")
                    for v in (data.get("candidate_paths") or ())
                ),
                updated_at=_text(data.get("updated_at"), "updated_at"),
                compilation_attempts=tuple(
                    LatexProjectCompilationAttempt.from_dict(item)
                    for item in (data.get("compilation_attempts") or ())
                ),
            )
        except (TypeError, ValueError) as exc:
            raise LatexProjectSerializationError(str(exc)) from exc


def provenance_path(stored: StoredLatexProject) -> Path:
    if not isinstance(stored, StoredLatexProject):
        raise TypeError("stored must be StoredLatexProject")
    root = Path(stored.project_dir)
    reject_symlink(root, "LaTeX-project directory")
    return root / LATEX_PROJECT_PROVENANCE_FILENAME


def _validate_binding(stored: StoredLatexProject, state: LatexProjectProvenanceState) -> None:
    if state.project_id != stored.project_id:
        raise LatexProjectIntegrityError("Persisted provenance belongs to another project")
    if state.archive_sha256 != stored.archive.archive_sha256:
        raise LatexProjectIntegrityError("Persisted provenance ZIP digest mismatch")
    if state.manifest_sha256 != stored.manifest.manifest_sha256:
        raise LatexProjectIntegrityError("Persisted provenance manifest digest mismatch")
    if state.source_artifact_id != stored.archive.source_artifact_id:
        raise LatexProjectIntegrityError("Persisted provenance source artifact mismatch")


def load_latex_project_provenance(
    stored: StoredLatexProject,
) -> Optional[LatexProjectProvenanceState]:
    path = provenance_path(stored)
    if not path.exists():
        return None
    try:
        state = LatexProjectProvenanceState.from_dict(read_json_object(path))
    except (OSError, ValueError) as exc:
        if isinstance(exc, LatexProjectSerializationError):
            raise
        raise LatexProjectSerializationError(str(exc)) from exc
    _validate_binding(stored, state)
    return state


def save_latex_project_provenance(
    stored: StoredLatexProject,
    state: LatexProjectProvenanceState,
) -> str:
    if not isinstance(state, LatexProjectProvenanceState):
        raise TypeError("state must be LatexProjectProvenanceState")
    _validate_binding(stored, state)
    path = provenance_path(stored)
    atomic_write_json(path, state.to_dict(), overwrite=True)
    return str(path.resolve())


def state_with_resolution(
    stored: StoredLatexProject,
    *,
    submission_id: str,
    resolution: LatexProjectResolution,
    previous: Optional[LatexProjectProvenanceState] = None,
) -> LatexProjectProvenanceState:
    if not isinstance(resolution, LatexProjectResolution):
        raise TypeError("resolution must be LatexProjectResolution")
    root = _text(resolution.root_relative_path, "root_relative_path")
    method = _text(resolution.resolution_method, "root_resolution_method")
    attempts = previous.compilation_attempts if previous is not None else ()
    return LatexProjectProvenanceState(
        submission_id=_text(submission_id, "submission_id"),
        source_artifact_id=stored.archive.source_artifact_id,
        project_id=stored.project_id,
        archive_sha256=stored.archive.archive_sha256,
        manifest_sha256=_text(stored.manifest.manifest_sha256, "manifest_sha256"),
        root_relative_path=root,
        root_resolution_method=method,
        candidate_paths=tuple(resolution.candidate_paths),
        compilation_attempts=attempts,
    )


def _relative_project_path(stored: StoredLatexProject, path: str) -> Optional[str]:
    target = Path(path).resolve()
    root = Path(stored.project_dir).resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return None


def _write_attempt_log(
    stored: StoredLatexProject,
    attempt_number: int,
    result: CompilationResult,
    *,
    started_at: str,
    completed_at: str,
) -> str:
    log_dir = Path(stored.project_dir) / LATEX_PROJECT_LOGS_DIRNAME
    reject_symlink(Path(stored.project_dir), "LaTeX-project directory")
    log_dir.mkdir(parents=True, exist_ok=True)
    reject_symlink(log_dir, "LaTeX-project log directory")
    filename = "compilation_attempt_%04d.log" % attempt_number
    path = log_dir / filename
    lines = [
        "LaTeX project compilation attempt %d" % attempt_number,
        "Started: %s" % started_at,
        "Completed: %s" % completed_at,
        "Engine: %s" % result.engine,
        "Success: %s" % result.success,
        "Return code: %s" % result.return_code,
        "Error code: %s" % (result.error_code or ""),
        "Error message: %s" % (result.error_message or ""),
        "",
        "--- stdout ---",
        result.stdout or "",
        "",
        "--- stderr ---",
        result.stderr or "",
        "",
    ]
    atomic_write_text(path, "\n".join(lines), overwrite=False)
    return path.relative_to(Path(stored.project_dir)).as_posix()


def append_compilation_attempt(
    stored: StoredLatexProject,
    state: LatexProjectProvenanceState,
    result: CompilationResult,
    *,
    compiler_options: Mapping[str, Any],
    started_at: str,
    completed_at: Optional[str] = None,
) -> LatexProjectProvenanceState:
    if not isinstance(result, CompilationResult):
        raise TypeError("result must be CompilationResult")
    _validate_binding(stored, state)
    completed = completed_at or _utc_now_iso()
    attempt_number = len(state.compilation_attempts) + 1
    log_relative = _write_attempt_log(
        stored,
        attempt_number,
        result,
        started_at=started_at,
        completed_at=completed,
    )
    pdf_relative = None
    pdf_sha = None
    if result.success and result.pdf_path:
        pdf_relative = _relative_project_path(stored, result.pdf_path)
        if pdf_relative is None:
            raise LatexProjectIntegrityError(
                "Compiled PDF is outside the canonical LaTeX-project derived tree"
            )
        pdf_sha = compute_file_sha256(result.pdf_path)
    attempt = LatexProjectCompilationAttempt(
        attempt_number=attempt_number,
        started_at=started_at,
        completed_at=completed,
        root_relative_path=_text(state.root_relative_path, "root_relative_path"),
        root_resolution_method=_text(
            state.root_resolution_method, "root_resolution_method"
        ),
        compiler_options=deepcopy(dict(compiler_options)),
        success=bool(result.success),
        engine=result.engine,
        return_code=result.return_code,
        passes_completed=result.passes_completed,
        duration_seconds=result.duration_seconds,
        warnings=tuple(result.warnings),
        error_code=result.error_code,
        error_message=result.error_message,
        compiled_pdf_relative_path=pdf_relative,
        compiled_pdf_sha256=pdf_sha,
        compilation_log_relative_path=log_relative,
    )
    return LatexProjectProvenanceState(
        submission_id=state.submission_id,
        source_artifact_id=state.source_artifact_id,
        project_id=state.project_id,
        archive_sha256=state.archive_sha256,
        manifest_sha256=state.manifest_sha256,
        root_relative_path=state.root_relative_path,
        root_resolution_method=state.root_resolution_method,
        candidate_paths=state.candidate_paths,
        compilation_attempts=state.compilation_attempts + (attempt,),
    )


def reusable_compiled_pdf(
    stored: StoredLatexProject,
    state: Optional[LatexProjectProvenanceState],
    *,
    root_relative_path: str,
    compiler_options: Mapping[str, Any],
) -> Optional[str]:
    if state is None:
        return None
    _validate_binding(stored, state)
    latest = state.latest_attempt
    if latest is None or not latest.success:
        return None
    if latest.root_relative_path != root_relative_path:
        return None
    if dict(latest.compiler_options) != dict(compiler_options):
        return None
    relative = latest.compiled_pdf_relative_path
    digest = latest.compiled_pdf_sha256
    if not relative or not digest:
        return None
    target = Path(stored.project_dir).joinpath(*Path(relative).parts)
    if target.is_symlink() or not target.is_file():
        return None
    try:
        if compute_file_sha256(str(target)) != digest:
            return None
    except (OSError, ValueError):
        return None
    return str(target.resolve())


def provenance_diagnostic_payload(
    stored: Optional[StoredLatexProject],
    state: Optional[LatexProjectProvenanceState],
    *,
    error: Optional[BaseException] = None,
    project_dir: Optional[str] = None,
    candidate_paths: Sequence[str] = (),
    root_relative_path: Optional[str] = None,
) -> Dict[str, Any]:
    latest = state.latest_attempt if state is not None else None
    status = state.status if state is not None else PROJECT_STATUS_COMPILATION_FAILED
    error_code = latest.error_code if latest is not None else None
    error_message = latest.error_message if latest is not None else None
    warnings = list(latest.warnings) if latest is not None else []
    compiler = latest.engine if latest is not None else None
    log_path = None
    source_project_dir = None
    root = root_relative_path or (state.root_relative_path if state is not None else None)
    candidates = list(candidate_paths or (state.candidate_paths if state is not None else ()))

    if stored is not None:
        project_dir = stored.project_dir
        source_project_dir = stored.extracted_root
        if latest is not None and latest.compilation_log_relative_path:
            log_path = str(
                Path(stored.project_dir)
                .joinpath(*Path(latest.compilation_log_relative_path).parts)
                .resolve()
            )

    if error is not None:
        error_message = str(error) or type(error).__name__
        if isinstance(error, LatexProjectIntegrityError):
            status = PROJECT_STATUS_INTEGRITY_FAILED
            error_code = "latex_project_integrity_failure"
        elif error_code is None:
            error_code = type(error).__name__

    recoverable = status != PROJECT_STATUS_INTEGRITY_FAILED
    return {
        "status": status,
        "project_id": state.project_id if state is not None else None,
        "root_relative_path": root,
        "root_resolution_method": (
            state.root_resolution_method if state is not None else None
        ),
        "candidate_paths": candidates,
        "compiler": compiler,
        "compiler_options": (
            deepcopy(latest.compiler_options) if latest is not None else {}
        ),
        "error_code": error_code,
        "error_message": error_message,
        "warnings": warnings,
        "compilation_log_path": log_path,
        "project_dir": project_dir,
        "source_project_dir": source_project_dir,
        "recoverable": recoverable,
        "attempt_count": len(state.compilation_attempts) if state is not None else 0,
        "compiled_pdf_sha256": (
            latest.compiled_pdf_sha256 if latest is not None else None
        ),
    }


__all__ = [
    "LATEX_PROJECT_LOGS_DIRNAME",
    "LATEX_PROJECT_PROVENANCE_FILENAME",
    "LATEX_PROJECT_PROVENANCE_SCHEMA_VERSION",
    "PROJECT_STATUS_COMPILED",
    "PROJECT_STATUS_COMPILATION_FAILED",
    "PROJECT_STATUS_INTEGRITY_FAILED",
    "PROJECT_STATUS_ROOT_RESOLVED",
    "LatexProjectCompilationAttempt",
    "LatexProjectProvenanceState",
    "append_compilation_attempt",
    "load_latex_project_provenance",
    "provenance_diagnostic_payload",
    "provenance_path",
    "reusable_compiled_pdf",
    "save_latex_project_provenance",
    "state_with_resolution",
]
