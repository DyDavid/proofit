"""Supabase database client and data persistence layer for Proofit.

Provides persistent storage for Resumes, Jobs, Analyses, and pgvector embeddings.
Gracefully handles offline mode / missing credentials with fallback indicators.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from api.config import settings

logger = logging.getLogger(__name__)

_supabase_client = None


def get_supabase_client() -> Any | None:
    """Lazily instantiate and cache the Supabase client."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = settings.supabase_url or os.getenv("SUPABASE_URL")
    key = (
        settings.supabase_service_key
        or settings.supabase_key
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )

    if not url or not key or "REPLACE_ME" in url or "REPLACE_ME" in key:
        return None

    try:
        from supabase import Client, create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception as err:
        logger.warning("Failed to initialize Supabase client: %s", err)
        return None


def is_supabase_connected() -> bool:
    """Check if Supabase is reachable and responding."""
    client = get_supabase_client()
    if not client:
        return False
    try:
        # Quick query on analyses or jobs table to verify connectivity
        res = client.table("analyses").select("id").limit(1).execute()
        return res is not None
    except Exception as err:
        logger.debug("Supabase connectivity check failed: %s", err)
        return False


# ============================================================================
# Job Persistence
# ============================================================================

def db_get_job_by_hash(content_hash: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("jobs").select("*").eq("content_hash", content_hash).maybe_single().execute()
        return res.data if res else None
    except Exception as err:
        logger.error("Error fetching job by hash %s: %s", content_hash, err)
        return None


def db_get_job(job_id: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
        return res.data if res else None
    except Exception as err:
        logger.error("Error fetching job %s: %s", job_id, err)
        return None


def db_upsert_job(job_id: str, content_hash: str, source: str, raw: str, title: str | None = None, company: str | None = None, location: str | None = None, normalized: dict[str, Any] | None = None) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        row: dict[str, Any] = {
            "id": job_id,
            "content_hash": content_hash,
            "source": source,
            "raw": raw,
        }
        if title:
            row["title"] = title
        if company:
            row["company"] = company
        if location:
            row["location"] = location
        if normalized:
            row["normalized"] = normalized

        client.table("jobs").upsert(row).execute()
        return True
    except Exception as err:
        logger.error("Error upserting job %s: %s", job_id, err)
        return False


# ============================================================================
# Resume Persistence
# ============================================================================

def db_get_resume(resume_id: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("resumes").select("*").eq("id", resume_id).maybe_single().execute()
        return res.data if res else None
    except Exception as err:
        logger.error("Error fetching resume %s: %s", resume_id, err)
        return None


def db_upsert_resume(resume_id: str, filename: str, content_type: str, size_bytes: int, raw_text: str | None = None, normalized: dict[str, Any] | None = None) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        row: dict[str, Any] = {
            "id": resume_id,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
        }
        if raw_text is not None:
            row["raw_text"] = raw_text
        if normalized is not None:
            row["normalized"] = normalized

        client.table("resumes").upsert(row).execute()
        return True
    except Exception as err:
        logger.error("Error upserting resume %s: %s", resume_id, err)
        return False


# ============================================================================
# Analysis Persistence
# ============================================================================

def db_create_analysis(analysis_id: str, resume_id: str, job_id: str, country: str, status: str = "queued") -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        row = {
            "id": analysis_id,
            "resume_id": resume_id,
            "job_id": job_id,
            "country": country,
            "status": status,
        }
        client.table("analyses").upsert(row).execute()
        return True
    except Exception as err:
        logger.error("Error creating analysis %s in db: %s", analysis_id, err)
        return False


def db_update_analysis_stage(analysis_id: str, stage: str | None = None, status: str | None = None, match_data: dict[str, Any] | None = None, error_message: str | None = None) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        row: dict[str, Any] = {}
        if stage is not None:
            row["stage"] = stage
        if status is not None:
            row["status"] = status
        if match_data is not None:
            row["match"] = match_data
        if error_message is not None:
            row["error_message"] = error_message

        if row:
            client.table("analyses").update(row).eq("id", analysis_id).execute()
        return True
    except Exception as err:
        logger.error("Error updating analysis %s in db: %s", analysis_id, err)
        return False


def db_get_analysis(analysis_id: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("analyses").select("*").eq("id", analysis_id).maybe_single().execute()
        return res.data if res else None
    except Exception as err:
        logger.error("Error fetching analysis %s: %s", analysis_id, err)
        return None


def db_list_analyses(resume_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if not client:
        return []
    try:
        query = client.table("analyses").select("*").order("created_at", desc=True).limit(limit)
        if resume_id:
            query = query.eq("resume_id", resume_id)
        res = query.execute()
        return res.data or []
    except Exception as err:
        logger.error("Error listing analyses: %s", err)
        return []


# ============================================================================
# Requirements & Evidence Embeddings (pgvector)
# ============================================================================

def db_save_jd_requirements(jd_id: str, jd_hash: str, requirements: list[dict[str, Any]], embeddings: dict[str, list[float]]) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        rows = [
            {
                "jd_id": jd_id,
                "jd_hash": jd_hash,
                "req_id": req.get("id"),
                "category": req.get("category", "hard_skill"),
                "is_required": (req.get("priority") == "required"),
                "description": req.get("text", ""),
                "canonical_skill": req.get("normalized_skill"),
                "embedding": embeddings.get(req.get("id")),
            }
            for req in requirements
            if req.get("id") and embeddings.get(req.get("id"))
        ]
        if rows:
            client.table("jd_requirements").upsert(rows).execute()
        return True
    except Exception as err:
        logger.error("Error saving jd requirements for %s: %s", jd_id, err)
        return False


def db_save_resume_evidence(resume_id: str, evidence: list[dict[str, Any]], embeddings: dict[str, list[float]]) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        rows = [
            {
                "resume_id": resume_id,
                "evidence_id": ev.get("id"),
                "evidence_type": ev.get("evidence_type", "project"),
                "description": ev.get("source_line", ""),
                "duration_months": ev.get("duration_months") or 0,
                "team_size": ev.get("team_size"),
                "outcome": ev.get("outcome"),
                "embedding": embeddings.get(ev.get("id")),
            }
            for ev in evidence
            if ev.get("id") and embeddings.get(ev.get("id"))
        ]
        if rows:
            client.table("resume_evidence").upsert(rows).execute()
        return True
    except Exception as err:
        logger.error("Error saving resume evidence for %s: %s", resume_id, err)
        return False
