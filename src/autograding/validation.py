"""Security-focused validation helpers for instructor autograding bundles.

v2.3.3 Commit 2 validates *instructor* test packages before they are copied into
immutable workspace storage.  Nothing in this module imports or executes test
code.  The helpers operate only on paths, bytes, text, and declarations.

The accepted top-level bundle layout is intentionally narrow::

    autograder.json
    tests/
    support/          # optional
    requirements.txt  # optional

This keeps accidental secrets, caches, virtual environments, and unrelated
files out of a committed grader package.
"""

from pathlib import Path, PurePosixPath
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .errors import AutogradingBundleValidationError


AUTOGRADER_CONFIG_FILENAME = "autograder.json"
TESTS_DIRECTORY = "tests"
SUPPORT_DIRECTORY = "support"
REQUIREMENTS_FILENAME = "requirements.txt"

ALLOWED_TOP_LEVEL_ENTRIES = (
    AUTOGRADER_CONFIG_FILENAME,
    TESTS_DIRECTORY,
    SUPPORT_DIRECTORY,
    REQUIREMENTS_FILENAME,
)
IGNORED_BUNDLE_METADATA_FILENAMES = (".DS_Store", "Thumbs.db")

DEFAULT_MAX_BUNDLE_FILES = 1000
DEFAULT_MAX_BUNDLE_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_BUNDLE_TOTAL_BYTES = 100 * 1024 * 1024

