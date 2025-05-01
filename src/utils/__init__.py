"""
UI utility functions for the Rubric Grading Tool.

This package contains utility functions for UI-related operations,
including layout management, file I/O, and PDF generation.
"""

# Import key functions from modules
from .file_io import (
    load_rubric,
    save_assessment,
    load_assessment,
    setup_auto_save,
    auto_save_assessment,
    cleanup_auto_save_files
)

from .layout import (
    setup_rubric_ui,
    setup_question_selection,
    select_all_questions,
    select_no_questions,
    clear_layout
)

from .pdf import (
    export_to_pdf,
    batch_export_assessments
)

# Define what should be exported
__all__ = [
    # File operations
    'load_rubric',
    'save_assessment',
    'load_assessment',
    'setup_auto_save',
    'auto_save_assessment',
    'cleanup_auto_save_files',

    # Layout operations
    'setup_rubric_ui',
    'setup_question_selection',
    'select_all_questions',
    'select_no_questions',
    'clear_layout',

    # PDF operations
    'export_to_pdf',
    'batch_export_assessments'
]