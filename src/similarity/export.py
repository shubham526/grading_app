"""CSV, JSON, matrix, and self-contained HTML export for similarity review."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from .highlight import render_side_by_side_html
from .models import FLAG_RANK, PairSimilarity, SimilarityReport


DISCLAIMER = (
    "Similarity scores are indicators for instructor review only. "
    "They do not determine whether academic misconduct occurred."
)

JSON_FILENAME = "similarity_report.json"
CSV_FILENAME = "similarity_pairs.csv"
MATRIX_FILENAME = "similarity_matrix.csv"
HTML_FILENAME = "similarity_report.html"

VALID_EXPORT_FORMATS = ("json", "csv", "html")

CSV_COLUMNS = [
    "Student A",
    "Student B",
    "Flag Level",
    "Overall Score",
    "Most Similar Question",
    "Exact File Match",
    "Normalized Text Match",
    "Max Ngram Similarity",
    "Warnings",
]


def _report_dict(report: SimilarityReport | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(report, SimilarityReport):
        return report.to_dict()
    if is_dataclass(report):
        return asdict(report)
    if isinstance(report, Mapping):
        return dict(report)
    raise TypeError("report must be a SimilarityReport or mapping.")


def _question_map(pair: PairSimilarity | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(pair, PairSimilarity):
        return pair.question_similarities
    return pair.get("question_similarities", {}) or {}


def _max_ngram(pair: PairSimilarity | Mapping[str, Any]) -> float:
    questions = _question_map(pair)
    scores: list[float] = []
    for question in questions.values():
        if hasattr(question, "ngram_jaccard"):
            scores.append(float(question.ngram_jaccard))
        elif isinstance(question, Mapping):
            scores.append(float(question.get("ngram_jaccard", 0.0) or 0.0))
    return max(scores, default=0.0)


def _pair_value(pair: PairSimilarity | Mapping[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(pair, PairSimilarity):
        return getattr(pair, key, default)
    return pair.get(key, default)


def _pair_notes(pair: PairSimilarity | Mapping[str, Any]) -> list[str]:
    raw = _pair_value(pair, "notes", []) or []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def _submission_answers(submission: Any) -> dict[str, str]:
    if isinstance(submission, Mapping):
        raw = (
            submission.get("extracted_answers")
            or submission.get("answers_by_question")
            or {}
        )
    else:
        raw = getattr(submission, "answers_by_question", {}) or {}

    if not isinstance(raw, Mapping):
        return {}
    return {
        str(question_id): str(answer or "")
        for question_id, answer in raw.items()
    }


def export_similarity_json(
    report: SimilarityReport | Mapping[str, Any],
    path: str | Path,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_report_dict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


def export_similarity_pairs_csv(
    report: SimilarityReport,
    path: str | Path,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for pair in report.pairs:
            writer.writerow(
                {
                    "Student A": pair.student_a,
                    "Student B": pair.student_b,
                    "Flag Level": pair.flag_level,
                    "Overall Score": pair.overall_score,
                    "Most Similar Question": pair.most_similar_question or "",
                    "Exact File Match": pair.exact_file_match,
                    "Normalized Text Match": pair.normalized_text_match,
                    "Max Ngram Similarity": _max_ngram(pair),
                    "Warnings": "; ".join(pair.notes),
                }
            )
    return output


def export_similarity_matrix_csv(
    report: SimilarityReport,
    path: str | Path,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    students = list(report.students)
    matrix: dict[tuple[str, str], float] = {}

    for student in students:
        matrix[(student, student)] = 1.0

    for pair in report.pairs:
        score = float(pair.overall_score)
        matrix[(pair.student_a, pair.student_b)] = score
        matrix[(pair.student_b, pair.student_a)] = score

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Student"] + students)
        for row_student in students:
            writer.writerow(
                [row_student]
                + [
                    matrix.get((row_student, column_student), 0.0)
                    for column_student in students
                ]
            )

    return output


def _html_pair_summary_row(pair: PairSimilarity) -> str:
    return (
        "<tr>"
        f"<td>{escape(pair.student_a)}</td>"
        f"<td>{escape(pair.student_b)}</td>"
        f"<td>{escape(pair.flag_level)}</td>"
        f"<td>{pair.overall_score:.4f}</td>"
        f"<td>{escape(pair.most_similar_question or '')}</td>"
        f"<td>{'yes' if pair.exact_file_match else 'no'}</td>"
        f"<td>{'yes' if pair.normalized_text_match else 'no'}</td>"
        f"<td>{_max_ngram(pair):.4f}</td>"
        "</tr>"
    )


def _question_shared_spans(pair: PairSimilarity, question_id: str) -> list[dict]:
    question = pair.question_similarities.get(question_id)
    if question is None:
        return []
    return list(question.shared_spans or [])


def render_similarity_report_html(
    report: SimilarityReport,
    submissions: Mapping[str, Any] | None = None,
) -> str:
    """Render a self-contained offline HTML review report."""

    flagged_pairs = [pair for pair in report.pairs if pair.flag_level != "none"]
    detail_pairs = [
        pair for pair in report.pairs if pair.flag_level in {"high", "exact"}
    ]

    if flagged_pairs:
        summary_rows = "\n".join(_html_pair_summary_row(pair) for pair in flagged_pairs)
    else:
        summary_rows = (
            '<tr><td colspan="8"><em>No similarity pairs exceeded the configured '
            "review thresholds.</em></td></tr>"
        )

    threshold_rows = "\n".join(
        f"<li><code>{escape(str(key))}</code>: {float(value):.4f}</li>"
        for key, value in report.thresholds.items()
    )
    method_items = "\n".join(
        f"<li><code>{escape(str(method))}</code></li>"
        for method in report.methods
    )

    detail_sections: list[str] = []
    for pair in detail_pairs:
        pair_heading = (
            f"<h3>{escape(pair.student_a)} ↔ {escape(pair.student_b)}</h3>"
            f"<p><strong>Flag:</strong> {escape(pair.flag_level)} &nbsp; "
            f"<strong>Overall:</strong> {pair.overall_score:.4f} &nbsp; "
            f"<strong>Most similar question:</strong> "
            f"{escape(pair.most_similar_question or '')}</p>"
        )

        question_sections: list[str] = []
        answers_a = (
            _submission_answers(submissions.get(pair.student_a))
            if submissions and pair.student_a in submissions
            else {}
        )
        answers_b = (
            _submission_answers(submissions.get(pair.student_b))
            if submissions and pair.student_b in submissions
            else {}
        )

        for question_id, question in pair.question_similarities.items():
            if answers_a or answers_b:
                comparison = render_side_by_side_html(
                    pair.student_a,
                    pair.student_b,
                    question_id,
                    answers_a.get(question_id, ""),
                    answers_b.get(question_id, ""),
                    question.shared_spans,
                )
            else:
                if question.shared_spans:
                    shared_items = "".join(
                        f"<li><code>{escape(str(span.get('text', '')))}</code></li>"
                        for span in question.shared_spans
                    )
                else:
                    shared_items = "<li><em>No shared phrases identified.</em></li>"
                comparison = (
                    f'<section class="question-comparison">'
                    f"<h4>Question {escape(question_id)}</h4>"
                    "<p><em>Original answer text was not supplied to the exporter. "
                    "Shared normalized phrases from the similarity report are shown below.</em></p>"
                    f"<ul>{shared_items}</ul>"
                    "</section>"
                )

            question_sections.append(
                comparison
                + (
                    '<p class="question-score">'
                    f"<strong>N-gram Jaccard:</strong> {question.ngram_jaccard:.4f} "
                    f"&nbsp; <strong>Question flag:</strong> "
                    f"{escape(question.flag_level)}"
                    "</p>"
                )
            )

        notes = (
            "<ul>"
            + "".join(f"<li>{escape(note)}</li>" for note in pair.notes)
            + "</ul>"
            if pair.notes
            else "<p><em>No pair warnings.</em></p>"
        )

        detail_sections.append(
            '<section class="pair-detail">'
            + pair_heading
            + "\n".join(question_sections)
            + "<h4>Warnings / notes</h4>"
            + notes
            + "</section>"
        )

    if not detail_sections:
        detail_sections.append(
            "<p><em>No high/exact pairs require expanded side-by-side review.</em></p>"
        )

    report_warnings = (
        "<ul>"
        + "".join(f"<li>{escape(warning)}</li>" for warning in report.warnings)
        + "</ul>"
        if report.warnings
        else "<p><em>No report warnings.</em></p>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Submission Similarity Review — {escape(report.assignment_id)}</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin: 2rem;
  color: #222;
  line-height: 1.45;
}}
h1, h2, h3, h4, h5 {{ line-height: 1.2; }}
.disclaimer {{
  border: 2px solid #555;
  border-radius: 8px;
  padding: 1rem;
  margin: 1rem 0 1.5rem;
  background: #f7f7f7;
}}
table {{
  border-collapse: collapse;
  width: 100%;
  margin: 1rem 0 2rem;
}}
th, td {{
  border: 1px solid #bbb;
  padding: .5rem;
  text-align: left;
  vertical-align: top;
}}
th {{ background: #f1f1f1; }}
.answer-grid {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1rem;
}}
.answer-panel {{
  border: 1px solid #bbb;
  border-radius: 6px;
  padding: .75rem;
  min-width: 0;
}}
.answer-panel pre {{
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}}
.shared-phrases {{
  margin-top: .75rem;
}}
.shared-count {{
  color: #666;
}}
.pair-detail {{
  border-top: 2px solid #777;
  padding-top: 1rem;
  margin-top: 2rem;
}}
.question-comparison {{
  margin: 1rem 0;
}}
.question-score {{
  margin-top: -.5rem;
}}
code {{ white-space: pre-wrap; }}
@media (max-width: 800px) {{
  .answer-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<h1>Submission Similarity Review</h1>

<div class="disclaimer"><strong>{escape(DISCLAIMER)}</strong></div>

<p>
  <strong>Assignment:</strong> {escape(report.assignment_id)}<br>
  <strong>Generated:</strong> {escape(report.generated_at)}<br>
  <strong>Students:</strong> {len(report.students)}<br>
  <strong>Pairs compared:</strong> {len(report.pairs)}
</p>

<h2>Methods</h2>
<ul>{method_items}</ul>

<h2>Thresholds</h2>
<ul>{threshold_rows}</ul>

<h2>Flagged pairs</h2>
<table>
<thead>
<tr>
  <th>Student A</th>
  <th>Student B</th>
  <th>Flag</th>
  <th>Overall</th>
  <th>Most Similar Q</th>
  <th>Exact File</th>
  <th>Normalized Match</th>
  <th>Max N-gram</th>
</tr>
</thead>
<tbody>
{summary_rows}
</tbody>
</table>

<h2>High / exact pair details</h2>
{''.join(detail_sections)}

<h2>Report warnings</h2>
{report_warnings}

<div class="disclaimer"><strong>{escape(DISCLAIMER)}</strong></div>
</body>
</html>
"""


