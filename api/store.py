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
from pathlib import Path
from typing import Literal

from engine.normalize.schema import AnalysisStatus, Match, MatchStage

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


@dataclass
class Store:
    resumes: dict[str, ResumeRecord] = field(default_factory=dict)
    jobs: dict[str, JobRecord] = field(default_factory=dict)
    jobs_by_hash: dict[str, str] = field(default_factory=dict)
    analyses: dict[str, AnalysisRecord] = field(default_factory=dict)
    _rotation_index: int = 0

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

    def pick_fixture(self, job_id: str) -> Match:
        job = self.jobs.get(job_id)
        text_lower = (job.raw if job else "").lower()
        for company, name in _FIXTURE_BY_COMPANY.items():
            if company in text_lower:
                return _FIXTURES[name]

        name = _FIXTURE_ROTATION[self._rotation_index % len(_FIXTURE_ROTATION)]
        self._rotation_index += 1
        return _FIXTURES[name]


store = Store()
