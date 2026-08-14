"""Submission-similarity review primitives.

v2.3.0 deterministic signals remain the foundation. v2.3.1 extends this
package with optional semantic-embedding primitives while keeping provider
dependencies isolated and automated tests fully offline.
"""

from .compare import (
    DEFAULT_THRESHOLDS,
    SHORT_ANSWER_TOKEN_THRESHOLD,
    VALID_SIMILARITY_METHODS,
    compare_submissions,
    compute_question_ngram_similarity,
    resolve_similarity_methods,
    resolve_similarity_thresholds,
)
from .export import (
    CSV_COLUMNS,
    CSV_FILENAME,
    DISCLAIMER,
    HTML_FILENAME,
    JSON_FILENAME,
    MATRIX_FILENAME,
    VALID_EXPORT_FORMATS,
    export_similarity_html,
    export_similarity_json,
    export_similarity_matrix_csv,
    export_similarity_pairs_csv,
    export_similarity_report,
    render_similarity_report_html,
)
from .embedding_provider import EmbeddingProvider
from .embeddings import (
    cosine_similarity,
    default_embedding_cache_dir,
    embedding_cache_key,
    get_embeddings,
    load_cached_embedding,
    save_cached_embedding,
)
from .mock_embedding_provider import MockEmbeddingProvider
from .highlight import find_shared_spans, render_side_by_side_html
from .hashing import compute_file_sha256, compute_text_sha256
from .models import (
    FLAG_LEVELS,
    FLAG_RANK,
    PairSimilarity,
    QuestionSimilarity,
    SimilarityReport,
    SimilaritySignal,
)
from .normalize import normalize_for_similarity
from .report import DEFAULT_METHODS, generate_similarity_report
from .shingles import (
    jaccard_similarity,
    make_word_shingles,
    tokenize_for_similarity,
)

__all__ = [
    "FLAG_LEVELS",
    "FLAG_RANK",
    "SimilaritySignal",
    "QuestionSimilarity",
    "PairSimilarity",
    "SimilarityReport",
    "EmbeddingProvider",
    "MockEmbeddingProvider",
    "cosine_similarity",
    "default_embedding_cache_dir",
    "embedding_cache_key",
    "get_embeddings",
    "load_cached_embedding",
    "save_cached_embedding",
    "DEFAULT_THRESHOLDS",
    "SHORT_ANSWER_TOKEN_THRESHOLD",
    "VALID_SIMILARITY_METHODS",
    "compare_submissions",
    "compute_question_ngram_similarity",
    "resolve_similarity_methods",
    "resolve_similarity_thresholds",
    "DEFAULT_METHODS",
    "generate_similarity_report",
    "find_shared_spans",
    "render_side_by_side_html",
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
    "compute_file_sha256",
    "compute_text_sha256",
    "normalize_for_similarity",
    "tokenize_for_similarity",
    "make_word_shingles",
    "jaccard_similarity",
    "SOURCE_LOADED",
    "SOURCE_SUBMISSIONS_FOLDER",
    "SOURCE_ASSESSMENT_FOLDER",
    "VALID_SOURCE_TYPES",
    "SimilaritySourceResult",
    "infer_similarity_question_ids",
    "collect_loaded_similarity_submissions",
    "collect_similarity_submissions_folder",
    "collect_similarity_assessment_folder",
    "collect_similarity_source",

]

from .sources import (
    SOURCE_ASSESSMENT_FOLDER,
    SOURCE_LOADED,
    SOURCE_SUBMISSIONS_FOLDER,
    VALID_SOURCE_TYPES,
    SimilaritySourceResult,
    collect_loaded_similarity_submissions,
    collect_similarity_assessment_folder,
    collect_similarity_source,
    collect_similarity_submissions_folder,
    infer_similarity_question_ids,
)
