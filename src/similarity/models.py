"""Data models for deterministic submission similarity review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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

    def __post_init__(self) -> None:
        self.question_id = str(self.question_id or "").strip()
        self.ngram_jaccard = float(self.ngram_jaccard)
        self.shared_shingle_count = int(self.shared_shingle_count)
        self.total_shingle_count = int(self.total_shingle_count)
        self.flag_level = _validate_flag_level(self.flag_level)

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

    def __post_init__(self) -> None:
        self.assignment_id = str(self.assignment_id or "").strip()
        if not self.assignment_id:
            raise ValueError("SimilarityReport.assignment_id must be non-empty.")
        self.generated_at = str(self.generated_at or "").strip()
        if not self.generated_at:
            raise ValueError("SimilarityReport.generated_at must be non-empty.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
