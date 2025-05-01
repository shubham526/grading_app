"""
UI components for the Rubric Grading Tool.

This package contains all UI-related components, including the main window,
widgets, dialogs, and UI utilities.
"""

from .main_window import RubricGrader

# Import sub-packages to make them available
import src.ui.widgets
import src.ui.dialogs

# Define what should be exported
__all__ = ['RubricGrader']