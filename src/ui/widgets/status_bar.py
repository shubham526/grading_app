"""Neutral application status bar with autosave and submission indicators."""

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QStatusBar, QWidget


_STATUS_COLORS = {
    "neutral": "#667085",
    "ready": "#2E7D5B",
    "success": "#2E7D5B",
    "warning": "#A66B16",
    "error": "#B94A48",
    "busy": "#3B5CCC",
    "info": "#3B5CCC",
}


class StatusBarWidget(QStatusBar):
    """Enhanced status bar with autosave, submission, and version status.

    Existing public methods are preserved.  Commit 5 adds
    ``set_submission_status`` so the submission workspace/controller can expose
    lightweight state without turning the whole status bar into an accent block.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._persistent_status = "Ready"
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("appStatusBar")
        self.setSizeGripEnabled(True)
        self.setStyleSheet(
            """
            QStatusBar#appStatusBar {
                background-color: #FFFFFF;
                color: #667085;
                border-top: 1px solid #D9DEE7;
                min-height: 28px;
            }
            QStatusBar#appStatusBar QLabel {
                background: transparent;
                border: none;
                padding: 0 4px;
            }
            QLabel#statusPrimary {
                color: #1F2937;
            }
            QLabel#statusKey {
                color: #98A2B3;
            }
            QLabel#statusVersion {
                color: #98A2B3;
            }
            """
        )

        self.status_label = QLabel("Ready", self)
        self.status_label.setObjectName("statusPrimary")
        self.addWidget(self.status_label, 1)

        self.submission_container = QWidget(self)
        submission_layout = QHBoxLayout(self.submission_container)
        submission_layout.setContentsMargins(4, 0, 4, 0)
        submission_layout.setSpacing(3)
        self.submission_key_label = QLabel("Submission:", self.submission_container)
        self.submission_key_label.setObjectName("statusKey")
        self.submission_status = QLabel("—", self.submission_container)
        submission_layout.addWidget(self.submission_key_label)
        submission_layout.addWidget(self.submission_status)
        self.addPermanentWidget(self.submission_container)

        self.auto_save_container = QWidget(self)
        auto_save_layout = QHBoxLayout(self.auto_save_container)
        auto_save_layout.setContentsMargins(8, 0, 4, 0)
        auto_save_layout.setSpacing(3)
        self.auto_save_label = QLabel("Auto-save:", self.auto_save_container)
        self.auto_save_label.setObjectName("statusKey")
        self.auto_save_status = QLabel("Ready", self.auto_save_container)
        auto_save_layout.addWidget(self.auto_save_label)
        auto_save_layout.addWidget(self.auto_save_status)
        self.addPermanentWidget(self.auto_save_container)

        self.version_label = QLabel("v1.0.0", self)
        self.version_label.setObjectName("statusVersion")
        self.version_label.setContentsMargins(8, 0, 4, 0)
        self.addPermanentWidget(self.version_label)

    def set_status(self, message):
        """Set the persistent primary application status message."""
        self._persistent_status = str(message or "")
        self.status_label.setText(self._persistent_status)

    def set_auto_save_status(self, status, is_error=False):
        """Set the auto-save state while preserving the legacy signature."""
        text = str(status or "")
        self.auto_save_status.setText(text)
        self._set_label_state(self.auto_save_status, "error" if is_error else "ready")

    def set_submission_status(self, status, state="neutral"):
        """Display the current submission/evidence state.

        ``state`` is semantic rather than a raw color and may be one of
        neutral/ready/success/warning/error/busy/info.
        """
        self.submission_status.setText(str(status or "—"))
        self._set_label_state(self.submission_status, state)

    def show_temporary_message(self, message, duration=3000):
        """Show a temporary primary message then restore persistent status."""
        self.status_label.setText(str(message or ""))
        QTimer.singleShot(max(0, int(duration)), self._restore_persistent_status)

    def _restore_persistent_status(self):
        self.status_label.setText(self._persistent_status)

    def set_version(self, version):
        """Set the version display text."""
        self.version_label.setText(str(version or ""))

    @staticmethod
    def _set_label_state(label, state):
        color = _STATUS_COLORS.get(str(state or "neutral").lower(), _STATUS_COLORS["neutral"])
        label.setStyleSheet(f"color: {color}; font-weight: 500;")
