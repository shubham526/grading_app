"""Persistent submission-evidence storage and transcription caching.

The grading UI is intentionally not involved here.  This module gives the
submission backend a stable on-disk evidence layout so a parsed submission can
be reopened without re-rendering or re-running a vision model.  It also records
provenance needed to decide whether a cached transcription is still valid.

Security / evidence invariants:

* accommodation PDFs remain authoritative; machine transcription is assistive;
* no accommodation reason or medical/disability information is accepted;
* SHA-256 hashes are evidence/provenance only and never affect scoring;
* persisted paths are kept under a normalized per-student directory;
* JSON/text writes are atomic, and symlinked evidence roots/student directories
  are rejected.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .matcher import normalize_student_id
from .models import ParsedSubmission, SUBMISSION_MODE_PDF_ACCOMMODATION
from .transcription import TranscriptionBackend, TranscriptionBatchResult


EVIDENCE_SCHEMA_VERSION = "1.0"
TRANSCRIPTION_CACHE_SCHEMA_VERSION = "1.0"

SUBMISSION_META_FILENAME = "submission_meta.json"
EXTRACTED_ANSWERS_FILENAME = "extracted_answers.json"
RAW_TEXT_FILENAME = "raw_text.txt"
TRANSCRIPTION_FILENAME = "transcription.json"
TRANSCRIPTION_CACHE_FILENAME = "transcription_cache.json"


@dataclass(frozen=True)
class EvidenceStoragePaths:
    """Stable paths for one student's persisted submission evidence."""

    storage_root: str
    student_dir: str
    source_dir: str
    pages_dir: str
    compiled_dir: str
    meta_path: str
    answers_path: str
    raw_text_path: str
    transcription_path: str
    transcription_cache_path: str

    def to_metadata(self) -> Dict[str, str]:
        return {
            "storage_root": self.storage_root,
            "student_dir": self.student_dir,
            "source_dir": self.source_dir,
            "pages_dir": self.pages_dir,
            "compiled_dir": self.compiled_dir,
            "meta_path": self.meta_path,
            "answers_path": self.answers_path,
            "raw_text_path": self.raw_text_path,
            "transcription_path": self.transcription_path,
            "transcription_cache_path": self.transcription_cache_path,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _reject_symlink(path: Path, label: str) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError(f"Symlinked {label} is not accepted: {path}")


def evidence_storage_paths(
    storage_root: str,
    student_id: str,
    *,
    create: bool = False,
) -> EvidenceStoragePaths:
    """Return the stable evidence layout for ``student_id``.

    The student component is normalized with the same rule used by submission
    discovery.  ``create=True`` creates only directories owned by this module.
    """
    normalized = normalize_student_id(student_id)
    if not normalized:
        raise ValueError(f"Invalid student ID for evidence storage: {student_id!r}")

    requested_root = Path(storage_root).expanduser()
    _reject_symlink(requested_root, "evidence storage root")
    root = requested_root.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    elif not root.exists():
        # Returning deterministic paths for a not-yet-created root is useful to
        # callers; do not require existence unless a read operation does so.
        pass

    student_dir = root / normalized
    _reject_symlink(student_dir, "student evidence directory")
    source_dir = student_dir / "source"
    pages_dir = student_dir / "pages"
    compiled_dir = student_dir / "compiled"

    if create:
        student_dir.mkdir(parents=True, exist_ok=True)
        for directory in (source_dir, pages_dir, compiled_dir):
            _reject_symlink(directory, "evidence subdirectory")
            directory.mkdir(parents=True, exist_ok=True)

    return EvidenceStoragePaths(
        storage_root=str(root),
        student_dir=str(student_dir),
        source_dir=str(source_dir),
        pages_dir=str(pages_dir),
        compiled_dir=str(compiled_dir),
        meta_path=str(student_dir / SUBMISSION_META_FILENAME),
        answers_path=str(student_dir / EXTRACTED_ANSWERS_FILENAME),
        raw_text_path=str(student_dir / RAW_TEXT_FILENAME),
        transcription_path=str(student_dir / TRANSCRIPTION_FILENAME),
        transcription_cache_path=str(student_dir / TRANSCRIPTION_CACHE_FILENAME),
    )


def compute_file_sha256(path: str, *, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 for a regular non-symlink file."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked files are not hashed as evidence: {requested}")
    source = requested.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))

    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(path.parent, "evidence output directory")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _atomic_write_json(path: Path, value: Any) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    _atomic_write_bytes(path, payload)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, str(text).encode("utf-8"))


