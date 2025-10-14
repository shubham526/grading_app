"""
Complete ABET Integration for Rubric Grading Tool

This file contains all the code needed to add ABET functionality.
Save this as: src/tools/abet_tool.py (replacing the empty file)
"""

import json
import os
from datetime import datetime
from collections import defaultdict
import numpy as np


class ABETMapping:
    """Class to manage ABET outcome mappings for rubric criteria."""

    def __init__(self, rubric_path=None):
        """Initialize ABET mapping."""
        self.rubric_path = rubric_path
        self.mappings = {}  # criterion_title -> [outcome_ids]
        self.outcome_weights = {}  # criterion_title -> {outcome_id: weight}

    def add_mapping(self, criterion_title, outcome_ids, weights=None):
        """
        Map a criterion to ABET outcomes.

        Args:
            criterion_title (str): Title of the criterion
            outcome_ids (list): List of ABET outcome IDs (e.g., ["SO1", "SO3"])
            weights (dict): Optional weights for each outcome {outcome_id: weight}
        """
        self.mappings[criterion_title] = outcome_ids

        if weights:
            self.outcome_weights[criterion_title] = weights
        else:
            # Equal weights by default
            equal_weight = 1.0 / len(outcome_ids)
            self.outcome_weights[criterion_title] = {
                oid: equal_weight for oid in outcome_ids
            }

    def save_mapping(self, file_path):
        """Save the mapping to a JSON file."""
        data = {
            "rubric_path": self.rubric_path,
            "mappings": self.mappings,
            "outcome_weights": self.outcome_weights,
            "created_date": datetime.now().isoformat()
        }

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load_mapping(cls, file_path):
        """Load a mapping from a JSON file."""
        with open(file_path, 'r') as f:
            data = json.load(f)

        mapping = cls(data.get("rubric_path"))
        mapping.mappings = data["mappings"]
        mapping.outcome_weights = data["outcome_weights"]

        return mapping


