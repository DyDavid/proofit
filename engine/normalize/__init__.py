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
    """Normalize raw job-description text into a Job."""
    from .normalizer import normalize_jd_text
    return normalize_jd_text(text)


def normalize_resume(file_bytes: bytes, filename: str) -> Resume:
    """Normalize an uploaded resume file into a Resume."""
    from .normalizer import normalize_resume_file
    return normalize_resume_file(file_bytes, filename)
