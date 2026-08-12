"""
Core module for the Rubric Grading Tool.

This package contains the core business logic for assessments,
grading, rubric handling, question-centric grading, and roster discovery.
"""

from .assessment import (
    create_blank_assessment_from_rubric,
    get_assessment_data,
    merge_partial_criteria_update,
    update_grading_progress_metadata,
    update_question_summary,
    update_total_points,
)
from .grader import extract_main_questions, is_valid_assessment
from .question_utils import (
    UNASSIGNED,
    OverallGradingProgress,
    QuestionProgress,
    compute_all_question_progress,
    compute_overall_criteria_progress,
    compute_question_progress,
    get_question_ids,
    group_criteria_by_question,
    infer_question_id_from_title,
    is_criterion_graded,
    normalize_question_id,
    resolve_criterion_question_id,
    sort_question_ids,
)
from .roster import (
    StudentRecord,
    assessment_path_for_student,
    load_roster_csv,
    load_students_from_assessment_dir,
    merge_student_records,
)
from .utils import extract_question_number

__all__ = [
    'get_assessment_data',
    'update_total_points',
    'update_question_summary',
    'merge_partial_criteria_update',
    'create_blank_assessment_from_rubric',
    'update_grading_progress_metadata',
    'extract_main_questions',
    'extract_question_number',
    'is_valid_assessment',
    'UNASSIGNED',
    'QuestionProgress',
    'OverallGradingProgress',
    'normalize_question_id',
    'resolve_criterion_question_id',
    'infer_question_id_from_title',
    'sort_question_ids',
    'group_criteria_by_question',
    'get_question_ids',
    'is_criterion_graded',
    'compute_question_progress',
    'compute_all_question_progress',
    'compute_overall_criteria_progress',
    'StudentRecord',
    'load_roster_csv',
    'load_students_from_assessment_dir',
    'merge_student_records',
    'assessment_path_for_student',
]
