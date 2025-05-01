from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QColor, QPainter, QPixmap


class FloatingActionButton(QPushButton):
    """Material Design styled floating action button."""

    def __init__(self, icon_name, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setIconSize(QSize(24, 24))

        # Create icon (placeholder - replace with proper icons)
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setPen(Qt.white)

        if icon_name == "save":
            # Draw a simple save icon
            painter.drawRect(4, 4, 16, 16)
            painter.drawLine(8, 10, 16, 10)
            painter.drawLine(8, 14, 16, 14)
        elif icon_name == "export":
            # Draw a simple export icon
            painter.drawRect(4, 8, 16, 12)
            painter.drawLine(12, 4, 12, 12)
            painter.drawLine(8, 8, 16, 8)
        elif icon_name == "add":
            # Draw a plus icon
            painter.drawLine(12, 6, 12, 18)
            painter.drawLine(6, 12, 18, 12)

        painter.end()

        self.setIcon(QIcon(pixmap))

        self.setStyleSheet("""
            QPushButton {
                background-color: #FF4081;
                border-radius: 28px;
                color: white;
                border: none;
            }
            QPushButton:hover {
                background-color: #F50057;
            }
            QPushButton:pressed {
                background-color: #C51162;
            }
        """)

        # Add drop shadow effect (if available)
        try:
            from PyQt5.QtWidgets import QGraphicsDropShadowEffect
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(8)
            shadow.setColor(QColor(0, 0, 0, 80))
            shadow.setOffset(0, 2)
            self.setGraphicsEffect(shadow)
        except ImportError:
            pass  # Skip shadow if not available