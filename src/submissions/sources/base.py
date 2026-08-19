"""Source-adapter contracts for canonical submission import.

v2.3.2 Commit 3 separates discovery/fetching from canonical persistence.  A
source adapter describes incoming submission candidates; ``SubmissionImporter``
handles roster matching, duplicate analysis, attempt assignment, and repository
commit.

The contract is intentionally Qt-free and source-agnostic so future adapters
(Canvas, Git, etc.) can plug into the same pipeline.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from ..domain import CandidateFile, ImportCandidate


@runtime_checkable
class SubmissionSourceAdapter(Protocol):
    """Protocol implemented by submission discovery/fetch adapters."""

    source_system: str

    def discover(
        self,
        *,
        assessment_id: Optional[str] = None,
    ) -> List[ImportCandidate]:
        """Return candidates without committing them to canonical storage."""
        ...

    def fetch(self, candidate: ImportCandidate) -> List[CandidateFile]:
        """Return a fresh verified view of a candidate's source files."""
        ...


__all__ = ["SubmissionSourceAdapter"]
