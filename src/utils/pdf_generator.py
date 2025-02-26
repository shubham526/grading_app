"""
PDF Generator for the Rubric Grading Tool.

This module provides functionality to generate PDF reports from assessment data.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
import datetime


def generate_assessment_pdf(file_path, assessment_data):
    """
    Generate a PDF report for an assessment.

    Args:
        file_path (str): Path where to save the PDF
        assessment_data (dict): Assessment data dictionary

    Returns:
        None
    """
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    styles = getSampleStyleSheet()

    # Create custom styles
    styles.add(ParagraphStyle(
        name='Title',
        parent=styles['Heading1'],
        alignment=1,  # Center alignment
        spaceAfter=12
    ))

    styles.add(ParagraphStyle(
        name='CriterionTitle',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=6
    ))

    styles.add(ParagraphStyle(
        name='Normal_Justified',
        parent=styles['Normal'],
        alignment=4  # Justified
    ))

    # Build content
    content = []

    # Header information
    title = assessment_data.get("assignment_name", "Assessment")
    content.append(Paragraph(title, styles['Title']))

    student_name = assessment_data.get("student_name", "")
    if student_name:
        content.append(Paragraph(f"Student: {student_name}", styles['Normal']))

    # Add date
    current_date = datetime.datetime.now().strftime("%B %d, %Y")
    content.append(Paragraph(f"Date: {current_date}", styles['Normal']))

    # Add score
    percentage = assessment_data.get("percentage", 0)
    total_awarded = assessment_data.get("total_awarded", 0)
    total_possible = assessment_data.get("total_possible", 0)

    # Create score table
    score_data = [
        ["Score", f"{total_awarded} / {total_possible}"],
        ["Percentage", f"{percentage:.1f}%"]
    ]

    # Determine grade based on percentage
    grade = ""
    if percentage >= 90:
        grade = "A"
    elif percentage >= 80:
        grade = "B"
    elif percentage >= 70:
        grade = "C"
    elif percentage >= 60:
        grade = "D"
    else:
        grade = "F"

    score_data.append(["Grade", grade])

    score_table = Table(score_data, colWidths=[100, 100])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ]))

    content.append(Spacer(1, 12))
    content.append(score_table)
    content.append(Spacer(1, 20))

    # Summary heading
    content.append(Paragraph("Assessment Summary", styles['Heading2']))
    content.append(Spacer(1, 6))

    # Add each criterion
    for criterion in assessment_data.get("criteria", []):
        # Criterion title
        content.append(Paragraph(criterion.get("title", ""), styles['CriterionTitle']))

        # Points
        points_awarded = criterion.get("points_awarded", 0)
        points_possible = criterion.get("points_possible", 0)
        content.append(Paragraph(f"Points: {points_awarded} / {points_possible}", styles['Normal']))

        # Selected level if any
        selected_level = criterion.get("selected_level", "")
        if selected_level:
            content.append(Paragraph(f"Achievement level: {selected_level}", styles['Normal']))

        # Comments if any
        comments = criterion.get("comments", "")
        if comments:
            content.append(Paragraph("Comments:", styles['Normal']))
            content.append(Paragraph(comments, styles['Normal_Justified']))

        content.append(Spacer(1, 12))

    # Add footer with page numbers
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.drawRightString(letter[0] - 30, 30, text)
        canvas.restoreState()

    # Build the PDF
    doc.build(content, onFirstPage=add_page_number, onLaterPages=add_page_number)