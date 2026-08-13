"""
PDF accommodation ingestion and page rendering.

PDF-only submissions are an explicit accommodation path. The original PDF is
always the authoritative evidence. Any selectable text extracted here and all
rendered page images are derived artifacts only; this module performs no OCR.

PyMuPDF is used because it provides both selectable-text extraction and faithful
page rasterization. The import is optional at module-import time so the rest of
the grading application can still start when the PDF feature dependency is not
installed; calls then return structured warnings/failures instead of crashing.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .matcher import normalize_student_id
from .models import (
    PdfPageArtifact,
    PdfRenderResult,
    SUBMISSION_MODE_PDF_ACCOMMODATION,
    SubmissionRecord,
)


DEFAULT_RENDER_DPI = 200
MIN_RENDER_DPI = 72
MAX_RENDER_DPI = 600
DEFAULT_MIN_TEXT_CHARS_PER_PAGE = 100
DEFAULT_MAX_PDF_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_PDF_PAGES = 250
DEFAULT_MAX_PAGE_PIXELS = 100_000_000

_MANAGED_PAGE_RE = re.compile(r"^page_\d+\.png$", re.IGNORECASE)


class _PdfProcessingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _import_pymupdf():
    """Import PyMuPDF across both modern and legacy module names."""
    try:
        import pymupdf  # type: ignore
        return pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore
            return pymupdf
        except ImportError:
            return None


def _pymupdf_version(module: Any) -> Optional[str]:
    value = getattr(module, "__version__", None)
    if value:
        return str(value)
    value = getattr(module, "VersionBind", None)
    return str(value) if value else None


def _validate_pdf_source(path: str, *, max_pdf_bytes: int) -> Path:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked PDF submissions are not accepted: {requested}")

    resolved = requested.resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {resolved}")

    size = resolved.stat().st_size
    if size <= 0:
        raise ValueError(f"PDF file is empty: {resolved}")
    if max_pdf_bytes <= 0:
        raise ValueError("max_pdf_bytes must be positive")
    if size > max_pdf_bytes:
        raise ValueError(
            f"PDF exceeds configured size limit ({size} > {max_pdf_bytes} bytes): {resolved}"
        )
    return resolved


def _open_checked_pdf(module: Any, path: Path, *, max_pages: int):
    try:
        document = module.open(str(path))
    except Exception as exc:  # PyMuPDF raises several document-specific types.
        raise _PdfProcessingError("pdf_read_failed", str(exc)) from exc

    try:
        if not bool(getattr(document, "is_pdf", False)):
            raise _PdfProcessingError("invalid_pdf", "The supplied file is not a PDF document.")
        if bool(getattr(document, "needs_pass", False)):
            raise _PdfProcessingError(
                "pdf_password_required",
                "Password-protected PDFs are not supported by the accommodation ingestion path.",
            )

        page_count = int(getattr(document, "page_count", len(document)))
        if page_count <= 0:
            raise _PdfProcessingError("pdf_has_no_pages", "The PDF contains no pages.")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        if page_count > max_pages:
            raise _PdfProcessingError(
                "pdf_page_limit_exceeded",
                f"PDF has {page_count} pages; configured limit is {max_pages}.",
            )
        return document
    except Exception:
        document.close()
        raise


def extract_text_from_pdf(
    path: str,
    *,
    min_chars_per_page: int = DEFAULT_MIN_TEXT_CHARS_PER_PAGE,
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
) -> Tuple[str, Dict[str, Any]]:
    """Extract selectable PDF text without OCR.

    The returned text is derived/assistive only. ``selectable_text`` is a
    conservative sufficiency flag based on character density; short text layers
    are preserved in ``text`` but are not treated as reliable question-answer
    material by the high-level parser.
    """
    source = _validate_pdf_source(path, max_pdf_bytes=max_pdf_bytes)
    if min_chars_per_page < 0:
        raise ValueError("min_chars_per_page must be non-negative")

    module = _import_pymupdf()
    base: Dict[str, Any] = {
        "source": "pdf",
        "source_path": str(source),
        "page_count": 0,
        "text_length": 0,
        "page_text_lengths": [],
        "text_layer_present": False,
        "selectable_text": False,
        "min_chars_per_page": min_chars_per_page,
        "renderer": "pymupdf" if module is not None else None,
        "renderer_version": _pymupdf_version(module) if module is not None else None,
        "was_repaired": False,
        "encrypted": False,
        "warnings": [],
        "error_code": None,
        "error_message": None,
        "ocr_performed": False,
    }

    if module is None:
        base["warnings"] = ["pdf_extraction_unavailable"]
        base["error_code"] = "pdf_extraction_unavailable"
        base["error_message"] = "PyMuPDF is not installed."
        return "", base

    document = None
    try:
        document = _open_checked_pdf(module, source, max_pages=max_pages)
        page_count = int(document.page_count)
        page_texts: List[str] = []
        lengths: List[int] = []

        for index in range(page_count):
            page = document.load_page(index)
            text = page.get_text("text") or ""
            text = str(text).rstrip()
            page_texts.append(text)
            lengths.append(len(text.strip()))

        raw_text = "\n\n".join(page_texts).strip()
        text_length = len(raw_text)
        threshold = page_count * min_chars_per_page
        text_layer_present = bool(raw_text.strip())
        selectable_text = text_layer_present and text_length >= threshold

        warnings: List[str] = []
        was_repaired = bool(getattr(document, "is_repaired", False))
        if was_repaired:
            warnings.append("pdf_repaired_on_open")
        if not selectable_text:
            warnings.append("pdf_may_be_image_only")

        base.update(
            {
                "page_count": page_count,
                "text_length": text_length,
                "page_text_lengths": lengths,
                "text_layer_present": text_layer_present,
                "selectable_text": selectable_text,
                "was_repaired": was_repaired,
                "encrypted": bool(getattr(document, "is_encrypted", False)),
                "warnings": warnings,
            }
        )
        return raw_text, base

    except _PdfProcessingError as exc:
        base["warnings"] = [exc.code]
        base["error_code"] = exc.code
        base["error_message"] = exc.message
        return "", base
    except Exception as exc:
        base["warnings"] = ["pdf_extraction_failed"]
        base["error_code"] = "pdf_extraction_failed"
        base["error_message"] = str(exc)
        return "", base
    finally:
        if document is not None:
            document.close()


def _validate_render_dpi(dpi: int) -> int:
    try:
        value = int(dpi)
    except (TypeError, ValueError) as exc:
        raise ValueError("dpi must be an integer") from exc
    if value < MIN_RENDER_DPI or value > MAX_RENDER_DPI:
        raise ValueError(f"dpi must be between {MIN_RENDER_DPI} and {MAX_RENDER_DPI}")
    return value


def _prepare_render_directory(output_dir: Optional[str]) -> Tuple[Path, bool]:
    if output_dir is None:
        return Path(tempfile.mkdtemp(prefix="grading_app_pdf_pages_")), True

    requested = Path(output_dir).expanduser()
    if requested.exists() and requested.is_symlink():
        raise ValueError(f"Symlinked render output directories are not accepted: {requested}")
    resolved = requested.resolve()
    resolved.mkdir(parents=True, exist_ok=True)

    # Remove only files owned by this renderer. This prevents stale page images
    # when a revised PDF has fewer pages while preserving unrelated caller data.
    for child in resolved.iterdir():
        if child.is_file() and not child.is_symlink() and _MANAGED_PAGE_RE.fullmatch(child.name):
            child.unlink()
    return resolved, False


def _estimated_page_pixels(page: Any, dpi: int) -> int:
    rect = page.rect
    width_px = max(1, int(round(float(rect.width) * dpi / 72.0)))
    height_px = max(1, int(round(float(rect.height) * dpi / 72.0)))
    return width_px * height_px


def render_pdf_pages(
    path: str,
    *,
    output_dir: Optional[str] = None,
    dpi: int = DEFAULT_RENDER_DPI,
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_page_pixels: int = DEFAULT_MAX_PAGE_PIXELS,
) -> PdfRenderResult:
    """Render each PDF page to a deterministic PNG at ``dpi``.

    Page numbers are 1-based and filenames are ``page_001.png`` etc. The
    original PDF is never modified. If no ``output_dir`` is supplied, a
    temporary directory is retained until ``cleanup_pdf_render_artifacts()`` is
    called so downstream transcription/UI code can consume the images.
    """
    start = time.monotonic()
    render_dpi = _validate_render_dpi(dpi)
    source = _validate_pdf_source(path, max_pdf_bytes=max_pdf_bytes)
    if max_page_pixels <= 0:
        raise ValueError("max_page_pixels must be positive")

    module = _import_pymupdf()
    if module is None:
        return PdfRenderResult(
            success=False,
            source_path=str(source),
            dpi=render_dpi,
            renderer=None,
            duration_seconds=time.monotonic() - start,
            warnings=["pdf_rendering_unavailable"],
            error_code="pdf_rendering_unavailable",
            error_message="PyMuPDF is not installed.",
        )

    document = None
    target: Optional[Path] = None
    temporary_output = False
    created_files: List[Path] = []
    page_artifacts: List[PdfPageArtifact] = []

    try:
        document = _open_checked_pdf(module, source, max_pages=max_pages)
        page_count = int(document.page_count)
        target, temporary_output = _prepare_render_directory(output_dir)
        digits = max(3, len(str(page_count)))

        for index in range(page_count):
            page = document.load_page(index)
            estimated_pixels = _estimated_page_pixels(page, render_dpi)
            if estimated_pixels > max_page_pixels:
                raise _PdfProcessingError(
                    "pdf_page_too_large",
                    f"Page {index + 1} would render to approximately {estimated_pixels} pixels; "
                    f"configured limit is {max_page_pixels}.",
                )

            pixmap = page.get_pixmap(
                dpi=render_dpi,
                colorspace=module.csRGB,
                alpha=False,
                annots=True,
            )
            image_path = target / f"page_{index + 1:0{digits}d}.png"
            pixmap.save(str(image_path))
            created_files.append(image_path)

            try:
                page_text = page.get_text("text") or ""
                text_length = len(str(page_text).strip())
            except Exception:
                text_length = 0

            page_artifacts.append(
                PdfPageArtifact(
                    page_number=index + 1,
                    image_path=str(image_path),
                    width_px=int(pixmap.width),
                    height_px=int(pixmap.height),
                    dpi=render_dpi,
                    text_length=text_length,
                )
            )

        warnings: List[str] = []
        if bool(getattr(document, "is_repaired", False)):
            warnings.append("pdf_repaired_on_open")

        return PdfRenderResult(
            success=True,
            source_path=str(source),
            dpi=render_dpi,
            output_dir=str(target),
            temporary_output=temporary_output,
            page_count=page_count,
            pages=page_artifacts,
            duration_seconds=time.monotonic() - start,
            renderer="pymupdf",
            renderer_version=_pymupdf_version(module),
            warnings=warnings,
        )

    except _PdfProcessingError as exc:
        for created in created_files:
            try:
                created.unlink()
            except OSError:
                pass
        if temporary_output and target is not None:
            shutil.rmtree(target, ignore_errors=True)
        return PdfRenderResult(
            success=False,
            source_path=str(source),
            dpi=render_dpi,
            output_dir=None if temporary_output else (str(target) if target else None),
            temporary_output=False,
            page_count=int(document.page_count) if document is not None else 0,
            pages=[],
            duration_seconds=time.monotonic() - start,
            renderer="pymupdf",
            renderer_version=_pymupdf_version(module),
            warnings=[exc.code],
            error_code=exc.code,
            error_message=exc.message,
        )
    except Exception as exc:
        for created in created_files:
            try:
                created.unlink()
            except OSError:
                pass
        if temporary_output and target is not None:
            shutil.rmtree(target, ignore_errors=True)
        return PdfRenderResult(
            success=False,
            source_path=str(source),
            dpi=render_dpi,
            output_dir=None if temporary_output else (str(target) if target else None),
            temporary_output=False,
            page_count=int(document.page_count) if document is not None else 0,
            pages=[],
            duration_seconds=time.monotonic() - start,
            renderer="pymupdf",
            renderer_version=_pymupdf_version(module),
            warnings=["pdf_rendering_failed"],
            error_code="pdf_rendering_failed",
            error_message=str(exc),
        )
    finally:
        if document is not None:
            document.close()


def cleanup_pdf_render_artifacts(result: PdfRenderResult) -> None:
    """Remove renderer-owned temporary page images, if any."""
    if not result.temporary_output or not result.output_dir:
        return
    shutil.rmtree(result.output_dir, ignore_errors=True)


def _choose_accommodation_pdf(paths: List[Path]) -> Path:
    for candidate in paths:
        if candidate.name.casefold() == "main.pdf":
            return candidate
    return max(paths, key=lambda item: (item.stat().st_size, item.name.casefold()))


def record_from_pdf_accommodation(
    path: str,
    *,
    student_id: Optional[str] = None,
) -> SubmissionRecord:
    """Create an explicit PDF-accommodation record from a file or directory.

    Calling this function is the authorization signal: PDF-only files are never
    auto-promoted to accommodations by normal submission discovery.
    """
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"Symlinked accommodation paths are not accepted: {requested}")
    resolved = requested.resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))

    warnings: List[str] = []
    if resolved.is_file():
        if resolved.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF accommodation file: {resolved}")
        selected = resolved
        root = resolved.parent
        inferred = normalize_student_id(student_id or resolved.name)
    elif resolved.is_dir():
        candidates = sorted(
            [
                item
                for item in resolved.iterdir()
                if item.is_file() and not item.is_symlink() and item.suffix.lower() == ".pdf"
            ],
            key=lambda item: item.name.casefold(),
        )
        if not candidates:
            raise ValueError(f"No PDF accommodation file found in: {resolved}")
        if len(candidates) > 1:
            warnings.append("multiple_pdf_files")
        selected = _choose_accommodation_pdf(candidates)
        root = resolved
        inferred = normalize_student_id(student_id or resolved.name)
    else:
        raise ValueError(f"Unsupported accommodation path: {resolved}")

    if not inferred:
        raise ValueError(f"Could not infer student ID for PDF accommodation: {resolved}")

    return SubmissionRecord(
        student_id=inferred,
        files={"pdf": str(selected)},
        warnings=warnings,
        submission_root=str(root),
        submission_mode=SUBMISSION_MODE_PDF_ACCOMMODATION,
        accommodation_mode=True,
    )


__all__ = [
    "DEFAULT_MAX_PAGE_PIXELS",
    "DEFAULT_MAX_PDF_BYTES",
    "DEFAULT_MAX_PDF_PAGES",
    "DEFAULT_MIN_TEXT_CHARS_PER_PAGE",
    "DEFAULT_RENDER_DPI",
    "MAX_RENDER_DPI",
    "MIN_RENDER_DPI",
    "cleanup_pdf_render_artifacts",
    "extract_text_from_pdf",
    "record_from_pdf_accommodation",
    "render_pdf_pages",
]
