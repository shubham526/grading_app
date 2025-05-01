from PyQt5.QtWidgets import QComboBox, QFrame, QListView, QStyledItemDelegate

from PyQt5.QtCore import QEvent, Qt


class BetterComboBox(QComboBox):
    """A ComboBox with improved dropdown behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set a list view with better item rendering
        list_view = QListView()
        list_view.setTextElideMode(Qt.ElideNone)  # Prevent text from being cut off
        self.setView(list_view)

        # Use a delegate for better item display
        delegate = QStyledItemDelegate()
        self.setItemDelegate(delegate)

    def showPopup(self):
        """Improve popup display."""
        super().showPopup()
        popup = self.findChild(QFrame)
        if popup:
            # Make popup wider to ensure text fits
            width = max(self.width() + 50, 300)
            popup.setMinimumWidth(width)
            # Set a larger maximum height
            popup.setMaximumHeight(400)


class ImprovedComboBox(QComboBox):
    """Custom QComboBox with improved dropdown behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view().setMouseTracking(True)
        self.setItemDelegate(QStyledItemDelegate())

    def showPopup(self):
        """Override to improve popup behavior."""
        super().showPopup()
        # Make the popup slightly wider to prevent the scrollbar from hiding items
        popup = self.findChild(QFrame)
        if popup:
            width = max(self.width(), popup.width() + 20)  # Extra width for scrollbar
            popup.setFixedWidth(width)

    def eventFilter(self, watched, event):
        """Filter events for dropdown fixes."""
        if event.type() == QEvent.MouseMove:
            return False  # Don't filter mouse move events
        return super().eventFilter(watched, event)