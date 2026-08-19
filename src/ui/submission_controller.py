"""Submission state/orchestration for the desktop grading UI.

This controller is deliberately Qt-free.  It sits between ``RubricGrader`` and
``src.submissions`` so the main window does not need to know about persistence
layouts, student-ID normalization, or assessment-JSON submission fields.

v2.3.2 Commit 6 extends the existing split responsibility:

* backend parsing/transcription functions remain in ``src.submissions``;
* canonical submission/attempt history remains in ``SubmissionRepository``;
* the controller keeps one active ``ParsedSubmission`` per student for grading;
* canonical attempt activation reparses through the existing parser bridge;
* assessment save paths still merge supporting evidence fields only.

The controller never changes scoring data.  ``submission_meta`` and
``extracted_answers`` are supporting evidence only.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.submissions import (
    FULL_SUBMISSION,
    ParsedSubmission,
    SUBMISSION_MODE_LATEX,
    Submission,
    SubmissionHandlerUnavailableError,
    SubmissionRepository,
    assessment_submission_fields,
    ensure_canonical_submission,
    load_persisted_submission,
    normalize_student_id,
    parse_canonical_submission,
    parse_pdf_accommodation,
    parse_submissions_folder,
    persist_canonical_submission_linkage,
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
        parse_canonical_fn: Callable[..., ParsedSubmission] = parse_canonical_submission,
        ensure_canonical_fn: Callable[..., Any] = ensure_canonical_submission,
        repository_factory: Callable[..., SubmissionRepository] = SubmissionRepository,
        persist_canonical_link_fn: Callable[..., Dict[str, Any]] = persist_canonical_submission_linkage,
    ) -> None:
        self._parse_folder_fn = parse_folder_fn
        self._parse_pdf_fn = parse_pdf_fn
        self._load_persisted_fn = load_persisted_fn
        self._assessment_fields_fn = assessment_fields_fn
        self._parse_canonical_fn = parse_canonical_fn
        self._ensure_canonical_fn = ensure_canonical_fn
        self._repository_factory = repository_factory
        self._persist_canonical_link_fn = persist_canonical_link_fn

        self._evidence_root: Optional[str] = None
        self._assessment_id: Optional[str] = None
        self._repository: Optional[SubmissionRepository] = None
        self._question_ids: Tuple[str, ...] = ()
        self._submissions: Dict[str, ParsedSubmission] = {}
        self._active_submission_ids: Dict[str, str] = {}
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
    def assessment_id(self) -> Optional[str]:
        return self._assessment_id

    @property
    def submission_repository(self) -> Optional[SubmissionRepository]:
        """Return the currently instantiated canonical repository, if any.

        Merely configuring ``evidence_root`` does not create repository
        directories; the repository is instantiated lazily on first canonical
        operation.
        """
        return self._repository

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

    @property
    def current_canonical_submission(self) -> Optional[Submission]:
        if not self._current_student_id or not self._assessment_id:
            return None
        return self.canonical_submission_for_student(
            self._current_student_id,
            ensure=False,
        )

    def set_evidence_root(self, evidence_root: Optional[str]) -> Optional[str]:
        """Set the persistent evidence root without creating it eagerly."""
        previous = self._evidence_root
        if not evidence_root:
            self._evidence_root = None
            self._repository = None
            self._active_submission_ids.clear()
            return None
        root = Path(evidence_root).expanduser().resolve()
        self._evidence_root = str(root)
        if previous != self._evidence_root:
            self._repository = None
            self._active_submission_ids.clear()
        return self._evidence_root

    def set_assessment_id(self, assessment_id: Optional[str]) -> Optional[str]:
        """Set the canonical assessment identity for repository operations."""
        value = str(assessment_id).strip() if assessment_id is not None else ""
        normalized = value or None
        if normalized != self._assessment_id:
            self._assessment_id = normalized
            # ParsedSubmission is assessment-specific even though the legacy
            # v2.2 cache was keyed only by student. Never carry parsed evidence
            # across a rubric/assessment boundary. Canonical history remains on
            # disk and can be reparsed when the assessment is selected again.
            self._submissions.clear()
            self._active_submission_ids.clear()
        return self._assessment_id

    def set_submission_repository(
        self,
        repository: Optional[SubmissionRepository],
    ) -> Optional[SubmissionRepository]:
        """Inject/replace the canonical repository used by this controller."""
        if repository is None:
            self._repository = None
            self._active_submission_ids.clear()
            return None
        if not isinstance(repository, SubmissionRepository):
            raise TypeError("repository must be SubmissionRepository or None")
        if self._evidence_root:
            expected = Path(self._evidence_root).expanduser().resolve()
            actual = Path(repository.storage_root).expanduser().resolve()
            if expected != actual:
                raise ValueError(
                    "repository.storage_root must match controller evidence_root"
                )
        else:
            self._evidence_root = str(Path(repository.storage_root).expanduser().resolve())
        self._repository = repository
        self._active_submission_ids.clear()
        return repository

    def _repository_for_use(self, *, create: bool = False) -> Optional[SubmissionRepository]:
        if self._repository is not None:
            return self._repository
        if not self._evidence_root:
            return None
        self._repository = self._repository_factory(
            self._evidence_root,
            create=create,
        )
        return self._repository

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
        self._active_submission_ids.clear()
        self._submissions_dir = None
        self._current_student_id = None
        self._current_question_id = None
        if not keep_configuration:
            self._evidence_root = None
            self._assessment_id = None
            self._repository = None
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
        self._remember_canonical_link(parsed)
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

    def _remember_canonical_link(self, parsed: ParsedSubmission) -> Optional[str]:
        metadata = parsed.metadata.get("canonical_submission", {})
        if not isinstance(metadata, Mapping):
            return None
        submission_id = str(metadata.get("submission_id") or "").strip()
        if not submission_id:
            return None
        assessment_id = str(metadata.get("assessment_id") or "").strip()
        if assessment_id and self._assessment_id is None:
            self._assessment_id = assessment_id
        if self._assessment_id and assessment_id and assessment_id != self._assessment_id:
            return None
        canonical_student = self.canonical_student_id(
            metadata.get("student_id") or parsed.student_id
        )
        self._active_submission_ids[canonical_student] = submission_id
        return submission_id

    def _attach_canonical_link(
        self,
        parsed: ParsedSubmission,
        submission: Submission,
        *,
        persist: bool = False,
    ) -> ParsedSubmission:
        parsed.metadata = deepcopy(parsed.metadata)
        existing = parsed.metadata.get("canonical_submission", {})
        existing = deepcopy(existing) if isinstance(existing, Mapping) else {}
        existing.update(
            {
                "schema_version": "1.0",
                "submission_id": submission.submission_id,
                "assessment_id": submission.assessment_id,
                "student_id": submission.student_id,
                "attempt": submission.attempt,
                "is_active_attempt": submission.is_active_attempt,
                "source_system": submission.source_system,
                "submitted_at": submission.submitted_at,
                "imported_at": submission.imported_at,
                "status": submission.status,
                "artifact_ids": [artifact.artifact_id for artifact in submission.artifacts],
            }
        )
        parsed.metadata["canonical_submission"] = existing
        self._active_submission_ids[
            self.canonical_student_id(submission.student_id)
        ] = submission.submission_id
        if persist and self._evidence_root:
            self._persist_canonical_link_fn(parsed, self._evidence_root)
        return parsed

    def _required_assessment_id(self, assessment_id: Optional[str] = None) -> str:
        explicit = str(assessment_id).strip() if assessment_id is not None else ""
        if explicit and self._assessment_id and explicit != self._assessment_id:
            raise ValueError(
                "assessment_id does not match controller assessment context: "
                f"{explicit!r} != {self._assessment_id!r}"
            )
        value = explicit or self._assessment_id or ""
        if not value:
            raise ValueError(
                "assessment_id is required for canonical submission operations"
            )
        return value

    def canonical_submission_for_student(
        self,
        student_id: Any,
        *,
        assessment_id: Optional[str] = None,
        ensure: bool = False,
        migrate_legacy: bool = True,
        verify_hashes: bool = True,
        require_verified: bool = True,
    ) -> Optional[Submission]:
        """Return the active canonical submission for one student.

        ``ensure=True`` may non-destructively migrate a v2.2 evidence bundle
        through Commit 5's compatibility service.
        """
        canonical = self.canonical_student_id(student_id)
        aid = self._required_assessment_id(assessment_id)
        repository = self._repository_for_use(create=False)
        if repository is None:
            return None

        if ensure:
            if not self._evidence_root:
                return None
            result = self._ensure_canonical_fn(
                self._evidence_root,
                aid,
                canonical,
                repository=repository,
                migrate_legacy=migrate_legacy,
                verify_hashes=verify_hashes,
                require_verified=require_verified,
            )
            submission = result.submission if result is not None else None
        else:
            submission = repository.get_active_submission(aid, canonical)

        if submission is not None:
            self._active_submission_ids[canonical] = submission.submission_id
        else:
            self._active_submission_ids.pop(canonical, None)
        return submission

    def submission_history_for_student(
        self,
        student_id: Any,
        *,
        assessment_id: Optional[str] = None,
    ) -> List[Submission]:
        """Return all canonical attempts for a student in repository order."""
        canonical = self.canonical_student_id(student_id)
        aid = self._required_assessment_id(assessment_id)
        repository = self._repository_for_use(create=False)
        if repository is None:
            return []
        history = repository.list_submissions(aid, canonical)
        active = next((item for item in history if item.is_active_attempt), None)
        if active is not None:
            self._active_submission_ids[canonical] = active.submission_id
        else:
            self._active_submission_ids.pop(canonical, None)
        return history

    def active_submission_id_for_student(
        self,
        student_id: Any,
        *,
        assessment_id: Optional[str] = None,
    ) -> Optional[str]:
        canonical = self.canonical_student_id(student_id)
        submission = self.canonical_submission_for_student(
            canonical,
            assessment_id=assessment_id,
            ensure=False,
        )
        return submission.submission_id if submission is not None else None

    def register_canonical_submission(
        self,
        submission: Submission,
        *,
        parsed: Optional[ParsedSubmission] = None,
        replace: bool = True,
    ) -> Submission:
        """Register repository-backed canonical identity in controller state."""
        if not isinstance(submission, Submission):
            raise TypeError("submission must be Submission")
        if self._assessment_id is None:
            self.set_assessment_id(submission.assessment_id)
        aid = self._required_assessment_id(submission.assessment_id)
        if aid != submission.assessment_id:
            raise ValueError(
                "Canonical submission assessment does not match controller assessment"
            )
        repository = self._repository_for_use(create=False)
        if repository is None:
            raise ValueError("evidence_root/repository is required")
        stored = repository.get_submission(
            submission.submission_id,
            assessment_id=submission.assessment_id,
            student_id=submission.student_id,
        )
        canonical = self.canonical_student_id(stored.student_id)
        if stored.is_active_attempt:
            self._active_submission_ids[canonical] = stored.submission_id
        if parsed is not None:
            self._attach_canonical_link(parsed, stored, persist=False)
            self.register_submission(parsed, student_id=canonical, replace=replace)
        return stored

    @staticmethod
    def _submission_is_pdf_accommodation(submission: Submission) -> bool:
        legacy = submission.metadata.get("legacy_migration", {})
        return bool(
            isinstance(legacy, Mapping)
            and str(legacy.get("legacy_submission_mode") or "")
            == "pdf_accommodation"
        )

    def _parse_canonical(
        self,
        submission: Submission,
        *,
        verify_hashes: bool = True,
        accommodation_mode: Optional[bool] = None,
        parse_options: Optional[Mapping[str, Any]] = None,
    ) -> ParsedSubmission:
        repository = self._repository_for_use(create=False)
        if repository is None:
            raise ValueError("evidence_root/repository is required")
        options = dict(parse_options or {})
        options.setdefault("verify_artifacts", verify_hashes)
        options.setdefault("evidence_dir", self._evidence_root)
        options.setdefault(
            "accommodation_mode",
            self._submission_is_pdf_accommodation(submission)
            if accommodation_mode is None
            else bool(accommodation_mode),
        )
        return self._parse_canonical_fn(
            submission,
            repository,
            self._question_ids or None,
            **options,
        )

    def set_active_canonical_submission(
        self,
        student_id: Any,
        submission_id: str,
        *,
        assessment_id: Optional[str] = None,
    ) -> Submission:
        """Switch repository active-attempt state without parsing the artifact."""
        canonical = self.canonical_student_id(student_id)
        aid = self._required_assessment_id(assessment_id)
        repository = self._repository_for_use(create=False)
        if repository is None:
            raise ValueError("evidence_root/repository is required")
        active = repository.set_active_submission(aid, canonical, submission_id)
        self._active_submission_ids[canonical] = active.submission_id

        parsed = self._submissions.get(canonical)
        if parsed is not None:
            linked = parsed.metadata.get("canonical_submission", {})
            linked_id = (
                str(linked.get("submission_id") or "").strip()
                if isinstance(linked, Mapping)
                else ""
            )
            if linked_id != active.submission_id:
                self._submissions.pop(canonical, None)
        return active

    def activate_submission(
        self,
        student_id: Any,
        submission_id: str,
        *,
        assessment_id: Optional[str] = None,
        verify_hashes: bool = True,
        accommodation_mode: Optional[bool] = None,
        parse_options: Optional[Mapping[str, Any]] = None,
    ) -> ParsedSubmission:
        """Parse a historical canonical attempt, then make it active atomically.

        The repository active pointer is changed only after parsing succeeds, so
        an unsupported/corrupt historical artifact cannot silently replace the
        currently active attempt.
        """
        canonical = self.canonical_student_id(student_id)
        aid = self._required_assessment_id(assessment_id)
        repository = self._repository_for_use(create=False)
        if repository is None:
            raise ValueError("evidence_root/repository is required")
        target = repository.get_submission(
            submission_id,
            assessment_id=aid,
            student_id=canonical,
        )
        parsed = self._parse_canonical(
            target,
            verify_hashes=verify_hashes,
            accommodation_mode=accommodation_mode,
            parse_options=parse_options,
        )
        active = repository.set_active_submission(aid, canonical, submission_id)
        self._attach_canonical_link(
            parsed,
            active,
            persist=bool(self._evidence_root),
        )
        self.register_submission(parsed, student_id=canonical, replace=True)
        self._current_student_id = canonical
        return parsed

    def _parsed_matches_assessment(self, parsed: ParsedSubmission) -> bool:
        """Return False when parsed evidence is linked to another assessment."""
        if not self._assessment_id:
            return True
        metadata = parsed.metadata.get("canonical_submission", {})
        if not isinstance(metadata, Mapping):
            return True
        linked_assessment = str(metadata.get("assessment_id") or "").strip()
        return not linked_assessment or linked_assessment == self._assessment_id

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

        # Preserve the fast v2.2 path first.  If canonical history exists, the
        # linkage below ensures the visible ParsedSubmission corresponds to the
        # repository's active attempt.
        try:
            parsed = self._load_persisted_fn(
                self._evidence_root,
                canonical,
                verify_hashes=verify_hashes,
            )
        except FileNotFoundError:
            parsed = None

        if parsed is not None and not self._parsed_matches_assessment(parsed):
            # v2.2 evidence lives in a student-only directory. If that bundle
            # has already been linked to another canonical assessment, it must
            # not be displayed or lazily migrated in the current assessment.
            parsed = None

        active: Optional[Submission] = None
        if self._assessment_id:
            try:
                active = self.canonical_submission_for_student(
                    canonical,
                    ensure=True,
                    migrate_legacy=True,
                    verify_hashes=verify_hashes,
                    require_verified=True,
                )
            except FileNotFoundError:
                active = None

        if active is not None:
            linked_id = None
            if parsed is not None:
                linked = parsed.metadata.get("canonical_submission", {})
                if isinstance(linked, Mapping):
                    linked_id = str(linked.get("submission_id") or "").strip() or None

            if parsed is not None and linked_id in (None, active.submission_id):
                if linked_id is None:
                    self._attach_canonical_link(
                        parsed,
                        active,
                        persist=True,
                    )
                self.register_submission(parsed, student_id=canonical, replace=True)
                return parsed

            try:
                parsed = self._parse_canonical(
                    active,
                    verify_hashes=verify_hashes,
                )
            except SubmissionHandlerUnavailableError:
                # Canonical programming/ZIP artifacts are legitimate repository
                # state even before their later-release handlers exist.
                return None

            self._attach_canonical_link(
                parsed,
                active,
                persist=bool(self._evidence_root),
            )
            self.register_submission(parsed, student_id=canonical, replace=True)
            return parsed

        if parsed is None:
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

        meta_assessment_id = meta.get("assessment_id") or assessment.get("assessment_id")
        if meta_assessment_id:
            self.set_assessment_id(str(meta_assessment_id))

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

        submission_id = str(meta.get("submission_id") or "").strip()
        if submission_id:
            metadata["canonical_submission"] = {
                "schema_version": "1.0",
                "submission_id": submission_id,
                "assessment_id": meta.get("assessment_id"),
                "student_id": canonical,
                "attempt": meta.get("attempt"),
                "source_system": meta.get("source_system"),
                "artifact_ids": list(meta.get("artifact_ids") or []),
            }

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
