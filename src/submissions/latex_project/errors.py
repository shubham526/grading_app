"""Errors for v2.3.4.2 LaTeX project ZIP ingestion."""


class LatexProjectError(Exception):
    """Base class for LaTeX-project ingestion failures."""


class LatexProjectValidationError(LatexProjectError, ValueError):
    """Raised when LaTeX-project domain/configuration data is invalid."""


class LatexProjectSerializationError(LatexProjectError, ValueError):
    """Raised when serialized LaTeX-project data cannot be decoded."""


class UnsupportedLatexProjectSchemaError(LatexProjectSerializationError):
    """Raised when serialized data uses an unsupported schema version."""


class LatexProjectArchiveError(LatexProjectError):
    """Base class for failures while inspecting or materializing ZIP archives."""


class LatexProjectArchiveRejectedError(LatexProjectArchiveError):
    """Raised when an untrusted ZIP violates a non-negotiable safety rule.

    ``diagnostics`` is a tuple of :class:`LatexProjectDiagnostic` objects when
    the archive layer can provide structured portable details.  The exception
    deliberately does not depend on the model module at import time, avoiding
    an errors <-> models cycle.
    """

    def __init__(self, message, diagnostics=()):
        super().__init__(str(message))
        self.diagnostics = tuple(diagnostics or ())


class LatexProjectStorageError(LatexProjectError):
    """Raised when immutable LaTeX-project storage cannot be committed/read."""


class LatexProjectIntegrityError(LatexProjectStorageError):
    """Raised when persisted archive/project bytes fail integrity verification."""


__all__ = [
    "LatexProjectArchiveError",
    "LatexProjectArchiveRejectedError",
    "LatexProjectError",
    "LatexProjectIntegrityError",
    "LatexProjectSerializationError",
    "LatexProjectStorageError",
    "LatexProjectValidationError",
    "UnsupportedLatexProjectSchemaError",
]
