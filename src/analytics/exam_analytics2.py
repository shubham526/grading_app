"""
Exam Analytics Tool for "Choose Best N of M" Format - CORRECTED
For exams where students can attempt any number of questions,
and the best N are counted toward their grade.
"""

import os
import sys
import json
import argparse
import numpy as np
from scipy import stats
from datetime import datetime
import csv
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib

matplotlib.use('Agg')
import seaborn as sns

sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['font.size'] = 10


def load_graded_exams(folder_path):
    """Load all JSON graded exam files from a folder."""
    exams = []
    if not os.path.exists(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist!")
        return exams

    json_files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
    if not json_files:
        print(f"Warning: No JSON files found in '{folder_path}'")
        return exams

    print(f"Found {len(json_files)} JSON files")
    for filename in json_files:
        filepath = os.path.join(folder_path, filename)
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                exams.append(data)
                print(f"  ✓ Loaded: {filename}")
        except Exception as e:
            print(f"  ✗ Error loading {filename}: {e}")

    return exams


def extract_analytics_data_with_attempts(exams):
    """
    Extract data tracking BOTH attempts and counting.

    Key distinction:
    - ATTEMPTED (selected=true): Student wrote an answer to this question
    - COUNTED (counted=true): Question was included in best 5 for grading
    - SKIPPED (selected=false): Student didn't write an answer
    """
    question_attempts = defaultdict(lambda: {
        'attempted_by': [],  # All students who attempted (selected=true)
        'counted_by': [],  # Students where it counted in best 5
        'skipped_by': [],  # Students who didn't attempt (selected=false)
        'all_scores': [],  # All scores (for all attempts)
        'counted_scores': [],  # Only scores that counted toward grade
        'max_points': 0
    })

    overall_scores = []
    student_info = []
    assignment_name = None
    student_attempt_counts = []  # Track how many questions each student attempted

    for student_idx, exam in enumerate(exams):
        if assignment_name is None:
            assignment_name = exam.get('assignment_name', 'Unknown Assignment')

        student_name = exam.get('student_name', 'Unknown Student')
        total_awarded = exam.get('total_awarded', 0)
        total_possible = exam.get('total_possible', 0)
        percentage = exam.get('percentage', 0)

        overall_scores.append(percentage)

        if percentage >= 90:
            grade = 'A'
        elif percentage >= 80:
            grade = 'B'
        elif percentage >= 70:
            grade = 'C'
        elif percentage >= 60:
            grade = 'D'
        else:
            grade = 'F'

        question_summary = exam.get('question_summary', [])

        # Count how many questions this student attempted
        n_attempted = sum(1 for q in question_summary if q.get('selected', False))
        n_counted = sum(1 for q in question_summary if q.get('counted', False))
        student_attempt_counts.append(n_attempted)

        student_info.append({
            'name': student_name,
            'score': total_awarded,
            'max_score': total_possible,
            'percentage': percentage,
            'grade': grade,
            'index': student_idx,
            'n_attempted': n_attempted,
            'n_counted': n_counted
        })

        # Process each question
        for q in question_summary:
            q_num = q.get('question')
            awarded = q.get('awarded', 0)
            possible = q.get('possible', 0)
            selected = q.get('selected', False)
            counted = q.get('counted', False)

            question_attempts[q_num]['max_points'] = possible

            if selected:
                # Student ATTEMPTED this question (wrote an answer)
                question_attempts[q_num]['attempted_by'].append(student_idx)
                question_attempts[q_num]['all_scores'].append(awarded)

                if counted:
                    # Question also COUNTED toward best 5
                    question_attempts[q_num]['counted_by'].append(student_idx)
                    question_attempts[q_num]['counted_scores'].append(awarded)
            else:
                # Student SKIPPED this question (didn't write an answer)
                question_attempts[q_num]['skipped_by'].append(student_idx)

    return dict(question_attempts), overall_scores, student_info, assignment_name, student_attempt_counts


def calculate_attempt_rate(question_data, total_students):
    """Calculate what percentage of students attempted each question."""
    attempt_rates = {}

    for q_num, data in question_data.items():
        n_attempted = len(data['attempted_by'])
        attempt_rates[q_num] = (n_attempted / total_students * 100) if total_students > 0 else 0

    return attempt_rates


def calculate_counting_rate(question_data, total_students):
    """Calculate what percentage of students had this question COUNT in best 5."""
    counting_rates = {}

    for q_num, data in question_data.items():
        n_counted = len(data['counted_by'])
        counting_rates[q_num] = (n_counted / total_students * 100) if total_students > 0 else 0

    return counting_rates


def calculate_conditional_difficulty(question_data, use_all_attempts=True):
    """
    Calculate difficulty among students who attempted the question.

    use_all_attempts=True: Use all attempts (including those not counted)
    use_all_attempts=False: Use only attempts that counted toward grade
    """
    difficulty = {}

    for q_num, data in question_data.items():
        scores = data['all_scores'] if use_all_attempts else data['counted_scores']

        if data['max_points'] > 0 and len(scores) > 0:
            avg_score = np.mean(scores)
            difficulty[q_num] = (avg_score / data['max_points']) * 100
        else:
            difficulty[q_num] = 0

    return difficulty


def calculate_conditional_discrimination(question_data, overall_scores, use_all_attempts=True):
    """
    Calculate discrimination among students who attempted the question.

    use_all_attempts=True: Use all attempts
    use_all_attempts=False: Use only attempts that counted
    """
    discrimination = {}

    for q_num, data in question_data.items():
        attempted_indices = data['attempted_by'] if use_all_attempts else data['counted_by']
        scores = data['all_scores'] if use_all_attempts else data['counted_scores']

        if len(attempted_indices) < 10:
            discrimination[q_num] = None
            continue

        # Get overall scores for students who attempted
        attempted_overall_scores = [overall_scores[i] for i in attempted_indices]

        n = len(attempted_indices)
        cutoff = max(1, int(n * 0.27))

        sorted_indices_local = np.argsort(attempted_overall_scores)
        lower_indices = sorted_indices_local[:cutoff]
        upper_indices = sorted_indices_local[-cutoff:]

        if data['max_points'] > 0:
            scores_array = np.array(scores)
            upper_avg = np.mean(scores_array[upper_indices])
            lower_avg = np.mean(scores_array[lower_indices])

            discrimination[q_num] = (upper_avg - lower_avg) / data['max_points']
        else:
            discrimination[q_num] = 0

    return discrimination


def analyze_selection_patterns(question_data, overall_scores):
    """
    Analyze WHO is attempting each question.
    Compare strong vs weak students.
    """
    selection_patterns = {}

    for q_num, data in question_data.items():
        attempted_indices = data['attempted_by']
        skipped_indices = data['skipped_by']
        counted_indices = data['counted_by']

        if len(attempted_indices) == 0:
            selection_patterns[q_num] = {
                'avg_overall_attempters': 0,
                'avg_overall_skippers': 0,
                'avg_overall_counted': 0,
                'selection_bias': 'None (no attempts)',
                'quality_analysis': 'No data'
            }
            continue

        # Average overall score of students who attempted
        avg_overall_attempted = np.mean([overall_scores[i] for i in attempted_indices])

        # Average overall score of students who skipped
        if len(skipped_indices) > 0:
            avg_overall_skipped = np.mean([overall_scores[i] for i in skipped_indices])
        else:
            avg_overall_skipped = 0

        # Average overall score of students where it COUNTED
        if len(counted_indices) > 0:
            avg_overall_counted = np.mean([overall_scores[i] for i in counted_indices])
        else:
            avg_overall_counted = 0

        # Determine selection bias
        diff = avg_overall_attempted - avg_overall_skipped

        if diff > 5:
            bias = "Strong students prefer"
        elif diff < -5:
            bias = "Weak students prefer"
        else:
            bias = "No clear bias"

        # Analyze question quality based on attempt vs counting
        n_attempted = len(attempted_indices)
        n_counted = len(counted_indices)
        exclusion_rate = ((n_attempted - n_counted) / n_attempted * 100) if n_attempted > 0 else 0

        if exclusion_rate > 30:
            quality = "Often excluded from best 5 (may be harder)"
        elif exclusion_rate < 10:
            quality = "Usually in best 5 (easier/better performance)"
        else:
            quality = "Mixed results"

        selection_patterns[q_num] = {
            'avg_overall_attempters': avg_overall_attempted,
            'avg_overall_skippers': avg_overall_skipped,
            'avg_overall_counted': avg_overall_counted,
            'selection_bias': bias,
            'bias_magnitude': abs(diff),
            'exclusion_rate': exclusion_rate,
            'quality_analysis': quality
        }

    return selection_patterns


def calculate_grade_distribution(overall_scores):
    """Calculate grade distribution."""
    grades = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
    for score in overall_scores:
        if score >= 90:
            grades['A'] += 1
        elif score >= 80:
            grades['B'] += 1
        elif score >= 70:
            grades['C'] += 1
        elif score >= 60:
            grades['D'] += 1
        else:
            grades['F'] += 1
    return grades


def get_discrimination_quality(value):
    """Get quality rating for discrimination index."""
    if value is None:
        return "Insufficient data"
    if value >= 0.40:
        return "Excellent"
    elif value >= 0.30:
        return "Good"
    elif value >= 0.20:
        return "Fair"
    else:
        return "Poor"


# ============================================================================
# PLOTTING FUNCTIONS
# ============================================================================

def plot_attempt_vs_counting_rates(question_stats, output_dir, assignment_name):
    """
    Plot attempt rate vs counting rate.
    Shows which questions students tried but weren't good enough to count.
    """
    plt.figure(figsize=(12, 6))

    questions = sorted(question_stats.keys())
    attempt_rates = [question_stats[q]['attempt_rate'] for q in questions]
    counting_rates = [question_stats[q]['counting_rate'] for q in questions]

    x = np.arange(len(questions))
    width = 0.35

    bars1 = plt.bar(x - width / 2, attempt_rates, width, label='ATTEMPTED',
                    color='#3498db', edgecolor='black', linewidth=1.5)
    bars2 = plt.bar(x + width / 2, counting_rates, width, label='COUNTED in best 5',
                    color='#2ecc71', edgecolor='black', linewidth=1.5)

    plt.xlabel('Question', fontsize=12, fontweight='bold')
    plt.ylabel('Percentage of Students (%)', fontsize=12, fontweight='bold')
    plt.title(f'Attempt Rate vs. Counting Rate\n{assignment_name}\n' +
              '(Gap = attempts excluded from best 5)',
              fontsize=14, fontweight='bold')
    plt.xticks(x, [f"Q{q}" for q in questions])
    plt.legend()
    plt.grid(True, alpha=0.3, axis='y')
    plt.ylim(0, 110)

    # Add exclusion rate annotations
    for i, q in enumerate(questions):
        exclusion = question_stats[q]['selection_pattern']['exclusion_rate']
        if exclusion > 10:
            y_pos = max(attempt_rates[i], counting_rates[i]) + 3
            plt.text(i, y_pos, f'{exclusion:.0f}% excluded',
                     ha='center', fontsize=8, color='red', fontweight='bold')

    output_path = os.path.join(output_dir, 'attempt_vs_counting.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Created: attempt_vs_counting.png")


def plot_selection_bias(question_stats, output_dir, assignment_name):
    """Plot WHO is choosing each question."""
    plt.figure(figsize=(12, 7))

    questions = sorted(question_stats.keys())
    attempters_avg = [question_stats[q]['selection_pattern']['avg_overall_attempters']
                      for q in questions]
    skippers_avg = [question_stats[q]['selection_pattern']['avg_overall_skippers']
                    for q in questions]
    counted_avg = [question_stats[q]['selection_pattern']['avg_overall_counted']
                   for q in questions]

    x = np.arange(len(questions))
    width = 0.25

    bars1 = plt.bar(x - width, attempters_avg, width, label='Who ATTEMPTED',
                    color='#3498db', edgecolor='black', linewidth=1.5)
    bars2 = plt.bar(x, counted_avg, width, label='Who had it COUNT',
                    color='#2ecc71', edgecolor='black', linewidth=1.5)
    bars3 = plt.bar(x + width, skippers_avg, width, label='Who SKIPPED',
                    color='#e74c3c', edgecolor='black', linewidth=1.5)

    plt.xlabel('Question', fontsize=12, fontweight='bold')
    plt.ylabel('Average Overall Exam Score (%)', fontsize=12, fontweight='bold')
    plt.title(f'Selection Bias Analysis\n{assignment_name}\n' +
              '(Higher = stronger students)',
              fontsize=14, fontweight='bold')
    plt.xticks(x, [f"Q{q}" for q in questions])
    plt.legend()
    plt.grid(True, alpha=0.3, axis='y')

    # Add annotations for significant bias
    for i, q in enumerate(questions):
        pattern = question_stats[q]['selection_pattern']
        diff = pattern['avg_overall_attempters'] - pattern['avg_overall_skippers']

        if abs(diff) > 5:
            y_pos = max(attempters_avg[i], skippers_avg[i], counted_avg[i]) + 3
            if diff > 0:
                text = 'Strong prefer ↑'
                color = 'green'
            else:
                text = 'Weak prefer ↓'
                color = 'red'

            plt.text(i, y_pos, text, ha='center', fontsize=9,
                     fontweight='bold', color=color)

    output_path = os.path.join(output_dir, 'selection_bias.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Created: selection_bias.png")


def plot_difficulty_comparison(question_stats, output_dir, assignment_name):
    """
    Compare difficulty calculated two ways:
    1. All attempts
    2. Only counted attempts
    """
    plt.figure(figsize=(12, 6))

    questions = sorted(question_stats.keys())
    diff_all = [question_stats[q]['difficulty_all_attempts'] for q in questions]
    diff_counted = [question_stats[q]['difficulty_counted_only'] for q in questions]

    x = np.arange(len(questions))
    width = 0.35

    bars1 = plt.bar(x - width / 2, diff_all, width, label='ALL attempts',
                    color='#3498db', edgecolor='black', linewidth=1.5, alpha=0.7)
    bars2 = plt.bar(x + width / 2, diff_counted, width, label='COUNTED only (best 5)',
                    color='#2ecc71', edgecolor='black', linewidth=1.5, alpha=0.7)

    plt.xlabel('Question', fontsize=12, fontweight='bold')
    plt.ylabel('Difficulty (% Mean Score)', fontsize=12, fontweight='bold')
    plt.title(f'Difficulty: All Attempts vs. Best 5 Only\n{assignment_name}\n' +
              '(Counted-only is higher = weaker students excluded)',
              fontsize=14, fontweight='bold')
    plt.xticks(x, [f"Q{q}" for q in questions])
    plt.legend()
    plt.grid(True, alpha=0.3, axis='y')
    plt.axhline(y=70, color='gray', linestyle='--', alpha=0.5)

    output_path = os.path.join(output_dir, 'difficulty_comparison.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Created: difficulty_comparison.png")


def plot_student_attempt_histogram(student_attempt_counts, output_dir, assignment_name):
    """Show how many questions students attempted."""
    plt.figure(figsize=(10, 6))

    plt.hist(student_attempt_counts, bins=range(0, 9), alpha=0.7,
             color='steelblue', edgecolor='black', rwidth=0.8)

    plt.xlabel('Number of Questions Attempted', fontsize=12, fontweight='bold')
    plt.ylabel('Number of Students', fontsize=12, fontweight='bold')
    plt.title(f'Student Attempt Distribution\n{assignment_name}\n' +
              '(Minimum required: 5)',
              fontsize=14, fontweight='bold')
    plt.xticks(range(0, 8))
    plt.axvline(x=5, color='red', linestyle='--', linewidth=2,
                label='Minimum required (5)')
    plt.legend()
    plt.grid(True, alpha=0.3, axis='y')

    # Add statistics
    mean_attempts = np.mean(student_attempt_counts)
    median_attempts = np.median(student_attempt_counts)
    plt.text(0.7, 0.95, f'Mean: {mean_attempts:.1f}\nMedian: {median_attempts:.0f}',
             transform=plt.gca().transAxes, fontsize=12, fontweight='bold',
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    output_path = os.path.join(output_dir, 'student_attempts.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Created: student_attempts.png")


def plot_score_distribution(overall_scores, output_dir, assignment_name):
    """Standard score distribution plot."""
    plt.figure(figsize=(12, 6))

    n, bins, patches = plt.hist(overall_scores, bins=15, alpha=0.7,
                                color='steelblue', edgecolor='black',
                                density=True, label='Actual Distribution')

    mu, sigma = np.mean(overall_scores), np.std(overall_scores)
    x = np.linspace(0, 100, 100)
    y = stats.norm.pdf(x, mu, sigma)
    plt.plot(x, y, 'r-', linewidth=2, label=f'Normal (μ={mu:.1f}, σ={sigma:.1f})')

    plt.xlabel('Score (%)', fontsize=12, fontweight='bold')
    plt.ylabel('Density', fontsize=12, fontweight='bold')
    plt.title(f'Score Distribution\n{assignment_name}', fontsize=14, fontweight='bold')
    plt.legend()
    plt.grid(True, alpha=0.3)

    output_path = os.path.join(output_dir, 'score_distribution.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Created: score_distribution.png")


def plot_grade_distribution(grades, output_dir, assignment_name):
    """Standard grade distribution plot."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    grade_labels = ['A', 'B', 'C', 'D', 'F']
    counts = [grades.get(g, 0) for g in grade_labels]
    colors = ['#2ecc71', '#3498db', '#f39c12', '#e67e22', '#e74c3c']

    bars = ax1.bar(grade_labels, counts, color=colors, edgecolor='black', linewidth=1.5)
    ax1.set_xlabel('Grade', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Number of Students', fontsize=12, fontweight='bold')
    ax1.set_title('Grade Distribution', fontsize=14, fontweight='bold')

    for bar in bars:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2., height,
                 f'{int(height)}', ha='center', va='bottom', fontweight='bold')

    total = sum(counts)
    if total > 0:
        filtered_labels = [grade_labels[i] for i, c in enumerate(counts) if c > 0]
        filtered_counts = [c for c in counts if c > 0]
        filtered_colors = [colors[i] for i, c in enumerate(counts) if c > 0]

        ax2.pie(filtered_counts, labels=filtered_labels, colors=filtered_colors,
                autopct='%1.1f%%', startangle=90, textprops={'fontweight': 'bold'})
        ax2.set_title('Grade Percentages', fontsize=14, fontweight='bold')

    plt.suptitle(f'{assignment_name}', fontsize=16, fontweight='bold', y=1.02)

    output_path = os.path.join(output_dir, 'grade_distribution.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Created: grade_distribution.png")


def generate_all_plots(analytics_data, student_attempt_counts, output_dir):
    """Generate all plots."""
    print("\nGenerating plots for 'best N of M' format...")

    assignment_name = analytics_data['assignment_name']
    overall_scores = [s['percentage'] for s in analytics_data['student_scores']]
    grades = analytics_data['grade_distribution']
    question_stats = analytics_data['question_stats']

    plot_attempt_vs_counting_rates(question_stats, output_dir, assignment_name)
    plot_selection_bias(question_stats, output_dir, assignment_name)
    plot_difficulty_comparison(question_stats, output_dir, assignment_name)
    plot_student_attempt_histogram(student_attempt_counts, output_dir, assignment_name)
    plot_score_distribution(overall_scores, output_dir, assignment_name)
    plot_grade_distribution(grades, output_dir, assignment_name)

    print(f"\n✓ All plots saved to: {output_dir}/")


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

def generate_analytics_report(exams):
    """Generate complete analytics report."""
    if not exams:
        print("No exam data to analyze!")
        return None, None

    question_data, overall_scores, student_info, assignment_name, student_attempt_counts = extract_analytics_data_with_attempts(
        exams)

    if not overall_scores:
        print("No student scores found!")
        return None, None

    total_students = len(overall_scores)
    print(f"\nAnalyzing {total_students} students with 'best N of M' format...")

    # Calculate metrics
    attempt_rates = calculate_attempt_rate(question_data, total_students)
    counting_rates = calculate_counting_rate(question_data, total_students)
    difficulty_all = calculate_conditional_difficulty(question_data, use_all_attempts=True)
    difficulty_counted = calculate_conditional_difficulty(question_data, use_all_attempts=False)
    discrimination_all = calculate_conditional_discrimination(question_data, overall_scores, use_all_attempts=True)
    discrimination_counted = calculate_conditional_discrimination(question_data, overall_scores, use_all_attempts=False)
    selection_patterns = analyze_selection_patterns(question_data, overall_scores)
    grades = calculate_grade_distribution(overall_scores)

    # Build question statistics
    question_stats = {}
    for q_num in sorted(question_data.keys()):
        data = question_data[q_num]

        question_stats[q_num] = {
            'attempt_rate': attempt_rates.get(q_num, 0),
            'counting_rate': counting_rates.get(q_num, 0),
            'n_attempted': len(data['attempted_by']),
            'n_counted': len(data['counted_by']),
            'n_skipped': len(data['skipped_by']),
            'difficulty_all_attempts': difficulty_all.get(q_num, 0),
            'difficulty_counted_only': difficulty_counted.get(q_num, 0),
            'discrimination_all_attempts': discrimination_all.get(q_num, 0),
            'discrimination_counted_only': discrimination_counted.get(q_num, 0),
            'discrimination_quality': get_discrimination_quality(discrimination_all.get(q_num)),
            'max_points': data['max_points'],
            'selection_pattern': selection_patterns[q_num]
        }

    analytics_data = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'assignment_name': assignment_name,
        'num_students': total_students,
        'exam_format': 'Best N of M (Attempt any, grade best 5)',
        'overall_stats': {
            'mean': float(np.mean(overall_scores)),
            'median': float(np.median(overall_scores)),
            'std_dev': float(np.std(overall_scores)),
            'min': float(np.min(overall_scores)),
            'max': float(np.max(overall_scores))
        },
        'attempt_stats': {
            'mean_attempts': float(np.mean(student_attempt_counts)),
            'median_attempts': float(np.median(student_attempt_counts)),
            'min_attempts': int(np.min(student_attempt_counts)),
            'max_attempts': int(np.max(student_attempt_counts))
        },
        'grade_distribution': grades,
        'question_stats': question_stats,
        'student_scores': student_info
    }

    return analytics_data, student_attempt_counts


def print_analytics_summary(analytics_data):
    """Print formatted summary."""
    if not analytics_data:
        return

    print("\n" + "=" * 90)
    print(f"ANALYTICS REPORT: {analytics_data['assignment_name']}")
    print(f"Format: {analytics_data['exam_format']}")
    print("=" * 90)

    print(f"\nGenerated: {analytics_data['timestamp']}")
    print(f"Number of Students: {analytics_data['num_students']}")

    print("\n" + "-" * 90)
    print("OVERALL STATISTICS")
    print("-" * 90)
    stats = analytics_data['overall_stats']
    print(f"  Mean Score:       {stats['mean']:.2f}%")
    print(f"  Median Score:     {stats['median']:.2f}%")
    print(f"  Std Deviation:    {stats['std_dev']:.2f}")
    print(f"  Minimum Score:    {stats['min']:.2f}%")
    print(f"  Maximum Score:    {stats['max']:.2f}%")

    print("\n" + "-" * 90)
    print("STUDENT ATTEMPT STATISTICS")
    print("-" * 90)
    attempt_stats = analytics_data['attempt_stats']
    print(f"  Mean Attempts:    {attempt_stats['mean_attempts']:.1f} questions")
    print(f"  Median Attempts:  {attempt_stats['median_attempts']:.0f} questions")
    print(f"  Min Attempts:     {attempt_stats['min_attempts']} questions")
    print(f"  Max Attempts:     {attempt_stats['max_attempts']} questions")

    print("\n" + "-" * 90)
    print("GRADE DISTRIBUTION")
    print("-" * 90)
    grades = analytics_data['grade_distribution']
    total = sum(grades.values())
    for grade in ['A', 'B', 'C', 'D', 'F']:
        count = grades.get(grade, 0)
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {grade}: {count:2d} students ({pct:5.1f}%) {bar}")

    print("\n" + "=" * 90)
    print("QUESTION ANALYSIS - Key Metrics")
    print("=" * 90)
    print(f"{'Q':<4} {'Attempt':<10} {'Counted':<10} {'N_Att':<8} {'Diff%':<10} {'Disc':<10} {'Selection Bias'}")
    print("-" * 90)

    for q_num in sorted(analytics_data['question_stats'].keys()):
        stats = analytics_data['question_stats'][q_num]
        pattern = stats['selection_pattern']

        attempt_str = f"{stats['attempt_rate']:.1f}%"
        counted_str = f"{stats['counting_rate']:.1f}%"
        n_str = f"{stats['n_attempted']}"
        diff_str = f"{stats['difficulty_all_attempts']:.1f}%"
        disc_val = stats['discrimination_all_attempts']
        disc_str = f"{disc_val:.3f}" if disc_val is not None else "N/A"
        bias = pattern['selection_bias']

        print(f"Q{q_num:<3} {attempt_str:<10} {counted_str:<10} {n_str:<8} {diff_str:<10} {disc_str:<10} {bias}")

    print("\n" + "=" * 90)
    print("DETAILED QUESTION ANALYSIS")
    print("=" * 90)

    for q_num in sorted(analytics_data['question_stats'].keys()):
        stats = analytics_data['question_stats'][q_num]
        pattern = stats['selection_pattern']

        print(f"\nQuestion {q_num}:")
        print(f"  Attempted by:     {stats['n_attempted']} students ({stats['attempt_rate']:.1f}%)")
        print(f"  Counted for:      {stats['n_counted']} students ({stats['counting_rate']:.1f}%)")
        print(f"  Skipped by:       {stats['n_skipped']} students")
        print(f"  Exclusion rate:   {pattern['exclusion_rate']:.1f}% (attempted but not in best 5)")
        print(f"")
        print(f"  Difficulty (all attempts):     {stats['difficulty_all_attempts']:.1f}%")
        print(f"  Difficulty (counted only):     {stats['difficulty_counted_only']:.1f}%")
        print(f"  Discrimination (all attempts): {stats['discrimination_all_attempts']:.3f}" if stats['discrimination_all_attempts'] is not None else "  Discrimination (all attempts): N/A")
        print(f"")
        print(f"  Avg overall score of attempters: {pattern['avg_overall_attempters']:.1f}%")
        print(f"  Avg overall score of skippers:   {pattern['avg_overall_skippers']:.1f}%")
        print(f"  Selection bias:                  {pattern['selection_bias']}")
        print(f"  Quality analysis:                {pattern['quality_analysis']}")

    print("\n" + "=" * 90)


def export_to_csv(analytics_data, output_path):
    """Export analytics to CSV."""
    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)

        writer.writerow(['Analytics Report - Best N of M Format'])
        writer.writerow(['Generated:', analytics_data['timestamp']])
        writer.writerow(['Assignment:', analytics_data['assignment_name']])
        writer.writerow(['Format:', analytics_data['exam_format']])
        writer.writerow(['Number of Students:', analytics_data['num_students']])
        writer.writerow([])

        writer.writerow(['OVERALL STATISTICS'])
        writer.writerow(['Metric', 'Value'])
        overall = analytics_data['overall_stats']
        writer.writerow(['Mean Score', f"{overall['mean']:.2f}%"])
        writer.writerow(['Median Score', f"{overall['median']:.2f}%"])
        writer.writerow(['Standard Deviation', f"{overall['std_dev']:.2f}"])
        writer.writerow(['Minimum Score', f"{overall['min']:.2f}%"])
        writer.writerow(['Maximum Score', f"{overall['max']:.2f}%"])
        writer.writerow([])

        writer.writerow(['STUDENT ATTEMPT STATISTICS'])
        writer.writerow(['Metric', 'Value'])
        attempt_stats = analytics_data['attempt_stats']
        writer.writerow(['Mean Attempts', f"{attempt_stats['mean_attempts']:.1f}"])
        writer.writerow(['Median Attempts', f"{attempt_stats['median_attempts']:.0f}"])
        writer.writerow(['Min Attempts', attempt_stats['min_attempts']])
        writer.writerow(['Max Attempts', attempt_stats['max_attempts']])
        writer.writerow([])

        writer.writerow(['GRADE DISTRIBUTION'])
        writer.writerow(['Grade', 'Count', 'Percentage'])
        grades = analytics_data['grade_distribution']
        total = sum(grades.values())
        for grade in ['A', 'B', 'C', 'D', 'F']:
            count = grades.get(grade, 0)
            pct = (count / total * 100) if total > 0 else 0
            writer.writerow([grade, count, f"{pct:.1f}%"])
        writer.writerow([])

        writer.writerow(['QUESTION ANALYSIS - SUMMARY'])
        writer.writerow(['Question', 'Attempt Rate', 'Counting Rate', 'N Attempted',
                        'N Counted', 'Exclusion Rate', 'Difficulty (All)',
                        'Difficulty (Counted)', 'Discrimination', 'Selection Bias'])

        for q_num in sorted(analytics_data['question_stats'].keys()):
            stats = analytics_data['question_stats'][q_num]
            pattern = stats['selection_pattern']
            disc = stats['discrimination_all_attempts']
            disc_str = f"{disc:.3f}" if disc is not None else "N/A"

            writer.writerow([
                f"Question {q_num}",
                f"{stats['attempt_rate']:.1f}%",
                f"{stats['counting_rate']:.1f}%",
                stats['n_attempted'],
                stats['n_counted'],
                f"{pattern['exclusion_rate']:.1f}%",
                f"{stats['difficulty_all_attempts']:.1f}%",
                f"{stats['difficulty_counted_only']:.1f}%",
                disc_str,
                pattern['selection_bias']
            ])
        writer.writerow([])

        writer.writerow(['QUESTION ANALYSIS - DETAILED'])
        writer.writerow(['Question', 'Attempters Avg Score', 'Skippers Avg Score',
                        'Counted Avg Score', 'Quality Analysis'])

        for q_num in sorted(analytics_data['question_stats'].keys()):
            stats = analytics_data['question_stats'][q_num]
            pattern = stats['selection_pattern']

            writer.writerow([
                f"Question {q_num}",
                f"{pattern['avg_overall_attempters']:.1f}%",
                f"{pattern['avg_overall_skippers']:.1f}%",
                f"{pattern['avg_overall_counted']:.1f}%",
                pattern['quality_analysis']
            ])
        writer.writerow([])

        writer.writerow(['STUDENT SCORES'])
        writer.writerow(['Student', 'Score', 'Percentage', 'Grade', 'N Attempted', 'N Counted'])

        for student in sorted(analytics_data['student_scores'], key=lambda x: x['percentage'], reverse=True):
            writer.writerow([
                student['name'],
                f"{student['score']:.1f} / {student['max_score']:.1f}",
                f"{student['percentage']:.1f}%",
                student['grade'],
                student['n_attempted'],
                student['n_counted']
            ])

    print(f"\n✓ CSV report exported to: {output_path}")


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Generate analytics for "best N of M" format exams',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('-i', '--input', required=True,
                        help='Input folder containing graded exam JSON files')
    parser.add_argument('-o', '--output',
                        help='Output CSV file path')
    parser.add_argument('--plots', action='store_true', default=True,
                        help='Generate visualization plots (default: True)')
    parser.add_argument('--no-plots', action='store_true',
                        help='Skip generating plots')
    parser.add_argument('--plot-dir',
                        help='Directory to save plots (default: plots/ in input folder)')
    parser.add_argument('--no-console', action='store_true',
                        help='Suppress console output')

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_arguments()

    input_folder = args.input
    if not os.path.exists(input_folder):
        print(f"Error: Input folder '{input_folder}' does not exist!")
        sys.exit(1)

    output_path = args.output if args.output else os.path.join(input_folder, 'analytics_best_n_of_m.csv')

    if args.plot_dir:
        plot_dir = args.plot_dir
    else:
        plot_dir = os.path.join(input_folder, 'plots')

    generate_plots = args.plots and not args.no_plots
    if generate_plots:
        os.makedirs(plot_dir, exist_ok=True)

    if not args.no_console:
        print(f"\n{'=' * 90}")
        print("EXAM ANALYTICS TOOL - Best N of M Format")
        print(f"{'=' * 90}")
        print(f"\nInput folder: {input_folder}")
        print(f"Output file:  {output_path}")
        if generate_plots:
            print(f"Plot folder:  {plot_dir}")

    exams = load_graded_exams(input_folder)
    if not exams:
        print("\nNo exams loaded. Exiting.")
        sys.exit(1)

    analytics_data, student_attempt_counts = generate_analytics_report(exams)
    if not analytics_data:
        print("\nFailed to generate analytics. Exiting.")
        sys.exit(1)

    if not args.no_console:
        print_analytics_summary(analytics_data)

    export_to_csv(analytics_data, output_path)

    if generate_plots:
        generate_all_plots(analytics_data, student_attempt_counts, plot_dir)

    if not args.no_console:
        print("\n" + "=" * 90)
        print("ANALYSIS COMPLETE!")
        print("=" * 90)
        if generate_plots:
            print(f"\n📊 Generated 6 visualization plots in: {plot_dir}/")
        print(f"📄 Report saved to: {output_path}")


if __name__ == "__main__":
    main()