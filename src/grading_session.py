"""Persistent grading-session checkpoints for resumable manual grading.

The checkpoint is intentionally separate from student assessment JSON.  A
student assessment records grading state for one student; this workspace-level
checkpoint records the instructor's cursor across the roster (workflow,
question, and student) so a question-by-question grading session can resume at
the exact place it stopped.

This module has no Qt dependency and uses only standard-library JSON/filesystem
primitives so it is straightforward to test and safe to reuse.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Optional


GRADING_SESSION_SCHEMA_VERSION = "1.0"
GRADING_SESSION_DIRNAME = ".grading_sessions"
QUESTION_CENTRIC_MODE = "question_centric"

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _required_text(value: Any, name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _safe_component(value: str) -> str:
    raw = _required_text(value, "assessment_id")
    cleaned = _SAFE_COMPONENT_RE.sub("_", raw).strip("._-") or "assessment"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:80]}__{digest}"


@dataclass(frozen=True)
class GradingSessionCheckpoint:
    assessment_id: str
    workflow_mode: str
    question_id: str
    student_id: str
    saved_at: str
    schema_version: str = GRADING_SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _required_text(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "workflow_mode", _required_text(self.workflow_mode, "workflow_mode"))
        object.__setattr__(self, "question_id", _required_text(self.question_id, "question_id"))
        object.__setattr__(self, "student_id", _required_text(self.student_id, "student_id"))
        object.__setattr__(self, "saved_at", _required_text(self.saved_at, "saved_at"))
        if str(self.schema_version) != GRADING_SESSION_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported grading-session schema {self.schema_version!r}; "
                f"expected {GRADING_SESSION_SCHEMA_VERSION!r}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GradingSessionCheckpoint":
        if not isinstance(data, Mapping):
            raise TypeError("grading-session checkpoint must be a mapping")
        return cls(
            assessment_id=data.get("assessment_id"),
            workflow_mode=data.get("workflow_mode"),
            question_id=data.get("question_id"),
            student_id=data.get("student_id"),
            saved_at=data.get("saved_at"),
            schema_version=data.get("schema_version", GRADING_SESSION_SCHEMA_VERSION),
        )


def grading_session_path(workspace: str, assessment_id: str) -> Path:
    root = Path(_required_text(workspace, "workspace")).expanduser().resolve()
    return root / GRADING_SESSION_DIRNAME / f"{_safe_component(assessment_id)}.json"


def save_grading_session_checkpoint(
    workspace: str,
    assessment_id: str,
    question_id: str,
    student_id: str,
    workflow_mode: str = QUESTION_CENTRIC_MODE,
) -> GradingSessionCheckpoint:
    checkpoint = GradingSessionCheckpoint(
        assessment_id=assessment_id,
        workflow_mode=workflow_mode,
        question_id=question_id,
        student_id=student_id,
        saved_at=datetime.now(timezone.utc).isoformat(),
    )
    path = grading_session_path(workspace, assessment_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(
        checkpoint.to_dict(),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"

    temp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            temp_name = handle.name
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()

    return checkpoint


def load_grading_session_checkpoint(
    workspace: str,
    assessment_id: str,
) -> Optional[GradingSessionCheckpoint]:
    path = grading_session_path(workspace, assessment_id)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Unsafe grading-session checkpoint path: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checkpoint = GradingSessionCheckpoint.from_dict(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if checkpoint.assessment_id != str(assessment_id).strip():
        return None
    return checkpoint


def clear_grading_session_checkpoint(workspace: str, assessment_id: str) -> bool:
    path = grading_session_path(workspace, assessment_id)
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Unsafe grading-session checkpoint path: {path}")
    path.unlink()
    return True


__all__ = [
    "GRADING_SESSION_DIRNAME",
    "GRADING_SESSION_SCHEMA_VERSION",
    "QUESTION_CENTRIC_MODE",
    "GradingSessionCheckpoint",
    "clear_grading_session_checkpoint",
    "grading_session_path",
    "load_grading_session_checkpoint",
    "save_grading_session_checkpoint",
]
