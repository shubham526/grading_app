"""
Generic hardened filesystem helpers for submission persistence.

v2.3.2 Commit 2 extracts the reusable file primitives that were previously
embedded in ``submissions.storage`` so both the legacy v2.2 evidence store and
the new canonical submission repository use the same hashing, symlink
rejection, atomic-write, and safe-copy behavior.

This module has no PyQt dependency and contains no grading logic.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._@+-]+")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._@+() -]+")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes suitable for hashing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    """Return SHA-256 for a canonical JSON serialization."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def reject_symlink(path: Path, label: str = "path") -> None:
    """Reject an existing path whose final component is a symlink."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Symlinked {label} is not accepted: {path}")


def _ensure_regular_source(path: str) -> Path:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked files are not accepted: {requested}")
    source = requested.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    return source


def compute_file_sha256(
    path: str,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Compute SHA-256 for a regular, non-symlink file."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    source = _ensure_regular_source(path)
    digest = hashlib.sha256()

    with source.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)

    return digest.hexdigest()


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    overwrite: bool = True,
) -> None:
    """Atomically write bytes into a non-symlinked output directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink(target.parent, "output directory")
    if target.is_symlink():
        raise ValueError(f"Symlinked output files are not accepted: {target}")

    if target.exists() and not overwrite:
        raise FileExistsError(str(target))

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=str(target.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        if target.exists() and not overwrite:
            raise FileExistsError(str(target))

        os.replace(str(temp_path), str(target))
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    overwrite: bool = True,
) -> None:
    """Atomically write pretty, deterministic UTF-8 JSON."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"

    atomic_write_bytes(
        Path(path),
        payload,
        overwrite=overwrite,
    )


def atomic_write_text(
    path: Path,
    text: str,
    *,
    overwrite: bool = True,
) -> None:
    """Atomically write UTF-8 text."""
    atomic_write_bytes(
        Path(path),
        str(text).encode("utf-8"),
        overwrite=overwrite,
    )


def read_json_object(path: Path) -> dict:
    """Read a JSON file and require an object at its root."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Symlinked JSON files are not accepted: {path}")

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON file: {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in file: {path}")

    return value


def copy_regular_file(
    source_path: str,
    target: Path,
    *,
    overwrite: bool = False,
) -> str:
    """
    Copy one regular non-symlink file through a temporary sibling.

    ``overwrite=False`` is the safe default for immutable canonical artifacts.
    The legacy v2.2 evidence store explicitly passes ``overwrite=True`` because
    it historically refreshes its one-per-student derived evidence files.
    """
    source = _ensure_regular_source(source_path)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink(target.parent, "output directory")
    if target.is_symlink():
        raise ValueError(f"Symlinked output files are not accepted: {target}")

    try:
        if source == target.resolve():
            return str(target.resolve())
    except FileNotFoundError:
        pass

    if target.exists() and not overwrite:
        raise FileExistsError(str(target))

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=str(target.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        shutil.copy2(str(source), str(temp_path))

        if target.exists() and not overwrite:
            raise FileExistsError(str(target))

        os.replace(str(temp_path), str(target))
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return str(target.resolve())


def safe_path_component(value: object, *, max_slug_chars: int = 64) -> str:
    """
    Return a deterministic path-safe component without using it as identity.

    The original ID remains stored in manifests/indexes.  A short SHA-256 suffix
    prevents collisions caused by normalization and case-insensitive filesystems.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        raise ValueError("path component must not be empty")

    slug = _SAFE_COMPONENT_RE.sub("_", raw).strip(" ._")
    if not slug:
        slug = "id"
    slug = slug[:max_slug_chars]

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{slug}__{digest}"


def safe_storage_filename(value: object, *, fallback: str = "artifact") -> str:
    """Return a display-friendly safe basename for canonical artifact storage."""
    raw = "" if value is None else str(value).strip()
    # Path(...).name on POSIX does not strip a backslash-based Windows path, so
    # normalize both separator styles first.
    raw = raw.replace("\\", "/")
    basename = raw.rsplit("/", 1)[-1].strip()

    if basename in {"", ".", ".."}:
        basename = fallback

    cleaned = _SAFE_FILENAME_RE.sub("_", basename)
    cleaned = cleaned.strip(" .")

    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback

    # Avoid pathological path lengths while preserving the suffix when possible.
    if len(cleaned) > 180:
        suffix = Path(cleaned).suffix[:20]
        stem = cleaned[:-len(suffix)] if suffix else cleaned
        stem_limit = max(1, 180 - len(suffix))
        cleaned = stem[:stem_limit] + suffix

    return cleaned


__all__ = [
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "canonical_json_bytes",
    "compute_file_sha256",
    "copy_regular_file",
    "read_json_object",
    "reject_symlink",
    "safe_path_component",
    "safe_storage_filename",
    "sha256_json",
]
