from PyQt5.QtGui import QColor, QPalette, QFont
from PyQt5.QtWidgets import QApplication

# Color palette based on Material Design
COLORS = {
    "primary": QColor(63, 81, 181),  # Indigo
    "primary_light": QColor(121, 134, 203),
    "primary_dark": QColor(48, 63, 159),
    "accent": QColor(255, 64, 129),  # Pink
    "background": QColor(245, 245, 245),
    "card": QColor(255, 255, 255),
    "text_primary": QColor(33, 33, 33),
    "text_secondary": QColor(117, 117, 117),
    "divider": QColor(189, 189, 189),
    "success": QColor(76, 175, 80),  # Green
    "warning": QColor(255, 152, 0),  # Orange
    "error": QColor(244, 67, 54),  # Red
    "info": QColor(3, 169, 244)  # Light Blue
}


def apply_material_style(app):
    """Apply a Material Design-inspired style to the application."""
    # Use Fusion style as base
    app.setStyle("Fusion")

    # Create palette
    palette = QPalette()
    palette.setColor(QPalette.Window, COLORS["background"])
    palette.setColor(QPalette.WindowText, COLORS["text_primary"])
    palette.setColor(QPalette.Base, COLORS["card"])
    palette.setColor(QPalette.AlternateBase, QColor(238, 238, 238))
    palette.setColor(QPalette.ToolTipBase, COLORS["primary_light"])
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, COLORS["text_primary"])
    palette.setColor(QPalette.Button, COLORS["card"])
    palette.setColor(QPalette.ButtonText, COLORS["text_primary"])
    palette.setColor(QPalette.Link, COLORS["primary"])
    palette.setColor(QPalette.Highlight, COLORS["primary"])
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

    app.setPalette(palette)

    # Set global font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Apply stylesheet for more control
    app.setStyleSheet("""
        QPushButton {
            border: none;
            padding: 8px 16px;
            background-color: #3F51B5;
            color: white;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #303F9F;
        }
        QPushButton:pressed {
            background-color: #1A237E;
        }
        QPushButton:disabled {
            background-color: #C5CAE9;
            color: #9FA8DA;
        }
        QLineEdit, QSpinBox, QTextEdit {
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            padding: 6px;
            background-color: white;
        }
        QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {
            border: 2px solid #3F51B5;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            margin-top: 12px;
            padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QScrollBar:vertical {
            border: none;
            background: #F5F5F5;
            width: 10px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #BDBDBD;
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QLabel[labelType="heading"] {
            font-size: 16px;
            font-weight: bold;
            color: #3F51B5;
        }
        QLabel[labelType="subheading"] {
            font-size: 14px;
            font-weight: bold;
        }
        QStatusBar {
            background-color: #3F51B5;
            color: white;
        }
        
        /* Fix for QComboBox dropdown issues */
        QComboBox {
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            padding: 6px;
            background-color: white;
            min-height: 25px;
        }
        QComboBox:focus {
            border: 2px solid #3F51B5;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 25px;
            border-left: 1px solid #BDBDBD;
        }
        QComboBox QAbstractItemView {
            border: 1px solid #BDBDBD;
            selection-background-color: #3F51B5;
            selection-color: white;
            background-color: white;
        }
        QComboBox QAbstractItemView::item {
            min-height: 30px;
            padding: 5px;
        }
        QComboBox QListView::item {
            padding-left: 10px;
            padding-right: 10px;
        }

        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        ;
        
        
        
        
        
        
        ght */
        */
        
        
        ted {
        
        
        
        
        
        

        /* Fix for toolbar navigation buttons */
        QToolButton {
            background-color: transparent;
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            padding: 3px;
        }
        QToolButton:hover {
            background-color: #E8EAF6;
        }
        QToolButton:pressed {
            background-color: #C5CAE9;
        }
        QToolButton:checked {
            background-color: #C5CAE9;
        }

        /* Specifically target the matplotlib navigation toolbar buttons */
        NavigationToolbar2QT QToolButton {
            background-color: white;
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            padding: 4px;
            margin: 2px;
        }
        NavigationToolbar2QT QToolButton:hover {
            background-color: #E8EAF6;
        }
        NavigationToolbar2QT QToolButton:pressed {
            background-color: #C5CAE9;
        }
        NavigationToolbar2QT QToolButton:checked {
            background-color: #C5CAE9;
        }
    """)