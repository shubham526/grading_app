"""SHA256 helpers for deterministic submission-similarity review."""

from __future__ import annotations

import hashlib
from pathlib import Path


_CHUNK_SIZE = 1024 * 1024


def compute_file_sha256(path: str | Path) -> str:
    """Compute SHA256 over raw file bytes.

    This is intended for byte-for-byte exact-file comparison. The caller is
    responsible for comparing hashes only for equivalent/canonical file types.
    """
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"Similarity source file does not exist: {file_path}")

    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_text_sha256(text: str) -> str:
    """Compute SHA256 over the supplied normalized text.

    Callers should pass ``normalize_for_similarity(text)`` when they want a
    normalized-text identity comparison.
    """
    if text is None:
        raise TypeError("text must be a string, not None")
    if not isinstance(text, str):
        text = str(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
