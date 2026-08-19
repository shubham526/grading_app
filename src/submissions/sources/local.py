"""Local-file submission source adapter for v2.3.2 Commit 3.

The adapter discovers incoming files and groups them into logical import
candidates.  It does not choose a grading parser and does not persist anything;
that work belongs to later layers.

Supported local layouts:

* explicitly selected files;
* a flat directory such as ``alice.tex`` + ``alice.pdf``;
* immediate student subdirectories, where all top-level regular files in one
  child directory are treated as one logical candidate.

Student identity is only hinted from filenames/directory names.  The importer
performs conservative matching against ``core.roster.StudentRecord`` objects.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..domain import (
    ARTIFACT_ROLE_ATTACHMENT,
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_ROLE_RENDERED,
    ARTIFACT_ROLE_SOURCE,
    ARTIFACT_TYPE_DOCX,
    ARTIFACT_TYPE_IMAGE,
    ARTIFACT_TYPE_PDF,
    ARTIFACT_TYPE_PYTHON,
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_TEXT,
    ARTIFACT_TYPE_UNKNOWN,
    ARTIFACT_TYPE_ZIP,
    MATCH_STATUS_UNMATCHED,
    SOURCE_SYSTEM_LOCAL_UPLOAD,
    VALIDATION_STATUS_PENDING,
    CandidateFile,
    ImportCandidate,
    generate_candidate_id,
)
from ..file_store import compute_file_sha256


_TYPE_BY_SUFFIX = {
    ".pdf": ARTIFACT_TYPE_PDF,
    ".tex": ARTIFACT_TYPE_TEX,
    ".py": ARTIFACT_TYPE_PYTHON,
    ".zip": ARTIFACT_TYPE_ZIP,
    ".docx": ARTIFACT_TYPE_DOCX,
    ".txt": ARTIFACT_TYPE_TEXT,
    ".md": ARTIFACT_TYPE_TEXT,
    ".markdown": ARTIFACT_TYPE_TEXT,
    ".png": ARTIFACT_TYPE_IMAGE,
    ".jpg": ARTIFACT_TYPE_IMAGE,
    ".jpeg": ARTIFACT_TYPE_IMAGE,
    ".webp": ARTIFACT_TYPE_IMAGE,
}

_SOURCE_TYPES = {
    ARTIFACT_TYPE_TEX,
    ARTIFACT_TYPE_ZIP,
}


def _artifact_type(path: Path) -> str:
    return _TYPE_BY_SUFFIX.get(path.suffix.casefold(), ARTIFACT_TYPE_UNKNOWN)


def _role_for(
    artifact_type: str,
    *,
    has_source_artifact: bool,
    multi_file: bool,
) -> str:
    if artifact_type in _SOURCE_TYPES:
        return ARTIFACT_ROLE_SOURCE
    if artifact_type == ARTIFACT_TYPE_PDF and has_source_artifact:
        return ARTIFACT_ROLE_RENDERED
    if artifact_type == ARTIFACT_TYPE_UNKNOWN and multi_file:
        return ARTIFACT_ROLE_ATTACHMENT
    return ARTIFACT_ROLE_PRIMARY


def _validate_local_path(path: Path) -> Path:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked local submission files are not accepted: {requested}")
    resolved = requested.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def _candidate_files(paths: Sequence[Path]) -> Tuple[List[CandidateFile], List[str]]:
    resolved_paths: List[Path] = []
    warnings: List[str] = []

    for path in paths:
        resolved = _validate_local_path(path)
        resolved_paths.append(resolved)

    types = [_artifact_type(path) for path in resolved_paths]
    has_source = any(value in _SOURCE_TYPES for value in types)
    multi_file = len(resolved_paths) > 1

    files: List[CandidateFile] = []
    for path, artifact_type in zip(resolved_paths, types):
        size_bytes = path.stat().st_size
        sha256 = compute_file_sha256(str(path))
        role = _role_for(
            artifact_type,
            has_source_artifact=has_source,
            multi_file=multi_file,
        )

        if artifact_type == ARTIFACT_TYPE_UNKNOWN:
            warnings.append(f"unknown_artifact_type:{path.name}")

        files.append(
            CandidateFile(
                source_path=str(path),
                original_filename=path.name,
                artifact_type=artifact_type,
                role=role,
                size_bytes=size_bytes,
                sha256=sha256,
                metadata={
                    "local_parent": str(path.parent),
                    "local_suffix": path.suffix.casefold(),
                },
            )
        )

    files.sort(key=lambda item: (item.original_filename.casefold(), item.source_path))
    return files, list(dict.fromkeys(warnings))


def _make_candidate(
    paths: Sequence[Path],
    *,
    identity_hints: Sequence[str],
    source_locator: str,
    assessment_id: Optional[str],
    grouping: str,
) -> ImportCandidate:
    candidate_files, warnings = _candidate_files(paths)
    hints = [str(value).strip() for value in identity_hints if str(value).strip()]

    return ImportCandidate(
        candidate_id=generate_candidate_id(),
        source_system=SOURCE_SYSTEM_LOCAL_UPLOAD,
        source_locator=source_locator,
        proposed_assessment_id=assessment_id,
        files=candidate_files,
        match_status=MATCH_STATUS_UNMATCHED,
        validation_status=VALIDATION_STATUS_PENDING,
        warnings=warnings,
        metadata={
            "identity_hints": list(dict.fromkeys(hints)),
            "grouping": grouping,
        },
    )


def _group_flat_paths(paths: Sequence[Path]) -> List[Tuple[str, List[Path]]]:
    """Group same-parent/same-stem files into one logical candidate."""
    grouped: Dict[Tuple[str, str], List[Path]] = {}

    for path in paths:
        requested = Path(path).expanduser()
        # Resolve the parent without following a potentially symlinked file.  The
        # actual file validation happens when the candidate is materialized.
        parent = requested.parent.resolve()
        key = (str(parent), requested.stem.casefold())
        grouped.setdefault(key, []).append(requested)

    results: List[Tuple[str, List[Path]]] = []
    for (_, stem), group in sorted(grouped.items(), key=lambda item: item[0]):
        results.append((stem, sorted(group, key=lambda p: p.name.casefold())))
    return results


def discover_local_files(
    file_paths: Sequence[str],
    *,
    assessment_id: Optional[str] = None,
) -> List[ImportCandidate]:
    """Discover explicitly selected files, pairing same-stem sibling formats."""
    if isinstance(file_paths, (str, bytes)):
        raise TypeError("file_paths must be a sequence of paths, not a single string")

    paths = [Path(value).expanduser() for value in file_paths]
    if not paths:
        return []

    candidates: List[ImportCandidate] = []
    for stem, group in _group_flat_paths(paths):
        source_locator = str(group[0].parent.resolve())
        candidates.append(
            _make_candidate(
                group,
                identity_hints=[stem],
                source_locator=source_locator,
                assessment_id=assessment_id,
                grouping="same_stem_files",
            )
        )

    return candidates


def discover_local_directory(
    directory: str,
    *,
    assessment_id: Optional[str] = None,
    include_student_subdirectories: bool = True,
) -> List[ImportCandidate]:
    """Discover candidates from a flat directory and immediate child folders."""
    requested = Path(directory).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked submission directories are not accepted: {requested}")
    root = requested.resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    candidates: List[ImportCandidate] = []

    flat_files = sorted(
        [
            child
            for child in root.iterdir()
            if child.is_file()
            and not child.is_symlink()
            and not child.name.startswith(".")
        ],
        key=lambda path: path.name.casefold(),
    )
    if flat_files:
        candidates.extend(
            discover_local_files(
                [str(path) for path in flat_files],
                assessment_id=assessment_id,
            )
        )

    if include_student_subdirectories:
        for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if (
                not child.is_dir()
                or child.is_symlink()
                or child.name.startswith(".")
            ):
                continue

            files = sorted(
                [
                    path
                    for path in child.iterdir()
                    if path.is_file()
                    and not path.is_symlink()
                    and not path.name.startswith(".")
                ],
                key=lambda path: path.name.casefold(),
            )
            if not files:
                continue

            candidates.append(
                _make_candidate(
                    files,
                    identity_hints=[child.name],
                    source_locator=str(child.resolve()),
                    assessment_id=assessment_id,
                    grouping="student_directory",
                )
            )

    return candidates


class LocalFileSourceAdapter:
    """Configured local source implementing ``SubmissionSourceAdapter``."""

    source_system = SOURCE_SYSTEM_LOCAL_UPLOAD

    def __init__(
        self,
        *,
        file_paths: Optional[Sequence[str]] = None,
        directory: Optional[str] = None,
        include_student_subdirectories: bool = True,
    ) -> None:
        if file_paths is not None and directory is not None:
            raise ValueError("Specify file_paths or directory, not both")
        if file_paths is None and directory is None:
            raise ValueError("file_paths or directory is required")
        if isinstance(file_paths, (str, bytes)):
            raise TypeError("file_paths must be a sequence of paths")

        self._file_paths = list(file_paths) if file_paths is not None else None
        self._directory = str(directory) if directory is not None else None
        self._include_student_subdirectories = bool(include_student_subdirectories)

    @classmethod
    def from_files(cls, file_paths: Sequence[str]) -> "LocalFileSourceAdapter":
        return cls(file_paths=file_paths)

    @classmethod
    def from_directory(
        cls,
        directory: str,
        *,
        include_student_subdirectories: bool = True,
    ) -> "LocalFileSourceAdapter":
        return cls(
            directory=directory,
            include_student_subdirectories=include_student_subdirectories,
        )

    def discover(
        self,
        *,
        assessment_id: Optional[str] = None,
    ) -> List[ImportCandidate]:
        if self._file_paths is not None:
            return discover_local_files(
                self._file_paths,
                assessment_id=assessment_id,
            )

        return discover_local_directory(
            self._directory or "",
            assessment_id=assessment_id,
            include_student_subdirectories=self._include_student_subdirectories,
        )

    def fetch(self, candidate: ImportCandidate) -> List[CandidateFile]:
        """Re-stat/re-hash candidate files immediately before repository commit."""
        if not isinstance(candidate, ImportCandidate):
            raise TypeError("candidate must be ImportCandidate")
        if candidate.source_system != self.source_system:
            raise ValueError(
                f"Candidate source {candidate.source_system!r} does not belong to "
                f"{self.source_system!r}"
            )

        refreshed: List[CandidateFile] = []
        for existing in candidate.files:
            path = _validate_local_path(Path(existing.source_path))
            size_bytes = path.stat().st_size
            sha256 = compute_file_sha256(str(path))

            # The previewed candidate is evidence of what the instructor chose.
            # Do not silently commit different bytes if the source file changes
            # between preview and commit.
            if existing.size_bytes is not None and existing.size_bytes != size_bytes:
                raise ValueError(
                    f"Local source changed after discovery: "
                    f"{existing.original_filename!r} size "
                    f"{existing.size_bytes} -> {size_bytes}"
                )
            if existing.sha256 is not None and existing.sha256 != sha256:
                raise ValueError(
                    f"Local source changed after discovery: "
                    f"{existing.original_filename!r} SHA-256 mismatch"
                )

            refreshed.append(
                CandidateFile(
                    source_path=str(path),
                    original_filename=existing.original_filename,
                    artifact_type=existing.artifact_type,
                    role=existing.role,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    metadata=deepcopy(existing.metadata),
                )
            )
        return refreshed


__all__ = [
    "LocalFileSourceAdapter",
    "discover_local_directory",
    "discover_local_files",
]
