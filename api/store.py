"""Unified store with Supabase PostgreSQL persistence and in-memory cache fallback.

Concurrency & Persistence Model
-------------------------------
1. **Multi-Worker Persistent Mode** (`get_supabase_client() is not None`):
   Reads and writes persist to Supabase PostgreSQL tables (`jobs`, `resumes`, `analyses`,
   `guest_ip_usage`, `usage_reservations`, `usage_events`, `jd_requirements`, `resume_evidence`).
   Concurrency-critical operations—such as claiming an analysis retry (`claim_analysis_retry`),
   reserving guest IP slots (`reserve_guest_usage`), and refreshing analysis state across
   workers—execute atomically in PostgreSQL using row-level locks (`FOR UPDATE`) and
   transactional advisory locks (`pg_advisory_xact_lock`). If persistence fails when
   configured, enforcement operations fail closed with HTTP 503 `SERVICE_UNAVAILABLE`.

2. **Single-Process In-Memory Fallback Mode** (`get_supabase_client() is None`):
   Used only in `ENGINE_MODE=mock` or offline local development without Supabase credentials.
   Synchronizes requests within a single Python process using `Store._lock` (`threading.RLock`).
   Multi-worker / multi-instance deployments MUST configure Supabase database persistence.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from api.db import (
    DatabasePersistenceError,
    db_billing_rpc,
    db_claim_analysis_retry,
    db_commit_resume_slot,
    db_create_analysis,
    db_get_analysis,
    db_get_guest_ip_last_used,
    db_get_job,
    db_get_resume,
    db_list_analyses,
    db_record_guest_ip_usage,
    db_release_guest_usage,
    db_release_resume_slot,
    db_reserve_guest_usage,
    db_reserve_resume_slot,
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
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class JobRecord:
    id: str
    content_hash: str
    source: Literal["text", "url"]
    raw: str
    normalized: Job | None = None
    created_at: datetime = field(default_factory=utcnow)


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
    retried_by: str | None = None
    reservation_id: str | None = None
    guest_ip_hash: str | None = None
    rewrite_in_progress: bool = False
    rewrite_status: str | None = None
    rewrite_rejected_count: int = 0


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
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    #: Caches the fixture name `pick_fixture_name` picked for a given job_id.
    #: Without this, calling `pick_fixture_name` twice for the same job_id on
    #: the rotation fallback path (once directly, once via `pick_fixture`'s
    #: internal delegation) would advance `_rotation_index` twice and hand
    #: back two *different* names — silently pairing a match with a baseline
    #: from an unrelated fixture. Caching makes the pick idempotent per job_id.
    _picked_fixture_names: dict[str, str] = field(default_factory=dict)
    max_guest_ip_entries: int = 5_000
    _resume_slots: dict[str, tuple[str, datetime]] = field(default_factory=dict, repr=False)
    max_guest_resumes: int = 100
    max_guest_analyses: int = 200
    max_jobs_cache: int = 500

    def _guest_ttl_hours(self) -> float:
        try:
            from api.config import settings

            return max(0.01, float(settings.guest_record_ttl_hours))
        except Exception:
            return 24.0

    def _abandoned_timeout_seconds(self) -> float:
        try:
            from api.config import settings

            return max(1.0, float(settings.analysis_abandoned_timeout_seconds))
        except Exception:
            return 600.0

    def _is_analysis_abandoned(
        self, record: AnalysisRecord, now: datetime | None = None
    ) -> bool:
        """Return True if an analysis has been stuck in queued/running past the abandoned threshold."""
        if record.status not in ("queued", "running"):
            return False
        eff_now = now or utcnow()
        cutoff = eff_now - timedelta(seconds=self._abandoned_timeout_seconds())
        return record.created_at <= cutoff

    def recover_abandoned_analysis(
        self, record: AnalysisRecord, now: datetime | None = None
    ) -> bool:
        """Transition an abandoned queued/running analysis to failed and release any active reservation."""
        with self._lock:
            if not self._is_analysis_abandoned(record, now=now):
                return False

            safe_msg = "Analysis timed out or was abandoned."
            err_payload = {
                "code": "ENGINE_FAILED",
                "message": safe_msg,
                "error_id": _new_id("err"),
            }
            record.status = "failed"
            record.match = None
            record.baseline = None
            record.error_message = safe_msg
            record.error = err_payload
            res_id = record.reservation_id
            uid = record.user_id
            is_guest = record.is_guest
            ip_hash = record.guest_ip_hash

        if get_supabase_client() and not is_guest:
            db_update_analysis_stage(
                analysis_id=record.id,
                status="failed",
                match_data=None,
                error_message=safe_msg,
            )

        if res_id:
            try:
                from api.billing.service import release_usage_reservation

                release_usage_reservation(res_id, uid, "analysis")
            except Exception as err:
                logger.warning("Failed to release reservation %s during abandoned recovery: %s", res_id, err)

        if is_guest and ip_hash:
            with contextlib.suppress(Exception):
                self.release_guest_ip_usage(ip_hash)

        return True

    def prune_expired(self, now: datetime | None = None) -> None:
        """Expire old guest records and enforce capacity caps to prevent unbounded memory growth."""
        with self._lock:
            eff_now = now or utcnow()
            cutoff = eff_now - timedelta(hours=self._guest_ttl_hours())

            # 1. Prune and bound guest_ip_usage
            expired_ips = [ip for ip, ts in self.guest_ip_usage.items() if ts <= cutoff]
            for ip in expired_ips:
                self.guest_ip_usage.pop(ip, None)
            if len(self.guest_ip_usage) > self.max_guest_ip_entries:
                sorted_ips = sorted(self.guest_ip_usage.items(), key=lambda item: item[1])
                excess = len(self.guest_ip_usage) - self.max_guest_ip_entries
                for ip, _ in sorted_ips[:excess]:
                    self.guest_ip_usage.pop(ip, None)

            # 2. Prune and bound guest resumes (user_id is None)
            expired_resumes = [
                rid
                for rid, rec in self.resumes.items()
                if rec.user_id is None and rec.created_at <= cutoff
            ]
            for rid in expired_resumes:
                self.resumes.pop(rid, None)

            guest_resumes = [rec for rec in self.resumes.values() if rec.user_id is None]
            if len(guest_resumes) > self.max_guest_resumes:
                guest_resumes.sort(key=lambda r: r.created_at)
                excess = len(guest_resumes) - self.max_guest_resumes
                for rec in guest_resumes[:excess]:
                    self.resumes.pop(rec.id, None)

            # 3. Prune and bound guest analyses (is_guest or user_id is None)
            expired_analyses = [
                aid
                for aid, rec in self.analyses.items()
                if (rec.is_guest or rec.user_id is None) and rec.created_at <= cutoff
            ]
            for aid in expired_analyses:
                self.analyses.pop(aid, None)

            guest_analyses = [
                rec for rec in self.analyses.values() if rec.is_guest or rec.user_id is None
            ]
            if len(guest_analyses) > self.max_guest_analyses:
                guest_analyses.sort(key=lambda a: a.created_at)
                excess = len(guest_analyses) - self.max_guest_analyses
                for rec in guest_analyses[:excess]:
                    self.analyses.pop(rec.id, None)

            from api.config import settings

            durable = get_supabase_client() is not None
            referenced = {a.job_id for a in self.analyses.values()}
            job_cutoff = eff_now - timedelta(hours=settings.job_unused_retention_hours)
            if not durable:
                for job_id, rec in list(self.jobs.items()):
                    if job_id not in referenced and rec.created_at <= job_cutoff:
                        self.jobs.pop(job_id, None)
                        self.jobs_by_hash.pop(rec.content_hash, None)
            # 4. Bound in-memory jobs cache
            if len(self.jobs) > self.max_jobs_cache:
                all_jobs = sorted((j for j in self.jobs.values() if durable or j.id not in referenced), key=lambda j: j.created_at)
                excess = len(self.jobs) - self.max_jobs_cache
                for job_rec in all_jobs[:excess]:
                    self.jobs.pop(job_rec.id, None)
                    if self.jobs_by_hash.get(job_rec.content_hash) == job_rec.id:
                        self.jobs_by_hash.pop(job_rec.content_hash, None)
                    self._picked_fixture_names.pop(job_rec.id, None)

    def reserve_resume_slot(self, user_id: str, limit: int) -> str | None:
        """Reserve before parsing; count committed and pending uploads atomically."""
        from api.config import settings

        slot_id = _new_id("res")
        ttl = max(1.0, settings.reservation_ttl_seconds)
        if get_supabase_client() is not None:
            return slot_id if db_reserve_resume_slot(user_id, slot_id, limit, ttl) else None
        with self._lock:
            now = utcnow()
            self._resume_slots = {rid: value for rid, value in self._resume_slots.items() if value[1] > now}
            used = sum(r.user_id == user_id for r in self.resumes.values())
            pending = sum(uid == user_id for uid, _ in self._resume_slots.values())
            if used + pending >= limit:
                return None
            self._resume_slots[slot_id] = (user_id, now + timedelta(seconds=ttl))
            return slot_id

    def release_resume_slot(self, user_id: str, slot_id: str) -> None:
        if get_supabase_client() is not None:
            db_release_resume_slot(user_id, slot_id)
        with self._lock:
            pending = self._resume_slots.get(slot_id)
            if pending is not None and pending[0] == user_id:
                self._resume_slots.pop(slot_id)

    def add_resume(
        self,
        filename: str,
        content_type: str,
        size: int,
        data: bytes | None = None,
        raw_text: str | None = None,
        normalized: Resume | None = None,
        user_id: str | None = None,
        slot_id: str | None = None,
    ) -> ResumeRecord:
        with self._lock:
            self.prune_expired()
            record = ResumeRecord(
                id=slot_id or _new_id("res"),
                filename=filename,
                content_type=content_type,
                size=size,
                data=data,
                raw_text=raw_text,
                normalized=normalized,
                user_id=user_id,
            )
        client = get_supabase_client()
        if slot_id is not None:
            from api.errors import ApiError

            if user_id is None:
                raise DatabasePersistenceError("Resume reservation requires an owner.")
            if client is not None:
                saved = db_commit_resume_slot(user_id, slot_id, {
                    "filename": filename, "content_type": content_type, "size_bytes": size,
                    "raw_text": raw_text,
                    "normalized": normalized.model_dump(mode="json") if normalized else None,
                })
            else:
                with self._lock:
                    pending = self._resume_slots.get(slot_id)
                    saved = pending is not None and pending[0] == user_id and pending[1] > utcnow()
                    if saved:
                        self.resumes[record.id] = record
                        self._resume_slots.pop(slot_id)
                        return record
            if not saved:
                raise ApiError(409, "RESUME_UNREADABLE", "The upload slot expired. Please upload again.")
        # Unlimited users and guests do not require a quota reservation.
        elif client is not None and user_id is not None:
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

        with self._lock:
            self.resumes[record.id] = record
            if user_id is None:
                self.prune_expired()
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
                raise DatabasePersistenceError("Saved resume count failed.") from None
            raise DatabasePersistenceError("Saved resume count unavailable.")
        return sum(1 for r in self.resumes.values() if r.user_id == user_id)

    def prune_user_resumes_for_slot(self, user_id: str, limit: int) -> None:
        """If user has reached or exceeded their saved resume limit, remove oldest resume to allow replacement."""
        client = get_supabase_client()
        if client is not None:
            try:
                res = (
                    client.table("resumes")
                    .select("id")
                    .eq("user_id", user_id)
                    .order("created_at", desc=False)
                    .execute()
                )
                rows = res.data or []
                if len(rows) >= limit:
                    to_remove = len(rows) - limit + 1
                    for r in rows[:to_remove]:
                        client.table("resumes").delete().eq("id", r["id"]).execute()
                        with self._lock:
                            self.resumes.pop(r["id"], None)
            except Exception:
                pass
        with self._lock:
            user_resumes = sorted(
                [r for r in self.resumes.values() if r.user_id == user_id],
                key=lambda r: r.created_at or utcnow(),
            )
            if len(user_resumes) >= limit:
                to_remove = len(user_resumes) - limit + 1
                for r in user_resumes[:to_remove]:
                    self.resumes.pop(r.id, None)

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
        from api.config import settings
        from api.errors import ApiError

        if get_supabase_client() is not None:
            result = db_billing_rpc("submit_bounded_job", {
                "p_id": _new_id("job"), "p_hash": content_hash, "p_raw": raw,
                "p_source": source, "p_max_unused": settings.job_unused_max_entries,
                "p_retention_hours": settings.job_unused_retention_hours,
            })
            if not isinstance(result.get("allowed"), bool):
                raise DatabasePersistenceError("Invalid job admission response")
            if not result["allowed"]:
                raise ApiError(429, "RATE_LIMITED", "Job storage is busy. Please try again later.")
            try:
                row = result["job"]
                if (not isinstance(result["cached"], bool) or row["content_hash"] != content_hash
                        or _content_hash(row["raw"]) != content_hash or row["source"] not in ("text", "url")):
                    raise ValueError("Invalid job")
                record = JobRecord(id=row["id"], content_hash=content_hash, source=row["source"], raw=row["raw"],
                                   normalized=Job.model_validate(row["normalized"]) if row.get("normalized") else None)
            except Exception:
                raise DatabasePersistenceError("Invalid job persistence response") from None
            with self._lock:
                self.jobs[record.id] = record
                self.jobs_by_hash[content_hash] = record.id
                self.prune_expired()
            return record, result["cached"]

        with self._lock:
            self.prune_expired()
            existing_id = self.jobs_by_hash.get(content_hash)
            if existing_id is not None and existing_id in self.jobs:
                return self.jobs[existing_id], True
            referenced = {a.job_id for a in self.analyses.values()}
            cap = min(self.max_jobs_cache, settings.job_unused_max_entries)
            while len(self.jobs) >= cap:
                unused = [j for j in self.jobs.values() if j.id not in referenced]
                if not unused:
                    raise ApiError(429, "RATE_LIMITED", "Job storage is busy. Please try again later.")
                oldest = min(unused, key=lambda j: j.created_at)
                self.jobs.pop(oldest.id)
                self.jobs_by_hash.pop(oldest.content_hash, None)
            record = JobRecord(
                id=_new_id("job"),
                content_hash=content_hash,
                source=source,
                raw=raw,
                normalized=normalized,
            )
            self.jobs[record.id] = record
            self.jobs_by_hash[content_hash] = record.id
            self.prune_expired()

        return record, False

    def get_job(self, job_id: str) -> JobRecord | None:
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
                self.prune_expired()
                return rec
            old = self.jobs.pop(job_id, None)
            if old:
                self.jobs_by_hash.pop(old.content_hash, None)
            return None
        with self._lock:
            self.prune_expired()
            return self.jobs.get(job_id)

    def save_normalized_resume(self, resume_id: str, normalized: Resume) -> ResumeRecord | None:
        with self._lock:
            rec = self.resumes.get(resume_id)
            if rec is not None:
                rec.normalized = normalized.model_copy(deep=True)
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
        with self._lock:
            rec = self.jobs.get(job_id)
            if rec is not None:
                rec.normalized = normalized.model_copy(deep=True)
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
        from api.errors import ApiError

        now = utcnow()
        cutoff = now - timedelta(hours=self._guest_ttl_hours())

        if get_supabase_client():
            try:
                last_db_str = db_get_guest_ip_last_used(ip_hash)
            except DatabasePersistenceError as exc:
                raise ApiError(
                    status_code=503,
                    code="SERVICE_UNAVAILABLE",
                    message="Persistence service unavailable; cannot verify guest limit safely.",
                ) from exc

            with self._lock:
                self.prune_expired(now=now)
                if last_db_str:
                    try:
                        last_db = datetime.fromisoformat(last_db_str.replace("Z", "+00:00"))
                        if last_db > cutoff:
                            self.guest_ip_usage[ip_hash] = last_db
                            return False
                    except ValueError:
                        pass
                # DB shows no active guest lock: clear any stale local cache entry
                self.guest_ip_usage.pop(ip_hash, None)
                return True

        with self._lock:
            self.prune_expired(now=now)
            last_mem = self.guest_ip_usage.get(ip_hash)
            return not (last_mem is not None and last_mem > cutoff)

    def record_guest_ip_usage(self, ip_hash: str) -> None:
        from api.errors import ApiError

        now = utcnow()
        if get_supabase_client():
            try:
                db_record_guest_ip_usage(ip_hash, now.isoformat())
            except DatabasePersistenceError as exc:
                raise ApiError(
                    status_code=503,
                    code="SERVICE_UNAVAILABLE",
                    message="Persistence service unavailable; cannot record guest usage safely.",
                ) from exc

        with self._lock:
            self.prune_expired(now=now)
            self.guest_ip_usage[ip_hash] = now
            self.prune_expired(now=now)

    def reserve_guest_ip_usage(self, ip_hash: str) -> bool:
        """Atomically checks if guest IP is allowed and reserves a slot if allowed.
        Returns True if reservation succeeded, False if limit reached (already used in 24h).
        Fails closed with HTTP 503 if database persistence is configured and fails.
        """
        from api.errors import ApiError

        now = utcnow()
        if get_supabase_client():
            try:
                res = db_reserve_guest_usage(ip_hash, ttl_hours=self._guest_ttl_hours())
            except DatabasePersistenceError as exc:
                raise ApiError(
                    status_code=503,
                    code="SERVICE_UNAVAILABLE",
                    message="Persistence service unavailable; cannot reserve guest slot safely.",
                ) from exc

            allowed = bool(res.get("allowed", False))
            last_str = res.get("last_analysis_at")
            parsed_ts = now
            if isinstance(last_str, str):
                with contextlib.suppress(ValueError):
                    parsed_ts = datetime.fromisoformat(last_str.replace("Z", "+00:00"))
            with self._lock:
                self.prune_expired(now=now)
                self.guest_ip_usage[ip_hash] = parsed_ts
            return allowed

        # Single-process fallback mode (documented: only when Supabase persistence is not configured)
        with self._lock:
            if not self.check_guest_ip_allowed(ip_hash):
                return False
            self.record_guest_ip_usage(ip_hash)
            return True

    def release_guest_ip_usage(self, ip_hash: str, prev_time: datetime | None = None) -> None:
        """Rollback or release guest IP usage when an analysis fails."""
        if get_supabase_client():
            prev_iso = prev_time.isoformat() if prev_time is not None else None
            db_release_guest_usage(ip_hash, prev_iso)
        with self._lock:
            if prev_time is not None:
                self.guest_ip_usage[ip_hash] = prev_time
            else:
                self.guest_ip_usage.pop(ip_hash, None)

    def create_analysis(
        self,
        resume_id: str,
        job_id: str,
        country: str,
        user_id: str | None = None,
        is_guest: bool = False,
        reservation_id: str | None = None,
    ) -> AnalysisRecord:
        with self._lock:
            self.prune_expired()
            record = AnalysisRecord(
                id=_new_id("an"),
                resume_id=resume_id,
                job_id=job_id,
                country=country,
                status="queued",
                user_id=user_id,
                is_guest=is_guest,
                created_at=utcnow(),
                reservation_id=reservation_id,
            )
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
                reservation_id=reservation_id,
            )

        with self._lock:
            self.analyses[record.id] = record
            if is_guest or user_id is None:
                self.prune_expired()
        return record

    def create_retry(
        self,
        original_id: str,
        user_id: str | None = None,
        is_guest: bool | None = None,
        reservation_id: str | None = None,
    ) -> AnalysisRecord | None:
        from api.errors import ApiError

        original = self.get_analysis(original_id)
        if original is None:
            return None

        target_user_id = user_id if user_id is not None else original.user_id
        target_is_guest = is_guest if is_guest is not None else original.is_guest

        # Multi-worker persistent path: coordinate atomically in PostgreSQL via row-level lock
        if get_supabase_client() and not target_is_guest:
            child_id = _new_id("an")
            try:
                rpc_res = db_claim_analysis_retry(
                    original_id=original_id,
                    child_id=child_id,
                    resume_id=original.resume_id,
                    job_id=original.job_id,
                    country=original.country,
                    user_id=target_user_id,
                    reservation_id=reservation_id,
                    abandoned_seconds=int(self._abandoned_timeout_seconds()),
                )
            except DatabasePersistenceError as exc:
                raise ApiError(
                    status_code=503,
                    code="SERVICE_UNAVAILABLE",
                    message="Persistence service unavailable; cannot coordinate retry safely.",
                ) from exc

            if not rpc_res.get("success", False):
                err_code = rpc_res.get("code", "ANALYSIS_IN_PROGRESS")
                if err_code == "ANALYSIS_NOT_FOUND":
                    return None
                err_msg = rpc_res.get(
                    "message", "A retry for this analysis is already in progress."
                )
                # Refresh local cache so this worker's in-memory record reflects the winning worker's retry
                active_retry_id = rpc_res.get("active_retry_id")
                if active_retry_id:
                    with self._lock:
                        original.retried_by = str(active_retry_id)
                raise ApiError(
                    status_code=409,
                    code="ANALYSIS_IN_PROGRESS",
                    message=str(err_msg),
                )

            with self._lock:
                self.prune_expired()
                child_rec = AnalysisRecord(
                    id=child_id,
                    resume_id=original.resume_id,
                    job_id=original.job_id,
                    country=original.country,
                    status="queued",
                    user_id=target_user_id,
                    is_guest=False,
                    reservation_id=reservation_id,
                )
                self.analyses[child_rec.id] = child_rec
                original.retried_by = child_rec.id
                return child_rec

        # Single-process in-memory fallback path (documented: only when DB persistence is not used)
        with self._lock:
            original = self.get_analysis(original_id)
            if original is None:
                return None

            self.recover_abandoned_analysis(original)

            # 1. State eligibility check
            if original.status in ("queued", "running"):
                raise ApiError(
                    status_code=409,
                    code="ANALYSIS_IN_PROGRESS",
                    message="Cannot retry an analysis that is still queued or running.",
                )

            # 2. Duplicate in-flight retry check (with abandoned work recovery)
            if original.retried_by:
                child = self.get_analysis(original.retried_by)
                if child is not None:
                    self.recover_abandoned_analysis(child)
                    if child.status in ("queued", "running"):
                        raise ApiError(
                            status_code=409,
                            code="ANALYSIS_IN_PROGRESS",
                            message="A retry for this analysis is already in progress.",
                        )

            child_rec = self.create_analysis(
                original.resume_id,
                original.job_id,
                original.country,
                user_id=target_user_id,
                is_guest=target_is_guest,
                reservation_id=reservation_id,
            )
            original.retried_by = child_rec.id
            return child_rec

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
        error: dict | None = None,
        rewrite_status: str | None = None,
        rewrite_rejected_count: int | None = None,
    ) -> AnalysisRecord | None:
        """Live-mode (F1 task 5) analysis mutation, with a best-effort Supabase
        mirror. Mock mode does not call this — `_run_mock_analysis` mutates
        `AnalysisRecord` fields directly and stays entirely in-memory, matching
        this codebase's convention that mock mode never touches a database."""
        with self._lock:
            record = self.analyses.get(analysis_id)
            if record is None and get_supabase_client():
                row = db_get_analysis(analysis_id)
                if row and (row.get("status") == "failed" or row.get("retried_by") is not None) and status != "failed":
                    logger.warning(
                        "Dropping late DB update for analysis %s: current_status=%s retried_by=%s target_status=%s",
                        analysis_id,
                        row.get("status"),
                        row.get("retried_by"),
                        status,
                    )
                    return None
            if record:
                # Prevent late results from modifying failed or retried analyses
                if (record.status == "failed" or record.retried_by is not None) and status != "failed":
                    logger.warning(
                        "Dropping late update for analysis %s: current_status=%s retried_by=%s target_status=%s",
                        analysis_id,
                        record.status,
                        record.retried_by,
                        status,
                    )
                    return record

                if stage is not None:
                    record.stage = stage
                if status is not None:
                    record.status = status
                if status == "failed":
                    record.match = None
                    record.baseline = None
                else:
                    if match is not None:
                        record.match = match.model_copy(deep=True)
                    if baseline is not None:
                        record.baseline = baseline.model_copy(deep=True)
                if error_message is not None:
                    record.error_message = error_message
                if error is not None:
                    record.error = dict(error)
                if rewrite_status is not None:
                    record.rewrite_status = rewrite_status
                if rewrite_rejected_count is not None:
                    record.rewrite_rejected_count = rewrite_rejected_count

        if get_supabase_client() and (record is None or not record.is_guest):
            match_json = (
                match.model_dump(mode="json")
                if (match is not None and status != "failed")
                else None
            )
            db_update_analysis_stage(
                analysis_id=analysis_id,
                stage=stage,
                status=status,
                match_data=match_json,
                error_message=error_message,
            )

        return record

    def get_analysis(self, analysis_id: str) -> AnalysisRecord | None:
        cached = self.analyses.get(analysis_id)
        if get_supabase_client() and (cached is None or not cached.is_guest):
            row = db_get_analysis(analysis_id)
            if row:
                match_obj = Match.model_validate(row["match"]) if row.get("match") else None
                baseline_obj: BaselineMatch | None = cached.baseline if cached else None
                if baseline_obj is None and match_obj and match_obj.job and match_obj.resume:
                    try:
                        from engine.match import run_baseline

                        baseline_obj = run_baseline(match_obj.job, match_obj.resume)
                    except Exception:
                        baseline_obj = None
                created_at = cached.created_at if cached else utcnow()
                raw_created = row.get("created_at")
                if isinstance(raw_created, str):
                    with contextlib.suppress(ValueError):
                        created_at = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
                elif isinstance(raw_created, datetime):
                    created_at = raw_created

                with self._lock:
                    if cached is not None:
                        cached.status = row.get("status", cached.status)
                        cached.stage = row.get("stage", cached.stage)
                        if match_obj is not None or cached.status == "failed":
                            cached.match = None if cached.status == "failed" else match_obj
                        if baseline_obj is not None and cached.status != "failed":
                            cached.baseline = baseline_obj
                        if row.get("error_message") is not None:
                            cached.error_message = row.get("error_message")
                        if row.get("retried_by") is not None:
                            cached.retried_by = row.get("retried_by")
                        if row.get("reservation_id") is not None:
                            cached.reservation_id = row.get("reservation_id")
                        cached.created_at = created_at
                        rec = cached
                    else:
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
                            created_at=created_at,
                            retried_by=row.get("retried_by"),
                            reservation_id=row.get("reservation_id"),
                        )
                        self.analyses[rec.id] = rec
                self.recover_abandoned_analysis(rec)
                return rec

        if cached is not None:
            self.recover_abandoned_analysis(cached)
            return cached
        return None

    def pick_fixture_name(self, job_id: str) -> str:
        """The fixture name `pick_fixture`/`pick_baseline` would each pick —
        factored out so a match and its baseline always come from the same
        fixture (run_baseline's contract: 'must be run on the same pair').

        Cached per job_id so repeated calls for the same job_id (e.g. one
        direct call plus one via `pick_fixture`'s internal delegation, in the
        same analysis run) always agree — otherwise the rotation fallback
        would advance on the second call and hand back a different name."""
        with self._lock:
            if job_id in _FIXTURES:
                return job_id

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
        return _FIXTURES[self.pick_fixture_name(job_id)].model_copy(deep=True)

    def pick_baseline(self, fixture_name: str) -> BaselineMatch:
        return _BASELINES[fixture_name].model_copy(deep=True)

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
