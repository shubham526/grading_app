"""Ephemeral host staging for isolated container execution.

The canonical submission repository and immutable grader-bundle store remain
source-of-truth.  A Docker run receives fresh copies in a temporary staging
root so the container never bind-mounts the grading workspace itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterable, Mapping, Optional

from ..errors import DockerSandboxError
from ..planner import ExecutionPlan
from ..workspace import PlannedWorkspaceFile


@dataclass(frozen=True)
class MaterializedSandbox:
    root: Path
    submission_dir: Path
    grader_dir: Path
    output_dir: Path
    runtime_dir: Optional[Path] = None


def _open_source_no_follow(path: Path):
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise DockerSandboxError("Could not open immutable execution input %s: %s" % (path, exc)) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DockerSandboxError("Execution input is not a regular file: %s" % path)
        return os.fdopen(fd, "rb")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _copy_verified(item: PlannedWorkspaceFile, destination_root: Path) -> None:
    source = Path(item.source_path)
    if source.is_symlink():
        raise DockerSandboxError("Symlinked execution inputs are not accepted: %s" % source)
    destination = destination_root / Path(*item.logical_path.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)

    digest = sha256()
    total = 0
    try:
        with _open_source_no_follow(source) as reader:
            with open(destination, "xb") as writer:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    writer.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
    except DockerSandboxError:
        raise
    except OSError as exc:
        raise DockerSandboxError(
            "Could not materialize execution input %s: %s" % (item.logical_path, exc)
        ) from exc

    if total != item.size_bytes:
        raise DockerSandboxError(
            "Execution input size changed for %s: expected %d, copied %d"
            % (item.logical_path, item.size_bytes, total)
        )
    actual = digest.hexdigest()
    if actual != item.sha256:
        raise DockerSandboxError(
            "Execution input hash changed for %s: expected %s, found %s"
            % (item.logical_path, item.sha256, actual)
        )
    try:
        os.chmod(destination, 0o444)
    except OSError as exc:
        raise DockerSandboxError("Could not mark staged input read-only: %s" % destination) from exc


def _copy_group(files: Iterable[PlannedWorkspaceFile], destination_root: Path) -> None:
    for item in tuple(files):
        _copy_verified(item, destination_root)



def _normalize_runtime_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip("/")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise DockerSandboxError("Runtime asset path must be a safe relative path")
    return "/".join(parts)


def _write_runtime_files(runtime_dir: Path, runtime_files: Mapping[str, bytes]) -> None:
    seen = set()
    for raw_path, raw_data in sorted(runtime_files.items(), key=lambda item: str(item[0]).casefold()):
        relative = _normalize_runtime_path(raw_path)
        folded = relative.casefold()
        if folded in seen:
            raise DockerSandboxError("Runtime asset path collision: %s" % relative)
        seen.add(folded)
        if not isinstance(raw_data, (bytes, bytearray)):
            raise DockerSandboxError("Runtime asset %s must be bytes" % relative)
        target = runtime_dir / Path(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(target, "xb") as handle:
                handle.write(bytes(raw_data))
            os.chmod(target, 0o444)
        except OSError as exc:
            raise DockerSandboxError("Could not stage runtime asset %s: %s" % (relative, exc)) from exc


def _prepare_permissions(root: Path, submission: Path, grader: Path, output: Path, runtime: Optional[Path] = None) -> None:
    # The production container runs as an unprivileged UID.  Staged read-only
    # directories therefore need traversal permission while the isolated output
    # directory needs write permission.  The entire tree is deleted after use.
    try:
        os.chmod(root, 0o755)
        for directory in (submission, grader):
            os.chmod(directory, 0o555)
        if runtime is not None:
            for directory in sorted((path for path in runtime.rglob("*") if path.is_dir()), key=lambda p: len(p.parts), reverse=True):
                os.chmod(directory, 0o555)
            os.chmod(runtime, 0o555)
        os.chmod(output, 0o777)
    except OSError as exc:
        raise DockerSandboxError("Could not set sandbox staging permissions: %s" % exc) from exc


class SandboxMaterializer:
    """Context manager owning one fresh host-side staging root."""

    def __init__(self, *, parent_dir: Optional[str] = None):
        self.parent_dir = None if parent_dir is None else str(Path(parent_dir).expanduser())
        self._root: Optional[Path] = None

    def materialize(self, plan: ExecutionPlan, runtime_files: Optional[Mapping[str, bytes]] = None) -> MaterializedSandbox:
        if not isinstance(plan, ExecutionPlan):
            raise TypeError("plan must be an ExecutionPlan")
        if self._root is not None:
            raise DockerSandboxError("SandboxMaterializer may materialize only once")
        try:
            root = Path(
                tempfile.mkdtemp(
                    prefix="grading_app_autograde_",
                    dir=self.parent_dir,
                )
            )
        except OSError as exc:
            raise DockerSandboxError("Could not create autograding sandbox staging root: %s" % exc) from exc

        self._root = root
        submission = root / "submission"
        grader = root / "grader"
        output = root / "output"
        runtime = root / "runtime" if runtime_files else None
        try:
            submission.mkdir()
            grader.mkdir()
            output.mkdir()
            if runtime is not None:
                runtime.mkdir()
            _copy_group(plan.workspace.submission_files, submission)
            _copy_group(plan.workspace.grader_files, grader)
            if runtime is not None:
                _write_runtime_files(runtime, runtime_files or {})
            _prepare_permissions(root, submission, grader, output, runtime)
        except Exception:
            self.cleanup()
            raise
        return MaterializedSandbox(
            root=root,
            submission_dir=submission,
            grader_dir=grader,
            output_dir=output,
            runtime_dir=runtime,
        )

    def cleanup(self) -> None:
        root = self._root
        self._root = None
        if root is None:
            return
        try:
            # Restore owner-write permission if the platform enforces the 0555
            # directory modes during recursive deletion.
            for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                try:
                    if path.is_dir() and not path.is_symlink():
                        os.chmod(path, 0o700)
                    elif path.is_file() and not path.is_symlink():
                        os.chmod(path, 0o600)
                except OSError:
                    pass
            try:
                os.chmod(root, 0o700)
            except OSError:
                pass
            shutil.rmtree(root)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise DockerSandboxError("Could not remove autograding sandbox staging root: %s" % exc) from exc

    def __enter__(self) -> "SandboxMaterializer":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.cleanup()
        return False


__all__ = [
    "MaterializedSandbox",
    "SandboxMaterializer",
]
