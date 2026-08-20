"""Errors for v2.3.4.2 LaTeX project ZIP ingestion.

Commit 1 defines only dependency-free domain/configuration contracts.  Archive
inspection, extraction, source resolution, and parser integration are added by
later commits.
"""


class LatexProjectError(Exception):
    """Base class for LaTeX-project ingestion failures."""


class LatexProjectValidationError(LatexProjectError, ValueError):
    """Raised when LaTeX-project domain/configuration data is invalid."""


class LatexProjectSerializationError(LatexProjectError, ValueError):
    """Raised when serialized LaTeX-project data cannot be decoded."""


class UnsupportedLatexProjectSchemaError(LatexProjectSerializationError):
    """Raised when serialized data uses an unsupported schema version."""


__all__ = [
    "LatexProjectError",
    "LatexProjectSerializationError",
    "LatexProjectValidationError",
    "UnsupportedLatexProjectSchemaError",
]
