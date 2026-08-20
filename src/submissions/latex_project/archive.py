"""Safe ZIP inspection and extraction for LaTeX project submissions.

The archive is treated as hostile input.  This module never calls
``ZipFile.extract``/``extractall`` and never executes or compiles extracted
content.  Member names and Unix file types are validated before any project
bytes are written, bounded resource limits are enforced from central-directory
metadata and again while streaming, and extracted files are created beneath a
fresh caller-supplied directory.
"""

from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path, PurePosixPath
import stat
import unicodedata
from typing import Optional, Tuple
import zipfile

from .config import LatexProjectIngestionConfig
from .errors import LatexProjectArchiveRejectedError, LatexProjectValidationError
from .models import (
    DIAGNOSTIC_BLOCKING,
    FILE_ROLE_BIBLIOGRAPHY,
    FILE_ROLE_DATA,
    FILE_ROLE_FIGURE,
    FILE_ROLE_OTHER,
    FILE_ROLE_STYLE,
    FILE_ROLE_TEX_SOURCE,
    LatexProjectDiagnostic,
    LatexProjectFile,
    LatexProjectManifest,
    normalize_project_relative_path,
)
from ..file_store import sha256_json


@dataclass(frozen=True)
class LatexArchiveExtractionSummary:
    """Portable summary returned after one successful safe extraction."""

    manifest: LatexProjectManifest
    zip_member_count: int
    regular_member_count: int
    ignored_members: Tuple[str, ...]


def _diagnostic(code, message, relative_path=None, metadata=None):
    return LatexProjectDiagnostic(
        code=code,
        message=message,
        severity=DIAGNOSTIC_BLOCKING,
        relative_path=relative_path,
        metadata=metadata or {},
    )


def _reject(code, message, relative_path=None, metadata=None):
    diagnostic = _diagnostic(
        code,
        message,
        relative_path=relative_path,
        metadata=metadata,
    )
    raise LatexProjectArchiveRejectedError(message, diagnostics=(diagnostic,))


_WINDOWS_RESERVED_BASENAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
_WINDOWS_INVALID_CHARS = set('<>:"|?*')


def _normalized_member_name(raw_name):
    try:
        relative_path = normalize_project_relative_path(raw_name, "ZIP member path")
    except LatexProjectValidationError as exc:
        _reject("unsafe_member_path", str(exc))
    for part in PurePosixPath(relative_path).parts:
        if any(ord(char) < 32 for char in part):
            _reject(
                "unsafe_member_path",
                "ZIP member path contains control characters: %s" % relative_path,
            )
        if any(char in _WINDOWS_INVALID_CHARS for char in part):
            _reject(
                "unsafe_member_path",
                "ZIP member path is not portable across supported filesystems: %s"
                % relative_path,
            )
        if part.endswith(".") or part.endswith(" "):
            _reject(
                "unsafe_member_path",
                "ZIP member path has a trailing dot/space component: %s"
                % relative_path,
            )
        basename = part.split(".", 1)[0].upper()
        if basename in _WINDOWS_RESERVED_BASENAMES:
            _reject(
                "unsafe_member_path",
                "ZIP member uses a reserved filesystem name: %s" % relative_path,
            )
    return relative_path


def _portable_path_key(relative_path):
    return "/".join(
        unicodedata.normalize("NFC", part).casefold()
        for part in PurePosixPath(relative_path).parts
    )


def _is_ignored(relative_path, config):
    path = PurePosixPath(relative_path)
    ignored_names = {item.casefold() for item in config.ignored_metadata_names}
    ignored_dirs = {item.casefold() for item in config.ignored_directory_names}
    if path.name.casefold() in ignored_names:
        return True
    return any(part.casefold() in ignored_dirs for part in path.parts[:-1])


def _unix_member_kind(info):
    """Return ``file``, ``dir``, ``link``, ``special`` or ``unknown``."""
    if info.is_dir():
        return "dir"
    if info.create_system != 3:
        return "file"
    mode = (info.external_attr >> 16) & 0xFFFF
    if not mode:
        return "file"
    kind = stat.S_IFMT(mode)
    if kind == stat.S_IFLNK:
        return "link"
    if kind == stat.S_IFDIR:
        return "dir"
    if kind in (0, stat.S_IFREG):
        return "file"
    return "special"


def _role_for_path(relative_path):
    suffix = PurePosixPath(relative_path).suffix.casefold()
    if suffix == ".tex":
        return FILE_ROLE_TEX_SOURCE
    if suffix == ".bib":
        return FILE_ROLE_BIBLIOGRAPHY
    if suffix in {".sty", ".cls", ".bst", ".bbx", ".cbx"}:
        return FILE_ROLE_STYLE
    if suffix in {
        ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".eps",
        ".ps", ".tif", ".tiff", ".bmp", ".webp",
    }:
        return FILE_ROLE_FIGURE
    if suffix in {
        ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".dat",
        ".txt",
    }:
        return FILE_ROLE_DATA
    return FILE_ROLE_OTHER


