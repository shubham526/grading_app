"""Configuration for v2.3.4.2 LaTeX project ZIP ingestion.

The configuration exposes bounded resource limits and deterministic project
resolution preferences.  Safety invariants such as rejecting path traversal,
absolute paths, and archive links are intentionally not configurable off.

Commit 1 does not inspect or extract archives; later commits enforce these
validated limits while processing untrusted ZIP metadata and bytes.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .errors import (
    LatexProjectSerializationError,
    LatexProjectValidationError,
    UnsupportedLatexProjectSchemaError,
)


LATEX_PROJECT_CONFIG_SCHEMA_VERSION = "1.0"

DEFAULT_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_FILE_COUNT = 1000
DEFAULT_MAX_COMPRESSION_RATIO = 200.0
DEFAULT_MAX_INCLUDE_DEPTH = 64
DEFAULT_PREFERRED_ROOT_NAMES = ("main.tex",)
DEFAULT_IGNORED_METADATA_NAMES = (".DS_Store", "Thumbs.db")
DEFAULT_IGNORED_DIRECTORY_NAMES = ("__MACOSX",)


def _text(value, name):
    value = "" if value is None else str(value).strip()
    if not value:
        raise LatexProjectValidationError("%s must not be empty" % name)
    return value


def _positive_int(value, name):
    if isinstance(value, bool):
        raise LatexProjectValidationError("%s must be an integer, not boolean" % name)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise LatexProjectValidationError("%s must be an integer" % name)
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = float(number)
    if numeric_value != float(number):
        raise LatexProjectValidationError("%s must be an integer" % name)
    if number <= 0:
        raise LatexProjectValidationError("%s must be greater than zero" % name)
    return number


def _positive_float(value, name):
    if isinstance(value, bool):
        raise LatexProjectValidationError("%s must be numeric, not boolean" % name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LatexProjectValidationError("%s must be numeric" % name)
    if not math.isfinite(number) or number <= 0:
        raise LatexProjectValidationError("%s must be a finite value greater than zero" % name)
    return number


def _metadata(value):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LatexProjectValidationError("metadata must be a mapping")
    return deepcopy(dict(value))


def _string_tuple(values, name, default=(), casefold_unique=False):
    if values is None:
        values = default
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Sequence):
        raise LatexProjectValidationError(
            "%s must be an ordered sequence of strings" % name
        )
    result = []
    seen = set()
    for raw in values:
        value = _text(raw, "%s entry" % name)
        key = value.casefold() if casefold_unique else value
        if key in seen:
            raise LatexProjectValidationError(
                "%s contains duplicate value %r" % (name, value)
            )
        seen.add(key)
        result.append(value)
    return tuple(result)


def _root_name_tuple(values):
    values = _string_tuple(
        values,
        "preferred_root_names",
        default=DEFAULT_PREFERRED_ROOT_NAMES,
        casefold_unique=True,
    )
    result = []
    for value in values:
        if "/" in value or "\\" in value or value in (".", ".."):
            raise LatexProjectValidationError(
                "preferred_root_names entries must be basenames, not paths"
            )
        if not value.lower().endswith(".tex"):
            raise LatexProjectValidationError(
                "preferred_root_names entries must end with .tex"
            )
        result.append(value)
    return tuple(result)


@dataclass(frozen=True)
class LatexProjectSafetyLimits:
    """Resource ceilings enforced before/during safe archive extraction."""

    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES
    max_total_uncompressed_bytes: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES
    max_file_count: int = DEFAULT_MAX_FILE_COUNT
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO

    def __post_init__(self):
        archive = _positive_int(self.max_archive_bytes, "max_archive_bytes")
        total = _positive_int(
            self.max_total_uncompressed_bytes,
            "max_total_uncompressed_bytes",
        )
        member = _positive_int(self.max_member_bytes, "max_member_bytes")
        count = _positive_int(self.max_file_count, "max_file_count")
        ratio = _positive_float(
            self.max_compression_ratio,
            "max_compression_ratio",
        )
        if member > total:
            raise LatexProjectValidationError(
                "max_member_bytes must not exceed max_total_uncompressed_bytes"
            )
        object.__setattr__(self, "max_archive_bytes", archive)
        object.__setattr__(self, "max_total_uncompressed_bytes", total)
        object.__setattr__(self, "max_member_bytes", member)
        object.__setattr__(self, "max_file_count", count)
        object.__setattr__(self, "max_compression_ratio", ratio)

    def to_dict(self):
        return {
            "max_archive_bytes": self.max_archive_bytes,
            "max_total_uncompressed_bytes": self.max_total_uncompressed_bytes,
            "max_member_bytes": self.max_member_bytes,
            "max_file_count": self.max_file_count,
            "max_compression_ratio": self.max_compression_ratio,
        }

    @classmethod
    def from_dict(cls, data):
        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            raise LatexProjectSerializationError("limits must be a mapping")
        allowed = {
            "max_archive_bytes",
            "max_total_uncompressed_bytes",
            "max_member_bytes",
            "max_file_count",
            "max_compression_ratio",
        }
        unknown = set(data) - allowed
        if unknown:
            raise LatexProjectValidationError(
                "Unsupported limit option(s): %s"
                % ", ".join(sorted(str(item) for item in unknown))
            )
        return cls(
            max_archive_bytes=data.get(
                "max_archive_bytes",
                DEFAULT_MAX_ARCHIVE_BYTES,
            ),
            max_total_uncompressed_bytes=data.get(
                "max_total_uncompressed_bytes",
                DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES,
            ),
            max_member_bytes=data.get(
                "max_member_bytes",
                DEFAULT_MAX_MEMBER_BYTES,
            ),
            max_file_count=data.get(
                "max_file_count",
                DEFAULT_MAX_FILE_COUNT,
            ),
            max_compression_ratio=data.get(
                "max_compression_ratio",
                DEFAULT_MAX_COMPRESSION_RATIO,
            ),
        )


@dataclass(frozen=True)
class LatexProjectIngestionConfig:
    """Validated project-ingestion policy shared by later v2.3.4.2 services."""

    limits: LatexProjectSafetyLimits = field(default_factory=LatexProjectSafetyLimits)
    preferred_root_names: Tuple[str, ...] = DEFAULT_PREFERRED_ROOT_NAMES
    max_include_depth: int = DEFAULT_MAX_INCLUDE_DEPTH
    ignored_metadata_names: Tuple[str, ...] = DEFAULT_IGNORED_METADATA_NAMES
    ignored_directory_names: Tuple[str, ...] = DEFAULT_IGNORED_DIRECTORY_NAMES
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        limits = self.limits
        if isinstance(limits, Mapping):
            limits = LatexProjectSafetyLimits.from_dict(limits)
        if not isinstance(limits, LatexProjectSafetyLimits):
            raise LatexProjectValidationError(
                "limits must be LatexProjectSafetyLimits or a mapping"
            )
        roots = _root_name_tuple(self.preferred_root_names)
        include_depth = _positive_int(
            self.max_include_depth,
            "max_include_depth",
        )
        ignored_names = _string_tuple(
            self.ignored_metadata_names,
            "ignored_metadata_names",
            default=DEFAULT_IGNORED_METADATA_NAMES,
            casefold_unique=True,
        )
        ignored_dirs = _string_tuple(
            self.ignored_directory_names,
            "ignored_directory_names",
            default=DEFAULT_IGNORED_DIRECTORY_NAMES,
            casefold_unique=True,
        )
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "preferred_root_names", roots)
        object.__setattr__(self, "max_include_depth", include_depth)
        object.__setattr__(self, "ignored_metadata_names", ignored_names)
        object.__setattr__(self, "ignored_directory_names", ignored_dirs)
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    def to_dict(self):
        return {
            "schema_version": LATEX_PROJECT_CONFIG_SCHEMA_VERSION,
            "limits": self.limits.to_dict(),
            "resolution": {
                "preferred_root_names": list(self.preferred_root_names),
                "max_include_depth": self.max_include_depth,
            },
            "ignored_metadata_names": list(self.ignored_metadata_names),
            "ignored_directory_names": list(self.ignored_directory_names),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise LatexProjectSerializationError(
                "LatexProjectIngestionConfig data must be a mapping"
            )
        version = data.get(
            "schema_version",
            LATEX_PROJECT_CONFIG_SCHEMA_VERSION,
        )
        if str(version) not in ("1", LATEX_PROJECT_CONFIG_SCHEMA_VERSION):
            raise UnsupportedLatexProjectSchemaError(
                "Unsupported LaTeX-project config schema %r; expected %r"
                % (version, LATEX_PROJECT_CONFIG_SCHEMA_VERSION)
            )
        allowed = {
            "schema_version",
            "limits",
            "resolution",
            "ignored_metadata_names",
            "ignored_directory_names",
            "metadata",
        }
        unknown = set(data) - allowed
        if unknown:
            raise LatexProjectValidationError(
                "Unsupported LaTeX-project config option(s): %s"
                % ", ".join(sorted(str(item) for item in unknown))
            )
        resolution = data.get("resolution", {})
        if resolution is None:
            resolution = {}
        if not isinstance(resolution, Mapping):
            raise LatexProjectSerializationError("resolution must be a mapping")
        allowed_resolution = {
            "preferred_root_names",
            "max_include_depth",
        }
        unknown_resolution = set(resolution) - allowed_resolution
        if unknown_resolution:
            raise LatexProjectValidationError(
                "Unsupported resolution option(s): %s"
                % ", ".join(sorted(str(item) for item in unknown_resolution))
            )
        return cls(
            limits=LatexProjectSafetyLimits.from_dict(data.get("limits", {})),
            preferred_root_names=tuple(
                resolution.get(
                    "preferred_root_names",
                    DEFAULT_PREFERRED_ROOT_NAMES,
                )
            ),
            max_include_depth=resolution.get(
                "max_include_depth",
                DEFAULT_MAX_INCLUDE_DEPTH,
            ),
            ignored_metadata_names=tuple(
                data.get(
                    "ignored_metadata_names",
                    DEFAULT_IGNORED_METADATA_NAMES,
                )
            ),
            ignored_directory_names=tuple(
                data.get(
                    "ignored_directory_names",
                    DEFAULT_IGNORED_DIRECTORY_NAMES,
                )
            ),
            metadata=data.get("metadata", {}),
        )


def load_latex_project_config(path):
    """Load and validate a deterministic JSON ingestion configuration."""

    config_path = Path(path).expanduser()
    if config_path.is_symlink():
        raise LatexProjectValidationError(
            "Symlinked LaTeX-project config files are not accepted: %s"
            % config_path
        )
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(str(config_path))
    if not config_path.is_file():
        raise IsADirectoryError(str(config_path))
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LatexProjectSerializationError(
            "Invalid LaTeX-project JSON in %s: %s" % (config_path, exc)
        )
    except UnicodeError as exc:
        raise LatexProjectSerializationError(
            "LaTeX-project config is not valid UTF-8: %s" % exc
        )
    return LatexProjectIngestionConfig.from_dict(payload)


def save_latex_project_config(config, path):
    """Write one validated ingestion configuration as deterministic UTF-8 JSON."""

    if not isinstance(config, LatexProjectIngestionConfig):
        raise TypeError("config must be LatexProjectIngestionConfig")
    output = Path(path).expanduser()
    if output.exists() and output.is_symlink():
        raise LatexProjectValidationError(
            "Refusing to write LaTeX-project config through symlink: %s" % output
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        config.to_dict(),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    output.write_text(text, encoding="utf-8")
    return output.resolve()


__all__ = [
    "DEFAULT_IGNORED_DIRECTORY_NAMES",
    "DEFAULT_IGNORED_METADATA_NAMES",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_FILE_COUNT",
    "DEFAULT_MAX_INCLUDE_DEPTH",
    "DEFAULT_MAX_MEMBER_BYTES",
    "DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES",
    "DEFAULT_PREFERRED_ROOT_NAMES",
    "LATEX_PROJECT_CONFIG_SCHEMA_VERSION",
    "LatexProjectIngestionConfig",
    "LatexProjectSafetyLimits",
    "load_latex_project_config",
    "save_latex_project_config",
]
