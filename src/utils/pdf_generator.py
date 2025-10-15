# utils/pdf_generator.py
# Replace your existing src/utils/pdf_generator.py with this version

from src.core.grader import extract_question_number
import html as html_module


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


def clean_text_for_pdf(text):
    """Clean text to remove LaTeX and problematic characters."""
    if not text:
        return ""

    # Replace common LaTeX commands with Unicode symbols
    replacements = {
        '\\sum': 'Σ',
        '\\Sigma': 'Σ',
        '\\prod': 'Π',
        '\\int': '∫',
        '\\alpha': 'α',
        '\\beta': 'β',
        '\\gamma': 'γ',
        '\\delta': 'δ',
        '\\theta': 'θ',
        '\\Theta': 'Θ',
        '\\lambda': 'λ',
        '\\mu': 'μ',
        '\\pi': 'π',
        '\\Pi': 'Π',
        '\\infty': '∞',
        '\\leq': '≤',
        '\\geq': '≥',
        '\\neq': '≠',
        '\\approx': '≈',
        '\\times': '×',
        '\\div': '÷',
        '\\sqrt': '√',
        '\\in': '∈',
        '\\notin': '∉',
        '\\subset': '⊂',
        '\\subseteq': '⊆',
        '\\cup': '∪',
        '\\cap': '∩',
        '\\emptyset': '∅',
        '\\forall': '∀',
        '\\exists': '∃',
        '\\partial': '∂',
        '\\nabla': '∇',
    }

    for latex, unicode_char in replacements.items():
        text = text.replace(latex, unicode_char)

    # Remove dollar signs (math mode delimiters)
    text = text.replace('$', '')

    # Remove any remaining backslashes
    text = text.replace('\\', '')

    # Escape HTML special characters
    text = html_module.escape(text)

    return text


