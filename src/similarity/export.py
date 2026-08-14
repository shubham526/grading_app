"""CSV, JSON, matrix, and self-contained HTML export for similarity review."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from .highlight import render_side_by_side_html
from .models import PairSimilarity, SimilarityReport


DISCLAIMER = (
    "Similarity scores are indicators for instructor review only. "
    "They do not determine whether academic misconduct occurred."
)

EMBEDDING_DISCLAIMER = (
    "Embedding similarity is a semantic signal and may be high for independently "
    "written correct solutions to the same problem. Review the underlying "
    "submissions before drawing conclusions."
)

JSON_FILENAME = "similarity_report.json"
CSV_FILENAME = "similarity_pairs.csv"
MATRIX_FILENAME = "similarity_matrix.csv"
HTML_FILENAME = "similarity_report.html"
CLUSTERS_FILENAME = "similarity_clusters.csv"
TRENDS_FILENAME = "similarity_trends.csv"

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
    "Embedding Max",
    "Pseudocode Max",
    "Cluster",
    "Trend Count",
    "Student A Text Source",
    "Student B Text Source",
    "Student A Assistive Transcription",
    "Student B Assistive Transcription",
    "Warnings",
]

CLUSTER_CSV_COLUMNS = [
    "Cluster ID",
    "Size",
    "Students",
    "Max Similarity",
    "Questions",
    "Signals",
]

TREND_CSV_COLUMNS = [
    "Student A",
    "Student B",
    "Assignments Flagged",
    "Count",
    "Max Similarity",
    "Questions",
    "Signals",
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


def _pair_value(
    pair: PairSimilarity | Mapping[str, Any],
    key: str,
    default: Any = None,
) -> Any:
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


def _canonical_pair(student_a: str, student_b: str) -> tuple[str, str]:
    return tuple(sorted((str(student_a), str(student_b))))


def _trend_for_pair(
    report: SimilarityReport,
    pair: PairSimilarity,
) -> Mapping[str, Any] | None:
    target = _canonical_pair(pair.student_a, pair.student_b)
    for trend in report.trends:
        if not isinstance(trend, Mapping):
            continue
        student_a = str(trend.get("student_a") or "")
        student_b = str(trend.get("student_b") or "")
        if student_a and student_b and _canonical_pair(student_a, student_b) == target:
            return trend
    return None


def _trend_count(report: SimilarityReport, pair: PairSimilarity) -> int:
    trend = _trend_for_pair(report, pair)
    if not trend:
        return 0
    try:
        return int(trend.get("count", len(trend.get("assignments", []) or [])) or 0)
    except (TypeError, ValueError):
        return 0


def _provenance_for_student(
    report: SimilarityReport,
    pair: PairSimilarity,
    student_id: str,
) -> Mapping[str, Any]:
    pair_provenance = pair.submission_provenance or {}
    value = pair_provenance.get(student_id)
    if isinstance(value, Mapping):
        return value
    report_value = (report.submission_provenance or {}).get(student_id)
    return report_value if isinstance(report_value, Mapping) else {}


def _analysis_text_source(provenance: Mapping[str, Any]) -> str:
    return str(
        provenance.get("analysis_text_source")
        or provenance.get("assistive_text_source")
        or provenance.get("source_used")
        or ""
    )


def _uses_assistive_transcription(provenance: Mapping[str, Any]) -> bool:
    return bool(provenance.get("uses_assistive_transcription", False))


def _format_optional_score(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.6f}"


def _format_list(value: Any, separator: str = "; ") -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return separator.join(str(item) for item in value)
    return str(value)


def _format_trend_questions(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _format_list(value)
    chunks: list[str] = []
    for assignment in sorted(value):
        raw_questions = value[assignment]
        if isinstance(raw_questions, (list, tuple, set)):
            questions = ", ".join(str(qid) for qid in raw_questions)
        else:
            questions = str(raw_questions or "")
        chunks.append(f"{assignment}: {questions}")
    return "; ".join(chunks)


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
            provenance_a = _provenance_for_student(report, pair, pair.student_a)
            provenance_b = _provenance_for_student(report, pair, pair.student_b)
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
                    "Embedding Max": _format_optional_score(
                        pair.embedding_max_similarity
                    ),
                    "Pseudocode Max": _format_optional_score(
                        pair.pseudocode_max_similarity
                    ),
                    "Cluster": "; ".join(pair.cluster_ids),
                    "Trend Count": _trend_count(report, pair),
                    "Student A Text Source": _analysis_text_source(provenance_a),
                    "Student B Text Source": _analysis_text_source(provenance_b),
                    "Student A Assistive Transcription": _uses_assistive_transcription(
                        provenance_a
                    ),
                    "Student B Assistive Transcription": _uses_assistive_transcription(
                        provenance_b
                    ),
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


def export_similarity_clusters_csv(
    report: SimilarityReport,
    path: str | Path,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CLUSTER_CSV_COLUMNS)
        writer.writeheader()
        for cluster in report.clusters:
            if not isinstance(cluster, Mapping):
                continue
            writer.writerow(
                {
                    "Cluster ID": cluster.get("cluster_id", ""),
                    "Size": cluster.get("size", ""),
                    "Students": _format_list(cluster.get("students", [])),
                    "Max Similarity": cluster.get("max_similarity", 0.0),
                    "Questions": _format_list(cluster.get("questions", [])),
                    "Signals": _format_list(cluster.get("signals", [])),
                }
            )
    return output


def export_similarity_trends_csv(
    report: SimilarityReport,
    path: str | Path,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TREND_CSV_COLUMNS)
        writer.writeheader()
        for trend in report.trends:
            if not isinstance(trend, Mapping):
                continue
            writer.writerow(
                {
                    "Student A": trend.get("student_a", ""),
                    "Student B": trend.get("student_b", ""),
                    "Assignments Flagged": _format_list(
                        trend.get("assignments", [])
                    ),
                    "Count": trend.get(
                        "count",
                        len(trend.get("assignments", []) or []),
                    ),
                    "Max Similarity": trend.get("max_similarity", 0.0),
                    "Questions": _format_trend_questions(
                        trend.get("questions", {})
                    ),
                    "Signals": _format_list(trend.get("signals", [])),
                }
            )
    return output


def _html_optional_score(value: float | None) -> str:
    return "—" if value is None else f"{float(value):.4f}"


def _html_pair_summary_row(report: SimilarityReport, pair: PairSimilarity) -> str:
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
        f"<td>{_html_optional_score(pair.embedding_max_similarity)}</td>"
        f"<td>{_html_optional_score(pair.pseudocode_max_similarity)}</td>"
        f"<td>{escape(', '.join(pair.cluster_ids) or '—')}</td>"
        f"<td>{_trend_count(report, pair)}</td>"
        "</tr>"
    )


def _html_cluster_rows(report: SimilarityReport) -> str:
    if not report.clusters:
        return (
            '<tr><td colspan="6"><em>No similarity clusters were generated.</em>'
            "</td></tr>"
        )

    rows: list[str] = []
    for cluster in report.clusters:
        if not isinstance(cluster, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(str(cluster.get('cluster_id', '')))}</td>"
            f"<td>{escape(str(cluster.get('size', '')))}</td>"
            f"<td>{escape(_format_list(cluster.get('students', []), ', '))}</td>"
            f"<td>{float(cluster.get('max_similarity', 0.0) or 0.0):.4f}</td>"
            f"<td>{escape(_format_list(cluster.get('questions', []), ', '))}</td>"
            f"<td>{escape(_format_list(cluster.get('signals', []), ', '))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _html_trend_rows(report: SimilarityReport) -> str:
    if not report.trends:
        return (
            '<tr><td colspan="7"><em>No cross-assignment similarity trends were '
            "provided for this report.</em></td></tr>"
        )

    rows: list[str] = []
    for trend in report.trends:
        if not isinstance(trend, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(str(trend.get('student_a', '')))}</td>"
            f"<td>{escape(str(trend.get('student_b', '')))}</td>"
            f"<td>{escape(_format_list(trend.get('assignments', []), ', '))}</td>"
            f"<td>{escape(str(trend.get('count', len(trend.get('assignments', []) or []))))}</td>"
            f"<td>{float(trend.get('max_similarity', 0.0) or 0.0):.4f}</td>"
            f"<td>{escape(_format_trend_questions(trend.get('questions', {})))}</td>"
            f"<td>{escape(_format_list(trend.get('signals', []), ', '))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _html_provenance_panel(
    report: SimilarityReport,
    pair: PairSimilarity,
    student_id: str,
) -> str:
    provenance = _provenance_for_student(report, pair, student_id)
    if not provenance:
        return (
            f"<div class=\"provenance-panel\"><h5>{escape(student_id)}</h5>"
            "<p><em>No submission provenance available.</em></p></div>"
        )

    assistive = _uses_assistive_transcription(provenance)
    transcription = provenance.get("transcription")
    transcription_text = ""
    if isinstance(transcription, Mapping) and transcription:
        provider = transcription.get("provider")
        model = transcription.get("model")
        details = [str(value) for value in (provider, model) if value]
        if details:
            transcription_text = (
                "<li><strong>Transcription:</strong> "
                + escape(" / ".join(details))
                + "</li>"
            )

    warning = (
        '<p class="assistive-warning"><strong>Note:</strong> Similarity analysis '
        "used assistive machine transcription for this submission.</p>"
        if assistive
        else ""
    )

    return (
        '<div class="provenance-panel">'
        f"<h5>{escape(student_id)}</h5>"
        "<ul>"
        f"<li><strong>Source used:</strong> "
        f"{escape(str(provenance.get('source_used') or ''))}</li>"
        f"<li><strong>Authoritative source:</strong> "
        f"{escape(str(provenance.get('authoritative_source') or ''))}</li>"
        f"<li><strong>Text used for analysis:</strong> "
        f"{escape(_analysis_text_source(provenance))}</li>"
        f"<li><strong>Assistive transcription:</strong> "
        f"{'yes' if assistive else 'no'}</li>"
        f"{transcription_text}"
        "</ul>"
        f"{warning}"
        "</div>"
    )


def _html_pair_signals(pair: PairSimilarity) -> str:
    if not pair.signals:
        return "<p><em>No pair signal details available.</em></p>"

    items: list[str] = []
    for method in sorted(pair.signals):
        payload = pair.signals[method]
        if isinstance(payload, Mapping):
            score = payload.get("score")
            score_text = (
                f"{float(score):.4f}"
                if isinstance(score, (int, float))
                else escape(str(score or ""))
            )
        else:
            score_text = escape(str(payload))
        items.append(
            f"<li><code>{escape(str(method))}</code>: {score_text}</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


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
        summary_rows = "\n".join(
            _html_pair_summary_row(report, pair) for pair in flagged_pairs
        )
    else:
        summary_rows = (
            '<tr><td colspan="12"><em>No similarity pairs exceeded the configured '
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
    advanced_method_items = "\n".join(
        f"<li><code>{escape(str(method))}</code></li>"
        for method in report.advanced_methods
    )
    if not advanced_method_items:
        advanced_method_items = "<li><em>No advanced methods enabled.</em></li>"

    embedding_notice = ""
    if (
        "embedding_cosine" in report.advanced_methods
        or bool((report.embedding_config or {}).get("enabled"))
    ):
        embedding_notice = (
            '<div class="semantic-warning"><strong>'
            + escape(EMBEDDING_DISCLAIMER)
            + "</strong></div>"
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

        detail_question_ids = list(pair.question_similarities)
        if not detail_question_ids and pair.most_similar_question:
            detail_question_ids = [pair.most_similar_question]
        if not detail_question_ids and (answers_a or answers_b):
            detail_question_ids = sorted(
                question_id
                for question_id in (set(answers_a) & set(answers_b))
                if question_id and question_id != "FULL_SUBMISSION"
            )

        question_sections: list[str] = []
        for question_id in detail_question_ids:
            question = pair.question_similarities.get(question_id)
            shared_spans = list(question.shared_spans or []) if question is not None else []
            if answers_a or answers_b:
                comparison = render_side_by_side_html(
                    pair.student_a,
                    pair.student_b,
                    question_id,
                    answers_a.get(question_id, ""),
                    answers_b.get(question_id, ""),
                    shared_spans,
                )
            else:
                if shared_spans:
                    shared_items = "".join(
                        f"<li><code>{escape(str(span.get('text', '')))}</code></li>"
                        for span in shared_spans
                    )
                else:
                    shared_items = "<li><em>No shared normalized phrases.</em></li>"
                comparison = (
                    '<section class="question-comparison">'
                    f"<h4>{escape(question_id)}</h4>"
                    "<p><em>Original answer text was not supplied to the exporter. "
                    "Shared normalized phrases from the similarity report are shown below.</em></p>"
                    f"<ul>{shared_items}</ul>"
                    "</section>"
                )

            if question is not None:
                advanced_bits: list[str] = []
                if question.embedding_cosine is not None:
                    advanced_bits.append(
                        "<strong>Embedding:</strong> "
                        f"{question.embedding_cosine:.4f}"
                    )
                if question.pseudocode_similarity is not None:
                    advanced_bits.append(
                        "<strong>Pseudocode:</strong> "
                        f"{question.pseudocode_similarity:.4f}"
                    )
                if question.advanced_flags:
                    advanced_bits.append(
                        "<strong>Advanced flags:</strong> "
                        + escape(", ".join(question.advanced_flags))
                    )
                if question.warnings:
                    advanced_bits.append(
                        "<strong>Question warnings:</strong> "
                        + escape("; ".join(question.warnings))
                    )

                score_line = (
                    '<p class="question-score">'
                    f"<strong>N-gram Jaccard:</strong> {question.ngram_jaccard:.4f} "
                    f"&nbsp; <strong>Deterministic question flag:</strong> "
                    f"{escape(question.flag_level)}"
                    + (
                        "<br>" + " &nbsp; ".join(advanced_bits)
                        if advanced_bits
                        else ""
                    )
                    + "</p>"
                )
            else:
                score_line = (
                    '<p class="question-score"><em>N-gram overlap was not selected '
                    "for this review.</em></p>"
                )

            question_sections.append(comparison + score_line)

        notes = (
            "<ul>"
            + "".join(f"<li>{escape(note)}</li>" for note in pair.notes)
            + "</ul>"
            if pair.notes
            else "<p><em>No pair warnings.</em></p>"
        )

        provenance = (
            '<div class="provenance-grid">'
            + _html_provenance_panel(report, pair, pair.student_a)
            + _html_provenance_panel(report, pair, pair.student_b)
            + "</div>"
        )

        pair_metadata = (
            "<p>"
            f"<strong>Embedding max:</strong> "
            f"{_html_optional_score(pair.embedding_max_similarity)} &nbsp; "
            f"<strong>Pseudocode max:</strong> "
            f"{_html_optional_score(pair.pseudocode_max_similarity)} &nbsp; "
            f"<strong>Clusters:</strong> "
            f"{escape(', '.join(pair.cluster_ids) or '—')} &nbsp; "
            f"<strong>Trend count:</strong> {_trend_count(report, pair)}"
            "</p>"
        )

        detail_sections.append(
            '<section class="pair-detail">'
            + pair_heading
            + pair_metadata
            + "\n".join(question_sections)
            + "<h4>Submission provenance</h4>"
            + provenance
            + "<h4>Pair signals</h4>"
            + _html_pair_signals(pair)
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
.semantic-warning, .assistive-warning {{
  border-left: 4px solid #666;
  padding: .75rem 1rem;
  margin: 1rem 0;
  background: #fafafa;
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
.answer-grid, .provenance-grid {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1rem;
}}
.answer-panel, .provenance-panel {{
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
  .answer-grid, .provenance-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<h1>Submission Similarity Review</h1>

<div class="disclaimer"><strong>{escape(DISCLAIMER)}</strong></div>
{embedding_notice}

<p>
  <strong>Assignment:</strong> {escape(report.assignment_id)}<br>
  <strong>Generated:</strong> {escape(report.generated_at)}<br>
  <strong>Students:</strong> {len(report.students)}<br>
  <strong>Pairs compared:</strong> {len(report.pairs)}<br>
  <strong>Clusters:</strong> {len(report.clusters)}<br>
  <strong>Cross-assignment trends:</strong> {len(report.trends)}
</p>

<h2>Deterministic methods</h2>
<ul>{method_items}</ul>

<h2>Advanced methods</h2>
<ul>{advanced_method_items}</ul>

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
  <th>Embedding Max</th>
  <th>Pseudocode Max</th>
  <th>Cluster</th>
  <th>Trend Count</th>
</tr>
</thead>
<tbody>
{summary_rows}
</tbody>
</table>

<h2>Clusters</h2>
<table>
<thead>
<tr>
  <th>Cluster ID</th>
  <th>Size</th>
  <th>Students</th>
  <th>Max Similarity</th>
  <th>Questions</th>
  <th>Signals</th>
</tr>
</thead>
<tbody>
{_html_cluster_rows(report)}
</tbody>
</table>

<h2>Trends</h2>
<table>
<thead>
<tr>
  <th>Student A</th>
  <th>Student B</th>
  <th>Assignments Flagged</th>
  <th>Count</th>
  <th>Max Similarity</th>
  <th>Questions</th>
  <th>Signals</th>
</tr>
</thead>
<tbody>
{_html_trend_rows(report)}
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
    """Export one similarity report in selected deterministic/advanced formats."""

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
        "clusters_csv": None,
        "trends_csv": None,
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
        results["clusters_csv"] = export_similarity_clusters_csv(
            report,
            destination / CLUSTERS_FILENAME,
        )
        results["trends_csv"] = export_similarity_trends_csv(
            report,
            destination / TRENDS_FILENAME,
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
    "EMBEDDING_DISCLAIMER",
    "JSON_FILENAME",
    "CSV_FILENAME",
    "MATRIX_FILENAME",
    "HTML_FILENAME",
    "CLUSTERS_FILENAME",
    "TRENDS_FILENAME",
    "CSV_COLUMNS",
    "CLUSTER_CSV_COLUMNS",
    "TREND_CSV_COLUMNS",
    "VALID_EXPORT_FORMATS",
    "export_similarity_json",
    "export_similarity_pairs_csv",
    "export_similarity_matrix_csv",
    "export_similarity_clusters_csv",
    "export_similarity_trends_csv",
    "render_similarity_report_html",
    "export_similarity_html",
    "export_similarity_report",
]
