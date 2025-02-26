#!/usr/bin/env python3
"""
Rubric Converter Tool

This script converts rubrics between different formats (JSON and CSV).
"""

import os
import sys
import json
import csv
import argparse


def json_to_csv(json_path, csv_path):
    """
    Convert a JSON rubric to CSV format.

    Args:
        json_path (str): Path to the JSON file
        csv_path (str): Path where to save the CSV file
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as file:
            rubric = json.load(file)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        return False

    # Validate the structure
    if "criteria" not in rubric or not isinstance(rubric["criteria"], list):
        print("Invalid rubric format: missing 'criteria' array")
        return False

    try:
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            # Determine the maximum number of levels
            max_levels = 0
            for criterion in rubric["criteria"]:
                levels = len(criterion.get("levels", []))
                if levels > max_levels:
                    max_levels = levels

            # Create headers
            headers = ["Criterion", "Description", "Points"]
            for i in range(max_levels):
                headers.extend([f"Level{i + 1} Title", f"Level{i + 1} Points"])

            writer = csv.writer(csvfile)
            writer.writerow(headers)

            # Write data
            for criterion in rubric["criteria"]:
                row = [
                    criterion.get("title", ""),
                    criterion.get("description", ""),
                    criterion.get("points", 0)
                ]

                # Add levels if available
                for level in criterion.get("levels", []):
                    row.extend([level.get("title", ""), level.get("points", 0)])

                # Pad row if needed
                while len(row) < len(headers):
                    row.append("")

                writer.writerow(row)

        print(f"Successfully converted to CSV: {csv_path}")
        return True

    except Exception as e:
        print(f"Error writing CSV file: {e}")
        return False


def csv_to_json(csv_path, json_path):
    """
    Convert a CSV rubric to JSON format.

    Args:
        csv_path (str): Path to the CSV file
        json_path (str): Path where to save the JSON file
    """
    rubric = {
        "title": os.path.splitext(os.path.basename(csv_path))[0],
        "criteria": []
    }

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            headers = next(reader, None)

            if not headers:
                print("CSV file is empty")
                return False

            for row in reader:
                if len(row) < 3 or not row[0].strip():
                    continue

                criterion = {
                    "title": row[0].strip(),
                    "description": row[1].strip() if len(row) > 1 else "",
                    "points": int(row[2]) if len(row) > 2 and row[2].strip().isdigit() else 10
                }

                # Check if there are achievement levels defined
                if len(row) > 3:
                    levels = []
                    for i in range(3, len(row), 2):
                        if i + 1 < len(row) and row[i].strip() and row[i + 1].strip():
                            try:
                                points = float(row[i + 1])
                            except ValueError:
                                points = 0

                            levels.append({
                                "title": row[i].strip(),
                                "points": points,
                                "description": ""
                            })

                    if levels:
                        criterion["levels"] = levels

                rubric["criteria"].append(criterion)

        # Write the JSON file
        with open(json_path, 'w', encoding='utf-8') as file:
            json.dump(rubric, file, indent=2)

        print(f"Successfully converted to JSON: {json_path}")
        return True

    except Exception as e:
        print(f"Error processing CSV file: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Convert rubrics between formats")
    parser.add_argument("input", help="Input file path")
    parser.add_argument("output", nargs="?", help="Output file path (optional)")
    parser.add_argument("-f", "--format", choices=["json", "csv"],
                        help="Force output format (otherwise inferred from extension)")

    args = parser.parse_args()

    # Check if input file exists
    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        return 1

    # Determine input format
    input_ext = os.path.splitext(args.input)[1].lower()
    if input_ext == '.json':
        input_format = 'json'
    elif input_ext == '.csv':
        input_format = 'csv'
    else:
        print(f"Unsupported input file extension: {input_ext}")
        return 1

    # Determine output format
    if args.format:
        output_format = args.format
    elif args.output:
        output_ext = os.path.splitext(args.output)[1].lower()
        if output_ext == '.json':
            output_format = 'json'
        elif output_ext == '.csv':
            output_format = 'csv'
        else:
            print(f"Unsupported output file extension: {output_ext}")
            return 1
    else:
        # Default to opposite format
        output_format = 'csv' if input_format == 'json' else 'json'

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base_path = os.path.splitext(args.input)[0]
        output_path = f"{base_path}.{output_format}"

    # Perform conversion
    if input_format == 'json' and output_format == 'csv':
        result = json_to_csv(args.input, output_path)
    elif input_format == 'csv' and output_format == 'json':
        result = csv_to_json(args.input, output_path)
    else:
        print(f"Cannot convert from {input_format} to {input_format}")
        return 1

    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())