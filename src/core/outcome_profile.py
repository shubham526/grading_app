"""
Outcome Profile — Rubric Grading Tool
======================================

An outcome profile is a JSON file that fully describes a course's assessment
configuration.  It is the single source of truth for:

  - Course Learning Outcomes  (LO1, LO2, …)
  - Program / Accreditation Outcomes  (SO1, SO2, … or any labels)
  - LO → Program-Outcome crosswalk
  - Performance bands and passing threshold
  - Keyword-to-LO auto-mapping rules

Design principles
-----------------
* The canonical internal field is ``program_outcomes``.
  The legacy name ``abet_outcomes`` is accepted on load and normalised;
  callers may use either name via the ``po_ids()`` / ``so_ids()`` aliases.
* All profile-level fields that were previously hard-coded in the scoring
  engine (bands, target %, passing bands) are now read from the profile.
* ``cs2500_algorithms.json`` is just one profile.  Any course can have its
  own profile by creating a JSON file in the profiles directory.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(__file__)
_DEFAULT_PROFILE_DIR = os.path.normpath(
    os.path.join(_HERE, "..", "..", "config", "outcome_profiles")
)
_BUILTIN_PROFILE   = "cs2500_algorithms"
_GENERIC_TEMPLATE  = "generic_course"


# ---------------------------------------------------------------------------
# OutcomeProfile
# ---------------------------------------------------------------------------

class OutcomeProfile:
    """
    Represents a fully loaded course outcome profile.

    Attribute naming
    ----------------
    ``program_outcomes``  — canonical dict {po_id: description}
    ``abet_outcomes``     — alias property → same as program_outcomes
    ``lo_to_program``     — canonical crosswalk dict {lo_id: [po_id, …]}
    ``lo_to_abet``        — alias property → same as lo_to_program
    ``keyword_to_lo``     — {lo_id: [keyword, …]} (lowercase)
    ``performance_bands`` — {band_name: (lo, hi)}
    ``passing_bands``     — [band_name, …]  bands that count as "passing"
    ``default_target_pct``— float, default pass threshold (e.g. 75.0)
    """

    def __init__(self, data: dict):
        self.schema_version: str  = data.get("schema_version", "2.0")
        self.profile_id:     str  = data.get("profile_id", "")
        self.course_code:    str  = data.get("course_code", "")
        self.course_name:    str  = data.get("course_name", "")

        # Course outcomes
        self.course_outcomes: Dict[str, str] = _strip_comments(
            data.get("course_outcomes", {})
        )

        # Program outcomes — accept both new name and legacy "abet_outcomes"
        raw_po = data.get("program_outcomes") or data.get("abet_outcomes") or {}
        self.program_outcomes: Dict[str, str] = _strip_comments(raw_po)

        # LO → Program crosswalk — accept both naming conventions
        raw_xwalk = (
            data.get("default_course_to_program")
            or data.get("default_lo_to_abet")
            or {}
        )
        self.lo_to_program: Dict[str, List[str]] = _strip_comments(raw_xwalk)

        # Keyword rules — accept both naming conventions
        raw_kw = (
            data.get("keyword_to_course_outcome")
            or data.get("keyword_to_lo")
            or {}
        )
        self.keyword_to_lo: Dict[str, List[str]] = _strip_comments(raw_kw)

        # Performance bands — load from profile, fall back to DEFAULT_BANDS
        raw_bands = _strip_comments(data.get("performance_bands", {}))
        if raw_bands:
            self.performance_bands: Dict[str, Tuple[float, float]] = {
                k: (float(v[0]), float(v[1])) for k, v in raw_bands.items()
            }
        else:
            from src.tools.abet_scoring import DEFAULT_BANDS
            self.performance_bands = dict(DEFAULT_BANDS)

        # Passing bands — names of bands whose students count as "passing"
        self.passing_bands: List[str] = data.get(
            "passing_bands", ["excellent", "adequate", "exemplary", "proficient"]
        )

        # Default target percentage
        self.default_target_pct: float = float(
            data.get("target_percentage", 75.0)
        )

    # ------------------------------------------------------------------
    # Backward-compat aliases
    # ------------------------------------------------------------------

    @property
    def abet_outcomes(self) -> Dict[str, str]:
        """Alias: same as program_outcomes."""
        return self.program_outcomes

    @property
    def lo_to_abet(self) -> Dict[str, List[str]]:
        """Alias: same as lo_to_program."""
        return self.lo_to_program

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def lo_ids(self) -> List[str]:
        return sorted(self.course_outcomes.keys())

    def po_ids(self) -> List[str]:
        """Return sorted program-outcome IDs (canonical name)."""
        return sorted(self.program_outcomes.keys())

    def so_ids(self) -> List[str]:
        """Alias for po_ids() — backward compat."""
        return self.po_ids()

    def lo_description(self, lo_id: str) -> str:
        return self.course_outcomes.get(lo_id, lo_id)

    def po_description(self, po_id: str) -> str:
        """Return description for a program outcome."""
        return self.program_outcomes.get(po_id, po_id)

    def so_description(self, so_id: str) -> str:
        """Alias for po_description() — backward compat."""
        return self.po_description(so_id)

    def program_for_lo(self, lo_id: str) -> List[str]:
        """Return program outcomes mapped to this LO."""
        return self.lo_to_program.get(lo_id, [])

    def abet_for_lo(self, lo_id: str) -> List[str]:
        """Alias — backward compat."""
        return self.program_for_lo(lo_id)

    def derive_program_from_los(self, lo_ids: List[str]) -> List[str]:
        """Return deduplicated union of program outcomes for the given LOs."""
        pos: List[str] = []
        for lo in lo_ids:
            for po in self.program_for_lo(lo):
                if po not in pos:
                    pos.append(po)
        return pos

    def derive_abet_from_los(self, lo_ids: List[str]) -> List[str]:
        """Alias — backward compat."""
        return self.derive_program_from_los(lo_ids)

    # ------------------------------------------------------------------
    # Auto-mapping
    # ------------------------------------------------------------------

    def infer_los_from_title(self, title: str) -> List[str]:
        """Use keyword rules to infer LOs from a criterion title."""
        title_lower = title.lower()
        matched: List[str] = []
        for lo_id, keywords in self.keyword_to_lo.items():
            for kw in keywords:
                if kw in title_lower:
                    if lo_id not in matched:
                        matched.append(lo_id)
                    break
        return matched

    def infer_program_outcomes_from_title(self, title: str) -> List[str]:
        """Infer program outcomes from title via LO keywords + crosswalk."""
        los = self.infer_los_from_title(title)
        return self.derive_program_from_los(los)

    def infer_sos_from_title(self, title: str) -> List[str]:
        """Alias — backward compat."""
        return self.infer_program_outcomes_from_title(title)

    # ------------------------------------------------------------------
    # Band helpers (used by scoring engine)
    # ------------------------------------------------------------------

    def compute_passing_count(self, band_counts: dict) -> int:
        """Sum counts across all passing bands."""
        return sum(
            band_counts.get(b, {}).get("count", 0)
            for b in self.passing_bands
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema_version":           self.schema_version,
            "profile_id":               self.profile_id,
            "course_code":              self.course_code,
            "course_name":              self.course_name,
            "course_outcomes":          self.course_outcomes,
            "program_outcomes":         self.program_outcomes,
            "default_course_to_program": self.lo_to_program,
            "keyword_to_course_outcome": self.keyword_to_lo,
            "performance_bands":        {k: list(v) for k, v in self.performance_bands.items()},
            "passing_bands":            self.passing_bands,
            "target_percentage":        self.default_target_pct,
        }


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_profile(profile_id_or_path: str) -> OutcomeProfile:
    """
    Load an OutcomeProfile by profile ID or explicit file path.

    Args:
        profile_id_or_path: E.g. "cs2500_algorithms" or "/path/to/profile.json"

    Raises:
        FileNotFoundError: Profile not found.
        ValueError:        Invalid JSON.
    """
    if os.sep in profile_id_or_path or profile_id_or_path.endswith(".json"):
        path = profile_id_or_path
    else:
        path = os.path.join(_DEFAULT_PROFILE_DIR, f"{profile_id_or_path}.json")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Outcome profile not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    return OutcomeProfile(data)


def load_default_profile() -> OutcomeProfile:
    """Load the built-in CS 2500 Algorithms profile."""
    return load_profile(_BUILTIN_PROFILE)


def load_generic_template() -> OutcomeProfile:
    """Load the generic course template profile."""
    return load_profile(_GENERIC_TEMPLATE)


def list_available_profiles(profile_dir: Optional[str] = None) -> List[str]:
    """Return list of available profile IDs (filenames without .json)."""
    directory = profile_dir or _DEFAULT_PROFILE_DIR
    if not os.path.isdir(directory):
        return []
    return [
        os.path.splitext(f)[0]
        for f in sorted(os.listdir(directory))
        if f.endswith(".json")
    ]


def create_profile_from_dict(data: dict) -> OutcomeProfile:
    """Create an OutcomeProfile directly from a dict (useful in tests/UI)."""
    return OutcomeProfile(data)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_comments(d: dict) -> dict:
    """Remove any key starting with '_' (used as inline JSON comments)."""
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if not k.startswith("_")}