def generate_assessment_pdf(file_path, assessment_data):
    """Generate a PDF report of the assessment with table-formatted achievement levels."""
    try:
        # Import reportlab for PDF generation
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_LEFT, TA_CENTER

        # Create the PDF document with margins
        doc = SimpleDocTemplate(
            file_path,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch
        )
        styles = getSampleStyleSheet()

        # Create custom styles
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=18,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=colors.HexColor('#2C3E50')
        )

        heading_style = ParagraphStyle(
            'Heading',
            parent=styles['Heading2'],
            fontSize=14,
            spaceAfter=8,
            spaceBefore=12,
            textColor=colors.HexColor('#34495E')
        )

        subheading_style = ParagraphStyle(
            'Subheading',
            parent=styles['Heading3'],
            fontSize=12,
            spaceAfter=6,
            spaceBefore=10,
            textColor=colors.HexColor('#2C3E50'),
            fontName='Helvetica-Bold'
        )

        normal_style = styles['Normal']

        small_style = ParagraphStyle(
            'Small',
            parent=styles['Normal'],
            fontSize=9
        )

        # Start building the document content
        content = []

        # Header information
        content.append(Paragraph(clean_text_for_pdf(assessment_data['assignment_name']), title_style))
        content.append(Spacer(1, 0.1 * inch))
        content.append(
            Paragraph(f"<b>Student:</b> {clean_text_for_pdf(assessment_data['student_name'])}", heading_style))
        content.append(Spacer(1, 0.15 * inch))

        # Summary table at the top
        percentage = assessment_data['percentage']
        letter_grade = get_letter_grade(percentage)

        summary_data = [
            [Paragraph("<b>Score</b>", normal_style),
             Paragraph(f"{assessment_data['total_awarded']} / {assessment_data['total_possible']}", normal_style)],
            [Paragraph("<b>Percentage</b>", normal_style),
             Paragraph(f"{percentage:.1f}%", normal_style)],
            [Paragraph("<b>Grade</b>", normal_style),
             Paragraph(letter_grade, normal_style)]
        ]

        summary_table = Table(summary_data, colWidths=[1.5 * inch, 2 * inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ECF0F1')),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))

        content.append(summary_table)
        content.append(Spacer(1, 0.25 * inch))

        # Grading configuration
        config = assessment_data['grading_config']
        if config['grading_mode'] == 'best_scores':
            config_text = f"<i>Grading Method: Best {config['questions_to_count']} of {len(assessment_data['question_summary'])} questions</i>"
        else:
            config_text = f"<i>Grading Method: {config['questions_to_count']} selected questions</i>"

        content.append(Paragraph(config_text, normal_style))
        content.append(Spacer(1, 0.2 * inch))

        # Question summary section
        content.append(Paragraph("Question Summary", heading_style))

        question_summary_data = [[
            Paragraph("<b>Question</b>", normal_style),
            Paragraph("<b>Score</b>", normal_style),
            Paragraph("<b>Percentage</b>", normal_style),
            Paragraph("<b>Status</b>", normal_style)
        ]]

        sorted_summary = sorted(
            assessment_data['question_summary'],
            key=lambda x: (not x['counted'], x['question'])
        )

        for q_summary in sorted_summary:
            q_num = q_summary['question']
            score = f"{q_summary['awarded']} / {q_summary['possible']}"
            percentage = f"{q_summary['percentage']:.1f}%"

            if q_summary['counted']:
                status = "✓ Counted"
                status_color = colors.HexColor('#27AE60')
            elif q_summary['selected']:
                status = "Selected"
                status_color = colors.HexColor('#F39C12')
            else:
                status = "Not selected"
                status_color = colors.HexColor('#95A5A6')

            question_summary_data.append([
                Paragraph(f"Question {q_num}", normal_style),
                Paragraph(score, normal_style),
                Paragraph(percentage, normal_style),
                Paragraph(f'<font color="{status_color.hexval()}">{status}</font>', normal_style)
            ])

        q_summary_table = Table(question_summary_data, colWidths=[1.2 * inch, 1 * inch, 1 * inch, 1.5 * inch])
        q_summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#34495E')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BDC3C7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 1), (-1, -1), 6),
        ]))

        content.append(q_summary_table)
        content.append(Spacer(1, 0.3 * inch))

        # Detailed assessment
        content.append(Paragraph("Detailed Assessment", heading_style))
        content.append(Spacer(1, 0.1 * inch))

        # Group criteria by question
        question_criteria = {}
        for criterion in assessment_data['criteria']:
            q_num = extract_question_number(criterion['title'])
            if q_num:
                if q_num not in question_criteria:
                    question_criteria[q_num] = []
                question_criteria[q_num].append(criterion)

        # Process each question
        for q_num in sorted(question_criteria.keys()):
            if q_num not in assessment_data['selected_questions']:
                continue

            # Question header
            if q_num in assessment_data['counted_questions']:
                status_badge = '<font color="#27AE60">✓ COUNTED</font>'
            else:
                status_badge = '<font color="#F39C12">NOT COUNTED</font>'

            question_header = f"<b>Question {q_num}</b> {status_badge}"
            content.append(Paragraph(question_header, subheading_style))
            content.append(Spacer(1, 0.1 * inch))

            # Process each criterion in this question
            for criterion in question_criteria[q_num]:
                criterion_elements = []

                # Criterion title and description
                title = criterion['title'].replace(f"Question {q_num}", "").strip()
                if title.startswith(":"):
                    title = title[1:].strip()

                criterion_elements.append(Paragraph(f"<b>{clean_text_for_pdf(title)}</b>", normal_style))

                if 'description' in criterion and criterion['description']:
                    desc_style = ParagraphStyle(
                        'CriterionDesc',
                        parent=normal_style,
                        fontSize=10,
                        textColor=colors.HexColor('#7F8C8D'),
                        leftIndent=10
                    )
                    criterion_elements.append(
                        Paragraph(f"<i>{clean_text_for_pdf(criterion['description'])}</i>", desc_style))

                criterion_elements.append(Spacer(1, 0.08 * inch))

                # Score box
                score_data = [[
                    Paragraph("<b>Points Earned</b>", small_style),
                    Paragraph(f"<b>{criterion['points_awarded']} / {criterion['points_possible']}</b>", normal_style)
                ]]

                score_table = Table(score_data, colWidths=[1.2 * inch, 1 * inch])
                score_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#ECF0F1')),
                    ('BACKGROUND', (1, 0), (1, 0), colors.white),
                    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7')),
                    ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                    ('ALIGN', (1, 0), (1, 0), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 6),
                ]))

                criterion_elements.append(score_table)
                criterion_elements.append(Spacer(1, 0.1 * inch))

                # Achievement levels table (if available)
                if 'levels' in criterion and criterion['levels']:
                    levels_header = Paragraph("<b>Achievement Levels:</b>", normal_style)
                    criterion_elements.append(levels_header)
                    criterion_elements.append(Spacer(1, 0.05 * inch))

                    levels_data = [[
                        Paragraph("<b>Level</b>", small_style),
                        Paragraph("<b>Points</b>", small_style),
                        Paragraph("<b>Description</b>", small_style)
                    ]]

                    selected_level = criterion.get('selected_level', '')

                    for level in criterion['levels']:
                        level_title = level.get('title', '')
                        level_points = level.get('points', 0)
                        level_desc = level.get('description', '')

                        # Check if this level was selected
                        level_name = level_title.split('(')[0].strip()
                        is_selected = selected_level and level_name in selected_level

                        if is_selected:
                            level_text = f'<b><font color="#27AE60">➤ {clean_text_for_pdf(level_title)}</font></b>'
                        else:
                            level_text = clean_text_for_pdf(level_title)

                        levels_data.append([
                            Paragraph(level_text, small_style),
                            Paragraph(str(level_points), small_style),
                            Paragraph(clean_text_for_pdf(level_desc) if level_desc else "—", small_style)
                        ])

                    # Calculate column widths
                    levels_table = Table(levels_data, colWidths=[1.8 * inch, 0.6 * inch, 4.3 * inch])

                    # Build style with WHITE header and row backgrounds
                    table_style = [
                        ('BACKGROUND', (0, 0), (-1, 0), colors.white),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('PADDING', (0, 0), (-1, -1), 6),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BDC3C7')),
                        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#2C3E50')),
                    ]

                    # Add row backgrounds for selected level
                    for i, level in enumerate(criterion['levels'], start=1):
                        level_title = level.get('title', '')
                        level_name = level_title.split('(')[0].strip()
                        is_selected = selected_level and level_name in selected_level

                        if is_selected:
                            table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#D5F4E6')))
                        else:
                            if i % 2 == 0:
                                table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F9FA')))

                    levels_table.setStyle(TableStyle(table_style))
                    criterion_elements.append(levels_table)
                    criterion_elements.append(Spacer(1, 0.1 * inch))

                # Comments section
                if 'comments' in criterion and criterion['comments']:
                    comments_header = Paragraph("<b>Instructor Feedback:</b>", normal_style)
                    criterion_elements.append(comments_header)

                    # Clean the comments text
                    comments_text = clean_text_for_pdf(criterion['comments'])

                    # Convert newlines to <br/> tags
                    comments_text = comments_text.replace('\n', '<br/>')

                    comments_style = ParagraphStyle(
                        'Comments',
                        parent=normal_style,
                        fontSize=10,
                        leftIndent=10,
                        rightIndent=10,
                        spaceBefore=4,
                        spaceAfter=4,
                        textColor=colors.HexColor('#2C3E50')
                    )

                    # Create a background box for comments
                    try:
                        comments_para = Paragraph(comments_text, comments_style)
                        comments_table = Table([[comments_para]], colWidths=[6.7 * inch])
                        comments_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEF9E7')),
                            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#F39C12')),
                            ('PADDING', (0, 0), (-1, -1), 10),
                        ]))
                        criterion_elements.append(comments_table)
                    except Exception as e:
                        # Fallback: just add as plain text if paragraph fails
                        print(f"Warning: Could not create paragraph for comments: {e}")
                        fallback_text = Paragraph(f"<i>{comments_text}</i>", normal_style)
                        criterion_elements.append(fallback_text)

                criterion_elements.append(Spacer(1, 0.15 * inch))

                # Add separator line between criteria
                separator = Table([['']], colWidths=[6.7 * inch])
                separator.setStyle(TableStyle([
                    ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#E0E0E0')),
                ]))
                criterion_elements.append(separator)
                criterion_elements.append(Spacer(1, 0.1 * inch))

                # Keep criterion together on same page if possible
                content.append(KeepTogether(criterion_elements))

            content.append(Spacer(1, 0.2 * inch))

        # Build and save the PDF
        doc.build(content)
        return True

    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return False