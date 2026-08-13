"""Embedded paged PDF viewer used by the Commit-5 submission workspace.

The viewer intentionally uses PyMuPDF, already required by v2.2 submission
rendering, instead of QtWebEngine/QtPdf.  It renders only the active page at the
requested zoom and keeps document zoom independent from the rest of the UI.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:  # PyMuPDF 1.24+ preferred import name
    import pymupdf as fitz
except ImportError:  # pragma: no cover - compatibility with older installations
    try:
        import fitz  # type: ignore
    except ImportError:  # pragma: no cover - handled as an in-pane error
        fitz = None


MIN_ZOOM_PERCENT = 25
MAX_ZOOM_PERCENT = 400
DEFAULT_ZOOM_PERCENT = 100
ZOOM_STEP = 15
MAX_RENDER_CACHE_ITEMS = 8


class PdfDocumentViewer(QFrame):
    """Simple single-page-at-a-time PDF/image viewer with zoom controls."""

    page_changed = pyqtSignal(int, int)  # current 1-based page, total pages
    zoom_changed = pyqtSignal(int)
    document_loaded = pyqtSignal(str, int)
    document_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pdfDocumentViewer")

        self._document = None
        self._document_path: Optional[str] = None
        self._page_image_paths: List[str] = []
        self._source_mode = "none"  # none | pdf | images
        self._current_page_index = 0
        self._zoom_percent = DEFAULT_ZOOM_PERCENT
        self._fit_mode: Optional[str] = None  # width | page | None
        self._authoritative = False
        self._title = "Document"
        self._render_cache: "OrderedDict[Tuple, QPixmap]" = OrderedDict()
        self._rendering = False
        self._resize_render_pending = False
        self.last_error: Optional[str] = None

        self._build_ui()
        self._install_shortcuts()
        self.clear_document()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("pdfViewerHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)

        self.title_label = QLabel("Document", header)
        self.title_label.setObjectName("pdfViewerTitle")
        header_layout.addWidget(self.title_label)

        self.authority_label = QLabel("", header)
        self.authority_label.setObjectName("pdfViewerAuthority")
        self.authority_label.setVisible(False)
        header_layout.addWidget(self.authority_label)
        header_layout.addStretch(1)
        layout.addWidget(header)

        toolbar = QWidget(self)
        toolbar.setObjectName("pdfViewerToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(6)

        self.zoom_out_button = self._toolbar_button("−", "Zoom out")
        self.zoom_out_button.clicked.connect(self.zoom_out)
        toolbar_layout.addWidget(self.zoom_out_button)

        self.zoom_spinbox = QSpinBox(toolbar)
        self.zoom_spinbox.setObjectName("pdfZoomSpinBox")
        self.zoom_spinbox.setRange(MIN_ZOOM_PERCENT, MAX_ZOOM_PERCENT)
        self.zoom_spinbox.setSingleStep(5)
        self.zoom_spinbox.setSuffix("%")
        self.zoom_spinbox.setValue(DEFAULT_ZOOM_PERCENT)
        self.zoom_spinbox.setKeyboardTracking(False)
        self.zoom_spinbox.setToolTip("Document zoom")
        self.zoom_spinbox.valueChanged.connect(self.set_zoom_percent)
        toolbar_layout.addWidget(self.zoom_spinbox)

        self.zoom_in_button = self._toolbar_button("+", "Zoom in")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        toolbar_layout.addWidget(self.zoom_in_button)

        self.fit_width_button = self._toolbar_button("Fit Width", "Fit page width to the viewer")
        self.fit_width_button.clicked.connect(self.fit_width)
        toolbar_layout.addWidget(self.fit_width_button)

        self.fit_page_button = self._toolbar_button("Fit Page", "Fit the entire page in the viewer")
        self.fit_page_button.clicked.connect(self.fit_page)
        toolbar_layout.addWidget(self.fit_page_button)

        toolbar_layout.addStretch(1)

        self.prev_page_button = self._toolbar_button("‹", "Previous page")
        self.prev_page_button.clicked.connect(self.previous_page)
        toolbar_layout.addWidget(self.prev_page_button)

        self.page_label = QLabel("Page — / —", toolbar)
        self.page_label.setObjectName("pdfPageLabel")
        toolbar_layout.addWidget(self.page_label)

        self.next_page_button = self._toolbar_button("›", "Next page")
        self.next_page_button.clicked.connect(self.next_page)
        toolbar_layout.addWidget(self.next_page_button)

        layout.addWidget(toolbar)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("pdfViewerScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.viewport().installEventFilter(self)

        self.page_container = QWidget(self.scroll_area)
        self.page_container.setObjectName("pdfPageContainer")
        page_layout = QVBoxLayout(self.page_container)
        page_layout.setContentsMargins(16, 16, 16, 16)
        page_layout.setAlignment(Qt.AlignCenter)

        self.page_label_widget = QLabel(self.page_container)
        self.page_label_widget.setObjectName("pdfRenderedPage")
        self.page_label_widget.setAlignment(Qt.AlignCenter)
        self.page_label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        page_layout.addWidget(self.page_label_widget, 0, Qt.AlignCenter)
        self.scroll_area.setWidget(self.page_container)
        layout.addWidget(self.scroll_area, 1)

        self.empty_state = QLabel("No submission document loaded.", self)
        self.empty_state.setObjectName("pdfEmptyState")
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setWordWrap(True)
        layout.addWidget(self.empty_state, 1)

        self.setStyleSheet(
            """
            QFrame#pdfDocumentViewer {
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 8px;
            }
            QWidget#pdfViewerHeader,
            QWidget#pdfViewerToolbar {
                background-color: #FFFFFF;
                border: none;
            }
            QWidget#pdfViewerHeader {
                border-bottom: 1px solid #E6E9EF;
            }
            QWidget#pdfViewerToolbar {
                border-bottom: 1px solid #E6E9EF;
            }
            QLabel#pdfViewerTitle {
                color: #1F2937;
                font-weight: 600;
            }
            QLabel#pdfViewerAuthority {
                color: #2E7D5B;
                background-color: #EEF7F2;
                border: 1px solid #D4EADF;
                border-radius: 9px;
                padding: 2px 7px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton[viewerToolbar="true"] {
                color: #475467;
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 5px;
                padding: 4px 8px;
                min-height: 22px;
            }
            QPushButton[viewerToolbar="true"]:hover {
                background-color: #F9FAFB;
                border-color: #C8CFDA;
                color: #1F2937;
            }
            QPushButton[viewerToolbar="true"]:pressed {
                background-color: #F2F4F7;
            }
            QPushButton[viewerToolbar="true"]:disabled {
                color: #98A2B3;
                background-color: #F9FAFB;
                border-color: #E6E9EF;
            }
            QSpinBox#pdfZoomSpinBox {
                min-width: 68px;
                padding: 4px 6px;
                color: #1F2937;
                background: #FFFFFF;
                border: 1px solid #D9DEE7;
                border-radius: 5px;
            }
            QLabel#pdfPageLabel {
                color: #667085;
                min-width: 78px;
                qproperty-alignment: AlignCenter;
            }
            QScrollArea#pdfViewerScrollArea {
                background-color: #F3F4F6;
                border: none;
            }
            QWidget#pdfPageContainer {
                background-color: #F3F4F6;
            }
            QLabel#pdfRenderedPage {
                background-color: #FFFFFF;
                border: 1px solid #D9DEE7;
            }
            QLabel#pdfEmptyState {
                color: #667085;
                background-color: #F9FAFB;
                padding: 24px;
            }
            """
        )

    @staticmethod
    def _toolbar_button(text, tooltip):
        button = QPushButton(text)
        button.setProperty("viewerToolbar", True)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.StrongFocus)
        return button

    def _install_shortcuts(self):
        self._zoom_in_shortcut = QShortcut(QKeySequence.ZoomIn, self)
        self._zoom_in_shortcut.activated.connect(self.zoom_in)
        self._zoom_out_shortcut = QShortcut(QKeySequence.ZoomOut, self)
        self._zoom_out_shortcut.activated.connect(self.zoom_out)
        self._fit_shortcut = QShortcut(QKeySequence("Ctrl+0"), self)
        self._fit_shortcut.activated.connect(self.fit_page)
        self._fit_shortcut_meta = QShortcut(QKeySequence("Meta+0"), self)
        self._fit_shortcut_meta.activated.connect(self.fit_page)

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def document_path(self):
        return self._document_path

    @property
    def page_count(self):
        if self._source_mode == "pdf" and self._document is not None:
            return int(self._document.page_count)
        if self._source_mode == "images":
            return len(self._page_image_paths)
        return 0

    @property
    def current_page(self):
        return self._current_page_index + 1 if self.page_count else 0

    @property
    def zoom_percent(self):
        return self._zoom_percent

    @property
    def fit_mode(self):
        return self._fit_mode

    @property
    def authoritative(self):
        return self._authoritative

    @property
    def has_document(self):
        return self.page_count > 0

    # ------------------------------------------------------------------
    # Loading / clearing
    # ------------------------------------------------------------------

    def set_document(self, path, *, title="Document", authoritative=False):
        """Load a PDF path for interactive viewing.

        Errors are displayed inside the viewer and emitted via ``document_error``
        rather than raising through the main Qt event loop.
        """
        self._close_document()
        self._render_cache.clear()
        self.last_error = None
        self._title = str(title or "Document")
        self._authoritative = bool(authoritative)
        self._page_image_paths = []
        self._source_mode = "none"
        self._current_page_index = 0

        if fitz is None:
            return self._set_error("PyMuPDF is not available; the PDF cannot be displayed.")

        requested = Path(str(path or "")).expanduser()
        if not requested.exists() or not requested.is_file():
            return self._set_error(f"PDF not found: {requested}")

        try:
            resolved = requested.resolve()
            document = fitz.open(str(resolved))
            if document.needs_pass:
                document.close()
                return self._set_error("The PDF is password protected and cannot be displayed.")
            if document.page_count <= 0:
                document.close()
                return self._set_error("The PDF contains no pages.")
        except Exception as exc:
            return self._set_error(f"Could not open PDF: {exc}")

        self._document = document
        self._document_path = str(resolved)
        self._source_mode = "pdf"
        self._fit_mode = "width"
        self._update_header()
        self._set_viewer_visible(True)
        self._update_navigation_state()
        self._render_current_page()
        self.document_loaded.emit(self._document_path, self.page_count)
        return True

    def set_page_images(self, image_paths: Iterable[str], *, title="Rendered pages", authoritative=False):
        """Use page-aligned image files as a display fallback.

        Normal operation should prefer ``set_document`` with the actual PDF;
        this fallback exists for a persisted evidence bundle whose original PDF
        is temporarily unavailable while derived rendered pages still exist.
        """
        self._close_document()
        self._render_cache.clear()
        self.last_error = None
        valid: List[str] = []
        for value in image_paths or []:
            path = Path(str(value)).expanduser()
            if path.exists() and path.is_file():
                valid.append(str(path.resolve()))
        if not valid:
            return self._set_error("No rendered page images are available.")

        self._document_path = None
        self._page_image_paths = valid
        self._source_mode = "images"
        self._current_page_index = 0
        self._title = str(title or "Rendered pages")
        self._authoritative = bool(authoritative)
        self._fit_mode = "width"
        self._update_header()
        self._set_viewer_visible(True)
        self._update_navigation_state()
        self._render_current_page()
        self.document_loaded.emit(valid[0], len(valid))
        return True

    def clear_document(self, message="No submission document loaded."):
        self._close_document()
        self._document_path = None
        self._page_image_paths = []
        self._source_mode = "none"
        self._current_page_index = 0
        self._fit_mode = None
        self._authoritative = False
        self.last_error = None
        self._render_cache.clear()
        self.page_label_widget.clear()
        self.title_label.setText("Document")
        self.authority_label.setVisible(False)
        self.empty_state.setText(str(message))
        self._set_viewer_visible(False)
        self._update_navigation_state()

    # ------------------------------------------------------------------
    # Page / zoom controls
    # ------------------------------------------------------------------

    def set_page(self, page_number):
        if not self.has_document:
            return False
        target = max(1, min(int(page_number), self.page_count)) - 1
        if target == self._current_page_index:
            return True
        self._current_page_index = target
        self._render_current_page()
        self._update_navigation_state()
        self.page_changed.emit(self.current_page, self.page_count)
        return True

    def previous_page(self):
        return self.set_page(self.current_page - 1) if self.current_page > 1 else False

    def next_page(self):
        return self.set_page(self.current_page + 1) if self.current_page < self.page_count else False

    def set_zoom_percent(self, percent):
        if self._rendering:
            return
        value = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, int(percent)))
        changed = value != self._zoom_percent or self._fit_mode is not None
        self._zoom_percent = value
        self._fit_mode = None
        self._sync_zoom_control()
        if changed and self.has_document:
            self._render_current_page()
            self.zoom_changed.emit(self._zoom_percent)

    def zoom_in(self):
        self.set_zoom_percent(self._zoom_percent + ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom_percent(self._zoom_percent - ZOOM_STEP)

    def fit_width(self):
        if not self.has_document:
            return
        self._fit_mode = "width"
        self._render_current_page()

    def fit_page(self):
        if not self.has_document:
            return
        self._fit_mode = "page"
        self._render_current_page()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_current_page(self):
        if not self.has_document or self._rendering:
            return
        self._rendering = True
        try:
            effective_zoom = self._effective_zoom_percent()
            self._zoom_percent = int(round(effective_zoom))
            self._sync_zoom_control()

            cache_key = (
                self._source_mode,
                self._document_path or tuple(self._page_image_paths),
                self._current_page_index,
                self._zoom_percent,
                self._fit_mode,
                self.scroll_area.viewport().width() if self._fit_mode else 0,
                self.scroll_area.viewport().height() if self._fit_mode == "page" else 0,
            )
            pixmap = self._render_cache.get(cache_key)
            if pixmap is None:
                if self._source_mode == "pdf":
                    pixmap = self._render_pdf_page(self._zoom_percent)
                else:
                    pixmap = self._render_image_page(self._zoom_percent)
                if pixmap is None:
                    return
                self._render_cache[cache_key] = pixmap
                self._render_cache.move_to_end(cache_key)
                while len(self._render_cache) > MAX_RENDER_CACHE_ITEMS:
                    self._render_cache.popitem(last=False)
            else:
                self._render_cache.move_to_end(cache_key)

            self.page_label_widget.setPixmap(pixmap)
            self.page_label_widget.resize(pixmap.size())
            self._update_navigation_state()
            self.page_changed.emit(self.current_page, self.page_count)
            self.zoom_changed.emit(self._zoom_percent)
        except Exception as exc:
            self._set_error(f"Could not render page {self.current_page}: {exc}")
        finally:
            self._rendering = False

    def _render_pdf_page(self, zoom_percent):
        if self._document is None:
            return None
        page = self._document.load_page(self._current_page_index)
        scale = max(0.01, float(zoom_percent) / 100.0)
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(image)

    def _render_image_page(self, zoom_percent):
        path = self._page_image_paths[self._current_page_index]
        original = QPixmap(path)
        if original.isNull():
            raise ValueError(f"Could not read rendered page image: {path}")
        scale = max(0.01, float(zoom_percent) / 100.0)
        size = QSize(
            max(1, int(round(original.width() * scale))),
            max(1, int(round(original.height() * scale))),
        )
        return original.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _effective_zoom_percent(self):
        if self._fit_mode is None:
            return self._zoom_percent

        page_width, page_height = self._current_page_native_size()
        if page_width <= 0 or page_height <= 0:
            return self._zoom_percent

        viewport = self.scroll_area.viewport().size()
        available_width = max(100, viewport.width() - 36)
        available_height = max(100, viewport.height() - 36)
        width_zoom = available_width / float(page_width) * 100.0
        if self._fit_mode == "width":
            desired = width_zoom
        else:
            height_zoom = available_height / float(page_height) * 100.0
            desired = min(width_zoom, height_zoom)
        return max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, desired))

    def _current_page_native_size(self):
        if self._source_mode == "pdf" and self._document is not None:
            page = self._document.load_page(self._current_page_index)
            rect = page.rect
            return float(rect.width), float(rect.height)
        if self._source_mode == "images":
            pix = QPixmap(self._page_image_paths[self._current_page_index])
            if not pix.isNull():
                return float(pix.width()), float(pix.height())
        return 0.0, 0.0

    # ------------------------------------------------------------------
    # Events / helpers
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            modifiers = event.modifiers()
            if modifiers & (Qt.ControlModifier | Qt.MetaModifier):
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                elif event.angleDelta().y() < 0:
                    self.zoom_out()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.has_document and self._fit_mode in {"width", "page"} and not self._resize_render_pending:
            self._resize_render_pending = True

            def rerender():
                self._resize_render_pending = False
                if self.has_document and self._fit_mode in {"width", "page"}:
                    self._render_current_page()

            QTimer.singleShot(80, rerender)

    def closeEvent(self, event):
        self._close_document()
        super().closeEvent(event)

    def _close_document(self):
        if self._document is not None:
            try:
                self._document.close()
            except Exception:
                pass
        self._document = None

    def _set_error(self, message):
        self.last_error = str(message)
        self._close_document()
        self._source_mode = "none"
        self._document_path = None
        self._page_image_paths = []
        self._render_cache.clear()
        self.page_label_widget.clear()
        self.empty_state.setText(self.last_error)
        self._set_viewer_visible(False)
        self._update_navigation_state()
        self.document_error.emit(self.last_error)
        return False

    def _set_viewer_visible(self, visible):
        self.scroll_area.setVisible(bool(visible))
        self.empty_state.setVisible(not bool(visible))

    def _update_header(self):
        self.title_label.setText(self._title)
        if self._authoritative:
            self.authority_label.setText("Authoritative evidence")
            self.authority_label.setVisible(True)
        else:
            self.authority_label.setVisible(False)

    def _update_navigation_state(self):
        total = self.page_count
        current = self.current_page
        self.page_label.setText(f"Page {current} / {total}" if total else "Page — / —")
        self.prev_page_button.setEnabled(total > 0 and current > 1)
        self.next_page_button.setEnabled(total > 0 and current < total)
        enabled = total > 0
        for widget in (
            self.zoom_out_button,
            self.zoom_spinbox,
            self.zoom_in_button,
            self.fit_width_button,
            self.fit_page_button,
        ):
            widget.setEnabled(enabled)

    def _sync_zoom_control(self):
        blocked = self.zoom_spinbox.blockSignals(True)
        self.zoom_spinbox.setValue(int(self._zoom_percent))
        self.zoom_spinbox.blockSignals(blocked)
