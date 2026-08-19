"""Configuration schema for v2.3.3 Programming Submission & Autograding.

Commit 1 uses JSON deliberately: the project gains no new third-party package,
and later bundle ingestion can hash one canonical serialized configuration.
The schema is strict enough to catch grading-policy mistakes before untrusted
student code is ever executable.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Dict, Mapping, Optional, Tuple

from .errors import (
    AutogradingSerializationError,
    AutogradingValidationError,
    UnsupportedAutogradingLanguageError,
    UnsupportedAutogradingRunnerError,
    UnsupportedAutogradingSchemaError,
)
from .models import ResourceLimits, TestDefinition, TestGroup


AUTOGRADING_CONFIG_SCHEMA_VERSION = "1.0"
SUPPORTED_AUTOGRADING_LANGUAGES = ("python",)
SUPPORTED_AUTOGRADING_RUNNERS = ("pytest",)

SCORING_METHOD_EXPLICIT_TEST_POINTS = "explicit_test_points"
SCORING_METHOD_EQUAL_WITHIN_GROUP = "equal_within_group"
SUPPORTED_SCORING_METHODS = (
    SCORING_METHOD_EXPLICIT_TEST_POINTS,
    SCORING_METHOD_EQUAL_WITHIN_GROUP,
)

DEFAULT_REPORTING_POLICY = {
    "show_public_test_details": True,
    "show_hidden_test_names_to_students": False,
}

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _text(value, name):
    value = "" if value is None else str(value).strip()
    if not value:
        raise AutogradingValidationError("%s must not be empty" % name)
    return value


def _finite_float(value, name, strictly_positive=False):
    if isinstance(value, bool):
        raise AutogradingValidationError("%s must be numeric, not boolean" % name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AutogradingValidationError("%s must be numeric" % name)
    if not math.isfinite(number):
        raise AutogradingValidationError("%s must be finite" % name)
    if strictly_positive and number <= 0:
        raise AutogradingValidationError("%s must be greater than zero" % name)
    return number


def _metadata(value, name="metadata"):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AutogradingValidationError("%s must be a mapping" % name)
    return deepcopy(dict(value))


def _normalize_relative_path(value, name):
    raw = _text(value, name).replace("\\", "/")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise AutogradingValidationError("%s must be a relative path" % name)
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise AutogradingValidationError("%s must be a relative path" % name)
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        raise AutogradingValidationError(
            "%s must not contain parent traversal" % name
        )
    normalized = "/".join(parts)
    if normalized.startswith("/"):
        raise AutogradingValidationError("%s must be a relative path" % name)
    return normalized


def _normalize_required_files(values, entrypoint):
    if values is None:
        values = ()
    if isinstance(values, (str, bytes, Mapping)):
        raise AutogradingValidationError("required_files must be an ordered sequence")
    result = []
    seen = set()
    for raw in values:
        value = _normalize_relative_path(raw, "required_files entry")
        if value in seen:
            raise AutogradingValidationError(
                "required_files contains duplicate path %r" % value
            )
        seen.add(value)
        result.append(value)
    if entrypoint not in seen:
        result.insert(0, entrypoint)
    return tuple(result)


def _coerce_tests(values):
    if values is None:
        values = ()
    if isinstance(values, (str, bytes)):
        raise AutogradingValidationError("tests must be a sequence")
    result = []
    for value in values:
        if isinstance(value, TestDefinition):
            result.append(value)
        elif isinstance(value, Mapping):
            result.append(TestDefinition.from_dict(value))
        else:
            raise AutogradingValidationError(
                "tests must contain TestDefinition objects or mappings"
            )
    if not result:
        raise AutogradingValidationError("at least one test is required")
    ids = [item.test_id for item in result]
    if len(ids) != len(set(ids)):
        raise AutogradingValidationError("test_id values must be unique")
    return tuple(result)


def _coerce_groups(values):
    if values is None:
        values = ()
    if isinstance(values, (str, bytes)):
        raise AutogradingValidationError("groups must be a sequence")
    result = []
    for value in values:
        if isinstance(value, TestGroup):
            result.append(value)
        elif isinstance(value, Mapping):
            result.append(TestGroup.from_dict(value))
        else:
            raise AutogradingValidationError(
                "groups must contain TestGroup objects or mappings"
            )
    ids = [item.group_id for item in result]
    if len(ids) != len(set(ids)):
        raise AutogradingValidationError("group_id values must be unique")
    return tuple(result)


def _normalize_reporting_policy(value):
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise AutogradingValidationError("reporting must be a mapping")
    unknown = set(value) - set(DEFAULT_REPORTING_POLICY)
    if unknown:
        raise AutogradingValidationError(
            "Unsupported reporting option(s): %s"
            % ", ".join(sorted(str(item) for item in unknown))
        )
    result = dict(DEFAULT_REPORTING_POLICY)
    result.update(dict(value))
    for key, item in result.items():
        if not isinstance(item, bool):
            raise AutogradingValidationError("reporting.%s must be boolean" % key)
    return result


def _close(left, right):
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)


def _validate_scoring(max_points, tests, groups, scoring_method):
    if scoring_method not in SUPPORTED_SCORING_METHODS:
        raise AutogradingValidationError(
            "scoring method must be one of: %s"
            % ", ".join(SUPPORTED_SCORING_METHODS)
        )

    if not groups:
        if scoring_method != SCORING_METHOD_EXPLICIT_TEST_POINTS:
            raise AutogradingValidationError(
                "equal_within_group scoring requires at least one group"
            )
        grouped_tests = [item for item in tests if item.group_id is not None]
        if grouped_tests:
            raise AutogradingValidationError(
                "tests may not declare group_id when no groups are configured"
            )
        missing = [item.test_id for item in tests if item.points is None]
        if missing:
            raise AutogradingValidationError(
                "explicit_test_points requires points for every test: %s"
                % ", ".join(missing)
            )
        total = sum(float(item.points) for item in tests)
        if not _close(total, max_points):
            raise AutogradingValidationError(
                "test points sum to %.6g but max_points is %.6g"
                % (total, max_points)
            )
        return

    by_group = {group.group_id: group for group in groups}
    assigned = {group.group_id: [] for group in groups}
    for test in tests:
        if test.group_id is None:
            raise AutogradingValidationError(
                "every test must declare group_id when groups are configured"
            )
        if test.group_id not in by_group:
            raise AutogradingValidationError(
                "test %r references unknown group_id %r"
                % (test.test_id, test.group_id)
            )
        assigned[test.group_id].append(test)

    empty_groups = [group_id for group_id, items in assigned.items() if not items]
    if empty_groups:
        raise AutogradingValidationError(
            "every configured group must contain at least one test: %s"
            % ", ".join(empty_groups)
        )

    group_total = sum(group.points for group in groups)
    if not _close(group_total, max_points):
        raise AutogradingValidationError(
            "group points sum to %.6g but max_points is %.6g"
            % (group_total, max_points)
        )

    if scoring_method == SCORING_METHOD_EXPLICIT_TEST_POINTS:
        missing = [test.test_id for test in tests if test.points is None]
        if missing:
            raise AutogradingValidationError(
                "explicit_test_points requires points for every test: %s"
                % ", ".join(missing)
            )
        for group in groups:
            total = sum(float(test.points) for test in assigned[group.group_id])
            if not _close(total, group.points):
                raise AutogradingValidationError(
                    "test points in group %r sum to %.6g but group points is %.6g"
                    % (group.group_id, total, group.points)
                )
    else:
        explicit = [test.test_id for test in tests if test.points is not None]
        if explicit:
            raise AutogradingValidationError(
                "equal_within_group requires test points to be omitted: %s"
                % ", ".join(explicit)
            )


@dataclass(frozen=True)
class AutogradingConfig:
    """Validated programming-autograder configuration for one assessment."""

    assessment_id: str
    max_points: float
    tests: Tuple[TestDefinition, ...]
    groups: Tuple[TestGroup, ...] = field(default_factory=tuple)
    language: str = "python"
    runner_type: str = "pytest"
    entrypoint: str = "submission.py"
    required_files: Tuple[str, ...] = field(default_factory=tuple)
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    scoring_method: str = SCORING_METHOD_EXPLICIT_TEST_POINTS
    reporting_policy: Dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_REPORTING_POLICY)
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        assessment_id = _text(self.assessment_id, "assessment_id")
        language = _text(self.language, "language").lower()
        runner_type = _text(self.runner_type, "runner_type").lower()
        if language not in SUPPORTED_AUTOGRADING_LANGUAGES:
            raise UnsupportedAutogradingLanguageError(
                "Unsupported autograding language %r; expected one of: %s"
                % (language, ", ".join(SUPPORTED_AUTOGRADING_LANGUAGES))
            )
        if runner_type not in SUPPORTED_AUTOGRADING_RUNNERS:
            raise UnsupportedAutogradingRunnerError(
                "Unsupported autograding runner %r; expected one of: %s"
                % (runner_type, ", ".join(SUPPORTED_AUTOGRADING_RUNNERS))
            )
        maximum = _finite_float(self.max_points, "max_points", strictly_positive=True)
        entrypoint = _normalize_relative_path(self.entrypoint, "entrypoint")
        required_files = _normalize_required_files(self.required_files, entrypoint)
        tests = _coerce_tests(self.tests)
        groups = _coerce_groups(self.groups)
        if isinstance(self.resource_limits, ResourceLimits):
            resource_limits = self.resource_limits
        elif isinstance(self.resource_limits, Mapping):
            resource_limits = ResourceLimits.from_dict(self.resource_limits)
        else:
            raise AutogradingValidationError(
                "resource_limits must be ResourceLimits or a mapping"
            )
        scoring_method = _text(self.scoring_method, "scoring_method").lower()
        reporting = _normalize_reporting_policy(self.reporting_policy)
        metadata = _metadata(self.metadata)

        _validate_scoring(maximum, tests, groups, scoring_method)

        object.__setattr__(self, "assessment_id", assessment_id)
        object.__setattr__(self, "max_points", maximum)
        object.__setattr__(self, "tests", tests)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "runner_type", runner_type)
        object.__setattr__(self, "entrypoint", entrypoint)
        object.__setattr__(self, "required_files", required_files)
        object.__setattr__(self, "resource_limits", resource_limits)
        object.__setattr__(self, "scoring_method", scoring_method)
        object.__setattr__(self, "reporting_policy", reporting)
        object.__setattr__(self, "metadata", metadata)

    def test_by_id(self, test_id):
        test_id = str(test_id or "").strip()
        for test in self.tests:
            if test.test_id == test_id:
                return test
        return None

    def group_by_id(self, group_id):
        group_id = str(group_id or "").strip()
        for group in self.groups:
            if group.group_id == group_id:
                return group
        return None

    def tests_for_group(self, group_id):
        group_id = str(group_id or "").strip()
        return tuple(test for test in self.tests if test.group_id == group_id)

    def to_dict(self):
        return {
            "schema_version": AUTOGRADING_CONFIG_SCHEMA_VERSION,
            "assessment_id": self.assessment_id,
            "language": self.language,
            "runner_type": self.runner_type,
            "entrypoint": self.entrypoint,
            "required_files": list(self.required_files),
            "max_points": self.max_points,
            "tests": [test.to_dict() for test in self.tests],
            "groups": [group.to_dict() for group in self.groups],
            "resource_limits": self.resource_limits.to_dict(),
            "scoring": {"method": self.scoring_method},
            "reporting": deepcopy(self.reporting_policy),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise AutogradingSerializationError(
                "AutogradingConfig data must be a mapping"
            )
        version = data.get("schema_version", AUTOGRADING_CONFIG_SCHEMA_VERSION)
        if str(version) not in ("1", AUTOGRADING_CONFIG_SCHEMA_VERSION):
            raise UnsupportedAutogradingSchemaError(
                "Unsupported autograding config schema %r; expected %r"
                % (version, AUTOGRADING_CONFIG_SCHEMA_VERSION)
            )

        scoring = data.get("scoring", {})
        if scoring is None:
            scoring = {}
        if not isinstance(scoring, Mapping):
            raise AutogradingSerializationError("scoring must be a mapping")
        unknown_scoring = set(scoring) - {"method"}
        if unknown_scoring:
            raise AutogradingValidationError(
                "Unsupported scoring option(s): %s"
                % ", ".join(sorted(str(item) for item in unknown_scoring))
            )

        tests = tuple(
            TestDefinition.from_dict(item)
            if isinstance(item, Mapping)
            else item
            for item in (data.get("tests") or ())
        )
        groups = tuple(
            TestGroup.from_dict(item)
            if isinstance(item, Mapping)
            else item
            for item in (data.get("groups") or ())
        )

        raw_max_points = data.get("max_points")
        if raw_max_points is None:
            # Convenience for the simplest explicit-test configuration.  The
            # canonical serialized form still writes max_points explicitly.
            if groups:
                raw_max_points = sum(group.points for group in groups)
            elif tests and all(test.points is not None for test in tests):
                raw_max_points = sum(float(test.points) for test in tests)
            else:
                raise AutogradingValidationError(
                    "max_points is required when it cannot be derived safely"
                )

        return cls(
            assessment_id=data.get("assessment_id"),
            max_points=raw_max_points,
            tests=tests,
            groups=groups,
            language=data.get("language", "python"),
            runner_type=data.get("runner_type", "pytest"),
            entrypoint=data.get("entrypoint", "submission.py"),
            required_files=tuple(data.get("required_files") or ()),
            resource_limits=(
                ResourceLimits.from_dict(data.get("resource_limits", {}))
                if isinstance(data.get("resource_limits", {}), Mapping)
                else data.get("resource_limits")
            ),
            scoring_method=scoring.get(
                "method",
                SCORING_METHOD_EXPLICIT_TEST_POINTS,
            ),
            reporting_policy=data.get("reporting", DEFAULT_REPORTING_POLICY),
            metadata=data.get("metadata", {}),
        )


def load_autograding_config(path):
    """Load and validate an ``autograder.json``-style config from disk."""

    config_path = Path(path).expanduser()
    if config_path.is_symlink():
        raise AutogradingValidationError(
            "Symlinked autograding config files are not accepted: %s" % config_path
        )
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(str(config_path))
    if not config_path.is_file():
        raise IsADirectoryError(str(config_path))
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AutogradingSerializationError(
            "Invalid autograding JSON in %s: %s" % (config_path, exc)
        )
    except UnicodeError as exc:
        raise AutogradingSerializationError(
            "Autograding config is not valid UTF-8: %s" % exc
        )
    return AutogradingConfig.from_dict(payload)


def save_autograding_config(config, path):
    """Write one validated config as deterministic UTF-8 JSON.

    This helper is intended for fixtures/tools.  Commit 2 owns immutable bundle
    storage and will not overwrite committed package files in place.
    """

    if not isinstance(config, AutogradingConfig):
        raise TypeError("config must be an AutogradingConfig")
    output = Path(path).expanduser()
    if output.exists() and output.is_symlink():
        raise AutogradingValidationError(
            "Refusing to write autograding config through symlink: %s" % output
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
    "AUTOGRADING_CONFIG_SCHEMA_VERSION",
    "AutogradingConfig",
    "DEFAULT_REPORTING_POLICY",
    "SCORING_METHOD_EQUAL_WITHIN_GROUP",
    "SCORING_METHOD_EXPLICIT_TEST_POINTS",
    "SUPPORTED_AUTOGRADING_LANGUAGES",
    "SUPPORTED_AUTOGRADING_RUNNERS",
    "SUPPORTED_SCORING_METHODS",
    "load_autograding_config",
    "save_autograding_config",
]