_TEST_FUNCTION_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(test_[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    flags=re.MULTILINE,
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNSAFE_REQUIREMENT_RE = re.compile(
    r"(?:^\s*-|://|\bgit\+|\bfile:|\bsvn\+|\bhg\+|\bbzr\+|"
    r"^\s*(?:\.{1,2}/|/|[A-Za-z]:[\\/])|"
    r"\s@\s*(?:\.{1,2}/|/|[A-Za-z]:[\\/]))",
    flags=re.IGNORECASE,
)


def normalize_bundle_relative_path(value, name="bundle path"):
    """Return one safe POSIX-style path relative to the bundle root."""

    text = "" if value is None else str(value).strip()
    if not text:
        raise AutogradingBundleValidationError("%s must not be empty" % name)
    if "\x00" in text:
        raise AutogradingBundleValidationError("%s contains a NUL byte" % name)
    if _WINDOWS_DRIVE_RE.match(text):
        raise AutogradingBundleValidationError("%s must be relative" % name)

    text = text.replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute():
        raise AutogradingBundleValidationError("%s must be relative" % name)

    parts = path.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise AutogradingBundleValidationError(
            "%s contains an unsafe path component" % name
        )
    if any(part.startswith(".") for part in parts):
        raise AutogradingBundleValidationError(
            "%s may not contain hidden path components" % name
        )
    return "/".join(parts)


def reject_symlink_chain(path, label="path", anchor=None):
    """Reject symlinks at a trust boundary or inside an app-controlled tree.

    A path selected by the user may legitimately live underneath an operating-
    system symlink.  macOS is the important example: ``/var`` is a symlink to
    ``/private/var``, and Python's temporary directories normally live below
    ``/var/folders``.  Rejecting *every* ancestor symlink therefore rejects
    ordinary, safe paths before the application reaches the selected directory.

    With no ``anchor``, only the selected path itself is treated as the trust
    boundary and rejected when that final component is a symlink.  Callers that
    own a directory tree can pass ``anchor``; every component from that anchor
    through ``path`` is then checked.  Symlinks above the anchor are deliberately
    outside this helper's trust boundary.
    """

    requested = Path(path).expanduser()

    if anchor is None:
        try:
            if requested.is_symlink():
                raise AutogradingBundleValidationError(
                    "Symlinked %s is not accepted: %s" % (label, requested)
                )
        except OSError as exc:
            raise AutogradingBundleValidationError(
                "Could not inspect %s %s: %s" % (label, requested, exc)
            )
        return

    anchor_path = Path(anchor).expanduser()
    try:
        absolute_anchor = anchor_path.absolute()
        absolute_requested = requested.absolute()
    except OSError as exc:
        raise AutogradingBundleValidationError(
            "Could not inspect %s: %s" % (label, exc)
        )

    try:
        relative = absolute_requested.relative_to(absolute_anchor)
    except ValueError:
        raise AutogradingBundleValidationError(
            "%s is outside the trusted path boundary: %s"
            % (label.capitalize(), absolute_anchor)
        )

    current = absolute_anchor
    components = (current,)
    if relative.parts:
        built = []
        for part in relative.parts:
            current = current / part
            built.append(current)
        components = (absolute_anchor,) + tuple(built)

    for current in components:
        try:
            if current.is_symlink():
                raise AutogradingBundleValidationError(
                    "Symlinked %s is not accepted: %s" % (label, current)
                )
        except OSError as exc:
            raise AutogradingBundleValidationError(
                "Could not inspect %s %s: %s" % (label, current, exc)
            )


def validate_requirements_text(text):
    """Apply a conservative static policy to optional ``requirements.txt``.

    Commit 2 does not install dependencies.  The purpose of this validation is
    to keep obviously host/path/VCS/network-oriented pip directives out of the
    immutable bundle contract before later execution-image work consumes it.
    Standard package requirement lines remain allowed.
    """

    if text is None:
        return ()
    if not isinstance(text, str):
        text = str(text)
    if "\x00" in text:
        raise AutogradingBundleValidationError(
            "requirements.txt contains a NUL byte"
        )

    normalized = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _UNSAFE_REQUIREMENT_RE.search(line):
            raise AutogradingBundleValidationError(
                "requirements.txt line %d uses an unsupported URL, VCS, local-file, "
                "or pip-option form" % line_number
            )
        normalized.append(line)
    return tuple(normalized)


def discover_test_function_names(text):
    """Return scoring-test function names visible in one Python test file.

    This is deliberately lexical, not executable and not tied to the host
    Python parser version.  It therefore remains usable when the eventual
    container runtime targets a newer Python syntax than the desktop app.
    """

    if not isinstance(text, str):
        text = str(text)
    return tuple(_TEST_FUNCTION_RE.findall(text))


def _split_pytest_node_id(test_id):
    parts = str(test_id or "").split("::")
    if len(parts) < 2:
        return None
    file_part = parts[0].strip()
    object_parts = [part.strip() for part in parts[1:] if part.strip()]
    if not file_part or not object_parts:
        return None
    return file_part, tuple(object_parts)


def validate_declared_test_ids(config, python_test_text_by_path):
    """Validate config test IDs against statically discoverable test functions.

    Two declaration styles are supported:

    * simple ID: ``test_empty`` -- must match one globally unique function name;
    * explicit pytest-style ID: ``tests/test_a.py::test_empty`` (or with a class
      component) -- the referenced file must exist and its final function name
      must be discoverable there.

    Every discoverable ``test_*`` function must also be declared.  This prevents
    an instructor from accidentally shipping scoring tests that are omitted from
    the point/visibility policy.
    """

    if config.runner_type != "pytest":
        return

    discovered_by_name = {}  # type: Dict[str, List[str]]
    discovered_by_path = {}  # type: Dict[str, Set[str]]
    for raw_path, raw_text in python_test_text_by_path.items():
        path = normalize_bundle_relative_path(raw_path, "test file path")
        names = set(discover_test_function_names(raw_text))
        discovered_by_path[path] = names
        for name in sorted(names):
            discovered_by_name.setdefault(name, []).append(path)

    if not discovered_by_name:
        raise AutogradingBundleValidationError(
            "tests/ does not contain any discoverable test_* functions"
        )

    declared_locations = set()  # type: Set[Tuple[str, str]]
    for test in config.tests:
        test_id = test.test_id
        selector = test.metadata.get("pytest_nodeid")
        if selector is not None:
            selector = str(selector).strip()
            if not selector:
                raise AutogradingBundleValidationError(
                    "metadata.pytest_nodeid for test_id %r must not be empty" % test_id
                )
        else:
            selector = test_id

        explicit = _split_pytest_node_id(selector)
        if explicit is not None:
            file_part, object_parts = explicit
            normalized_file = normalize_bundle_relative_path(
                file_part,
                "pytest test_id file path",
            )
            if not normalized_file.startswith(TESTS_DIRECTORY + "/"):
                raise AutogradingBundleValidationError(
                    "pytest test_id %r must reference a file under tests/" % test_id
                )
            if normalized_file not in discovered_by_path:
                raise AutogradingBundleValidationError(
                    "pytest test_id %r references unknown test file %r"
                    % (test_id, normalized_file)
                )
            function_name = object_parts[-1].split("[", 1)[0]
            if function_name not in discovered_by_path[normalized_file]:
                raise AutogradingBundleValidationError(
                    "pytest test_id %r references unknown function %r"
                    % (test_id, function_name)
                )
            location = (normalized_file, function_name)
        else:
            simple_name = str(selector).strip()
            matches = discovered_by_name.get(simple_name, [])
            if not matches:
                raise AutogradingBundleValidationError(
                    "configured test_id %r resolves to unknown pytest test %r"
                    % (test_id, simple_name)
                )
            if len(matches) > 1:
                raise AutogradingBundleValidationError(
                    "test selector %r for test_id %r is ambiguous across files: %s; "
                    "use an explicit pytest-style node ID"
                    % (simple_name, test_id, ", ".join(sorted(matches)))
                )
            location = (matches[0], simple_name)

        if location in declared_locations:
            raise AutogradingBundleValidationError(
                "multiple configured test IDs resolve to the same test function: %s::%s"
                % location
            )
        declared_locations.add(location)

    undisclosed = []
    for path in sorted(discovered_by_path):
        for function_name in sorted(discovered_by_path[path]):
            if (path, function_name) not in declared_locations:
                undisclosed.append("%s::%s" % (path, function_name))
    if undisclosed:
        raise AutogradingBundleValidationError(
            "bundle contains undeclared pytest test function(s): %s"
            % ", ".join(undisclosed)
        )


def classify_bundle_file(relative_path):
    """Return a stable role label for one accepted bundle file."""

    path = normalize_bundle_relative_path(relative_path)
    if path == AUTOGRADER_CONFIG_FILENAME:
        return "config"
    if path == REQUIREMENTS_FILENAME:
        return "requirements"
    if path == TESTS_DIRECTORY or path.startswith(TESTS_DIRECTORY + "/"):
        return "test"
    if path == SUPPORT_DIRECTORY or path.startswith(SUPPORT_DIRECTORY + "/"):
        return "support"
    return "other"


__all__ = [
    "ALLOWED_TOP_LEVEL_ENTRIES",
    "AUTOGRADER_CONFIG_FILENAME",
    "DEFAULT_MAX_BUNDLE_FILE_BYTES",
    "DEFAULT_MAX_BUNDLE_FILES",
    "DEFAULT_MAX_BUNDLE_TOTAL_BYTES",
    "IGNORED_BUNDLE_METADATA_FILENAMES",
    "REQUIREMENTS_FILENAME",
    "SUPPORT_DIRECTORY",
    "TESTS_DIRECTORY",
    "classify_bundle_file",
    "discover_test_function_names",
    "normalize_bundle_relative_path",
    "reject_symlink_chain",
    "validate_declared_test_ids",
    "validate_requirements_text",
]
