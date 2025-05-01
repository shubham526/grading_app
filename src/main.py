#!/usr/bin/env python3
"""
Rubric Grading Tool - Main Entry Point

This module initializes and launches the Rubric Grading application.
"""

import sys
from PyQt5.QtWidgets import QApplication

# Fix: import RubricGrader from the proper module
from src.ui.main_window import RubricGrader
from src.utils.styles import apply_material_style
from src.utils.splash_screen import EnhancedSplashScreen


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    apply_material_style(app)  # Apply our custom Material Design style

    # Create and show enhanced splash screen
    splash = EnhancedSplashScreen()
    splash.show()
    app.processEvents()

    # Create the main window with a splash animation
    window = None

    def show_main_window():
        nonlocal window
        window = RubricGrader()
        window.show()
        splash.finish(window)

    # Run the startup sequence with callback
    splash.run_startup_sequence(show_main_window)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()