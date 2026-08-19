"""Submission source adapters for v2.3.2 canonical ingestion."""

from .base import SubmissionSourceAdapter
from .local import (
    LocalFileSourceAdapter,
    discover_local_directory,
    discover_local_files,
)

__all__ = [
    "LocalFileSourceAdapter",
    "SubmissionSourceAdapter",
    "discover_local_directory",
    "discover_local_files",
]
