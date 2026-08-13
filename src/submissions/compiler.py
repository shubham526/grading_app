"""
Restricted LaTeX-to-PDF compilation for untrusted student submissions.

Compilation is intentionally isolated from the student's source directory:
regular source files are staged into a temporary workspace, symlinks are not
followed, shell escape is disabled, TeX open/read/write policy is restricted,
and each compiler pass has a hard wall-clock timeout.  This is a defense-in-
depth boundary, not a replacement for an OS/container sandbox when processing
truly adversarial LaTeX.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .models import CompilationResult


ALLOWED_ENGINES = ("pdflatex", "xelatex")
_DEFAULT_SKIPPED_DIRS = {".git", ".hg", ".svn", "__pycache__", ".grading_app_build"}


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n...[compiler output truncated]...\n"
    keep = max(0, max_chars - len(marker))
    return text[:keep] + marker


def _stage_source_tree(
    source_path: Path,
    workspace: Path,
    *,
    max_source_files: int,
    max_source_bytes: int,
    max_single_file_bytes: int,
) -> Tuple[Path, List[str]]:
    """Copy regular, non-symlink files from the submission root into workspace."""
    source_root = source_path.parent.resolve()
    staged_root = workspace / "source"
    staged_root.mkdir(parents=True, exist_ok=True)

    warnings: List[str] = []
    file_count = 0
    total_bytes = 0

    for path in sorted(source_root.rglob("*"), key=lambda p: str(p).casefold()):
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue

        if any(part in _DEFAULT_SKIPPED_DIRS for part in relative.parts):
            continue

        if path.is_symlink():
            warnings.append(f"skipped_symlink:{relative.as_posix()}")
            continue
        if not path.is_file():
            continue

        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValueError(f"Could not stat source file {path}: {exc}") from exc

        file_count += 1
        total_bytes += size
        if file_count > max_source_files:
            raise ValueError("latex_source_file_limit_exceeded")
        if size > max_single_file_bytes:
            raise ValueError(f"latex_source_file_too_large:{relative.as_posix()}")
        if total_bytes > max_source_bytes:
            raise ValueError("latex_source_total_size_exceeded")

        destination = staged_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    staged_main = staged_root / source_path.name
    if not staged_main.is_file():
        raise ValueError("latex_main_source_not_staged")
    return staged_main, warnings


def _compiler_environment(workspace: Path, output_dir: Path) -> Dict[str, str]:
    """Build a minimal environment for kpathsea/TeX execution."""
    home = workspace / "home"
    temp = workspace / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)

    env: Dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value

    env.update({
        "HOME": str(home),
        "TMPDIR": str(temp),
        "TEMP": str(temp),
        "TMP": str(temp),
        # kpathsea paranoid mode: disallow arbitrary absolute/parent paths for
        # document file IO while still permitting installed TeX tree lookups.
        "openin_any": "p",
        "openout_any": "p",
        "shell_escape": "f",
        "shell_escape_commands": "",
        "TEXMFOUTPUT": str(output_dir),
    })
    return env


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    process.kill()


def _run_tex_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Dict[str, str],
    timeout_seconds: float,
) -> Tuple[int, str, str, bool]:
    """Run one TeX pass and return (code, stdout, stderr, timed_out)."""
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode, stdout or "", stderr or "", False
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        stdout, stderr = process.communicate()
        return process.returncode if process.returncode is not None else -9, stdout or "", stderr or "", True


def cleanup_compilation_artifacts(result: CompilationResult) -> None:
    """Remove a temporary output directory created by ``compile_tex_to_pdf``."""
    if not result.temporary_output or not result.build_dir:
        return
    try:
        shutil.rmtree(result.build_dir)
    except FileNotFoundError:
        pass


def compile_tex_to_pdf(
    path: str,
    *,
    output_dir: Optional[str] = None,
    engine: str = "pdflatex",
    passes: int = 1,
    timeout_seconds: float = 30.0,
    max_source_files: int = 500,
    max_source_bytes: int = 100 * 1024 * 1024,
    max_single_file_bytes: int = 25 * 1024 * 1024,
    max_pdf_bytes: int = 100 * 1024 * 1024,
    max_log_chars: int = 200_000,
) -> CompilationResult:
    """Compile a .tex source to PDF in a restricted temporary workspace.

    ``output_dir`` is recommended for durable artifacts.  When omitted, a
    dedicated temporary output directory is created and retained; callers may
    later remove it with ``cleanup_compilation_artifacts``.

    The function returns a ``CompilationResult`` instead of raising for normal
    compiler failures, missing engines, and timeouts.  Invalid API arguments or
    missing source paths still raise immediately.
    """
    requested_path = Path(path).expanduser()
    if requested_path.is_symlink():
        raise ValueError(f"Symlinked LaTeX sources are not accepted: {requested_path}")
    source_path = requested_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))
    if not source_path.is_file() or source_path.suffix.lower() != ".tex":
        raise ValueError(f"Expected a .tex file: {source_path}")
    if engine not in ALLOWED_ENGINES:
        raise ValueError(f"Unsupported LaTeX engine {engine!r}; allowed: {', '.join(ALLOWED_ENGINES)}")
    if passes < 1 or passes > 3:
        raise ValueError("passes must be between 1 and 3")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    for name, value in (
        ("max_source_files", max_source_files),
        ("max_source_bytes", max_source_bytes),
        ("max_single_file_bytes", max_single_file_bytes),
        ("max_pdf_bytes", max_pdf_bytes),
        ("max_log_chars", max_log_chars),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    executable = shutil.which(engine)
    if executable is None:
        return CompilationResult(
            success=False,
            source_path=str(source_path),
            engine=engine,
            error_code="engine_unavailable",
            error_message=f"LaTeX engine not found on PATH: {engine}",
        )

    temporary_output = output_dir is None
    if output_dir is None:
        final_dir = Path(tempfile.mkdtemp(prefix="grading_app_compiled_"))
    else:
        final_dir = Path(output_dir).expanduser().resolve()
        final_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()
    all_stdout: List[str] = []
    all_stderr: List[str] = []
    warnings: List[str] = []
    passes_completed = 0
    return_code: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    final_pdf: Optional[Path] = None

    try:
        with tempfile.TemporaryDirectory(prefix="grading_app_latex_workspace_") as workspace_text:
            workspace = Path(workspace_text)
            compile_output = workspace / "output"
            compile_output.mkdir(parents=True, exist_ok=True)

            try:
                staged_main, staging_warnings = _stage_source_tree(
                    source_path,
                    workspace,
                    max_source_files=max_source_files,
                    max_source_bytes=max_source_bytes,
                    max_single_file_bytes=max_single_file_bytes,
                )
            except ValueError as exc:
                error_code = str(exc).split(":", 1)[0]
                error_message = str(exc)
                return CompilationResult(
                    success=False,
                    source_path=str(source_path),
                    engine=engine,
                    build_dir=str(final_dir) if temporary_output else None,
                    temporary_output=temporary_output,
                    duration_seconds=time.monotonic() - start_time,
                    error_code=error_code,
                    error_message=error_message,
                )

            warnings.extend(staging_warnings)
            env = _compiler_environment(workspace, compile_output)
            command = [
                executable,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-no-shell-escape",
                "-recorder",
                f"-output-directory={compile_output}",
                staged_main.name,
            ]

            for pass_index in range(passes):
                return_code, stdout, stderr, timed_out = _run_tex_process(
                    command,
                    cwd=staged_main.parent,
                    env=env,
                    timeout_seconds=timeout_seconds,
                )
                all_stdout.append(stdout)
                all_stderr.append(stderr)

                if timed_out:
                    error_code = "latex_compilation_timeout"
                    error_message = (
                        f"{engine} exceeded {timeout_seconds:.1f}s on pass {pass_index + 1}."
                    )
                    break
                if return_code != 0:
                    error_code = "latex_compilation_failed"
                    error_message = f"{engine} exited with status {return_code} on pass {pass_index + 1}."
                    break

                passes_completed += 1

            compiled_pdf = compile_output / f"{staged_main.stem}.pdf"
            if error_code is None:
                if not compiled_pdf.is_file():
                    error_code = "compiled_pdf_missing"
                    error_message = "LaTeX engine reported success but produced no PDF."
                else:
                    pdf_size = compiled_pdf.stat().st_size
                    if pdf_size > max_pdf_bytes:
                        error_code = "compiled_pdf_too_large"
                        error_message = f"Compiled PDF exceeds {max_pdf_bytes} bytes."
                    else:
                        with compiled_pdf.open("rb") as handle:
                            signature = handle.read(5)
                        if signature != b"%PDF-":
                            error_code = "compiled_pdf_invalid"
                            error_message = "Compiler output does not have a PDF signature."

            if error_code is None:
                final_pdf = final_dir / f"{source_path.stem}.pdf"
                shutil.copy2(compiled_pdf, final_pdf)

    except OSError as exc:
        error_code = "latex_compilation_io_error"
        error_message = str(exc)

    success = error_code is None and final_pdf is not None
    if not success and temporary_output:
        # Failure has no useful durable artifact.  Clean the temporary output
        # directory now rather than leaking it; build_dir is therefore None.
        shutil.rmtree(final_dir, ignore_errors=True)
        result_build_dir = None
    else:
        result_build_dir = str(final_dir) if temporary_output else None

    return CompilationResult(
        success=success,
        source_path=str(source_path),
        engine=engine,
        pdf_path=str(final_pdf) if final_pdf is not None else None,
        build_dir=result_build_dir,
        temporary_output=temporary_output and success,
        return_code=return_code,
        passes_completed=passes_completed,
        duration_seconds=time.monotonic() - start_time,
        stdout=_truncate("\n".join(all_stdout), max_log_chars),
        stderr=_truncate("\n".join(all_stderr), max_log_chars),
        warnings=warnings,
        error_code=error_code,
        error_message=error_message,
    )


__all__ = [
    "ALLOWED_ENGINES",
    "cleanup_compilation_artifacts",
    "compile_tex_to_pdf",
]