def _manifest_with_digest(project_id, files, metadata):
    ordered = tuple(sorted(files, key=lambda item: item.relative_path))
    base = LatexProjectManifest(
        project_id=project_id,
        files=ordered,
        total_uncompressed_bytes=sum(item.size_bytes for item in ordered),
        manifest_sha256=None,
        metadata=metadata,
    )
    payload = base.to_dict()
    payload["manifest_sha256"] = None
    digest = sha256_json(payload)
    return LatexProjectManifest(
        project_id=base.project_id,
        files=base.files,
        total_uncompressed_bytes=base.total_uncompressed_bytes,
        manifest_sha256=digest,
        metadata=base.metadata,
    )


def compute_manifest_sha256(manifest):
    """Recompute the deterministic digest used by ``LatexProjectManifest``."""
    payload = manifest.to_dict()
    payload["manifest_sha256"] = None
    return sha256_json(payload)


def _validate_member_table(infos, config):
    limits = config.limits
    seen = {}
    file_paths = set()
    regular_count = 0
    total_uncompressed = 0
    normalized = []

    for info in infos:
        relative_path = _normalized_member_name(info.filename)
        key = _portable_path_key(relative_path)
        if key in seen:
            _reject(
                "duplicate_member_path",
                "ZIP contains duplicate or case-colliding member paths: %s and %s"
                % (seen[key], relative_path),
                relative_path=relative_path,
            )
        seen[key] = relative_path

        kind = _unix_member_kind(info)
        if kind == "link":
            _reject(
                "archive_link_rejected",
                "ZIP links are not accepted: %s" % relative_path,
                relative_path=relative_path,
            )
        if kind == "special":
            _reject(
                "archive_special_file_rejected",
                "ZIP special files are not accepted: %s" % relative_path,
                relative_path=relative_path,
            )
        if info.flag_bits & 0x1:
            _reject(
                "encrypted_member_rejected",
                "Encrypted ZIP members are not accepted: %s" % relative_path,
                relative_path=relative_path,
            )

        # A regular file cannot also be an ancestor of another member.  Catch
        # this before extraction so the result is deterministic on all hosts.
        parents = PurePosixPath(relative_path).parents
        for parent in parents:
            parent_text = str(parent)
            if parent_text == ".":
                continue
            if _portable_path_key(parent_text) in file_paths:
                _reject(
                    "file_directory_conflict",
                    "ZIP member is nested beneath a regular-file path: %s"
                    % relative_path,
                    relative_path=relative_path,
                )
        if kind == "file":
            prefix = relative_path.casefold() + "/"
            if any(existing.startswith(prefix) for existing in seen if existing != key):
                _reject(
                    "file_directory_conflict",
                    "ZIP regular file conflicts with an existing directory path: %s"
                    % relative_path,
                    relative_path=relative_path,
                )
            file_paths.add(key)
            regular_count += 1
            if regular_count > limits.max_file_count:
                _reject(
                    "file_count_limit_exceeded",
                    "ZIP contains more than %d regular files" % limits.max_file_count,
                    metadata={"limit": limits.max_file_count},
                )
            if info.file_size < 0 or info.compress_size < 0:
                _reject(
                    "invalid_member_size",
                    "ZIP member declares an invalid size: %s" % relative_path,
                    relative_path=relative_path,
                )
            if info.file_size > limits.max_member_bytes:
                _reject(
                    "member_size_limit_exceeded",
                    "ZIP member exceeds the %d-byte limit: %s"
                    % (limits.max_member_bytes, relative_path),
                    relative_path=relative_path,
                    metadata={
                        "declared_size_bytes": info.file_size,
                        "limit": limits.max_member_bytes,
                    },
                )
            total_uncompressed += info.file_size
            if total_uncompressed > limits.max_total_uncompressed_bytes:
                _reject(
                    "total_size_limit_exceeded",
                    "ZIP declared uncompressed size exceeds the %d-byte limit"
                    % limits.max_total_uncompressed_bytes,
                    metadata={
                        "declared_total_uncompressed_bytes": total_uncompressed,
                        "limit": limits.max_total_uncompressed_bytes,
                    },
                )
            if info.file_size:
                if info.compress_size <= 0:
                    ratio = float("inf")
                else:
                    ratio = float(info.file_size) / float(info.compress_size)
                if ratio > limits.max_compression_ratio:
                    _reject(
                        "compression_ratio_limit_exceeded",
                        "ZIP member exceeds the %.1fx compression-ratio limit: %s"
                        % (limits.max_compression_ratio, relative_path),
                        relative_path=relative_path,
                        metadata={
                            "compression_ratio": ratio,
                            "limit": limits.max_compression_ratio,
                        },
                    )

        normalized.append((info, relative_path, kind))

    return normalized, regular_count


