"""
Core module for the Rubric Grading Tool.

This package contains the core business logic for assessments,
grading, rubric handling, and question-centric grading utilities.
"""

from .assessment import (
    create_blank_assessment_from_rubric,
    get_assessment_data,
    merge_partial_criteria_update,
    update_question_summary,
    update_total_points,
)
from .grader import extract_main_questions, is_valid_assessment
from .question_utils import (
    UNASSIGNED,
    QuestionProgress,
    compute_all_question_progress,
    compute_question_progress,
    get_question_ids,
    group_criteria_by_question,
    infer_question_id_from_title,
    is_criterion_graded,
    normalize_question_id,
    sort_question_ids,
)
from .utils import extract_question_number

__all__ = [
    'create_blank_assessment_from_rubric',
    'get_assessment_data',
    'merge_partial_criteria_update',
    'update_total_points',
    'update_question_summary',
    'extract_main_questions',
    'extract_question_number',
    'is_valid_assessment',
    'UNASSIGNED',
    'QuestionProgress',
    'compute_all_question_progress',
    'compute_question_progress',
    'get_question_ids',
    'group_criteria_by_question',
    'infer_question_id_from_title',
    'is_criterion_graded',
    'normalize_question_id',
    'sort_question_ids',
]