class ABETAssessmentAnalyzer:
    """Analyze assessment data for ABET reporting."""

    def __init__(self, abet_mapping):
        """
        Initialize the analyzer.

        Args:
            abet_mapping (ABETMapping): ABET outcome mapping
        """
        self.mapping = abet_mapping
        self.assessments = []

    def add_assessment(self, assessment_data):
        """Add an assessment to analyze."""
        self.assessments.append(assessment_data)

    def load_assessments_from_directory(self, directory):
        """Load all assessment JSON files from a directory."""
        count = 0
        for filename in os.listdir(directory):
            if filename.endswith('.json') and not filename.startswith('abet'):
                file_path = os.path.join(directory, filename)
                try:
                    with open(file_path, 'r') as f:
                        assessment = json.load(f)
                        # Validate it's an assessment (has criteria)
                        if 'criteria' in assessment:
                            self.add_assessment(assessment)
                            count += 1
                except Exception as e:
                    print(f"Error loading {filename}: {e}")
        return count

    def calculate_outcome_scores(self):
        """
        Calculate aggregated scores for each ABET outcome.

        Returns:
            dict: {outcome_id: {'scores': [], 'mean': float, 'percentages': []}}
        """
        outcome_data = defaultdict(lambda: {'scores': [], 'percentages': []})

        for assessment in self.assessments:
            criteria = assessment.get('criteria', [])

            # Track outcomes per student
            student_outcomes = defaultdict(list)

            for criterion in criteria:
                title = criterion['title']

                # Check if this criterion is mapped to ABET outcomes
                if title in self.mapping.mappings:
                    outcome_ids = self.mapping.mappings[title]
                    weights = self.mapping.outcome_weights[title]

                    # Calculate percentage score for this criterion
                    awarded = criterion['points_awarded']
                    possible = criterion['points_possible']

                    if possible > 0:
                        percentage = (awarded / possible) * 100

                        # Distribute the score to mapped outcomes based on weights
                        for outcome_id in outcome_ids:
                            weight = weights.get(outcome_id, 1.0)
                            weighted_percentage = percentage * weight

                            student_outcomes[outcome_id].append(weighted_percentage)

            # Average the percentages for each outcome for this student
            for outcome_id, percentages in student_outcomes.items():
                if percentages:
                    avg_percentage = np.mean(percentages)
                    outcome_data[outcome_id]['percentages'].append(avg_percentage)

        # Calculate statistics for each outcome
        results = {}
        for outcome_id, data in outcome_data.items():
            percentages = data['percentages']
            if percentages:
                results[outcome_id] = {
                    'percentages': percentages,
                    'mean': float(np.mean(percentages)),
                    'median': float(np.median(percentages)),
                    'std_dev': float(np.std(percentages)),
                    'min': float(np.min(percentages)),
                    'max': float(np.max(percentages)),
                    'count': len(percentages)
                }
            else:
                results[outcome_id] = {
                    'percentages': [],
                    'mean': 0,
                    'median': 0,
                    'std_dev': 0,
                    'min': 0,
                    'max': 0,
                    'count': 0
                }

        return results

    def calculate_performance_levels(self, outcome_scores):
        """
        Categorize student performance into levels for each outcome.

        Args:
            outcome_scores (dict): Results from calculate_outcome_scores()

        Returns:
            dict: Performance level distribution for each outcome
        """
        levels = {}

        for outcome_id, data in outcome_scores.items():
            percentages = data['percentages']

            # Define performance levels
            exemplary = sum(1 for p in percentages if p >= 90)
            proficient = sum(1 for p in percentages if 80 <= p < 90)
            developing = sum(1 for p in percentages if 70 <= p < 80)
            unsatisfactory = sum(1 for p in percentages if p < 70)

            total = len(percentages)

            levels[outcome_id] = {
                'exemplary': {
                    'count': exemplary,
                    'percentage': (exemplary / total * 100) if total > 0 else 0
                },
                'proficient': {
                    'count': proficient,
                    'percentage': (proficient / total * 100) if total > 0 else 0
                },
                'developing': {
                    'count': developing,
                    'percentage': (developing / total * 100) if total > 0 else 0
                },
                'unsatisfactory': {
                    'count': unsatisfactory,
                    'percentage': (unsatisfactory / total * 100) if total > 0 else 0
                },
                'proficient_or_higher': {
                    'count': exemplary + proficient,
                    'percentage': ((exemplary + proficient) / total * 100) if total > 0 else 0
                }
            }

        return levels

    def generate_abet_report(self, output_path, course_info=None):
        """
        Generate a comprehensive ABET assessment report.

        Args:
            output_path (str): Path to save the report
            course_info (dict): Optional course information

        Returns:
            dict: The generated report
        """
        outcome_scores = self.calculate_outcome_scores()
        performance_levels = self.calculate_performance_levels(outcome_scores)

        report = {
            'report_date': datetime.now().isoformat(),
            'course_info': course_info or {},
            'num_students': len(self.assessments),
            'outcome_scores': outcome_scores,
            'performance_levels': performance_levels,
            'summary': self._generate_summary(outcome_scores, performance_levels),
            'meets_targets': self._check_targets(performance_levels, course_info)
        }

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        return report

    def _check_targets(self, performance_levels, course_info):
        """Check if performance meets targets."""
        target = course_info.get('target_percentage', 70) if course_info else 70

        results = {}
        for outcome_id, levels in performance_levels.items():
            proficient_plus = levels['proficient_or_higher']['percentage']
            results[outcome_id] = {
                'percentage': proficient_plus,
                'target': target,
                'meets_target': proficient_plus >= target
            }

        return results

    def _generate_summary(self, outcome_scores, performance_levels):
        """Generate a text summary of the assessment results."""
        summary_lines = []

        summary_lines.append("ABET Student Outcome Assessment Summary")
        summary_lines.append("=" * 60)
        summary_lines.append("")
        summary_lines.append(f"Total Students Assessed: {len(self.assessments)}")
        summary_lines.append("")

        for outcome_id in sorted(outcome_scores.keys()):
            scores = outcome_scores[outcome_id]
            levels = performance_levels[outcome_id]

            summary_lines.append(f"{outcome_id}:")
            summary_lines.append(f"  Mean Score: {scores['mean']:.1f}%")
            summary_lines.append(f"  Median Score: {scores['median']:.1f}%")
            summary_lines.append(f"  Range: {scores['min']:.1f}% - {scores['max']:.1f}%")
            summary_lines.append(f"  Standard Deviation: {scores['std_dev']:.1f}%")
            summary_lines.append(f"  Students Assessed: {scores['count']}")
            summary_lines.append(f"  Performance Distribution:")
            summary_lines.append(
                f"    - Exemplary (≥90%): {levels['exemplary']['count']} ({levels['exemplary']['percentage']:.1f}%)")
            summary_lines.append(
                f"    - Proficient (80-89%): {levels['proficient']['count']} ({levels['proficient']['percentage']:.1f}%)")
            summary_lines.append(
                f"    - Developing (70-79%): {levels['developing']['count']} ({levels['developing']['percentage']:.1f}%)")
            summary_lines.append(
                f"    - Unsatisfactory (<70%): {levels['unsatisfactory']['count']} ({levels['unsatisfactory']['percentage']:.1f}%)")
            summary_lines.append(
                f"  Proficient or Higher: {levels['proficient_or_higher']['count']} ({levels['proficient_or_higher']['percentage']:.1f}%)")
            summary_lines.append("")

        return "\n".join(summary_lines)


def create_mapping_from_dict(mapping_dict):
    """
    Helper function to create ABETMapping from a dictionary.

    Args:
        mapping_dict (dict): Dictionary with 'mappings' key

    Returns:
        ABETMapping: Configured mapping object
    """
    mapping = ABETMapping()

    for criterion_title, data in mapping_dict.get('mappings', {}).items():
        outcomes = data.get('outcomes', [])
        weights = data.get('weights', {})
        mapping.add_mapping(criterion_title, outcomes, weights)

    return mapping