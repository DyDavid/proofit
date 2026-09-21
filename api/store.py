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
from engine.normalize.schema import AnalysisStatus, Job, Match, MatchStage, Resume

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
    error_message: str | None = None


@dataclass
class Store:
    resumes: dict[str, ResumeRecord] = field(default_factory=dict)
    jobs: dict[str, JobRecord] = field(default_factory=dict)
    jobs_by_hash: dict[str, str] = field(default_factory=dict)
    analyses: dict[str, AnalysisRecord] = field(default_factory=dict)
    _rotation_index: int = 0

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

    def update_analysis(
        self,
        analysis_id: str,
        stage: MatchStage | None = None,
        status: AnalysisStatus | None = None,
        match: Match | None = None,
        error_message: str | None = None,
    ) -> AnalysisRecord | None:
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

    def pick_fixture(self, job_id: str) -> Match:
        job = self.get_job(job_id)
        text_lower = (job.raw if job else "").lower()
        for company, name in _FIXTURE_BY_COMPANY.items():
            if company in text_lower:
                return _FIXTURES[name]

        name = _FIXTURE_ROTATION[self._rotation_index % len(_FIXTURE_ROTATION)]
        self._rotation_index += 1
        return _FIXTURES[name]


store = Store()
