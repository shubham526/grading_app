"""Shared fixtures for v2.3.3 autograding tests."""

import json
from pathlib import Path

from src.autograding.bundle_store import TestBundleStore
from src.submissions.domain import (
    ARTIFACT_ROLE_PRIMARY,
    ARTIFACT_TYPE_PYTHON,
    CandidateFile,
)
from src.submissions.repository import SubmissionRepository


def write_test_bundle(root, assessment_id="LAB1", *, required_files=None):
    root = Path(root)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": "1.0",
        "assessment_id": assessment_id,
        "language": "python",
        "runner_type": "pytest",
        "entrypoint": "main.py",
        "required_files": list(required_files or ["helpers.py"]),
        "max_points": 10,
        "tests": [
            {
                "test_id": "test_basic",
                "name": "Basic",
                "visibility": "public",
                "points": 10,
            }
        ],
        "resource_limits": {
            "wall_timeout_seconds": 7,
            "memory_mb": 384,
            "cpu_count": 1,
            "pids_limit": 64,
            "stdout_max_bytes": 4096,
            "stderr_max_bytes": 4096,
            "network_enabled": False,
        },
    }
    (root / "autograder.json").write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_public.py").write_text(
        "def test_basic():\n    assert True\n",
        encoding="utf-8",
    )
    return root


def make_bundle_store(workspace):
    return TestBundleStore(
        workspace,
        now_fn=lambda: "2026-08-19T20:00:00Z",
        bundle_id_factory=lambda: "bundle_test_v1",
    )


def import_test_bundle(workspace, source, assessment_id="LAB1"):
    store = make_bundle_store(workspace)
    result = store.import_bundle(source, expected_assessment_id=assessment_id)
    return store, result.bundle


def make_submission_repository(root):
    return SubmissionRepository(str(root))


def create_python_submission(
    repository,
    source_root,
    *,
    assessment_id="LAB1",
    student_id="alice",
    files=None,
    make_active=True,
    attempt=None,
    programming_paths=None,
):
    source_root = Path(source_root)
    source_root.mkdir(parents=True, exist_ok=True)
    files = files or {
        "main.py": "VALUE = 1\n",
        "helpers.py": "def helper():\n    return 1\n",
    }
    programming_paths = programming_paths or {}
    candidates = []
    for name, content in files.items():
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        candidates.append(
            CandidateFile(
                source_path=str(path),
                original_filename=Path(name).name,
                artifact_type=ARTIFACT_TYPE_PYTHON,
                role=ARTIFACT_ROLE_PRIMARY,
                metadata=(
                    {"programming_relative_path": programming_paths[name]}
                    if name in programming_paths
                    else {}
                ),
            )
        )
    return repository.create_submission(
        assessment_id=assessment_id,
        student_id=student_id,
        files=candidates,
        make_active=make_active,
        attempt=attempt,
        imported_at="2026-08-19T19:00:00Z",
    )