def _copy_file(source_path: str, target: Path) -> str:
    requested = Path(source_path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked evidence files are not accepted: {requested}")
    source = requested.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(target.parent, "evidence output directory")

    # Avoid copying a file onto itself when the parser already rendered directly
    # into the persistent evidence directory.
    try:
        if source == target.resolve():
            return str(target.resolve())
    except FileNotFoundError:
        pass

    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(str(source), str(temp_path))
        os.replace(str(temp_path), str(target))
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
    return str(target.resolve())


def _relative_to_student(path: str, student_dir: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(student_dir))
    except ValueError:
        return str(resolved)


def _resolve_manifest_path(value: str, student_dir: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((student_dir / path).resolve())


def _rewrite_rendering_paths_for_storage(metadata: Dict[str, Any], student_dir: Path) -> None:
    rendering = metadata.get("rendering")
    if not isinstance(rendering, dict):
        return
    output_dir = rendering.get("output_dir")
    if output_dir:
        rendering["output_dir"] = _relative_to_student(str(output_dir), student_dir)
    pages = rendering.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if isinstance(page, dict) and page.get("image_path"):
            page["image_path"] = _relative_to_student(str(page["image_path"]), student_dir)


def _resolve_rendering_paths_after_load(metadata: Dict[str, Any], student_dir: Path) -> None:
    rendering = metadata.get("rendering")
    if not isinstance(rendering, dict):
        return
    output_dir = rendering.get("output_dir")
    if output_dir:
        rendering["output_dir"] = _resolve_manifest_path(str(output_dir), student_dir)
    pages = rendering.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if isinstance(page, dict) and page.get("image_path"):
            page["image_path"] = _resolve_manifest_path(str(page["image_path"]), student_dir)


def _rewrite_transcription_paths_for_storage(value: Dict[str, Any], student_dir: Path) -> None:
    pages = value.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if isinstance(page, dict) and page.get("source_image"):
            page["source_image"] = _relative_to_student(str(page["source_image"]), student_dir)


def _resolve_transcription_paths_after_load(value: Dict[str, Any], student_dir: Path) -> None:
    pages = value.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if isinstance(page, dict) and page.get("source_image"):
            page["source_image"] = _resolve_manifest_path(str(page["source_image"]), student_dir)


def _logical_persist_target(
    logical_name: str,
    source_path: str,
    *,
    submission_mode: str,
    paths: EvidenceStoragePaths,
) -> Optional[Path]:
    source = Path(source_path)
    suffix = source.suffix.lower()
    source_dir = Path(paths.source_dir)
    compiled_dir = Path(paths.compiled_dir)

    if logical_name == "latex":
        return source_dir / "main.tex"
    if logical_name == "pdf":
        if submission_mode == SUBMISSION_MODE_PDF_ACCOMMODATION:
            return source_dir / "original.pdf"
        return source_dir / "reference.pdf"
    if logical_name == "compiled_pdf":
        return compiled_dir / "main.pdf"
    if logical_name == "markdown" and suffix:
        return source_dir / f"submission{suffix}"
    if logical_name == "text" and suffix:
        return source_dir / f"submission{suffix}"
    return None


def _page_target_name(page_number: int, total_pages: int) -> str:
    digits = max(3, len(str(max(1, total_pages))))
    return f"page_{page_number:0{digits}d}.png"


def _persist_page_images(
    metadata: Dict[str, Any],
    paths: EvidenceStoragePaths,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Copy rendered pages into ``pages/`` and rewrite metadata in place.

    Returns ``(page_hashes, hash_targets)``.
    """
    rendering = metadata.get("rendering")
    if not isinstance(rendering, dict):
        return {}, {}
    pages = rendering.get("pages")
    if not isinstance(pages, list) or not pages:
        return {}, {}

    target_dir = Path(paths.pages_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    total = len(pages)
    page_hashes: Dict[str, str] = {}
    hash_targets: Dict[str, str] = {}

    expected_names = set()
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or not page.get("image_path"):
            continue
        page_number = int(page.get("page_number") or index)
        name = _page_target_name(page_number, total)
        expected_names.add(name)
        target = target_dir / name
        persisted = _copy_file(str(page["image_path"]), target)
        page["image_path"] = persisted
        key = f"page_{page_number:03d}_sha256"
        page_hashes[key] = compute_file_sha256(persisted)
        hash_targets[key] = _relative_to_student(persisted, Path(paths.student_dir))

    # Remove only renderer-owned page artifacts left from an older persisted
    # version with more pages.  Never touch unrelated user files.
    for child in target_dir.iterdir():
        if (
            child.is_file()
            and not child.is_symlink()
            and child.name.startswith("page_")
            and child.suffix.lower() == ".png"
            and child.name not in expected_names
        ):
            child.unlink()

    rendering["output_dir"] = str(target_dir.resolve())
    rendering["temporary_output"] = False
    return page_hashes, hash_targets


def _transcription_summary(value: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: deepcopy(value.get(key))
        for key in (
            "enabled",
            "status",
            "backend",
            "model",
            "prompt_version",
            "all_pages_usable",
            "any_page_usable",
            "assistive_only",
            "authoritative",
            "cache",
        )
        if key in value
    }


def persist_submission_evidence(
    parsed: ParsedSubmission,
    storage_root: str,
) -> ParsedSubmission:
    """Persist one parsed submission and return a copy pointing at stable files.

    The input object is not mutated.  Original source locations are retained in
    ``submission_meta.json`` as provenance, while ``result.files`` points to the
    persisted copies whenever a known logical file type is copied.
    """
    result = deepcopy(parsed)
    paths = evidence_storage_paths(storage_root, result.student_id, create=True)
    student_dir = Path(paths.student_dir)

    original_files = dict(result.files)
    persisted_files = dict(result.files)
    file_hashes: Dict[str, str] = {}
    hash_targets: Dict[str, str] = {}

    for logical_name, source_path in list(result.files.items()):
        if logical_name == "rendered_pages_dir" or not source_path:
            continue
        target = _logical_persist_target(
            logical_name,
            str(source_path),
            submission_mode=result.submission_mode,
            paths=paths,
        )
        if target is None:
            continue
        persisted = _copy_file(str(source_path), target)
        persisted_files[logical_name] = persisted
        hash_key = f"{logical_name}_sha256"
        file_hashes[hash_key] = compute_file_sha256(persisted)
        hash_targets[hash_key] = _relative_to_student(persisted, student_dir)

    page_hashes, page_targets = _persist_page_images(result.metadata, paths)
    file_hashes.update(page_hashes)
    hash_targets.update(page_targets)

    rendering = result.metadata.get("rendering")
    if isinstance(rendering, dict) and rendering.get("output_dir"):
        persisted_files["rendered_pages_dir"] = str(Path(paths.pages_dir).resolve())

    transcription_meta = result.metadata.get("transcription")
    if isinstance(transcription_meta, dict):
        # Ensure page provenance points at the stable page copies.
        pages = transcription_meta.get("pages")
        rendering_pages = (
            rendering.get("pages", [])
            if isinstance(rendering, dict) and isinstance(rendering.get("pages"), list)
            else []
        )
        if isinstance(pages, list):
            for index, page in enumerate(pages):
                if not isinstance(page, dict):
                    continue
                if index < len(rendering_pages) and isinstance(rendering_pages[index], dict):
                    stable_image = rendering_pages[index].get("image_path")
                    if stable_image:
                        page["source_image"] = stable_image

    result.files = persisted_files

    persisted_at = _utc_now_iso()
    evidence_meta = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "persisted": True,
        "persisted_at": persisted_at,
        "student_dir": str(student_dir),
        "meta_path": paths.meta_path,
        "answers_path": paths.answers_path,
        "raw_text_path": paths.raw_text_path,
        "transcription_path": paths.transcription_path,
        "transcription_cache_path": paths.transcription_cache_path,
        "file_hashes": dict(file_hashes),
        "hash_targets": dict(hash_targets),
    }
    result.metadata["evidence"] = evidence_meta

    _atomic_write_text(Path(paths.raw_text_path), result.raw_text)
    _atomic_write_json(Path(paths.answers_path), dict(result.answers_by_question))

    if isinstance(transcription_meta, dict) and transcription_meta:
        stored_transcription = deepcopy(transcription_meta)
        _rewrite_transcription_paths_for_storage(stored_transcription, student_dir)
        _atomic_write_json(Path(paths.transcription_path), stored_transcription)
    else:
        try:
            Path(paths.transcription_path).unlink()
        except FileNotFoundError:
            pass

    stored_metadata = deepcopy(result.metadata)
    stored_metadata.pop("transcription", None)
    _rewrite_rendering_paths_for_storage(stored_metadata, student_dir)
    stored_metadata["evidence"] = {
        **deepcopy(evidence_meta),
        "student_dir": ".",
        "meta_path": SUBMISSION_META_FILENAME,
        "answers_path": EXTRACTED_ANSWERS_FILENAME,
        "raw_text_path": RAW_TEXT_FILENAME,
        "transcription_path": TRANSCRIPTION_FILENAME,
        "transcription_cache_path": TRANSCRIPTION_CACHE_FILENAME,
    }

    manifest_files = {
        key: _relative_to_student(value, student_dir)
        for key, value in persisted_files.items()
        if value
    }

    manifest = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "persisted_at": persisted_at,
        "student_id": result.student_id,
        "submission_mode": result.submission_mode,
        "accommodation_mode": bool(result.accommodation_mode),
        "source_used": result.source_used,
        "files": manifest_files,
        "original_files": original_files,
        "file_hashes": file_hashes,
        "hash_targets": hash_targets,
        "warnings": list(result.warnings),
        "question_split_status": result.metadata.get("question_split_status"),
        "authoritative_source": result.metadata.get("authoritative_source"),
        "assistive_text_source": result.metadata.get("assistive_text_source"),
        "transcription_summary": (
            _transcription_summary(transcription_meta)
            if isinstance(transcription_meta, dict)
            else {}
        ),
        "raw_text_file": RAW_TEXT_FILENAME,
        "extracted_answers_file": EXTRACTED_ANSWERS_FILENAME,
        "transcription_file": (
            TRANSCRIPTION_FILENAME
            if isinstance(transcription_meta, dict) and transcription_meta
            else None
        ),
        "metadata": stored_metadata,
    }
    _atomic_write_json(Path(paths.meta_path), manifest)
    return result


def _read_json_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON evidence file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in evidence file: {path}")
    return value


def load_persisted_submission(
    storage_root: str,
    student_id: str,
    *,
    verify_hashes: bool = True,
) -> ParsedSubmission:
    """Load a previously persisted submission without invoking PDF/VLM backends."""
    paths = evidence_storage_paths(storage_root, student_id, create=False)
    student_dir = Path(paths.student_dir)
    meta_path = Path(paths.meta_path)
    if not meta_path.exists():
        raise FileNotFoundError(str(meta_path))

    manifest = _read_json_object(meta_path)
    schema = str(manifest.get("schema_version", ""))
    if schema != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported evidence schema {schema!r}; expected {EVIDENCE_SCHEMA_VERSION!r}."
        )

    files_raw = manifest.get("files", {})
    files: Dict[str, str] = {}
    if isinstance(files_raw, dict):
        for key, value in files_raw.items():
            if isinstance(value, str) and value:
                files[str(key)] = _resolve_manifest_path(value, student_dir)

    answers_path = student_dir / str(manifest.get("extracted_answers_file") or EXTRACTED_ANSWERS_FILENAME)
    answers_raw = _read_json_object(answers_path)
    answers = {str(key): str(value) for key, value in answers_raw.items()}

    raw_text_path = student_dir / str(manifest.get("raw_text_file") or RAW_TEXT_FILENAME)
    try:
        raw_text = raw_text_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raw_text = ""

    metadata = deepcopy(manifest.get("metadata", {}))
    if not isinstance(metadata, dict):
        metadata = {}
    _resolve_rendering_paths_after_load(metadata, student_dir)

    transcription_file = manifest.get("transcription_file")
    if isinstance(transcription_file, str) and transcription_file:
        trans_path = student_dir / transcription_file
        if trans_path.exists():
            transcription = _read_json_object(trans_path)
            _resolve_transcription_paths_after_load(transcription, student_dir)
            metadata["transcription"] = transcription

    warnings = [str(value) for value in manifest.get("warnings", [])]

    file_hashes = manifest.get("file_hashes", {})
    hash_targets = manifest.get("hash_targets", {})
    verification: Dict[str, Any] = {
        "performed": bool(verify_hashes),
        "ok": True,
        "mismatches": [],
        "missing": [],
    }
    if verify_hashes and isinstance(file_hashes, dict) and isinstance(hash_targets, dict):
        for key, expected in file_hashes.items():
            target_value = hash_targets.get(key)
            if not isinstance(expected, str) or not isinstance(target_value, str):
                continue
            target = Path(_resolve_manifest_path(target_value, student_dir))
            if not target.exists():
                verification["ok"] = False
                verification["missing"].append(str(key))
                warnings.append(f"persisted_evidence_missing:{key}")
                continue
            try:
                actual = compute_file_sha256(str(target))
            except (OSError, ValueError):
                verification["ok"] = False
                verification["missing"].append(str(key))
                warnings.append(f"persisted_evidence_unreadable:{key}")
                continue
            if actual != expected:
                verification["ok"] = False
                verification["mismatches"].append(str(key))
                warnings.append(f"persisted_evidence_hash_mismatch:{key}")

    evidence = metadata.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    evidence.update(
        {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "persisted": True,
            "persisted_at": manifest.get("persisted_at"),
            "student_dir": str(student_dir),
            "meta_path": paths.meta_path,
            "answers_path": str(answers_path),
            "raw_text_path": str(raw_text_path),
            "transcription_path": paths.transcription_path,
            "transcription_cache_path": paths.transcription_cache_path,
            "file_hashes": deepcopy(file_hashes) if isinstance(file_hashes, dict) else {},
            "hash_targets": deepcopy(hash_targets) if isinstance(hash_targets, dict) else {},
            "verification": verification,
            "loaded_from_persistence": True,
        }
    )
    metadata["evidence"] = evidence

    return ParsedSubmission(
        student_id=str(manifest.get("student_id") or normalize_student_id(student_id)),
        source_used=str(manifest.get("source_used") or "none"),
        raw_text=raw_text,
        answers_by_question=answers,
        files=files,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
        submission_mode=str(manifest.get("submission_mode") or "latex"),
        accommodation_mode=bool(manifest.get("accommodation_mode", False)),
    )


def _backend_cache_identity(backend: TranscriptionBackend) -> Dict[str, Any]:
    identity = backend.cache_identity()
    if not isinstance(identity, dict):
        raise ValueError("TranscriptionBackend.cache_identity() must return a dictionary")
    return deepcopy(identity)


def build_transcription_cache_inputs(
    *,
    backend: TranscriptionBackend,
    image_paths: Sequence[str],
    render_dpi: int,
    source_sha256: str,
) -> Dict[str, Any]:
    """Build deterministic cache inputs from evidence + inference configuration."""
    pages = []
    for index, image_path in enumerate(image_paths, start=1):
        pages.append(
            {
                "page_number": index,
                "sha256": compute_file_sha256(str(image_path)),
            }
        )
    return {
        "backend": _backend_cache_identity(backend),
        "source_sha256": str(source_sha256),
        "render_dpi": int(render_dpi),
        "pages": pages,
    }


def transcription_cache_key(cache_inputs: Mapping[str, Any]) -> str:
    return _sha256_json(dict(cache_inputs))


def save_transcription_cache(
    cache_path: str,
    *,
    batch: TranscriptionBatchResult,
    cache_inputs: Mapping[str, Any],
) -> Dict[str, Any]:
    """Persist page-aligned transcription provenance plus cache validity inputs."""
    inputs = deepcopy(dict(cache_inputs))
    key = transcription_cache_key(inputs)
    payload = {
        "schema_version": TRANSCRIPTION_CACHE_SCHEMA_VERSION,
        "created_at": _utc_now_iso(),
        "cache_key": key,
        # Failed/partial outputs remain useful provenance but are never reused as
        # an automatic successful cache hit.
        "cache_eligible": bool(batch.all_pages_usable),
        "cache_inputs": inputs,
        "batch": batch.to_metadata(),
    }
    _atomic_write_json(Path(cache_path), payload)
    return {
        "status": "stored",
        "cache_key": key,
        "cache_eligible": bool(batch.all_pages_usable),
        "path": str(Path(cache_path).resolve()),
    }


def load_cached_transcription(
    cache_path: str,
    *,
    backend: TranscriptionBackend,
    image_paths: Sequence[str],
    render_dpi: int,
    source_sha256: str,
) -> Tuple[Optional[TranscriptionBatchResult], Dict[str, Any]]:
    """Return a successful cached batch only when every provenance input matches.

    Corrupt, stale, partial, or missing caches are ordinary cache misses and do
    not block grading or inference.
    """
    path = Path(cache_path).expanduser()
    try:
        current_inputs = build_transcription_cache_inputs(
            backend=backend,
            image_paths=image_paths,
            render_dpi=render_dpi,
            source_sha256=source_sha256,
        )
        current_key = transcription_cache_key(current_inputs)
    except Exception as exc:
        return None, {
            "status": "miss",
            "reason": "cache_input_error",
            "error": str(exc),
        }

    if not path.exists():
        return None, {
            "status": "miss",
            "reason": "cache_not_found",
            "cache_key": current_key,
        }
    if path.is_symlink():
        return None, {
            "status": "miss",
            "reason": "cache_symlink_rejected",
            "cache_key": current_key,
        }

    try:
        payload = _read_json_object(path)
    except (OSError, ValueError) as exc:
        return None, {
            "status": "miss",
            "reason": "cache_invalid",
            "cache_key": current_key,
            "error": str(exc),
        }

    if payload.get("schema_version") != TRANSCRIPTION_CACHE_SCHEMA_VERSION:
        return None, {
            "status": "miss",
            "reason": "cache_schema_mismatch",
            "cache_key": current_key,
        }
    if payload.get("cache_key") != current_key:
        return None, {
            "status": "miss",
            "reason": "cache_key_mismatch",
            "cache_key": current_key,
            "stored_cache_key": payload.get("cache_key"),
        }
    if not bool(payload.get("cache_eligible")):
        return None, {
            "status": "miss",
            "reason": "cached_result_not_eligible",
            "cache_key": current_key,
        }

    batch_data = payload.get("batch")
    if not isinstance(batch_data, dict):
        return None, {
            "status": "miss",
            "reason": "cache_batch_missing",
            "cache_key": current_key,
        }
    try:
        batch = TranscriptionBatchResult.from_metadata(batch_data)
    except (TypeError, ValueError, KeyError) as exc:
        return None, {
            "status": "miss",
            "reason": "cache_batch_invalid",
            "cache_key": current_key,
            "error": str(exc),
        }
    if not batch.all_pages_usable or len(batch.pages) != len(image_paths):
        return None, {
            "status": "miss",
            "reason": "cache_batch_incomplete",
            "cache_key": current_key,
        }

    # The text/status/provenance are reused, while source-image paths are rebound
    # to the current verified page artifacts.
    for page, image_path in zip(batch.pages, image_paths):
        page.source_image = str(Path(image_path).expanduser().resolve())
        page.metadata = dict(page.metadata)
        page.metadata["cache_reused"] = True

    return batch, {
        "status": "hit",
        "cache_key": current_key,
        "path": str(path.resolve()),
        "created_at": payload.get("created_at"),
    }


def assessment_submission_fields(parsed: ParsedSubmission) -> Dict[str, Any]:
    """Return the optional assessment-JSON fields for a loaded submission.

    These fields are intentionally isolated from score/criterion data.  Commit 5
    can merge them into the UI's saved assessment without changing grading math.
    """
    evidence = parsed.metadata.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    transcription = parsed.metadata.get("transcription", {})
    if not isinstance(transcription, dict):
        transcription = {}

    submission_meta = {
        "student_id": parsed.student_id,
        "submission_mode": parsed.submission_mode,
        "accommodation_mode": bool(parsed.accommodation_mode),
        "source_used": parsed.source_used,
        "files": dict(parsed.files),
        "file_hashes": deepcopy(evidence.get("file_hashes", {})),
        "extraction_timestamp": evidence.get("persisted_at") or _utc_now_iso(),
        "question_split_status": parsed.metadata.get("question_split_status"),
        "authoritative_source": parsed.metadata.get("authoritative_source"),
        "assistive_text_source": parsed.metadata.get("assistive_text_source"),
        "warnings": list(parsed.warnings),
        "transcription": _transcription_summary(transcription),
    }
    if evidence.get("student_dir"):
        submission_meta["evidence_dir"] = evidence.get("student_dir")

    return {
        "submission_meta": submission_meta,
        "extracted_answers": dict(parsed.answers_by_question),
    }


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "EXTRACTED_ANSWERS_FILENAME",
    "EvidenceStoragePaths",
    "RAW_TEXT_FILENAME",
    "SUBMISSION_META_FILENAME",
    "TRANSCRIPTION_CACHE_FILENAME",
    "TRANSCRIPTION_CACHE_SCHEMA_VERSION",
    "TRANSCRIPTION_FILENAME",
    "assessment_submission_fields",
    "build_transcription_cache_inputs",
    "compute_file_sha256",
    "evidence_storage_paths",
    "load_cached_transcription",
    "load_persisted_submission",
    "persist_submission_evidence",
    "save_transcription_cache",
    "transcription_cache_key",
]
