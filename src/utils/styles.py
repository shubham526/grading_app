"""Application-wide visual system for the Rubric Grading Tool.

Commit 5 replaces the old saturated Material-style theme with a neutral-first
professional desktop palette and a restrained indigo accent.  The public
``apply_material_style`` name is preserved for backwards compatibility with the
existing entry point, although the implementation is no longer a Material
Design theme.
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QFontDatabase, QPainter, QPalette, QPolygon
from PyQt5.QtWidgets import QComboBox, QSpinBox, QStyleFactory


# Hex values are useful for QSS; COLORS retains QColor values for the existing
# main-window call sites (for example COLORS["divider"].name()).
SEMANTIC_COLORS = {
    "primary": "#3B5CCC",
    "primary_hover": "#304DAF",
    "primary_pressed": "#263F96",
    "primary_soft": "#EEF2FF",
    "background": "#F6F7F9",
    "surface": "#FFFFFF",
    "surface_alt": "#F9FAFB",
    "text_primary": "#1F2937",
    "text_secondary": "#667085",
    "text_muted": "#98A2B3",
    "border": "#D9DEE7",
    "divider": "#E6E9EF",
    "success": "#2E7D5B",
    "warning": "#A66B16",
    "error": "#B94A48",
    "disabled_text": "#98A2B3",
    "disabled_background": "#EEF1F5",
    "selection_text": "#FFFFFF",
}

COLORS = {name: QColor(value) for name, value in SEMANTIC_COLORS.items()}

# Compatibility aliases used by older modules/plugins.  Keep them semantic but
# do not reintroduce the old indigo/pink visual hierarchy.
COLORS.update(
    {
        "card": COLORS["surface"],
        "primary_light": QColor("#7386D8"),
        "primary_dark": COLORS["primary_hover"],
        "accent": COLORS["primary"],
        "info": COLORS["primary"],
    }
)




class VisibleArrowComboBox(QComboBox):
    """QComboBox with an explicitly painted dropdown chevron.

    Qt/macOS can suppress or wash out the native arrow when a global stylesheet
    is active.  Painting the small indicator ourselves keeps the normal combo-box
    behavior and hit target while guaranteeing a visible affordance.
    """

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLORS["text_muted"] if not self.isEnabled() else QColor("#475467"))
        cx = max(10, self.width() - 15)
        cy = self.height() // 2
        painter.drawPolygon(QPolygon([
            QPoint(cx - 4, cy - 2),
            QPoint(cx + 4, cy - 2),
            QPoint(cx, cy + 3),
        ]))


class VisibleArrowSpinBox(QSpinBox):
    """QSpinBox with guaranteed visible up/down arrow indicators.

    The underlying QSpinBox buttons remain native/Fusion buttons, so mouse and
    keyboard behavior is unchanged.  We only paint the two arrow glyphs after
    Qt paints the control; this avoids platform/theme-specific invisible arrows.
    """

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLORS["text_muted"] if not self.isEnabled() else QColor("#475467"))

        cx = max(10, self.width() - 12)
        upper_y = max(7, self.height() // 4)
        lower_y = min(self.height() - 7, (self.height() * 3) // 4)

        painter.drawPolygon(QPolygon([
            QPoint(cx - 4, upper_y + 2),
            QPoint(cx + 4, upper_y + 2),
            QPoint(cx, upper_y - 3),
        ]))
        painter.drawPolygon(QPolygon([
            QPoint(cx - 4, lower_y - 2),
            QPoint(cx + 4, lower_y - 2),
            QPoint(cx, lower_y + 3),
        ]))


APP_STYLESHEET = r"""
QMainWindow, QDialog {
    background-color: #F6F7F9;
    color: #1F2937;
}

QWidget {
    color: #1F2937;
}

QLabel[labelType="heading"] {
    color: #1F2937;
    font-size: 15px;
    font-weight: 600;
}

QLabel[labelType="subheading"] {
    color: #344054;
    font-size: 13px;
    font-weight: 600;
}

QPushButton {
    min-height: 28px;
    padding: 5px 12px;
    border: 1px solid #D0D5DD;
    border-radius: 6px;
    background-color: #FFFFFF;
    color: #344054;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #F9FAFB;
    border-color: #B8C0CC;
}
QPushButton:pressed {
    background-color: #F2F4F7;
}
QPushButton:disabled {
    background-color: #EEF1F5;
    border-color: #E2E6EC;
    color: #98A2B3;
}

QPushButton[buttonRole="primary"],
QPushButton[workspaceAction="primary"] {
    background-color: #3B5CCC;
    border-color: #3B5CCC;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton[buttonRole="primary"]:hover,
QPushButton[workspaceAction="primary"]:hover {
    background-color: #304DAF;
    border-color: #304DAF;
}
QPushButton[buttonRole="primary"]:pressed,
QPushButton[workspaceAction="primary"]:pressed {
    background-color: #263F96;
    border-color: #263F96;
}
QPushButton[buttonRole="primary"]:disabled,
QPushButton[workspaceAction="primary"]:disabled {
    background-color: #D9DFF5;
    border-color: #D9DFF5;
    color: #8B97C7;
}

QPushButton[buttonRole="danger"] {
    background-color: #FFFFFF;
    border-color: #E3B8B7;
    color: #B94A48;
}
QPushButton[buttonRole="danger"]:hover {
    background-color: #FDF1F1;
    border-color: #D99E9C;
}

QLineEdit,
QTextEdit,
QPlainTextEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox {
    min-height: 28px;
    padding: 4px 7px;
    border: 1px solid #D0D5DD;
    border-radius: 6px;
    background-color: #FFFFFF;
    color: #1F2937;
    selection-background-color: #3B5CCC;
    selection-color: #FFFFFF;
}
QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border: 1px solid #3B5CCC;
}
QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    background-color: #EEF1F5;
    color: #98A2B3;
}

