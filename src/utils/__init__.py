"""
Utility functions for the Rubric Grading Tool.

This package contains utility functions for file I/O, layout management,
PDF generation, and rubric parsing.

Note: this package imports PyQt5 (via file_io.py).  Headless code and tests
should import individual modules directly rather than importing from this
package to avoid the Qt dependency chain.
"""

# File I/O
from .file_io import (
    load_rubric,
    save_assessment,
    load_assessment,
    setup_auto_save,
    auto_save_assessment,
    cleanup_auto_save_files,
)

# Layout helpers
from .layout import (
    setup_rubric_ui,
    setup_question_selection,
    select_all_questions,
    select_no_questions,
    clear_layout,
)

# PDF export
from .pdf import (
    export_to_pdf,
    batch_export_assessments,
)

# Rubric parser shim (delegates to src.core.rubric)
from .rubric_parser import (
    parse_rubric_file,
    parse_json_rubric,
    parse_csv_rubric,
)

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
    'batch_export_assessments',
    # Rubric parsing
    'parse_rubric_file',
    'parse_json_rubric',
    'parse_csv_rubric',
]