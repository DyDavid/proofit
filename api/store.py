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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from api.db import (
    db_create_analysis,
    db_get_analysis,
    db_get_guest_ip_last_used,
    db_get_job,
    db_get_job_by_hash,
    db_get_resume,
    db_list_analyses,
    db_record_guest_ip_usage,
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
    user_id: str | None = None


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
    user_id: str | None = None
    is_guest: bool = False
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
    guest_ip_usage: dict[str, datetime] = field(default_factory=dict)
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
        user_id: str | None = None,
    ) -> ResumeRecord:
        record = ResumeRecord(
            id=_new_id("res"),
            filename=filename,
            content_type=content_type,
            size=size,
            data=data,
            raw_text=raw_text,
            normalized=normalized,
            user_id=user_id,
        )
        self.resumes[record.id] = record

        # Persist to Supabase if available (only for authenticated users; guest resumes stay in memory)
        if get_supabase_client() and user_id is not None:
            norm_json = normalized.model_dump(mode="json") if normalized else None
            db_upsert_resume(
                resume_id=record.id,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
                raw_text=raw_text,
                normalized=norm_json,
                user_id=user_id,
            )

        return record

    def count_user_resumes(self, user_id: str) -> int:
        client = get_supabase_client()
        if client is not None:
            try:
                res = (
                    client.table("resumes")
                    .select("id", count="exact")
                    .eq("user_id", user_id)
                    .execute()
                )
                if res.count is not None:
                    return int(res.count)
            except Exception:
                pass
        return sum(1 for r in self.resumes.values() if r.user_id == user_id)

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
                    user_id=row.get("user_id"),
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

    def save_normalized_resume(self, resume_id: str, normalized: Resume) -> ResumeRecord | None:
        rec = self.resumes.get(resume_id)
        if rec is not None:
            rec.normalized = normalized
        if get_supabase_client() and rec is not None and rec.user_id is not None:
            db_upsert_resume(
                resume_id=rec.id,
                filename=rec.filename,
                content_type=rec.content_type,
                size_bytes=rec.size,
                raw_text=rec.raw_text,
                normalized=normalized.model_dump(mode="json"),
                user_id=rec.user_id,
            )
        return rec

    def save_normalized_job(self, job_id: str, normalized: Job) -> JobRecord | None:
        rec = self.jobs.get(job_id)
        if rec is not None:
            rec.normalized = normalized
        if get_supabase_client() and rec is not None:
            db_upsert_job(
                job_id=rec.id,
                content_hash=rec.content_hash,
                source=rec.source,
                raw=rec.raw,
                title=normalized.title,
                company=normalized.company,
                location=normalized.location,
                normalized=normalized.model_dump(mode="json"),
            )
        return rec

    def check_guest_ip_allowed(self, ip_hash: str) -> bool:
        """Returns True if this salted IP hash has not run a guest analysis in the past 24h."""
        now = utcnow()
        cutoff = now - timedelta(hours=24)

        last_mem = self.guest_ip_usage.get(ip_hash)
        if last_mem is not None and last_mem > cutoff:
            return False

        if get_supabase_client():
            last_db_str = db_get_guest_ip_last_used(ip_hash)
            if last_db_str:
                try:
                    last_db = datetime.fromisoformat(last_db_str.replace("Z", "+00:00"))
                    if last_db > cutoff:
                        self.guest_ip_usage[ip_hash] = last_db
                        return False
                except ValueError:
                    pass

        return True

    def record_guest_ip_usage(self, ip_hash: str) -> None:
        now = utcnow()
        self.guest_ip_usage[ip_hash] = now
        if get_supabase_client():
            db_record_guest_ip_usage(ip_hash, now.isoformat())

    def create_analysis(
        self,
        resume_id: str,
        job_id: str,
        country: str,
        user_id: str | None = None,
        is_guest: bool = False,
    ) -> AnalysisRecord:
        record = AnalysisRecord(
            id=_new_id("an"),
            resume_id=resume_id,
            job_id=job_id,
            country=country,
            status="queued",
            user_id=user_id,
            is_guest=is_guest,
        )
        self.analyses[record.id] = record

        # Phase 1.5: Guest results are returned in memory for the single session,
        # never saved to Supabase.
        if get_supabase_client() and not is_guest:
            db_create_analysis(
                analysis_id=record.id,
                resume_id=resume_id,
                job_id=job_id,
                country=country,
                status="queued",
                user_id=user_id,
            )

        return record

    def create_retry(self, original_id: str) -> AnalysisRecord | None:
        original = self.get_analysis(original_id)
        if original is None:
            return None
        return self.create_analysis(
            original.resume_id,
            original.job_id,
            original.country,
            user_id=original.user_id,
            is_guest=original.is_guest,
        )

    def analyses_for_resume(
        self,
        resume_id: str | None = None,
        user_id: str | None = None,
    ) -> list[AnalysisRecord]:
        """Completed analyses for a user and/or resume, newest first.

        - When `user_id` is provided: includes all completed non-guest analyses
          owned by `user_id` (hydrating from Supabase if needed), plus any
          unowned (`user_id is None`, `not is_guest`) analyses matching `resume_id`.
        - When `user_id` is None: includes only unowned (`user_id is None`,
          `not is_guest`) analyses matching `resume_id`. Never leaks another
          user's rows.
        """
        if get_supabase_client() and user_id is not None:
            for row in db_list_analyses(user_id=user_id):
                aid = row.get("id")
                if aid and aid not in self.analyses:
                    match_obj = Match.model_validate(row["match"]) if row.get("match") else None
                    self.analyses[aid] = AnalysisRecord(
                        id=aid,
                        resume_id=row.get("resume_id") or "",
                        job_id=row.get("job_id") or "",
                        country=row.get("country", "KH"),
                        status=row.get("status", "done"),
                        stage=row.get("stage"),
                        match=match_obj,
                        error_message=row.get("error_message"),
                        user_id=row.get("user_id"),
                        is_guest=False,
                    )

        done: list[AnalysisRecord] = []
        for a in self.analyses.values():
            if a.status != "done" or a.match is None or a.is_guest:
                continue
            if user_id is not None:
                if a.user_id == user_id or (resume_id and a.resume_id == resume_id and a.user_id is None):
                    done.append(a)
            else:
                if resume_id and a.resume_id == resume_id and a.user_id is None:
                    done.append(a)

        return sorted(done, key=lambda a: a.created_at, reverse=True)

    def update_analysis(
        self,
        analysis_id: str,
        stage: MatchStage | None = None,
        status: AnalysisStatus | None = None,
        match: Match | None = None,
        baseline: BaselineMatch | None = None,
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
            if baseline is not None:
                record.baseline = baseline
            if error_message is not None:
                record.error_message = error_message

        if get_supabase_client() and (record is None or not record.is_guest):
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
                baseline_obj: BaselineMatch | None = None
                if match_obj and match_obj.job and match_obj.resume:
                    try:
                        from engine.match import run_baseline

                        baseline_obj = run_baseline(match_obj.job, match_obj.resume)
                    except Exception:
                        baseline_obj = None
                rec = AnalysisRecord(
                    id=row["id"],
                    resume_id=row.get("resume_id") or "",
                    job_id=row.get("job_id") or "",
                    country=row.get("country", "KH"),
                    status=row.get("status", "done"),
                    stage=row.get("stage"),
                    match=match_obj,
                    baseline=baseline_obj,
                    error_message=row.get("error_message"),
                    user_id=row.get("user_id"),
                    is_guest=False,
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
