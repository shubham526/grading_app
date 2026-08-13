"""Submission state/orchestration for the desktop grading UI.

This controller is deliberately Qt-free.  It sits between ``RubricGrader`` and
``src.submissions`` so the main window does not need to know about persistence
layouts, student-ID normalization, or assessment-JSON submission fields.

Commit 5 uses a split responsibility:

* backend parsing/transcription functions remain in ``src.submissions``;
* background workers may call the controller's parse helpers later;
* parsed results are registered on the UI thread;
* the controller owns the currently active student/question submission state;
* assessment save paths ask the controller to merge optional submission fields.

The controller never changes scoring data.  ``submission_meta`` and
``extracted_answers`` are supporting evidence only.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from src.submissions import (
    FULL_SUBMISSION,
    ParsedSubmission,
    SUBMISSION_MODE_LATEX,
    assessment_submission_fields,
    load_persisted_submission,
    normalize_student_id,
    parse_pdf_accommodation,
    parse_submissions_folder,
)


DEFAULT_EVIDENCE_DIRNAME = "submission_evidence"


class SubmissionController:
    """Own submission state for one grading-window session.

    The class is intentionally synchronous and Qt-independent.  Long-running
    parsing may be executed by a worker in Commit 5; the worker can call the
    ``parse_*`` helpers and hand the returned objects back to the UI thread for
    registration with ``register_submissions``/``register_submission``.
    """

    def __init__(
        self,
        *,
        evidence_root: Optional[str] = None,
        question_ids: Optional[Sequence[str]] = None,
        parse_folder_fn: Callable[..., Dict[str, ParsedSubmission]] = parse_submissions_folder,
        parse_pdf_fn: Callable[..., ParsedSubmission] = parse_pdf_accommodation,
        load_persisted_fn: Callable[..., ParsedSubmission] = load_persisted_submission,
        assessment_fields_fn: Callable[[ParsedSubmission], Dict[str, Any]] = assessment_submission_fields,
    ) -> None:
        self._parse_folder_fn = parse_folder_fn
        self._parse_pdf_fn = parse_pdf_fn
        self._load_persisted_fn = load_persisted_fn
        self._assessment_fields_fn = assessment_fields_fn

        self._evidence_root: Optional[str] = None
        self._question_ids: Tuple[str, ...] = ()
        self._submissions: Dict[str, ParsedSubmission] = {}
        self._submissions_dir: Optional[str] = None
        self._current_student_id: Optional[str] = None
        self._current_question_id: Optional[str] = None

        self.set_evidence_root(evidence_root)
        self.set_question_ids(question_ids or ())

    # ------------------------------------------------------------------
    # Configuration/state
    # ------------------------------------------------------------------

    @property
    def evidence_root(self) -> Optional[str]:
        return self._evidence_root

    @property
    def question_ids(self) -> Tuple[str, ...]:
        return self._question_ids

    @property
    def submissions_dir(self) -> Optional[str]:
        return self._submissions_dir

    @property
    def current_student_id(self) -> Optional[str]:
        return self._current_student_id

    @property
    def current_question_id(self) -> Optional[str]:
        return self._current_question_id

    @property
    def submissions(self) -> Dict[str, ParsedSubmission]:
        """Return a shallow mapping copy so callers cannot replace controller state."""
        return dict(self._submissions)

    @property
    def current_submission(self) -> Optional[ParsedSubmission]:
        if not self._current_student_id:
            return None
        return self._submissions.get(self._current_student_id)

    def set_evidence_root(self, evidence_root: Optional[str]) -> Optional[str]:
        """Set the persistent evidence root without creating it eagerly."""
        if not evidence_root:
            self._evidence_root = None
            return None
        root = Path(evidence_root).expanduser().resolve()
        self._evidence_root = str(root)
        return self._evidence_root

    def set_assessments_dir(self, assessments_dir: Optional[str]) -> Optional[str]:
        """Use ``<assessments_dir>/submission_evidence`` as the evidence root."""
        if not assessments_dir:
            return self.set_evidence_root(None)
        root = Path(assessments_dir).expanduser().resolve() / DEFAULT_EVIDENCE_DIRNAME
        return self.set_evidence_root(str(root))

    def set_question_ids(self, question_ids: Iterable[str]) -> Tuple[str, ...]:
        cleaned = []
        seen = set()
        for value in question_ids or ():
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        self._question_ids = tuple(cleaned)
        return self._question_ids

    def set_current_question(self, question_id: Optional[str]) -> Optional[str]:
        value = str(question_id).strip() if question_id is not None else ""
        self._current_question_id = value or None
        return self._current_question_id

    def deactivate_student(self) -> None:
        self._current_student_id = None

    def clear(self, *, keep_configuration: bool = True) -> None:
        """Forget loaded submissions and active context.

        Evidence on disk is never deleted by this operation.
        """
        self._submissions.clear()
        self._submissions_dir = None
        self._current_student_id = None
        self._current_question_id = None
        if not keep_configuration:
            self._evidence_root = None
            self._question_ids = ()

    # ------------------------------------------------------------------
    # Identity/registration
    # ------------------------------------------------------------------

    @staticmethod
    def canonical_student_id(student_id: Any) -> str:
        canonical = normalize_student_id(str(student_id or ""))
        if not canonical:
            raise ValueError(f"Invalid student ID: {student_id!r}")
        return canonical

    def register_submission(
        self,
        parsed: ParsedSubmission,
        *,
        student_id: Optional[str] = None,
        replace: bool = True,
    ) -> ParsedSubmission:
        if not isinstance(parsed, ParsedSubmission):
            raise TypeError("parsed must be a ParsedSubmission")

        requested = self.canonical_student_id(student_id or parsed.student_id)
        parsed_id = self.canonical_student_id(parsed.student_id)
        if requested != parsed_id:
            raise ValueError(
                "Submission student ID does not match registration key: "
                f"{requested!r} != {parsed_id!r}"
            )
        if not replace and requested in self._submissions:
            raise ValueError(f"Submission already registered for student {requested!r}")

        self._submissions[requested] = parsed
        return parsed

    def register_submissions(
        self,
        parsed_by_student: Mapping[str, ParsedSubmission],
        *,
        submissions_dir: Optional[str] = None,
        replace: bool = True,
    ) -> Dict[str, ParsedSubmission]:
        registered: Dict[str, ParsedSubmission] = {}
        for raw_id, parsed in (parsed_by_student or {}).items():
            item = self.register_submission(parsed, student_id=str(raw_id), replace=replace)
            registered[self.canonical_student_id(raw_id)] = item

        if submissions_dir:
            self._submissions_dir = str(Path(submissions_dir).expanduser().resolve())
        return registered

    def submission_for_student(
        self,
        student_id: Any,
        *,
        load_persisted: bool = False,
        verify_hashes: bool = True,
    ) -> Optional[ParsedSubmission]:
        canonical = self.canonical_student_id(student_id)
        parsed = self._submissions.get(canonical)
        if parsed is not None or not load_persisted or not self._evidence_root:
            return parsed

        try:
            parsed = self._load_persisted_fn(
                self._evidence_root,
                canonical,
                verify_hashes=verify_hashes,
            )
        except FileNotFoundError:
            return None
        self.register_submission(parsed, student_id=canonical, replace=True)
        return parsed

    def activate_student(
        self,
        student_id: Any,
        *,
        load_persisted: bool = True,
        verify_hashes: bool = True,
    ) -> Optional[ParsedSubmission]:
        canonical = self.canonical_student_id(student_id)
        self._current_student_id = canonical
        return self.submission_for_student(
            canonical,
            load_persisted=load_persisted,
            verify_hashes=verify_hashes,
        )

    # ------------------------------------------------------------------
    # Backend parse helpers (safe to invoke from future workers)
    # ------------------------------------------------------------------

    def parse_normal_submissions(
        self,
        submissions_dir: str,
        *,
        question_ids: Optional[Sequence[str]] = None,
        compile_pdf: bool = True,
        compilation_dir: Optional[str] = None,
        compiler_options: Optional[Dict[str, Any]] = None,
        persist_evidence: bool = True,
    ) -> Dict[str, ParsedSubmission]:
        """Parse normal LaTeX submissions without mutating controller state."""
        ids = tuple(question_ids) if question_ids is not None else self._question_ids
        evidence_dir = self._evidence_root if persist_evidence else None
        return self._parse_folder_fn(
            submissions_dir,
            ids or None,
            compile_pdf=compile_pdf,
            compilation_dir=compilation_dir,
            compiler_options=compiler_options,
            evidence_dir=evidence_dir,
        )

    def parse_pdf_accommodation(
        self,
        student_id: str,
        pdf_path: str,
        *,
        question_ids: Optional[Sequence[str]] = None,
        transcribe_handwriting: bool = False,
        transcription_backend: Any = None,
        transcription_options: Optional[Dict[str, Any]] = None,
        render_dir: Optional[str] = None,
        render_dpi: Optional[int] = None,
        pdf_options: Optional[Dict[str, Any]] = None,
        persist_evidence: bool = True,
        reuse_cached_transcription: bool = True,
    ) -> ParsedSubmission:
        """Parse one explicitly selected PDF accommodation without registering it."""
        canonical = self.canonical_student_id(student_id)
        ids = tuple(question_ids) if question_ids is not None else self._question_ids
        evidence_dir = self._evidence_root if persist_evidence else None

        kwargs: Dict[str, Any] = {
            "student_id": canonical,
            "transcribe_handwriting": transcribe_handwriting,
            "transcription_backend": transcription_backend,
            "transcription_options": transcription_options,
            "render_dir": render_dir,
            "pdf_options": pdf_options,
            "evidence_dir": evidence_dir,
            "reuse_cached_transcription": reuse_cached_transcription,
        }
        # Preserve parser's backend default when no explicit DPI is supplied.
        if render_dpi is not None:
            kwargs["render_dpi"] = render_dpi

        return self._parse_pdf_fn(pdf_path, ids or None, **kwargs)

    # ------------------------------------------------------------------
    # Question/answer access
    # ------------------------------------------------------------------

    def answer_for_student(
        self,
        student_id: Any,
        question_id: Optional[str] = None,
        *,
        allow_full_submission_fallback: bool = False,
        load_persisted: bool = False,
    ) -> Optional[str]:
        parsed = self.submission_for_student(
            student_id,
            load_persisted=load_persisted,
        )
        if parsed is None:
            return None

        qid = question_id or self._current_question_id
        if qid:
            answer = parsed.get_answer(qid)
            if answer is not None:
                return answer
        if allow_full_submission_fallback:
            return parsed.get_answer(FULL_SUBMISSION)
        return None

    def current_answer(
        self,
        *,
        allow_full_submission_fallback: bool = False,
    ) -> Optional[str]:
        if not self._current_student_id:
            return None
        return self.answer_for_student(
            self._current_student_id,
            self._current_question_id,
            allow_full_submission_fallback=allow_full_submission_fallback,
        )

    # ------------------------------------------------------------------
    # Assessment JSON bridge
    # ------------------------------------------------------------------

    def merge_submission_fields(
        self,
        assessment: Mapping[str, Any],
        *,
        student_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a deep-copied assessment with optional submission fields added."""
        merged = deepcopy(dict(assessment or {}))
        target_id = student_id or self._current_student_id
        if not target_id:
            return merged

        parsed = self.submission_for_student(target_id, load_persisted=False)
        if parsed is None:
            return merged

        fields = self._assessment_fields_fn(parsed)
        if isinstance(fields, dict):
            # Only the two backend-defined supporting fields are accepted.
            if "submission_meta" in fields:
                merged["submission_meta"] = deepcopy(fields["submission_meta"])
            if "extracted_answers" in fields:
                merged["extracted_answers"] = deepcopy(fields["extracted_answers"])
        return merged

    def restore_from_assessment(
        self,
        assessment: Mapping[str, Any],
        *,
        verify_hashes: bool = True,
    ) -> Optional[ParsedSubmission]:
        """Restore submission state referenced by a saved assessment.

        Preferred path: load the persisted evidence bundle.  If that bundle is
        unavailable but the assessment contains ``submission_meta`` and
        ``extracted_answers``, reconstruct a limited in-memory representation so
        the question answer remains available.  The reconstructed object is
        explicitly marked as lacking verified persisted evidence.
        """
        if not isinstance(assessment, Mapping):
            return None
        meta = assessment.get("submission_meta")
        if not isinstance(meta, Mapping):
            return None

        raw_student_id = meta.get("student_id") or assessment.get("student_id")
        if not raw_student_id:
            return None
        canonical = self.canonical_student_id(raw_student_id)

        evidence_student_dir = meta.get("evidence_dir")
        candidate_roots = []
        if isinstance(evidence_student_dir, str) and evidence_student_dir.strip():
            student_dir = Path(evidence_student_dir).expanduser().resolve()
            candidate_roots.append(str(student_dir.parent))
        if self._evidence_root and self._evidence_root not in candidate_roots:
            candidate_roots.append(self._evidence_root)

        for root in candidate_roots:
            try:
                parsed = self._load_persisted_fn(
                    root,
                    canonical,
                    verify_hashes=verify_hashes,
                )
            except FileNotFoundError:
                continue
            self._evidence_root = root
            self.register_submission(parsed, student_id=canonical, replace=True)
            self._current_student_id = canonical
            return parsed

        answers_raw = assessment.get("extracted_answers")
        if not isinstance(answers_raw, Mapping):
            return None
        answers = {str(key): str(value) for key, value in answers_raw.items()}

        files_raw = meta.get("files")
        files = (
            {str(k): str(v) for k, v in files_raw.items() if v}
            if isinstance(files_raw, Mapping)
            else {}
        )
        warnings_raw = meta.get("warnings")
        warnings = (
            [str(value) for value in warnings_raw]
            if isinstance(warnings_raw, (list, tuple))
            else []
        )
        warnings.append("persisted_evidence_unavailable")

        metadata = {
            "question_split_status": meta.get("question_split_status"),
            "authoritative_source": meta.get("authoritative_source"),
            "assistive_text_source": meta.get("assistive_text_source"),
            "evidence": {
                "persisted": False,
                "loaded_from_assessment_json": True,
                "verification": {
                    "performed": False,
                    "ok": False,
                    "mismatches": [],
                    "missing": ["persisted_evidence_bundle"],
                },
            },
        }
        transcription_summary = meta.get("transcription")
        if isinstance(transcription_summary, Mapping):
            metadata["transcription"] = dict(transcription_summary)

        parsed = ParsedSubmission(
            student_id=canonical,
            source_used=str(meta.get("source_used") or "none"),
            raw_text="",
            answers_by_question=answers,
            files=files,
            warnings=list(dict.fromkeys(warnings)),
            metadata=metadata,
            submission_mode=str(meta.get("submission_mode") or SUBMISSION_MODE_LATEX),
            accommodation_mode=bool(meta.get("accommodation_mode", False)),
        )
        self.register_submission(parsed, student_id=canonical, replace=True)
        self._current_student_id = canonical
        return parsed


__all__ = [
    "DEFAULT_EVIDENCE_DIRNAME",
    "SubmissionController",
]
