"""Normalization — job descriptions and resumes into the one schema.

OWNER: **Person A** (PERSON_B_PLAN_v2.md §2 "Person A owns").

Two jobs live here:

1. ``schema.py`` — the locked Pydantic models. Every other package, the API, the
   fixtures and the generated TypeScript all speak these and nothing else. Person A
   publishes the final version at **Checkpoint 1** (end of Week 3); the file
   currently in the tree is Person B's provisional draft, written from
   PROJECT_SPEC.md §8 so Phase 1 is not blocked.
2. ``normalize_jd`` / ``normalize_resume`` — two of the five callables on the
   ownership boundary (§2 contract 2). Declared here as typed stubs so that the
   API, the tests and mypy can be written against the real signatures today.

Everything public in ``schema`` is re-exported from this package, so both spellings
work and neither is wrong::

    from engine.normalize import Job, Match, Resume        # convenience
    from engine.normalize.schema import Job, Match, Resume # explicit

``api/`` calls the two functions below and nothing else in this package's
internals (engine/README.md, "The internals rule").
"""

from __future__ import annotations

from .schema import (
    NON_EMPLOYMENT_EVIDENCE,
    PRIORITY_DISPLAY_ORDER,
    SCHEMA_VERSION,
    VERDICT_DISPLAY_ORDER,
    AnalysisStatus,
    BaselineMatch,
    BaselineResult,
    Education,
    Evidence,
    EvidenceType,
    HiddenStrength,
    Job,
    Match,
    MatchResult,
    MatchStage,
    PriorityAction,
    RealismVerdict,
    Requirement,
    RequirementCategory,
    RequirementPriority,
    Resume,
    SchemaBundle,
    Seniority,
    SourceType,
    SponsorsVisa,
    Verdict,
    utcnow,
)

__all__ = [
    # ── re-exported from .schema (mirrors schema.__all__ exactly) ─────────────
    "NON_EMPLOYMENT_EVIDENCE",
    "PRIORITY_DISPLAY_ORDER",
    "SCHEMA_VERSION",
    "VERDICT_DISPLAY_ORDER",
    "AnalysisStatus",
    "BaselineMatch",
    "BaselineResult",
    "Education",
    "Evidence",
    "EvidenceType",
    "HiddenStrength",
    "Job",
    "Match",
    "MatchResult",
    "MatchStage",
    "PriorityAction",
    "RealismVerdict",
    "Requirement",
    "RequirementCategory",
    "RequirementPriority",
    "Resume",
    "SchemaBundle",
    "Seniority",
    "SourceType",
    "SponsorsVisa",
    "Verdict",
    "utcnow",
    # ── contract callables owned by Person A ──────────────────────────────────
    "normalize_jd",
    "normalize_resume",
]


def normalize_jd(text: str) -> Job:
    """Normalize raw job-description text into a :class:`Job`.

    CONTRACT (PERSON_B_PLAN_v2.md §2, "The contract between you", item 2)::

        engine.normalize.normalize_jd(text: str) -> Job

    Owned by **Person A**. Person B calls it from ``api/routes/jobs.py`` and never
    reaches into this package's internals.

    Args:
        text: The job post as plain text. Either pasted by the user (
            ``source_type="pasted"``) or the return value of
            :func:`engine.ingest.fetch_jd` (``source_type="scraped"``). Leading and
            trailing whitespace is not significant.

    Returns:
        A validated :class:`~engine.normalize.schema.Job`. Every requirement in the
        post becomes one :class:`~engine.normalize.schema.Requirement` record with
        its own ``id`` (``r1``, ``r2``, …) and its ``text`` quoted **verbatim** from
        the post — the results screen shows the JD's own words back to the user, so
        paraphrasing here is a defect. ``content_hash`` must be a hash of ``text``:
        PROJECT_SPEC.md §9 rule 4 forbids re-normalizing the same JD, because LLM
        cost otherwise scales with traffic.

    Raises:
        NotImplementedError: Always, until Person A lands the implementation. The
            schema this returns locks at **Checkpoint 1** (end of Week 3); the API
            switches from fixtures to this function at **Checkpoint 2** (end of
            Week 7).
        ValueError: (once implemented) when ``text`` is empty or carries no
            recognizable requirement — surfaced by the API as ``JOB_EMPTY``.

    Fixture:
        ``data/fixtures/`` holds a golden ``Job`` for this function (§2 contract 3).
        Build and test against it first, live engine second.
    """
    raise NotImplementedError(
        "engine.normalize.normalize_jd is Person A's to implement "
        "(PERSON_B_PLAN_v2.md §2, contract 2); the Job schema it returns locks at "
        "Checkpoint 1, end of Week 3. Until Checkpoint 2 wires the live engine, run "
        "the API with ENGINE_MODE=mock, which serves the golden Job fixture from "
        "data/fixtures/."
    )


def normalize_resume(file_bytes: bytes, filename: str) -> Resume:
    """Normalize an uploaded resume file into a :class:`Resume`.

    CONTRACT (PERSON_B_PLAN_v2.md §2, "The contract between you", item 2)::

        engine.normalize.normalize_resume(file_bytes: bytes, filename: str) -> Resume

    Owned by **Person A**. Person B calls it from ``api/routes/resumes.py`` and never
    reaches into this package's internals.

    Args:
        file_bytes: The raw uploaded file. PDF or DOCX only, 5 MB maximum — the API
            enforces both before calling, rejecting with ``RESUME_BAD_TYPE`` and
            ``RESUME_TOO_LARGE`` respectively.
        filename: The original client filename, used to choose the parser
            (``.pdf`` → pdfminer.six, ``.docx`` → python-docx; PROJECT_SPEC.md §7).
            Never trusted as a filesystem path.

    Returns:
        A validated :class:`~engine.normalize.schema.Resume`. Each thing the
        candidate has actually done becomes one
        :class:`~engine.normalize.schema.Evidence` record with its own ``id``
        (``e1``, ``e2``, …) and a ``source_line`` copied **verbatim** from the
        resume — the results screen highlights that exact string, and the F5
        hallucination validator in ``engine.rewrite`` checks generated claims
        against it. F4 is the point of the project: coursework, projects,
        competitions and volunteering are first-class ``evidence_type`` values, not
        second-class text, because a fresh graduate has no employment bullets.
        ``total_years_work`` counts paid employment only, so ``0.0`` is a correct
        and expected answer.

    Raises:
        NotImplementedError: Always, until Person A lands the implementation. The
            schema this returns locks at **Checkpoint 1** (end of Week 3); the API
            switches from fixtures to this function at **Checkpoint 2** (end of
            Week 7).
        ValueError: (once implemented) when the file yields no extractable text —
            a scanned image PDF, for instance — surfaced by the API as
            ``RESUME_UNREADABLE``.

    Fixture:
        ``data/fixtures/`` holds a golden ``Resume`` for this function
        (§2 contract 3), drawn from the anonymized PDFs in ``data/resumes/``.
    """
    raise NotImplementedError(
        "engine.normalize.normalize_resume is Person A's to implement "
        "(PERSON_B_PLAN_v2.md §2, contract 2); the Resume schema it returns locks at "
        "Checkpoint 1, end of Week 3. Until Checkpoint 2 wires the live engine, run "
        "the API with ENGINE_MODE=mock, which serves the golden Resume fixture from "
        "data/fixtures/."
    )
