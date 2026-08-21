"""Self-contained v2.3.3 release fixture used by repository regressions.

Commit v2.3.4.2 hardening removes the historical dependency on an untracked
repository-root ``fixtures/`` directory.  Tests build the same release-shaped
fixture beneath a temporary directory instead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ASSESSMENT_ID = "V233_AUTO1"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(root: Path) -> None:
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.name == "MANIFEST.txt":
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((relative, digest))
    lines = [
        "v2.3.3 autograding release acceptance fixture",
        "relative_path  sha256",
    ]
    lines.extend("%s  %s" % item for item in entries)
    _write(root / "MANIFEST.txt", "\n".join(lines) + "\n")


def write_release_fixture(root) -> Path:
    """Create a deterministic Docker-independent v2.3.3 acceptance fixture."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    bundle = root / "autograder_bundle"
    config = {
        "schema_version": "1.0",
        "assessment_id": ASSESSMENT_ID,
        "language": "python",
        "runner_type": "pytest",
        "entrypoint": "main.py",
        "required_files": ["main.py"],
        "max_points": 10,
        "tests": [
            {
                "test_id": "public_basic",
                "name": "Public basic behavior",
                "visibility": "public",
                "points": 4,
                "metadata": {
                    "pytest_nodeid": "tests/test_release.py::test_public_basic"
                },
            },
            {
                "test_id": "hidden_zero",
                "name": "Hidden zero behavior",
                "visibility": "hidden",
                "points": 3,
                "metadata": {
                    "pytest_nodeid": "tests/test_release.py::test_hidden_zero"
                },
            },
            {
                "test_id": "hidden_negative",
                "name": "Hidden negative behavior",
                "visibility": "hidden",
                "points": 3,
                "metadata": {
                    "pytest_nodeid": "tests/test_release.py::test_hidden_negative"
                },
            },
        ],
        "resource_limits": {
            "wall_timeout_seconds": 8,
            "memory_mb": 256,
            "cpu_count": 1,
            "pids_limit": 64,
            "stdout_max_bytes": 8192,
            "stderr_max_bytes": 8192,
            "network_enabled": False,
        },
    }
    _write(bundle / "autograder.json", json.dumps(config, indent=2) + "\n")
    _write(
        bundle / "tests" / "test_release.py",
        "def test_public_basic():\n"
        "    assert True\n\n"
        "def test_hidden_zero():\n"
        "    assert True\n\n"
        "def test_hidden_negative():\n"
        "    assert True\n",
    )

    submissions = {
        "aaron": "def solve(x):\n    return x\n",
        "alice": "def solve(x):\n    return max(0, x)\n",
        "bob": "def solve(x):\n    return 1\n",
        "carol": "def solve(:\n    return 0\n",
        "dave": "def solve(x):\n    return -x\n",
    }
    for student_id, source in submissions.items():
        _write(root / "submissions" / student_id / "main.py", source)

    expected = {
        "assessment_id": ASSESSMENT_ID,
        "students": {
            "aaron": {
                "statuses": {
                    "public_basic": "passed",
                    "hidden_zero": "passed",
                    "hidden_negative": "passed",
                },
                "score": 10.0,
                "requires_review": False,
            },
            "alice": {
                "statuses": {
                    "public_basic": "passed",
                    "hidden_zero": "passed",
                    "hidden_negative": "failed",
                },
                "score": 7.0,
                "requires_review": False,
            },
            "bob": {
                "statuses": {
                    "public_basic": "passed",
                    "hidden_zero": "failed",
                    "hidden_negative": "failed",
                },
                "score": 4.0,
                "requires_review": False,
            },
            "carol": {
                "statuses": {
                    "public_basic": "failed",
                    "hidden_zero": "failed",
                    "hidden_negative": "failed",
                },
                "score": 0.0,
                "requires_review": False,
            },
            "dave": {
                "statuses": {
                    "public_basic": "failed",
                    "hidden_zero": "passed",
                    "hidden_negative": "passed",
                },
                "score": 6.0,
                "requires_review": False,
            },
        },
    }
    _write(root / "EXPECTED_RESULTS.json", json.dumps(expected, indent=2) + "\n")
    _manifest(root)
    return root


__all__ = ["ASSESSMENT_ID", "write_release_fixture"]