/*
 * Commit 5 is a deliberately light UI even when macOS itself is using Dark
 * appearance.  The native macOS combo/spin-box style can otherwise render a
 * dark field (and pale arrows) inside our light dialog.  We run Qt's Fusion
 * widget style under the light application palette, then keep the standard
 * Fusion dropdown/stepper subcontrols.  This gives us legible values and
 * visible arrows without custom image assets.
 */
QComboBox {
    padding-right: 26px;
}
QSpinBox,
QDoubleSpinBox {
    padding-right: 28px;
}
QSpinBox::up-button,
QSpinBox::down-button,
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {
    width: 24px;
}

QGroupBox {
    margin-top: 10px;
    padding-top: 8px;
    border: 1px solid #D9DEE7;
    border-radius: 7px;
    background-color: #FFFFFF;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #344054;
}

QTabWidget::pane {
    border: 1px solid #D9DEE7;
    border-radius: 6px;
    background: #FFFFFF;
}
QTabBar::tab {
    padding: 6px 11px;
    color: #667085;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #304DAF;
    border-bottom-color: #3B5CCC;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    color: #344054;
}

QToolButton {
    min-width: 26px;
    min-height: 26px;
    padding: 2px 5px;
    border: 1px solid transparent;
    border-radius: 5px;
    background-color: transparent;
    color: #475467;
}
QToolButton:hover {
    background-color: #F2F4F7;
    border-color: #E6E9EF;
}
QToolButton:pressed,
QToolButton:checked {
    background-color: #EAECF0;
}
QToolButton:disabled {
    color: #B2B8C2;
}

QSplitter::handle {
    background-color: #E6E9EF;
}
QSplitter::handle:hover {
    background-color: #C8CFDA;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}

QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #C8CFDA;
    min-height: 24px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #AEB7C4;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    border: none;
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #C8CFDA;
    min-width: 24px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

QMenu {
    background-color: #FFFFFF;
    border: 1px solid #D9DEE7;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px 6px 10px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #EEF2FF;
    color: #304DAF;
}

QToolTip {
    background-color: #1F2937;
    color: #FFFFFF;
    border: 1px solid #1F2937;
    padding: 4px 6px;
}

QStatusBar {
    background-color: #FFFFFF;
    color: #667085;
    border-top: 1px solid #D9DEE7;
}

/* Keep matplotlib's embedded toolbar neutral and legible. */
NavigationToolbar2QT QToolButton {
    background-color: #FFFFFF;
    border: 1px solid #D9DEE7;
    border-radius: 5px;
    padding: 3px;
    margin: 1px;
}
NavigationToolbar2QT QToolButton:hover {
    background-color: #F2F4F7;
}
NavigationToolbar2QT QToolButton:pressed,
NavigationToolbar2QT QToolButton:checked {
    background-color: #EAECF0;
}
"""


def _native_ui_font():
    """Return Qt's platform-selected general UI font."""

    return QFontDatabase.systemFont(QFontDatabase.GeneralFont)


def _build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, COLORS["background"])
    palette.setColor(QPalette.WindowText, COLORS["text_primary"])
    palette.setColor(QPalette.Base, COLORS["surface"])
    palette.setColor(QPalette.AlternateBase, COLORS["surface_alt"])
    palette.setColor(QPalette.ToolTipBase, COLORS["text_primary"])
    palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Text, COLORS["text_primary"])
    palette.setColor(QPalette.Button, COLORS["surface"])
    palette.setColor(QPalette.ButtonText, COLORS["text_primary"])
    palette.setColor(QPalette.Link, COLORS["primary"])
    palette.setColor(QPalette.Highlight, COLORS["primary"])
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))

    palette.setColor(QPalette.Disabled, QPalette.WindowText, COLORS["disabled_text"])
    palette.setColor(QPalette.Disabled, QPalette.Text, COLORS["disabled_text"])
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, COLORS["disabled_text"])
    palette.setColor(QPalette.Disabled, QPalette.Button, COLORS["disabled_background"])
    palette.setColor(QPalette.Disabled, QPalette.Base, COLORS["disabled_background"])
    return palette


def apply_app_style(app) -> None:
    """Apply the Commit-5 light palette, system font, and global QSS.

    Qt's macOS native controls inherit the OS appearance independently of some
    palette roles.  When macOS is in Dark mode this can produce black spin-box
    editors inside our intentionally light application.  Fusion respects the
    application palette consistently while the system font keeps the UI feeling
    at home on macOS.
    """

    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    app.setPalette(_build_palette())
    native_font = _native_ui_font()
    if native_font is not None:
        app.setFont(native_font)
    app.setStyleSheet(APP_STYLESHEET)


def apply_material_style(app) -> None:
    """Compatibility wrapper retained for the existing ``src.main`` import."""

    apply_app_style(app)


__all__ = [
    "APP_STYLESHEET",
    "COLORS",
    "SEMANTIC_COLORS",
    "VisibleArrowComboBox",
    "VisibleArrowSpinBox",
    "apply_app_style",
    "apply_material_style",
]
