# utils/pdf_generator.py
# Replace your existing src/utils/pdf_generator.py with this updated version

from src.core.grader import extract_question_number
import markdown
from markdown.extensions.extra import ExtraExtension


def get_letter_grade(percentage):
    """Return a letter grade based on percentage."""
    if percentage >= 90:
        return "A"
    elif percentage >= 80:
        return "B"
    elif percentage >= 70:
        return "C"
    elif percentage >= 60:
        return "D"
    else:
        return "F"


def generate_assessment_pdf(file_path, assessment_data):
    """Generate a PDF report of the assessment."""
    try:
        # Import reportlab for PDF generation
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_LEFT

        # Create the PDF document
        doc = SimpleDocTemplate(file_path, pagesize=letter)
        styles = getSampleStyleSheet()

        # Create custom styles
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=1,  # Center
            spaceAfter=12
        )

        heading_style = ParagraphStyle(
            'Heading',
            parent=styles['Heading2'],
            fontSize=14,
            spaceAfter=6
        )

        subheading_style = ParagraphStyle(
            'Subheading',
            parent=styles['Heading3'],
            fontSize=12,
            spaceAfter=6
        )

        # Style for criterion descriptions
        description_style = ParagraphStyle(
            'Description',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#555555'),
            leftIndent=20,
            spaceAfter=6
        )

        # Style for achievement level descriptions
        level_description_style = ParagraphStyle(
            'LevelDescription',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            leftIndent=30,
            rightIndent=10,
            spaceAfter=4,
            alignment=TA_LEFT
        )

        normal_style = styles['Normal']

        # Start building the document content
        content = []

        # Header information
        content.append(Paragraph(f"{assessment_data['assignment_name']}", title_style))
        content.append(Spacer(1, 0.1 * inch))
        content.append(Paragraph(f"Student: {assessment_data['student_name']}", heading_style))
        content.append(Spacer(1, 0.2 * inch))

        # Summary table at the top
        percentage = assessment_data['percentage']
        letter_grade = get_letter_grade(percentage)

        summary_data = [
            ["Score", f"{assessment_data['total_awarded']} / {assessment_data['total_possible']}"],
            ["Percentage", f"{percentage:.1f}%"],
            ["Grade", letter_grade]
        ]

        summary_table = Table(summary_data, colWidths=[2 * inch, 2 * inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))

        content.append(summary_table)
        content.append(Spacer(1, 0.3 * inch))

        # Grading configuration summary
        config = assessment_data['grading_config']

        if config['grading_mode'] == 'best_scores':
            config_text = f"Grading Method: Best {config['questions_to_count']} of {len(assessment_data['question_summary'])} questions"
        else:
            config_text = f"Grading Method: {config['questions_to_count']} selected questions"

        content.append(Paragraph(config_text, normal_style))
        content.append(Spacer(1, 0.2 * inch))

        # Question summary table
        content.append(Paragraph("Question Summary", heading_style))

        # Create question summary table with Paragraph elements for better wrapping
        question_data = [["Question", "Score", "Percentage", "Status"]]

        # Sort questions by whether they're counted, then by question number
        sorted_summary = sorted(
            assessment_data['question_summary'],
            key=lambda x: (not x['counted'], x['question'])
        )

        for q_summary in sorted_summary:
            q_num = q_summary['question']
            score = f"{q_summary['awarded']} / {q_summary['possible']}"
            percentage = f"{q_summary['percentage']:.1f}%"

            if q_summary['counted']:
                status = "Counted in final score"
            elif q_summary['selected']:
                status = "Selected but not counted"
            else:
                status = "Not selected"

            question_data.append([
                Paragraph(f"Question {q_num}", normal_style),
                Paragraph(score, normal_style),
                Paragraph(percentage, normal_style),
                Paragraph(status, normal_style)
            ])

        # Create and style the table
        q_table = Table(question_data, colWidths=[1.5 * inch, 1 * inch, 1 * inch, 2.5 * inch])
        q_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (1, 1), (2, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))

        content.append(q_table)
        content.append(Spacer(1, 0.2 * inch))

        # Detailed criteria
        content.append(Paragraph("Detailed Assessment", heading_style))

        # Group criteria by question
        question_criteria = {}
        for criterion in assessment_data['criteria']:
            q_num = extract_question_number(criterion['title'])
            if q_num:
                if q_num not in question_criteria:
                    question_criteria[q_num] = []
                question_criteria[q_num].append(criterion)

        # Add each question's criteria
        for q_num in sorted(question_criteria.keys()):
            # Check if this question was selected
            if q_num in assessment_data['selected_questions']:
                # Determine status for this question
                if q_num in assessment_data['counted_questions']:
                    status = " (Counted in final score)"
                    q_style = subheading_style
                else:
                    status = " (Not counted in final score)"
                    # Create a muted style for non-counted questions
                    q_style = ParagraphStyle(
                        'MutedHeading',
                        parent=subheading_style,
                        textColor=colors.gray
                    )

                content.append(Paragraph(f"Question {q_num}{status}", q_style))

                # Process each criterion in this question
                for criterion in question_criteria[q_num]:
                    # Criterion title
                    title = criterion['title'].replace(f"Question {q_num}", "").strip()
                    if title.startswith(":"):
                        title = title[1:].strip()

                    content.append(Paragraph(f"<b>{title}</b>", normal_style))

                    # Add criterion description if it exists
                    if 'description' in criterion and criterion['description']:
                        desc_text = criterion['description']
                        content.append(Paragraph(f"<i>{desc_text}</i>", description_style))

                    # Score information
                    score_text = f"<b>Score:</b> {criterion['points_awarded']} / {criterion['points_possible']} points"
                    content.append(Paragraph(score_text, normal_style))
                    content.append(Spacer(1, 0.05 * inch))

                    # Achievement levels (if available)
                    if 'levels' in criterion and criterion['levels']:
                        content.append(Paragraph("<b>Achievement Levels:</b>", normal_style))

                        for level in criterion['levels']:
                            level_title = level.get('title', '')
                            level_points = level.get('points', 0)
                            level_desc = level.get('description', '')

                            # Check if this level was selected
                            selected_level = criterion.get('selected_level', '')
                            # Extract just the level name (without points)
                            level_name = level_title.split('(')[0].strip()

                            if selected_level and level_name in selected_level:
                                # This level was selected - make it bold/highlighted
                                level_header = f"<b>➤ {level_title}</b> [SELECTED]"
                            else:
                                level_header = f"• {level_title}"

                            content.append(Paragraph(level_header, normal_style))

                            if level_desc:
                                content.append(Paragraph(level_desc, level_description_style))

                            content.append(Spacer(1, 0.05 * inch))

                    # Comments
                    comments = criterion.get('comments', "")
                    if comments:
                        content.append(Paragraph("<b>Instructor Comments:</b>", normal_style))
                        # Convert markdown to HTML for PDF
                        html_comments = markdown.markdown(comments, extensions=[ExtraExtension()])
                        # Replace LaTeX math delimiters with basic text
                        html_comments = html_comments.replace('$', '')
                        content.append(Paragraph(html_comments, normal_style))
                    else:
                        content.append(Paragraph("<i>No comments provided.</i>", description_style))

                    content.append(Spacer(1, 0.15 * inch))

                content.append(Spacer(1, 0.1 * inch))

        # Build and save the PDF
        doc.build(content)
        return True

    except ImportError:
        # If reportlab is not installed, use a simpler approach
        with open(file_path, 'w') as file:
            file.write(f"{assessment_data['assignment_name']}\n")
            file.write(f"Student: {assessment_data['student_name']}\n\n")

            # Simple summary
            file.write("SUMMARY\n-------\n")
            file.write(f"Score: {assessment_data['total_awarded']} / {assessment_data['total_possible']}\n")
            file.write(f"Percentage: {assessment_data['percentage']:.1f}%\n")
            file.write(f"Grade: {get_letter_grade(assessment_data['percentage'])}\n\n")

            file.write("Question Summary:\n")
            for q_summary in assessment_data['question_summary']:
                status = "Counted" if q_summary['counted'] else "Not counted"
                file.write(f"Question {q_summary['question']}: {q_summary['awarded']} / {q_summary['possible']} ")
                file.write(f"({q_summary['percentage']:.1f}%) - {status}\n")

            file.write("\nDetailed Assessment:\n")
            for criterion in assessment_data['criteria']:
                file.write(f"\n{criterion['title']}: {criterion['points_awarded']} / {criterion['points_possible']}\n")

                if 'description' in criterion and criterion['description']:
                    file.write(f"Description: {criterion['description']}\n")

                if 'levels' in criterion and criterion['levels']:
                    file.write("Achievement Levels:\n")
                    for level in criterion['levels']:
                        marker = "► " if level['title'] == criterion.get('selected_level', '') else "  "
                        file.write(f"{marker}{level['title']}: {level.get('description', 'No description')}\n")

                if 'comments' in criterion and criterion['comments']:
                    file.write(f"Comments: {criterion['comments']}\n")

        return True