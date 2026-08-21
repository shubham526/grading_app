"""Self-contained helpers for v2.3.4.2 LaTeX-project hardening tests."""

from __future__ import annotations

from pathlib import Path
import zipfile

from src.submissions.latex_project import (
    LatexProjectArchiveStore,
    discover_latex_project,
    resolve_latex_project_root,
)


def complete_document(body="PASS"):
    return (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        + str(body)
        + "\n\\end{document}\n"
    )


def write_zip(root, name, entries, *, compression=zipfile.ZIP_DEFLATED):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / name
    with zipfile.ZipFile(archive, "w", compression=compression) as zf:
        for relative, data in entries:
            if isinstance(data, str):
                data = data.encode("utf-8")
            zf.writestr(relative, data)
    return archive


def ingest_project(root, entries, *, project_id="lproj-hardening", config=None):
    root = Path(root)
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    archive = write_zip(incoming, project_id + ".zip", entries)
    store = LatexProjectArchiveStore(root / "store")
    stored = store.ingest_zip(
        archive,
        "artifact-hardening",
        project_id=project_id,
        imported_at="2026-08-21T03:30:00Z",
        config=config,
    )
    return store, stored


def discover_and_resolve(stored, *, config=None):
    discovery = discover_latex_project(
        stored.extracted_root,
        stored.manifest,
        config=config,
    )
    resolution = resolve_latex_project_root(discovery, config=config)
    return discovery, resolution


__all__ = [
    "complete_document",
    "discover_and_resolve",
    "ingest_project",
    "write_zip",
]
