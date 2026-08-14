"""Assignment-level reference-solution ingestion and persistence.

Reference solutions are instructor-authored grading aids, not student evidence.
LaTeX is the preferred canonical format because it preserves mathematical
notation and can be split deterministically by rubric question.  A digital PDF
with selectable text is supported as a fallback.  Image-only/scanned reference
PDFs remain viewable but are not silently OCR/VLM-transcribed in v2.2.0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from .compiler import compile_tex_to_pdf
from .latex import extract_text_from_tex
from .pdf import extract_text_from_pdf
from .splitter import FULL_SUBMISSION, split_answers_by_question
from .storage import compute_file_sha256


REFERENCE_SOLUTION_DIRNAME = "reference_solution"
REFERENCE_META_FILENAME = "reference_solution_meta.json"
REFERENCE_ANSWERS_FILENAME = "extracted_answers.json"
REFERENCE_RAW_TEXT_FILENAME = "raw_text.txt"


@dataclass
class ReferenceSolution:
    """Persisted instructor reference solution for one assignment."""

    source_type: str
    canonical_source_path: str
    display_pdf_path: Optional[str]
    raw_text: str
    answers_by_question: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def answer_for_question(self, question_id: Optional[str]) -> Optional[str]:
        if question_id:
            value = self.answers_by_question.get(str(question_id))
            if value is not None:
                return str(value)
        if FULL_SUBMISSION in self.answers_by_question:
            return str(self.answers_by_question[FULL_SUBMISSION])
        return None

    def to_metadata(self, *, root: Optional[Path] = None) -> Dict[str, Any]:
        data = {
            "source_type": self.source_type,
            "canonical_source_path": self.canonical_source_path,
            "display_pdf_path": self.display_pdf_path,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }
        if root is not None:
            for key in ("canonical_source_path", "display_pdf_path"):
                value = data.get(key)
                if not value:
                    continue
                try:
                    data[key] = str(Path(value).resolve().relative_to(root.resolve()))
                except ValueError:
                    pass
        return data


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _safe_source(path: str) -> Path:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked reference solutions are not accepted: {requested}")
    source = requested.resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    suffix = source.suffix.lower()
    if suffix not in {".tex", ".pdf"}:
        raise ValueError("Reference solution must be a .tex or .pdf file")
    return source


def reference_solution_root(assessments_dir: str, *, create: bool = False) -> Path:
    if not assessments_dir:
        raise ValueError("assessments_dir is required")
    root = Path(assessments_dir).expanduser().resolve() / REFERENCE_SOLUTION_DIRNAME
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def prepare_reference_solution(
    source_path: str,
    assessments_dir: str,
    question_ids: Optional[Sequence[str]] = None,
) -> ReferenceSolution:
    """Parse, compile when appropriate, and persist one reference solution."""

    source = _safe_source(source_path)
    root = reference_solution_root(assessments_dir, create=True)
    source_dir = root / "source"
    compiled_dir = root / "compiled"
    source_dir.mkdir(parents=True, exist_ok=True)
    compiled_dir.mkdir(parents=True, exist_ok=True)

    warnings: List[str] = []
    metadata: Dict[str, Any] = {
        "authoritative": True,
        "assignment_level": True,
        "question_ids_requested": [str(v) for v in (question_ids or [])],
        "source_sha256": compute_file_sha256(str(source)),
    }

    if source.suffix.lower() == ".tex":
        source_type = "latex"
        raw_text, extraction = extract_text_from_tex(str(source))
        answers, split_warnings = split_answers_by_question(raw_text, question_ids)
        warnings.extend(str(v) for v in extraction.get("warnings", []) or [])
        warnings.extend(str(v) for v in split_warnings)

        # Compile from the original source tree so safe local includes continue
        # to work even though the persisted canonical entry point is one .tex.
        compilation = compile_tex_to_pdf(str(source), output_dir=str(compiled_dir))
        metadata["extraction"] = extraction
        metadata["compilation"] = compilation.to_metadata(include_logs=False)
        if not compilation.success:
            warnings.append(compilation.error_code or "latex_compilation_failed")

        canonical = source_dir / "solution.tex"
        shutil.copy2(source, canonical)
        display_pdf = Path(compilation.pdf_path).resolve() if compilation.success and compilation.pdf_path else None
        metadata.update(
            {
                "canonical_format": "latex",
                "machine_readable_source": "latex",
                "preferred_for_ai_grading": True,
                "display_source": "compiled_pdf" if display_pdf else None,
            }
        )
    else:
        source_type = "pdf"
        raw_text, extraction = extract_text_from_pdf(str(source))
        if extraction.get("selectable_text") and raw_text.strip():
            answers, split_warnings = split_answers_by_question(raw_text, question_ids)
            warnings.extend(str(v) for v in split_warnings)
            machine_readable_source = "pdf_selectable_text"
        else:
            answers = {}
            machine_readable_source = None
            warnings.append("reference_pdf_has_no_usable_selectable_text")
        warnings.extend(str(v) for v in extraction.get("warnings", []) or [])

        canonical = source_dir / "solution.pdf"
        shutil.copy2(source, canonical)
        display_pdf = canonical
        metadata.update(
            {
                "canonical_format": "pdf",
                "machine_readable_source": machine_readable_source,
                "preferred_for_ai_grading": False,
                "display_source": "original_pdf",
                "extraction": extraction,
            }
        )

    warnings = list(dict.fromkeys(warnings))
    result = ReferenceSolution(
        source_type=source_type,
        canonical_source_path=str(canonical.resolve()),
        display_pdf_path=str(display_pdf) if display_pdf else None,
        raw_text=raw_text,
        answers_by_question={str(k): str(v) for k, v in answers.items()},
        warnings=warnings,
        metadata=metadata,
    )

    _atomic_write_text(root / REFERENCE_RAW_TEXT_FILENAME, raw_text)
    _atomic_write_json(root / REFERENCE_ANSWERS_FILENAME, result.answers_by_question)
    _atomic_write_json(root / REFERENCE_META_FILENAME, result.to_metadata(root=root))
    return result


def load_reference_solution(assessments_dir: str) -> Optional[ReferenceSolution]:
    """Load a previously persisted reference solution, if present."""

    root = reference_solution_root(assessments_dir, create=False)
    meta_path = root / REFERENCE_META_FILENAME
    if not meta_path.exists():
        return None

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    answers_path = root / REFERENCE_ANSWERS_FILENAME
    raw_path = root / REFERENCE_RAW_TEXT_FILENAME
    answers = json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.exists() else {}
    raw_text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""

    def resolve_optional(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        return str(path.resolve())

    canonical = resolve_optional(data.get("canonical_source_path"))
    if not canonical:
        return None
    return ReferenceSolution(
        source_type=str(data.get("source_type") or ""),
        canonical_source_path=canonical,
        display_pdf_path=resolve_optional(data.get("display_pdf_path")),
        raw_text=raw_text,
        answers_by_question={str(k): str(v) for k, v in (answers or {}).items()},
        warnings=[str(v) for v in data.get("warnings", []) or []],
        metadata=dict(data.get("metadata", {}) or {}),
    )


__all__ = [
    "REFERENCE_ANSWERS_FILENAME",
    "REFERENCE_META_FILENAME",
    "REFERENCE_RAW_TEXT_FILENAME",
    "REFERENCE_SOLUTION_DIRNAME",
    "ReferenceSolution",
    "load_reference_solution",
    "prepare_reference_solution",
    "reference_solution_root",
]
