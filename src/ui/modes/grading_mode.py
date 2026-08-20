"""Grading-mode domain for the dual-mode application shell.

v2.3.4.1 makes the instructor workflow explicit instead of inferring it from
submission file types. This module is intentionally Qt-free.
"""

from enum import Enum


class GradingMode(str, Enum):
    """Top-level grading workflow selected by the instructor."""

    WRITTEN = "written"
    PROGRAMMING = "programming"

    @property
    def display_name(self):
        if self is GradingMode.WRITTEN:
            return "Written / Text"
        return "Programming"

    @classmethod
    def coerce(cls, value):
        """Return a GradingMode for enum/string input."""

        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            for mode in cls:
                if normalized in (mode.value, mode.name.lower()):
                    return mode
        raise ValueError("Unsupported grading mode: {!r}".format(value))
