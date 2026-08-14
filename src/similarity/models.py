"""Data models for deterministic submission similarity review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any


FLAG_LEVELS = ("none", "low", "medium", "high", "exact")
FLAG_RANK = {level: index for index, level in enumerate(FLAG_LEVELS)}


def _validate_flag_level(value: str) -> str:
    if value not in FLAG_RANK:
        allowed = ", ".join(FLAG_LEVELS)
        raise ValueError(
            f"Unsupported similarity flag level {value!r}; expected one of: {allowed}"
        )
    return value


@dataclass
class SimilaritySignal:
    """One explainable similarity signal."""

    method: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.method = str(self.method or "").strip()
        if not self.method:
            raise ValueError("SimilaritySignal.method must be non-empty.")
        self.score = float(self.score)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuestionSimilarity:
    """Similarity evidence for one matching question ID."""

    question_id: str
    ngram_jaccard: float = 0.0
    shared_shingle_count: int = 0
    total_shingle_count: int = 0
    shared_spans: list[dict[str, Any]] = field(default_factory=list)
    flag_level: str = "none"
    warnings: list[str] = field(default_factory=list)
    embedding_cosine: float | None = None
    pseudocode_similarity: float | None = None
    advanced_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.question_id = str(self.question_id or "").strip()
        self.ngram_jaccard = float(self.ngram_jaccard)
        self.shared_shingle_count = int(self.shared_shingle_count)
        self.total_shingle_count = int(self.total_shingle_count)
        self.flag_level = _validate_flag_level(self.flag_level)
        if self.embedding_cosine is not None:
            self.embedding_cosine = float(self.embedding_cosine)
            if not math.isfinite(self.embedding_cosine) or not 0.0 <= self.embedding_cosine <= 1.0:
                raise ValueError("QuestionSimilarity.embedding_cosine must be between 0 and 1.")
        if self.pseudocode_similarity is not None:
            self.pseudocode_similarity = float(self.pseudocode_similarity)
            if (
                not math.isfinite(self.pseudocode_similarity)
                or not 0.0 <= self.pseudocode_similarity <= 1.0
            ):
                raise ValueError(
                    "QuestionSimilarity.pseudocode_similarity must be between 0 and 1."
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PairSimilarity:
    """Deterministic similarity result for one unique student pair."""

    student_a: str
    student_b: str
    overall_score: float = 0.0
    flag_level: str = "none"
    most_similar_question: str | None = None
    exact_file_match: bool = False
    normalized_text_match: bool = False
    question_similarities: dict[str, QuestionSimilarity] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    embedding_max_similarity: float | None = None
    pseudocode_max_similarity: float | None = None
    cluster_ids: list[str] = field(default_factory=list)
    trend_flags: list[str] = field(default_factory=list)
    submission_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.student_a = str(self.student_a or "").strip()
        self.student_b = str(self.student_b or "").strip()
        if not self.student_a or not self.student_b:
            raise ValueError("PairSimilarity requires non-empty student identifiers.")
        if self.student_a == self.student_b:
            raise ValueError("PairSimilarity requires two distinct students.")
        self.overall_score = float(self.overall_score)
        self.flag_level = _validate_flag_level(self.flag_level)
        if self.most_similar_question is not None:
            self.most_similar_question = str(self.most_similar_question)
        if self.embedding_max_similarity is not None:
            self.embedding_max_similarity = float(self.embedding_max_similarity)
            if (
                not math.isfinite(self.embedding_max_similarity)
                or not 0.0 <= self.embedding_max_similarity <= 1.0
            ):
                raise ValueError(
                    "PairSimilarity.embedding_max_similarity must be between 0 and 1."
                )
        if self.pseudocode_max_similarity is not None:
            self.pseudocode_max_similarity = float(self.pseudocode_max_similarity)
            if (
                not math.isfinite(self.pseudocode_max_similarity)
                or not 0.0 <= self.pseudocode_max_similarity <= 1.0
            ):
                raise ValueError(
                    "PairSimilarity.pseudocode_max_similarity must be between 0 and 1."
                )

        cleaned_cluster_ids: list[str] = []
        seen_cluster_ids: set[str] = set()
        for raw_cluster_id in self.cluster_ids:
            cluster_id = str(raw_cluster_id or "").strip()
            if not cluster_id or cluster_id in seen_cluster_ids:
                continue
            seen_cluster_ids.add(cluster_id)
            cleaned_cluster_ids.append(cluster_id)
        self.cluster_ids = cleaned_cluster_ids

        cleaned_trend_flags: list[str] = []
        seen_trend_flags: set[str] = set()
        for raw_flag in self.trend_flags:
            flag = str(raw_flag or "").strip()
            if not flag or flag in seen_trend_flags:
                continue
            seen_trend_flags.add(flag)
            cleaned_trend_flags.append(flag)
        self.trend_flags = cleaned_trend_flags

        if not isinstance(self.submission_provenance, dict):
            raise TypeError("PairSimilarity.submission_provenance must be a dictionary.")
        cleaned_provenance: dict[str, dict[str, Any]] = {}
        for raw_student_id, raw_value in self.submission_provenance.items():
            student_id = str(raw_student_id or "").strip()
            if not student_id:
                continue
            if raw_value is None:
                cleaned_provenance[student_id] = {}
            elif isinstance(raw_value, dict):
                cleaned_provenance[student_id] = dict(raw_value)
            else:
                raise TypeError(
                    "PairSimilarity submission provenance values must be dictionaries."
                )
        self.submission_provenance = cleaned_provenance

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimilarityReport:
    """Assignment-level similarity-review report schema."""

    assignment_id: str
    generated_at: str
    methods: list[str] = field(default_factory=list)
    students: list[str] = field(default_factory=list)
    pairs: list[PairSimilarity] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    report_type: str = "submission_similarity"
    advanced_methods: list[str] = field(default_factory=list)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    trends: list[dict[str, Any]] = field(default_factory=list)
    embedding_config: dict[str, Any] = field(default_factory=dict)
    pseudocode_config: dict[str, Any] = field(default_factory=dict)
    submission_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.assignment_id = str(self.assignment_id or "").strip()
        if not self.assignment_id:
            raise ValueError("SimilarityReport.assignment_id must be non-empty.")
        self.generated_at = str(self.generated_at or "").strip()
        if not self.generated_at:
            raise ValueError("SimilarityReport.generated_at must be non-empty.")

        cleaned_advanced_methods: list[str] = []
        seen_advanced_methods: set[str] = set()
        for raw_method in self.advanced_methods:
            method = str(raw_method or "").strip()
            if not method or method in seen_advanced_methods:
                continue
            seen_advanced_methods.add(method)
            cleaned_advanced_methods.append(method)
        self.advanced_methods = cleaned_advanced_methods

        if not isinstance(self.embedding_config, dict):
            raise TypeError("SimilarityReport.embedding_config must be a dictionary.")
        if not isinstance(self.pseudocode_config, dict):
            raise TypeError("SimilarityReport.pseudocode_config must be a dictionary.")
        if not isinstance(self.submission_provenance, dict):
            raise TypeError("SimilarityReport.submission_provenance must be a dictionary.")

        cleaned_report_provenance: dict[str, dict[str, Any]] = {}
        for raw_student_id, raw_value in self.submission_provenance.items():
            student_id = str(raw_student_id or "").strip()
            if not student_id:
                continue
            if raw_value is None:
                cleaned_report_provenance[student_id] = {}
            elif isinstance(raw_value, dict):
                cleaned_report_provenance[student_id] = dict(raw_value)
            else:
                raise TypeError(
                    "SimilarityReport submission provenance values must be dictionaries."
                )
        self.submission_provenance = cleaned_report_provenance

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
