from PyQt5.QtWidgets import QStatusBar, QLabel, QProgressBar, QHBoxLayout, QWidget
from PyQt5.QtCore import Qt, QTimer


class StatusBarWidget(QStatusBar):
    """Enhanced status bar with auto-save indicator and version information."""

    def __init__(self, parent=None):
        """Initialize the status bar widget."""
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Set up the status bar UI."""
        self.setStyleSheet("""
            QStatusBar {
                background-color: #3F51B5;
                color: white;
            }
            QStatusBar QLabel {
                color: white;
                padding: 3px;
            }
        """)

        # Status message
        self.status_label = QLabel("Ready")
        self.addWidget(self.status_label, 1)  # Stretch factor of 1 allows it to expand

        # Auto-save indicator
        self.auto_save_container = QWidget()
        auto_save_layout = QHBoxLayout(self.auto_save_container)
        auto_save_layout.setContentsMargins(0, 0, 0, 0)

        self.auto_save_label = QLabel("Auto-save:")
        auto_save_layout.addWidget(self.auto_save_label)

        self.auto_save_status = QLabel("Ready")
        auto_save_layout.addWidget(self.auto_save_status)

        self.addPermanentWidget(self.auto_save_container)

        # Add a spacer
        spacer_label = QLabel("")
        spacer_label.setFixedWidth(10)
        self.addPermanentWidget(spacer_label)

        # Version information (from the StatusBar class)
        self.version_label = QLabel("v1.0.0")
        self.version_label.setStyleSheet("color: rgba(255, 255, 255, 0.7);")
        self.addPermanentWidget(self.version_label)

    def set_status(self, message):
        """Set the status message."""
        self.status_label.setText(message)

    def set_auto_save_status(self, status, is_error=False):
        """Set the auto-save status."""
        self.auto_save_status.setText(status)
        if is_error:
            self.auto_save_status.setStyleSheet("color: #FFCDD2;")  # Light red
        else:
            self.auto_save_status.setStyleSheet("color: white;")

    def show_temporary_message(self, message, duration=3000):
        """Show a temporary message and revert back after duration."""
        old_message = self.status_label.text()
        self.status_label.setText(message)

        def restore():
            self.status_label.setText(old_message)

        QTimer.singleShot(duration, restore)

    def set_version(self, version):
        """Set the version display text."""
        self.version_label.setText(version)