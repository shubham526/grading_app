"""Execution-workspace planning primitives for v2.3.3 Commit 3.

This module describes *what* an isolated backend will receive later.  It does
not create temporary directories, copy student code, invoke pytest, or execute
anything.  Source paths are verified immutable inputs owned by the canonical
submission repository or immutable test-bundle store.

The eventual backend will materialize this logical layout::

    /workspace/
        submission/   # exact canonical student artifacts, read-only input
        grader/       # exact immutable instructor bundle, read-only input
        output/       # backend-owned writable result channel

Commit 3 therefore gives Commit 4/5 a deterministic, inspectable contract while
keeping execution completely absent from the current release slice.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Mapping, Sequence, Tuple

from .errors import ExecutionPlanValidationError


EXECUTION_WORKSPACE_SCHEMA_VERSION = "1.0"

WORKSPACE_NAMESPACE_SUBMISSION = "submission"
WORKSPACE_NAMESPACE_GRADER = "grader"
WORKSPACE_NAMESPACES = (
    WORKSPACE_NAMESPACE_SUBMISSION,
    WORKSPACE_NAMESPACE_GRADER,
)

SUBMISSION_DIRECTORY = "submission"
GRADER_DIRECTORY = "grader"
OUTPUT_DIRECTORY = "output"


def _text(value: Any, name: str) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        raise ExecutionPlanValidationError("%s must not be empty" % name)
    return value


def _sha256(value: Any, name: str = "sha256") -> str:
    digest = _text(value, name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ExecutionPlanValidationError(
            "%s must be a 64-character hexadecimal SHA-256 digest" % name
        )
    return digest


def normalize_workspace_relative_path(value: Any, name: str = "path") -> str:
    """Return a safe normalized POSIX path relative to one workspace namespace.

    The same rules are used for canonical programming logical paths and grader
    bundle paths.  Windows separators are normalized so a future container
    receives one portable path vocabulary regardless of the host platform.
    """

    raw = _text(value, name).replace("\\", "/")
    windows = PureWindowsPath(raw)
    if windows.drive or windows.root:
        raise ExecutionPlanValidationError("%s must be relative" % name)

    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ExecutionPlanValidationError("%s must be relative" % name)

    parts = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ExecutionPlanValidationError("%s must not contain '..'" % name)
        if "\x00" in part:
            raise ExecutionPlanValidationError("%s must not contain NUL bytes" % name)
        parts.append(part)

    if not parts:
        raise ExecutionPlanValidationError("%s must not be empty" % name)

    normalized = PurePosixPath(*parts).as_posix()
    if normalized.startswith("../") or normalized == "..":
        raise ExecutionPlanValidationError("%s escapes its workspace namespace" % name)
    return normalized


def _verified_source_path(value: Any, name: str = "source_path") -> str:
    requested = Path(_text(value, name)).expanduser()
    if requested.is_symlink():
        raise ExecutionPlanValidationError(
            "Symlinked execution-plan source files are not accepted: %s" % requested
        )
    resolved = requested.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ExecutionPlanValidationError(
            "Execution-plan source file does not exist: %s" % resolved
        )
    return str(resolved)


@dataclass(frozen=True)
class PlannedWorkspaceFile:
    """One exact immutable file that a future backend will mount/copy read-only."""

    namespace: str
    logical_path: str
    source_path: str
    sha256: str
    size_bytes: int
    source_id: str
    read_only: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        namespace = _text(self.namespace, "namespace").lower()
        if namespace not in WORKSPACE_NAMESPACES:
            raise ExecutionPlanValidationError(
                "namespace must be one of: %s" % ", ".join(WORKSPACE_NAMESPACES)
            )
        logical_path = normalize_workspace_relative_path(
            self.logical_path,
            "logical_path",
        )
        source_path = _verified_source_path(self.source_path)
        digest = _sha256(self.sha256)
        if isinstance(self.size_bytes, bool):
            raise ExecutionPlanValidationError("size_bytes must be an integer")
        try:
            size = int(self.size_bytes)
        except (TypeError, ValueError):
            raise ExecutionPlanValidationError("size_bytes must be an integer")
        if size < 0:
            raise ExecutionPlanValidationError("size_bytes must be non-negative")
        actual_size = Path(source_path).stat().st_size
        if actual_size != size:
            raise ExecutionPlanValidationError(
                "source file size changed while planning %s: expected %d, found %d"
                % (logical_path, size, actual_size)
            )
        source_id = _text(self.source_id, "source_id")
        if self.read_only is not True:
            raise ExecutionPlanValidationError(
                "planned input files must be read_only=True"
            )
        if not isinstance(self.metadata, Mapping):
            raise ExecutionPlanValidationError("metadata must be a mapping")

        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "logical_path", logical_path)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @property
    def destination_relative_path(self) -> str:
        root = (
            SUBMISSION_DIRECTORY
            if self.namespace == WORKSPACE_NAMESPACE_SUBMISSION
            else GRADER_DIRECTORY
        )
        return PurePosixPath(root, self.logical_path).as_posix()

    def to_dict(self, *, include_source_path: bool = True) -> Dict[str, Any]:
        payload = {
            "namespace": self.namespace,
            "logical_path": self.logical_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_id": self.source_id,
            "read_only": self.read_only,
            "metadata": deepcopy(self.metadata),
        }
        if include_source_path:
            payload["source_path"] = self.source_path
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlannedWorkspaceFile":
        if not isinstance(data, Mapping):
            raise ExecutionPlanValidationError(
                "PlannedWorkspaceFile data must be a mapping"
            )
        return cls(
            namespace=data.get("namespace"),
            logical_path=data.get("logical_path"),
            source_path=data.get("source_path"),
            sha256=data.get("sha256"),
            size_bytes=data.get("size_bytes"),
            source_id=data.get("source_id"),
            read_only=data.get("read_only", True),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ExecutionWorkspaceSpec:
    """Validated logical workspace for one future isolated grading run."""

    submission_files: Tuple[PlannedWorkspaceFile, ...]
    grader_files: Tuple[PlannedWorkspaceFile, ...]
    entrypoint: str
    output_directory: str = OUTPUT_DIRECTORY
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        submission_files = tuple(self.submission_files or ())
        grader_files = tuple(self.grader_files or ())
        if not submission_files:
            raise ExecutionPlanValidationError(
                "submission_files must contain at least one file"
            )
        if not grader_files:
            raise ExecutionPlanValidationError(
                "grader_files must contain at least one file"
            )
        if any(not isinstance(item, PlannedWorkspaceFile) for item in submission_files):
            raise ExecutionPlanValidationError(
                "submission_files must contain PlannedWorkspaceFile objects"
            )
        if any(not isinstance(item, PlannedWorkspaceFile) for item in grader_files):
            raise ExecutionPlanValidationError(
                "grader_files must contain PlannedWorkspaceFile objects"
            )
        if any(
            item.namespace != WORKSPACE_NAMESPACE_SUBMISSION
            for item in submission_files
        ):
            raise ExecutionPlanValidationError(
                "submission_files must use the submission namespace"
            )
        if any(item.namespace != WORKSPACE_NAMESPACE_GRADER for item in grader_files):
            raise ExecutionPlanValidationError(
                "grader_files must use the grader namespace"
            )

        self._validate_unique_paths(submission_files, "submission")
        self._validate_unique_paths(grader_files, "grader")

        entrypoint = normalize_workspace_relative_path(self.entrypoint, "entrypoint")
        submission_paths = {item.logical_path for item in submission_files}
        if entrypoint not in submission_paths:
            raise ExecutionPlanValidationError(
                "entrypoint %r is not present in submission files" % entrypoint
            )

        output_directory = normalize_workspace_relative_path(
            self.output_directory,
            "output_directory",
        )
        if "/" in output_directory:
            raise ExecutionPlanValidationError(
                "output_directory must be one top-level workspace directory name"
            )
        if output_directory.casefold() in {
            SUBMISSION_DIRECTORY.casefold(),
            GRADER_DIRECTORY.casefold(),
        }:
            raise ExecutionPlanValidationError(
                "output_directory conflicts with a read-only workspace namespace"
            )
        if not isinstance(self.metadata, Mapping):
            raise ExecutionPlanValidationError("metadata must be a mapping")

        object.__setattr__(self, "submission_files", submission_files)
        object.__setattr__(self, "grader_files", grader_files)
        object.__setattr__(self, "entrypoint", entrypoint)
        object.__setattr__(self, "output_directory", output_directory)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    @staticmethod
    def _validate_unique_paths(
        files: Sequence[PlannedWorkspaceFile],
        label: str,
    ) -> None:
        seen = {}
        for item in files:
            folded = item.logical_path.casefold()
            previous = seen.get(folded)
            if previous is not None:
                raise ExecutionPlanValidationError(
                    "%s workspace has a case-insensitive path collision: %r and %r"
                    % (label, previous, item.logical_path)
                )
            seen[folded] = item.logical_path

    @property
    def entrypoint_file(self) -> PlannedWorkspaceFile:
        for item in self.submission_files:
            if item.logical_path == self.entrypoint:
                return item
        raise ExecutionPlanValidationError("entrypoint file is missing")

    def to_dict(self, *, include_source_paths: bool = True) -> Dict[str, Any]:
        return {
            "schema_version": EXECUTION_WORKSPACE_SCHEMA_VERSION,
            "submission_directory": SUBMISSION_DIRECTORY,
            "grader_directory": GRADER_DIRECTORY,
            "output_directory": self.output_directory,
            "entrypoint": self.entrypoint,
            "submission_files": [
                item.to_dict(include_source_path=include_source_paths)
                for item in self.submission_files
            ],
            "grader_files": [
                item.to_dict(include_source_path=include_source_paths)
                for item in self.grader_files
            ],
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionWorkspaceSpec":
        if not isinstance(data, Mapping):
            raise ExecutionPlanValidationError(
                "ExecutionWorkspaceSpec data must be a mapping"
            )
        version = data.get("schema_version")
        if version is not None and str(version) != EXECUTION_WORKSPACE_SCHEMA_VERSION:
            raise ExecutionPlanValidationError(
                "Unsupported execution-workspace schema %r; expected %r"
                % (version, EXECUTION_WORKSPACE_SCHEMA_VERSION)
            )
        return cls(
            submission_files=tuple(
                PlannedWorkspaceFile.from_dict(item)
                for item in (data.get("submission_files") or ())
            ),
            grader_files=tuple(
                PlannedWorkspaceFile.from_dict(item)
                for item in (data.get("grader_files") or ())
            ),
            entrypoint=data.get("entrypoint"),
            output_directory=data.get("output_directory", OUTPUT_DIRECTORY),
            metadata=data.get("metadata", {}),
        )


__all__ = [
    "EXECUTION_WORKSPACE_SCHEMA_VERSION",
    "ExecutionWorkspaceSpec",
    "GRADER_DIRECTORY",
    "OUTPUT_DIRECTORY",
    "PlannedWorkspaceFile",
    "SUBMISSION_DIRECTORY",
    "WORKSPACE_NAMESPACE_GRADER",
    "WORKSPACE_NAMESPACE_SUBMISSION",
    "WORKSPACE_NAMESPACES",
    "normalize_workspace_relative_path",
]