def safe_extract_latex_project_zip(
    archive_path,
    destination,
    project_id,
    config=None,
    chunk_size=1024 * 1024,
):
    """Safely extract one ZIP into an empty destination and return its manifest.

    The caller owns persistence/transactionality.  ``destination`` must not be
    a symlink and must be empty when this function starts.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if config is None:
        config = LatexProjectIngestionConfig()
    elif not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig")

    archive = Path(archive_path).expanduser()
    if archive.is_symlink():
        _reject("archive_symlink_rejected", "Symlinked ZIP archives are not accepted")
    archive = archive.resolve()
    if not archive.exists() or not archive.is_file():
        raise FileNotFoundError(str(archive))
    archive_size = archive.stat().st_size
    if archive_size > config.limits.max_archive_bytes:
        _reject(
            "archive_size_limit_exceeded",
            "ZIP archive exceeds the %d-byte limit" % config.limits.max_archive_bytes,
            metadata={
                "archive_size_bytes": archive_size,
                "limit": config.limits.max_archive_bytes,
            },
        )

    output = Path(destination).expanduser()
    if output.is_symlink():
        _reject("destination_symlink_rejected", "Extraction destination must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("extraction destination must be empty")

    try:
        zf = zipfile.ZipFile(str(archive), mode="r")
    except (zipfile.BadZipFile, OSError) as exc:
        _reject("invalid_zip", "Invalid ZIP archive: %s" % exc)

    try:
        infos = zf.infolist()
        normalized, regular_count = _validate_member_table(infos, config)
        files = []
        ignored = []
        actual_total = 0

        for info, relative_path, kind in normalized:
            if kind == "dir":
                continue
            if _is_ignored(relative_path, config):
                ignored.append(relative_path)
                continue

            target = output.joinpath(*PurePosixPath(relative_path).parts)
            # Parents are created by us beneath a fresh temporary root.  We do
            # not preserve archive permissions/executable bits.
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or target.exists():
                _reject(
                    "extraction_path_conflict",
                    "Extraction target already exists: %s" % relative_path,
                    relative_path=relative_path,
                )

            digest = hashlib.sha256()
            member_written = 0
            try:
                source = zf.open(info, mode="r")
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                _reject(
                    "member_open_failed",
                    "Could not read ZIP member %s: %s" % (relative_path, exc),
                    relative_path=relative_path,
                )

            try:
                with source, target.open("xb") as handle:
                    while True:
                        try:
                            block = source.read(chunk_size)
                        except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                            _reject(
                                "member_read_failed",
                                "Could not read ZIP member %s: %s"
                                % (relative_path, exc),
                                relative_path=relative_path,
                            )
                        if not block:
                            break
                        member_written += len(block)
                        actual_total += len(block)
                        if member_written > config.limits.max_member_bytes:
                            _reject(
                                "member_size_limit_exceeded",
                                "Extracted ZIP member exceeds the %d-byte limit: %s"
                                % (config.limits.max_member_bytes, relative_path),
                                relative_path=relative_path,
                            )
                        if actual_total > config.limits.max_total_uncompressed_bytes:
                            _reject(
                                "total_size_limit_exceeded",
                                "Extracted ZIP bytes exceed the %d-byte limit"
                                % config.limits.max_total_uncompressed_bytes,
                            )
                        digest.update(block)
                        handle.write(block)
            except LatexProjectArchiveRejectedError:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise
            except OSError as exc:
                try:
                    target.unlink()
                except OSError:
                    pass
                _reject(
                    "member_write_failed",
                    "Could not materialize ZIP member %s: %s"
                    % (relative_path, exc),
                    relative_path=relative_path,
                )

            if member_written != info.file_size:
                _reject(
                    "member_size_mismatch",
                    "ZIP member size changed while reading: %s" % relative_path,
                    relative_path=relative_path,
                    metadata={
                        "declared_size_bytes": info.file_size,
                        "actual_size_bytes": member_written,
                    },
                )

            media_type = mimetypes.guess_type(relative_path)[0]
            files.append(
                LatexProjectFile(
                    relative_path=relative_path,
                    size_bytes=member_written,
                    sha256=digest.hexdigest(),
                    role=_role_for_path(relative_path),
                    media_type=media_type,
                    metadata={
                        "zip_compressed_bytes": info.compress_size,
                        "zip_crc32": "%08x" % info.CRC,
                    },
                )
            )

        manifest = _manifest_with_digest(
            project_id,
            files,
            metadata={
                "zip_member_count": len(infos),
                "regular_member_count": regular_count,
                "ignored_members": sorted(ignored),
            },
        )
        return LatexArchiveExtractionSummary(
            manifest=manifest,
            zip_member_count=len(infos),
            regular_member_count=regular_count,
            ignored_members=tuple(sorted(ignored)),
        )
    finally:
        zf.close()


__all__ = [
    "LatexArchiveExtractionSummary",
    "compute_manifest_sha256",
    "safe_extract_latex_project_zip",
]
