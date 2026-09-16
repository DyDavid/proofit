"""In-memory store for mock mode.

Deliberately not a database: Phase 2 CP2 replaces this with Supabase once
`ENGINE_MODE=live` exists (PERSON_B_PLAN_v2.md §5 Phase 2 task 5). Everything
here resets on process restart, which is fine for a demo and for the
`?demo=1` mode Phase 5 adds later.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from engine.normalize.schema import AnalysisStatus, BaselineMatch, Match, MatchStage, utcnow

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"

#: Ordered so the progress stepper (web/components/progress/ProgressStepper.tsx)
#: has something to advance through even in mock mode.
STAGE_ORDER: tuple[MatchStage, ...] = (
    "reading_resume",
    "reading_job",
    "matching_requirements",
    "checking_realism",
)

#: Matches a submitted JD's company name to the fixture that was hand-written
#: against that exact real posting (PERSON_B_PLAN_v2.md §5 Phase 1 task 3).
#: Falls back to round-robin so an arbitrary pasted JD still demos all three
#: realism outcomes across repeated runs.
_FIXTURE_BY_COMPANY: dict[str, str] = {
    "angkor digital": "fresh_grad_strong_fit",
    "meridian systems": "fresh_grad_stretch",
    "northwind labs": "unrealistic",
}
_FIXTURE_ROTATION = ("fresh_grad_strong_fit", "fresh_grad_stretch", "unrealistic")


def _load_fixture(name: str) -> Match:
    raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    return Match.model_validate(raw)


_FIXTURES: dict[str, Match] = {name: _load_fixture(name) for name in _FIXTURE_ROTATION}


def _load_baseline_fixture(name: str) -> BaselineMatch:
    raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    return BaselineMatch.model_validate(raw)


_BASELINES: dict[str, BaselineMatch] = {
    name: _load_baseline_fixture(name) for name in _FIXTURE_ROTATION
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]


@dataclass
class ResumeRecord:
    id: str
    filename: str
    content_type: str
    size: int


@dataclass
class JobRecord:
    id: str
    content_hash: str
    source: Literal["text", "url"]
    raw: str


@dataclass
class AnalysisRecord:
    id: str
    resume_id: str
    job_id: str
    country: str
    status: AnalysisStatus = "queued"
    stage: MatchStage | None = None
    match: Match | None = None
    baseline: BaselineMatch | None = None
    error: dict | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class RewriteRejection:
    """One F5 validator failure (PERSON_B_PLAN_v2.md §5 Phase 3 task 5) — a
    report figure for the evaluation chapter, not an error to hide. Lives here
    rather than in a real DB table for the same reason `AnalysisRecord` does:
    nothing in this codebase has a real database yet (`engine/README.md` line
    30 gives DB migrations to Person A, but Supabase isn't wired until CP2)."""

    id: str
    analysis_id: str
    requirement_id: str
    evidence_id: str
    suggested_phrasing: str
    violations: list[dict[str, str]]
    retry_succeeded: bool
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Store:
    resumes: dict[str, ResumeRecord] = field(default_factory=dict)
    jobs: dict[str, JobRecord] = field(default_factory=dict)
    jobs_by_hash: dict[str, str] = field(default_factory=dict)
    analyses: dict[str, AnalysisRecord] = field(default_factory=dict)
    rewrite_rejections: list[RewriteRejection] = field(default_factory=list)
    _rotation_index: int = 0
    #: Caches the fixture name `pick_fixture_name` picked for a given job_id.
    #: Without this, calling `pick_fixture_name` twice for the same job_id on
    #: the rotation fallback path (once directly, once via `pick_fixture`'s
    #: internal delegation) would advance `_rotation_index` twice and hand
    #: back two *different* names — silently pairing a match with a baseline
    #: from an unrelated fixture. Caching makes the pick idempotent per job_id.
    _picked_fixture_names: dict[str, str] = field(default_factory=dict)

    def add_resume(self, filename: str, content_type: str, size: int) -> ResumeRecord:
        record = ResumeRecord(id=_new_id("res"), filename=filename, content_type=content_type, size=size)
        self.resumes[record.id] = record
        return record

    def add_job(self, raw: str, source: Literal["text", "url"]) -> tuple[JobRecord, bool]:
        """Returns (record, cached) — PROJECT_SPEC.md §9 rule 4: never
        re-normalize the same JD. `cached=True` means an existing job with
        the same content hash was returned instead of a new one."""
        content_hash = _content_hash(raw)
        existing_id = self.jobs_by_hash.get(content_hash)
        if existing_id is not None:
            return self.jobs[existing_id], True

        record = JobRecord(id=_new_id("job"), content_hash=content_hash, source=source, raw=raw)
        self.jobs[record.id] = record
        self.jobs_by_hash[content_hash] = record.id
        return record, False

    def create_analysis(self, resume_id: str, job_id: str, country: str) -> AnalysisRecord:
        record = AnalysisRecord(id=_new_id("an"), resume_id=resume_id, job_id=job_id, country=country)
        self.analyses[record.id] = record
        return record

    def create_retry(self, original_id: str) -> AnalysisRecord | None:
        original = self.analyses.get(original_id)
        if original is None:
            return None
        return self.create_analysis(original.resume_id, original.job_id, original.country)

    def analyses_for_resume(self, resume_id: str) -> list[AnalysisRecord]:
        """Completed analyses for one resume, newest first — the History list
        (PERSON_B_PLAN_v2.md §5 Phase 3 task 2). Only `status == "done"`
        records carry a `match`, which is where job title/company/coverage/
        realism come from in mock mode — there is no separate normalized-job
        store to join against."""
        done = [
            a for a in self.analyses.values()
            if a.resume_id == resume_id and a.status == "done" and a.match is not None
        ]
        return sorted(done, key=lambda a: a.created_at, reverse=True)

    def pick_fixture_name(self, job_id: str) -> str:
        """The fixture name `pick_fixture`/`pick_baseline` would each pick —
        factored out so a match and its baseline always come from the same
        fixture (run_baseline's contract: 'must be run on the same pair').

        Cached per job_id so repeated calls for the same job_id (e.g. one
        direct call plus one via `pick_fixture`'s internal delegation, in the
        same analysis run) always agree — otherwise the rotation fallback
        would advance on the second call and hand back a different name."""
        cached = self._picked_fixture_names.get(job_id)
        if cached is not None:
            return cached

        job = self.jobs.get(job_id)
        text_lower = (job.raw if job else "").lower()
        for company, name in _FIXTURE_BY_COMPANY.items():
            if company in text_lower:
                self._picked_fixture_names[job_id] = name
                return name

        name = _FIXTURE_ROTATION[self._rotation_index % len(_FIXTURE_ROTATION)]
        self._rotation_index += 1
        self._picked_fixture_names[job_id] = name
        return name

    def pick_fixture(self, job_id: str) -> Match:
        return _FIXTURES[self.pick_fixture_name(job_id)]

    def pick_baseline(self, fixture_name: str) -> BaselineMatch:
        return _BASELINES[fixture_name]

    def log_rewrite_rejection(
        self,
        *,
        analysis_id: str,
        requirement_id: str,
        evidence_id: str,
        suggested_phrasing: str,
        violations: list[dict[str, str]],
        retry_succeeded: bool,
    ) -> RewriteRejection:
        record = RewriteRejection(
            id=_new_id("rej"),
            analysis_id=analysis_id,
            requirement_id=requirement_id,
            evidence_id=evidence_id,
            suggested_phrasing=suggested_phrasing,
            violations=violations,
            retry_succeeded=retry_succeeded,
        )
        self.rewrite_rejections.append(record)
        return record


store = Store()
