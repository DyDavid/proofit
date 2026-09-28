"""Unified store with Supabase PostgreSQL persistence and in-memory cache fallback.

When Supabase credentials are provided, reads and writes persist to Supabase tables:
`jobs`, `resumes`, `analyses`, `jd_requirements`, and `resume_evidence`.
When offline or in mock mode without credentials, gracefully falls back to the in-memory store.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from api.db import (
    db_create_analysis,
    db_get_analysis,
    db_get_job,
    db_get_job_by_hash,
    db_get_resume,
    db_list_analyses,
    db_update_analysis_stage,
    db_upsert_job,
    db_upsert_resume,
    get_supabase_client,
)
from engine.normalize.schema import (
    AnalysisStatus,
    BaselineMatch,
    Job,
    Match,
    MatchStage,
    Resume,
    utcnow,
)

logger = logging.getLogger(__name__)
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"

STAGE_ORDER: tuple[MatchStage, ...] = (
    "reading_resume",
    "reading_job",
    "matching_requirements",
    "checking_realism",
)

_FIXTURE_BY_COMPANY: dict[str, str] = {
    "angkor digital": "fresh_grad_strong_fit",
    "meridian systems": "fresh_grad_stretch",
    "northwind labs": "unrealistic",
}
_FIXTURE_ROTATION = ("fresh_grad_strong_fit", "fresh_grad_stretch", "unrealistic")


def _load_fixture(name: str) -> Match:
    raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
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
    data: bytes | None = None
    raw_text: str | None = None
    normalized: Resume | None = None


@dataclass
class JobRecord:
    id: str
    content_hash: str
    source: Literal["text", "url"]
    raw: str
    normalized: Job | None = None


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
    error_message: str | None = None
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

    def add_resume(
        self,
        filename: str,
        content_type: str,
        size: int,
        data: bytes | None = None,
        raw_text: str | None = None,
        normalized: Resume | None = None,
    ) -> ResumeRecord:
        record = ResumeRecord(
            id=_new_id("res"),
            filename=filename,
            content_type=content_type,
            size=size,
            data=data,
            raw_text=raw_text,
            normalized=normalized,
        )
        self.resumes[record.id] = record

        # Persist to Supabase if available
        if get_supabase_client():
            norm_json = normalized.model_dump(mode="json") if normalized else None
            db_upsert_resume(
                resume_id=record.id,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
                raw_text=raw_text,
                normalized=norm_json,
            )

        return record

    def get_resume(self, resume_id: str) -> ResumeRecord | None:
        if resume_id in self.resumes:
            return self.resumes[resume_id]

        if get_supabase_client():
            row = db_get_resume(resume_id)
            if row:
                norm_obj = Resume.model_validate(row["normalized"]) if row.get("normalized") else None
                rec = ResumeRecord(
                    id=row["id"],
                    filename=row.get("filename", "resume"),
                    content_type=row.get("content_type", "application/pdf"),
                    size=row.get("size_bytes", 0),
                    raw_text=row.get("raw_text"),
                    normalized=norm_obj,
                )
                self.resumes[rec.id] = rec
                return rec
        return None

    def add_job(
        self,
        raw: str,
        source: Literal["text", "url"],
        normalized: Job | None = None,
    ) -> tuple[JobRecord, bool]:
        """Returns (record, cached)."""
        content_hash = _content_hash(raw)

        # 1. Check in-memory hash index
        existing_id = self.jobs_by_hash.get(content_hash)
        if existing_id is not None and existing_id in self.jobs:
            return self.jobs[existing_id], True

        # 2. Check Supabase by content_hash
        if get_supabase_client():
            row = db_get_job_by_hash(content_hash)
            if row:
                norm_obj = Job.model_validate(row["normalized"]) if row.get("normalized") else None
                rec = JobRecord(
                    id=row["id"],
                    content_hash=row["content_hash"],
                    source=row.get("source", source),
                    raw=row.get("raw", raw),
                    normalized=norm_obj,
                )
                self.jobs[rec.id] = rec
                self.jobs_by_hash[content_hash] = rec.id
                return rec, True

        # 3. Create new Job
        record = JobRecord(
            id=_new_id("job"),
            content_hash=content_hash,
            source=source,
            raw=raw,
            normalized=normalized,
        )
        self.jobs[record.id] = record
        self.jobs_by_hash[content_hash] = record.id

        if get_supabase_client():
            norm_json = normalized.model_dump(mode="json") if normalized else None
            title = normalized.title if normalized else None
            company = normalized.company if normalized else None
            location = normalized.location if normalized else None
            db_upsert_job(
                job_id=record.id,
                content_hash=content_hash,
                source=source,
                raw=raw,
                title=title,
                company=company,
                location=location,
                normalized=norm_json,
            )

        return record, False

    def get_job(self, job_id: str) -> JobRecord | None:
        if job_id in self.jobs:
            return self.jobs[job_id]

        if get_supabase_client():
            row = db_get_job(job_id)
            if row:
                norm_obj = Job.model_validate(row["normalized"]) if row.get("normalized") else None
                rec = JobRecord(
                    id=row["id"],
                    content_hash=row["content_hash"],
                    source=row.get("source", "text"),
                    raw=row.get("raw", ""),
                    normalized=norm_obj,
                )
                self.jobs[rec.id] = rec
                self.jobs_by_hash[rec.content_hash] = rec.id
                return rec
        return None

    def create_analysis(self, resume_id: str, job_id: str, country: str) -> AnalysisRecord:
        record = AnalysisRecord(
            id=_new_id("an"),
            resume_id=resume_id,
            job_id=job_id,
            country=country,
            status="queued",
        )
        self.analyses[record.id] = record

        if get_supabase_client():
            db_create_analysis(
                analysis_id=record.id,
                resume_id=resume_id,
                job_id=job_id,
                country=country,
                status="queued",
            )

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

    def update_analysis(
        self,
        analysis_id: str,
        stage: MatchStage | None = None,
        status: AnalysisStatus | None = None,
        match: Match | None = None,
        error_message: str | None = None,
    ) -> AnalysisRecord | None:
        """Live-mode (F1 task 5) analysis mutation, with a best-effort Supabase
        mirror. Mock mode does not call this — `_run_mock_analysis` mutates
        `AnalysisRecord` fields directly and stays entirely in-memory, matching
        this codebase's convention that mock mode never touches a database."""
        record = self.analyses.get(analysis_id)
        if record:
            if stage is not None:
                record.stage = stage
            if status is not None:
                record.status = status
            if match is not None:
                record.match = match
            if error_message is not None:
                record.error_message = error_message

        if get_supabase_client():
            match_json = match.model_dump(mode="json") if match else None
            db_update_analysis_stage(
                analysis_id=analysis_id,
                stage=stage,
                status=status,
                match_data=match_json,
                error_message=error_message,
            )

        return record

    def get_analysis(self, analysis_id: str) -> AnalysisRecord | None:
        if analysis_id in self.analyses:
            return self.analyses[analysis_id]

        if get_supabase_client():
            row = db_get_analysis(analysis_id)
            if row:
                match_obj = Match.model_validate(row["match"]) if row.get("match") else None
                rec = AnalysisRecord(
                    id=row["id"],
                    resume_id=row.get("resume_id") or "",
                    job_id=row.get("job_id") or "",
                    country=row.get("country", "KH"),
                    status=row.get("status", "done"),
                    stage=row.get("stage"),
                    match=match_obj,
                    error_message=row.get("error_message"),
                )
                self.analyses[rec.id] = rec
                return rec
        return None

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
