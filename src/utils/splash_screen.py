from PyQt5.QtWidgets import QSplashScreen, QProgressBar, QVBoxLayout, QLabel, QWidget
from PyQt5.QtGui import QColor, QPainter, QPixmap, QFont
from PyQt5.QtCore import Qt, QTimer


class EnhancedSplashScreen(QSplashScreen):
    """Enhanced splash screen with progress bar and animation."""

    def __init__(self, parent=None):
        # Create base pixmap
        pixmap = QPixmap(400, 250)
        pixmap.fill(QColor(63, 81, 181))  # Primary color

        super().__init__(pixmap, Qt.WindowStaysOnTopHint)

        # Create widget to hold content
        self.content = QWidget(self)
        self.content.setGeometry(0, 0, 400, 250)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(20, 20, 20, 20)

        # Add title
        title = QLabel("Rubric Grading Tool")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        # Add spacer
        layout.addStretch()

        # Add tagline
        tagline = QLabel("Professional grading made simple")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setStyleSheet("color: white; font-size: 14px;")
        layout.addWidget(tagline)

        # Add progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: rgba(255, 255, 255, 0.3);
                border-radius: 3px;
                height: 6px;
            }
            QProgressBar::chunk {
                background-color: white;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress)

        # Add status label
        self.status = QLabel("Starting...")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px;")
        layout.addWidget(self.status)

        # Initial message
        self.showMessage("Starting application...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)

    def update_progress(self, value, message):
        """Update the progress bar and message."""
        self.progress.setValue(value)
        self.status.setText(message)
        self.showMessage(message, Qt.AlignBottom | Qt.AlignHCenter, Qt.white)

    def run_startup_sequence(self, callback):
        """Run an animated startup sequence."""
        sequence = [
            (10, "Loading resources..."),
            (30, "Initializing components..."),
            (50, "Setting up UI..."),
            (70, "Checking for auto-saves..."),
            (90, "Almost ready..."),
            (100, "Complete!")
        ]

        current_step = 0

        def next_step():
            nonlocal current_step
            if current_step < len(sequence):
                progress, message = sequence[current_step]
                self.update_progress(progress, message)
                current_step += 1
                QTimer.singleShot(500, next_step)
            else:
                callback()

        QTimer.singleShot(100, next_step)