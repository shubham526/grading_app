#!/usr/bin/env python3
"""
Rubric Template Generator

This script helps create new rubric templates in JSON format.
"""

import os
import sys
import json
import argparse
from datetime import datetime

# Standard achievement levels
DEFAULT_LEVELS = [
    {"title": "Excellent", "description": "Exceeds expectations", "points": 100},
    {"title": "Good", "description": "Meets all expectations", "points": 80},
    {"title": "Satisfactory", "description": "Meets basic expectations", "points": 60},
    {"title": "Needs Improvement", "description": "Partially meets expectations", "points": 40},
    {"title": "Unsatisfactory", "description": "Does not meet expectations", "points": 20}
]

# Common rubric templates
TEMPLATES = {
    "essay": {
        "title": "Essay Assignment",
        "description": "Evaluation rubric for an essay assignment",
        "criteria": [
            {
                "title": "Thesis Statement",
                "description": "Clear, arguable thesis that establishes the purpose",
                "points": 10
            },
            {
                "title": "Organization",
                "description": "Logical structure with clear introduction, body, and conclusion",
                "points": 20
            },
            {
                "title": "Evidence & Support",
                "description": "Use of credible sources and evidence to support arguments",
                "points": 25
            },
            {
                "title": "Analysis & Critical Thinking",
                "description": "Depth of analysis and critical engagement with the topic",
                "points": 25
            },
            {
                "title": "Grammar & Mechanics",
                "description": "Correct grammar, punctuation, spelling, and formatting",
                "points": 10
            },
            {
                "title": "Style & Voice",
                "description": "Appropriate tone and effective writing style",
                "points": 10
            }
        ]
    },
    "presentation": {
        "title": "Oral Presentation",
        "description": "Evaluation rubric for an oral presentation",
        "criteria": [
            {
                "title": "Content & Organization",
                "description": "Well-structured and relevant content",
                "points": 30
            },
            {
                "title": "Delivery & Speaking Skills",
                "description": "Clear speech, appropriate pace, and engagement",
                "points": 25
            },
            {
                "title": "Visual Aids",
                "description": "Quality and effectiveness of visual materials",
                "points": 20
            },
            {
                "title": "Audience Interaction",
                "description": "Engagement with audience and handling of questions",
                "points": 15
            },
            {
                "title": "Time Management",
                "description": "Appropriate use of allocated time",
                "points": 10
            }
        ]
    },
    "project": {
        "title": "Group Project",
        "description": "Evaluation rubric for a group project",
        "criteria": [
            {
                "title": "Project Outcome",
                "description": "Quality and completeness of the final product",
                "points": 40
            },
            {
                "title": "Methodology",
                "description": "Appropriateness and execution of methods used",
                "points": 20
            },
            {
                "title": "Teamwork & Collaboration",
                "description": "Effective coordination and contribution of all members",
                "points": 15
            },
            {
                "title": "Documentation",
                "description": "Quality of project documentation and reporting",
                "points": 15
            },
            {
                "title": "Presentation",
                "description": "Effective communication of project results",
                "points": 10
            }
        ]
    },
    "empty": {
        "title": "New Rubric",
        "description": "Custom evaluation rubric",
        "criteria": [
            {
                "title": "Criterion 1",
                "description": "Description of first criterion",
                "points": 25
            },
            {
                "title": "Criterion 2",
                "description": "Description of second criterion",
                "points": 25
            },
            {
                "title": "Criterion 3",
                "description": "Description of third criterion",
                "points": 25
            },
            {
                "title": "Criterion 4",
                "description": "Description of fourth criterion",
                "points": 25
            }
        ]
    }
}


def create_rubric_template(template_name, output_path, title=None, include_levels=True, scale=100):
    """
    Create a new rubric template.

    Args:
        template_name (str): Name of the template to use
        output_path (str): Path where to save the template
        title (str, optional): Custom title for the rubric
        include_levels (bool): Whether to include achievement levels
        scale (int): Point scale to use (default 100)

    Returns:
        bool: True if successful, False otherwise
    """
    # Get the base template
    if template_name not in TEMPLATES:
        print(f"Unknown template: {template_name}")
        print(f"Available templates: {', '.join(TEMPLATES.keys())}")
        return False

    template = TEMPLATES[template_name].copy()

    # Apply custom title if provided
    if title:
        template["title"] = title

    # Scale the points
    total_points = sum(criterion["points"] for criterion in template["criteria"])
    scale_factor = scale / total_points

    for criterion in template["criteria"]:
        criterion["points"] = round(criterion["points"] * scale_factor)

        # Add achievement levels if requested
        if include_levels:
            criterion["levels"] = []
            max_points = criterion["points"]

            for level in DEFAULT_LEVELS:
                criterion["levels"].append({
                    "title": level["title"],
                    "description": level["description"],
                    "points": round(max_points * (level["points"] / 100))
                })

    # Add metadata
    template["metadata"] = {
        "created": datetime.now().isoformat(),
        "generator": "rubric_template.py",
        "template": template_name
    }

    # Write to file
    try:
        with open(output_path, 'w', encoding='utf-8') as file:
            json.dump(template, file, indent=2)
        print(f"Template created successfully: {output_path}")
        return True
    except Exception as e:
        print(f"Error writing template: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate rubric templates")
    parser.add_argument("template", choices=list(TEMPLATES.keys()) + ["list"],
                        help="Template name or 'list' to show available templates")
    parser.add_argument("output", nargs="?", help="Output file path")
    parser.add_argument("-t", "--title", help="Custom title for the rubric")
    parser.add_argument("--no-levels", action="store_true", help="Do not include achievement levels")
    parser.add_argument("-s", "--scale", type=int, default=100, help="Point scale (default: 100)")

    args = parser.parse_args()

    # Just list available templates
    if args.template == "list":
        print("Available templates:")
        for name, template in TEMPLATES.items():
            print(f"  {name}: {template['title']}")
        return 0

    # Must provide an output path
    if not args.output:
        print("Error: Output file path is required")
        return 1

    # Create the template
    result = create_rubric_template(
        args.template,
        args.output,
        title=args.title,
        include_levels=not args.no_levels,
        scale=args.scale
    )

    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())