def export_similarity_html(
    report: SimilarityReport,
    path: str | Path,
    submissions: Mapping[str, Any] | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_similarity_report_html(report, submissions=submissions),
        encoding="utf-8",
    )
    return output


def export_similarity_report(
    report: SimilarityReport,
    output_dir: str | Path,
    *,
    formats: Sequence[str] = ("json", "csv", "html"),
    include_matrix: bool = True,
    submissions: Mapping[str, Any] | None = None,
) -> dict[str, Path | None]:
    """Export one similarity report in selected deterministic formats."""

    selected: list[str] = []
    for raw_format in formats:
        fmt = str(raw_format).strip().lower()
        if fmt and fmt not in selected:
            selected.append(fmt)

    if not selected:
        raise ValueError("At least one similarity export format is required.")

    invalid = [fmt for fmt in selected if fmt not in VALID_EXPORT_FORMATS]
    if invalid:
        raise ValueError(
            "Unsupported similarity export format(s): " + ", ".join(invalid)
        )

    destination = Path(output_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)

    results: dict[str, Path | None] = {
        "json": None,
        "csv": None,
        "matrix_csv": None,
        "html": None,
    }

    if "json" in selected:
        results["json"] = export_similarity_json(
            report,
            destination / JSON_FILENAME,
        )

    if "csv" in selected:
        results["csv"] = export_similarity_pairs_csv(
            report,
            destination / CSV_FILENAME,
        )
        if include_matrix:
            results["matrix_csv"] = export_similarity_matrix_csv(
                report,
                destination / MATRIX_FILENAME,
            )

    if "html" in selected:
        results["html"] = export_similarity_html(
            report,
            destination / HTML_FILENAME,
            submissions=submissions,
        )

    return results


__all__ = [
    "DISCLAIMER",
    "JSON_FILENAME",
    "CSV_FILENAME",
    "MATRIX_FILENAME",
    "HTML_FILENAME",
    "CSV_COLUMNS",
    "VALID_EXPORT_FORMATS",
    "export_similarity_json",
    "export_similarity_pairs_csv",
    "export_similarity_matrix_csv",
    "render_similarity_report_html",
    "export_similarity_html",
    "export_similarity_report",
]
