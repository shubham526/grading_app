#!/usr/bin/env python3
"""
Rubric Grading Tool - Main Entry Point

This module initializes and launches the Rubric Grading application.
"""

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QColor, QPalette

from grader import RubricGrader


def setup_application_style(app):
    """Set up the application's visual style and color palette."""
    # Use Fusion style for a modern, cross-platform look
    app.setStyle("Fusion")

    # Create a clean, professional color palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.WindowText, QColor(51, 51, 51))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(247, 247, 247))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor(51, 51, 51))
    palette.setColor(QPalette.Text, QColor(51, 51, 51))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor(51, 51, 51))
    palette.setColor(QPalette.Link, QColor(0, 102, 204))
    palette.setColor(QPalette.Highlight, QColor(0, 102, 204))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

    app.setPalette(palette)


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    setup_application_style(app)

    window = RubricGrader()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()