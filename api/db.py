"""Supabase database client and data persistence layer for Proofit.

Provides persistent storage for Resumes, Jobs, Analyses, and pgvector embeddings.
Only explicit mock/offline mode uses local state. Required persistence failures
raise safe errors rather than resetting enforcement to an empty local ledger.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any
from urllib.parse import urlsplit

from api.config import settings

logger = logging.getLogger(__name__)

_supabase_client = None
_supabase_client_config: tuple[str, str] | None = None
_client_lock = threading.RLock()


class DatabasePersistenceError(RuntimeError):
    """Raised when database persistence is configured and required for safety/enforcement,
    but a database operation fails. Callers must fail closed rather than bypassing limits."""


def _unwrap_rpc_result(res: Any, op_name: str) -> dict[str, Any]:
    """Normalize a Supabase PostgREST RPC response into a dict, or raise DatabasePersistenceError."""
    if res is None:
        raise DatabasePersistenceError(f"Empty RPC response from {op_name}")
    data = getattr(res, "data", None)
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        raise DatabasePersistenceError(f"Unexpected list RPC payload from {op_name}")
    if isinstance(data, dict):
        return data
    raise DatabasePersistenceError(f"Unexpected RPC payload from {op_name}")


def persistence_is_offline() -> bool:
    """Only explicit mock/offline operation may use process-local enforcement."""
    return settings.engine_mode == "mock" or settings.persistence_mode == "offline"


def validate_persistence_config() -> tuple[str, str] | None:
    """Validate required credentials without connecting or exposing their values."""
    if persistence_is_offline():
        return None
    url = (settings.supabase_url or os.getenv("SUPABASE_URL") or "").strip()
    key = (
        settings.supabase_service_key
        or settings.supabase_service_role_key
        or settings.supabase_key
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY") or ""
    ).strip()
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme in ("https", "http") and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and not any(c.isspace() for c in url)
        )
        _ = parsed.port
    except ValueError:
        valid_url = False
    if not valid_url or not key or "REPLACE_ME" in url or "REPLACE_ME" in key:
        raise DatabasePersistenceError("Required persistence configuration is missing or invalid.")
    return url, key


def get_supabase_client() -> Any | None:
    """Return None only for explicit offline mode; failures remain failures until recovery."""
    global _supabase_client, _supabase_client_config
    config = validate_persistence_config()
    if config is None:
        return None
    with _client_lock:
        if _supabase_client is not None and _supabase_client_config == config:
            return _supabase_client
        try:
            from supabase import create_client

            client = create_client(*config)
            if client is None:
                raise DatabasePersistenceError("Persistence client was not initialized.")
        except Exception:
            # SDK errors can contain credentials or full request URLs. Do not log them.
            logger.warning("Persistence client initialization failed.")
            raise DatabasePersistenceError("Persistence service is unavailable.") from None
        _supabase_client = client
        _supabase_client_config = config
        return client


def is_supabase_connected() -> bool:
    """Check if Supabase is reachable and responding."""
    try:
        client = get_supabase_client()
        if client is None:
            return False
        # Quick query on analyses or jobs table to verify connectivity
        res = client.table("analyses").select("id").limit(1).execute()
        return res is not None
    except Exception:
        logger.debug("Persistence connectivity check failed.")
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
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_get_job_by_hash.") from None


def db_get_job(job_id: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
        return res.data if res else None
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_get_job.") from None


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
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_upsert_job.") from None


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
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_get_resume.") from None


def db_upsert_resume(
    resume_id: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    raw_text: str | None = None,
    normalized: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> bool:
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
        if user_id is not None:
            row["user_id"] = user_id

        client.table("resumes").upsert(row).execute()
        return True
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_upsert_resume.") from None


# ============================================================================
# Analysis Persistence
# ============================================================================

def db_create_analysis(
    analysis_id: str,
    resume_id: str,
    job_id: str,
    country: str,
    status: str = "queued",
    user_id: str | None = None,
    reservation_id: str | None = None,
) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        row: dict[str, Any] = {
            "id": analysis_id,
            "resume_id": resume_id,
            "job_id": job_id,
            "country": country,
            "status": status,
        }
        if user_id is not None:
            row["user_id"] = user_id
        if reservation_id is not None:
            row["reservation_id"] = reservation_id
        client.table("analyses").upsert(row).execute()
        return True
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_create_analysis.") from None


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
        if status == "failed":
            row["match"] = None
        elif match_data is not None:
            row["match"] = match_data
        if error_message is not None:
            row["error_message"] = error_message

        if row:
            client.table("analyses").update(row).eq("id", analysis_id).execute()
        return True
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_update_analysis_stage.") from None


def db_get_analysis(analysis_id: str) -> dict[str, Any] | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("analyses").select("*").eq("id", analysis_id).maybe_single().execute()
        return res.data if res else None
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_get_analysis.") from None


def db_list_analyses(
    resume_id: str | None = None,
    limit: int = 50,
    ids: list[str] | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if not client:
        return []
    try:
        query = client.table("analyses").select("*").order("created_at", desc=True).limit(limit)
        if resume_id:
            query = query.eq("resume_id", resume_id)
        if user_id:
            query = query.eq("user_id", user_id)
        if ids is not None:
            if not ids:
                return []
            query = query.in_("id", ids)
        res = query.execute()
        return res.data or []
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_list_analyses.") from None


def db_get_guest_ip_last_used(ip_hash: str) -> str | None:
    client = get_supabase_client()
    if not client:
        return None
    try:
        res = client.table("guest_ip_usage").select("last_analysis_at").eq("ip_hash", ip_hash).maybe_single().execute()
        if res and res.data:
            return res.data.get("last_analysis_at")
        return None
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_get_guest_ip_last_used.") from None


def db_record_guest_ip_usage(ip_hash: str, timestamp_iso: str) -> bool:
    client = get_supabase_client()
    if not client:
        return False
    try:
        client.table("guest_ip_usage").upsert({
            "ip_hash": ip_hash,
            "last_analysis_at": timestamp_iso,
        }).execute()
        return True
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_record_guest_ip_usage.") from None


# ============================================================================
# Atomic Multi-Worker Concurrency & Quota RPCs (Phase 4)
# ============================================================================

def db_reserve_analysis_attempt(subject: str, limit: int) -> bool:
    """Consume a non-refundable attempt atomically across database-backed workers."""
    client = get_supabase_client()
    if client is None:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "reserve_analysis_attempt", {"p_subject": subject, "p_limit": limit}
        ).execute()
        data = _unwrap_rpc_result(res, "reserve_analysis_attempt")
        if not isinstance(data.get("allowed"), bool):
            raise DatabasePersistenceError("Invalid analysis attempt response.")
        return data["allowed"] is True
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_reserve_analysis_attempt.") from None


def db_reserve_user_quota(
    user_id: str,
    kind: str,
    reservation_id: str,
    limit: int | None,
    window_start_iso: str,
    expires_at_iso: str,
) -> dict[str, Any]:
    """Atomically check and reserve a quota slot in PostgreSQL across workers."""
    client = get_supabase_client()
    if not client:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "reserve_user_quota",
            {
                "p_user_id": user_id,
                "p_kind": kind,
                "p_reservation_id": reservation_id,
                "p_limit": limit,
                "p_window_start": window_start_iso,
                "p_expires_at": expires_at_iso,
            },
        ).execute()
        return _unwrap_rpc_result(res, "reserve_user_quota")
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_reserve_user_quota.") from None


def db_commit_usage_reservation(
    reservation_id: str | None,
    user_id: str | None,
    kind: str,
) -> dict[str, Any]:
    """Idempotently transition an active reservation to committed and record one usage_event."""
    client = get_supabase_client()
    if not client:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "commit_usage_reservation",
            {
                "p_reservation_id": reservation_id,
                "p_user_id": user_id,
                "p_kind": kind,
            },
        ).execute()
        return _unwrap_rpc_result(res, "commit_usage_reservation")
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_commit_usage_reservation.") from None


def db_release_usage_reservation(reservation_id: str | None) -> dict[str, Any]:
    """Idempotently release an active reservation without recording usage."""
    client = get_supabase_client()
    if not client:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "release_usage_reservation",
            {"p_reservation_id": reservation_id},
        ).execute()
        return _unwrap_rpc_result(res, "release_usage_reservation")
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_release_usage_reservation.") from None


def db_claim_analysis_retry(
    original_id: str,
    child_id: str,
    resume_id: str,
    job_id: str,
    country: str,
    user_id: str | None = None,
    reservation_id: str | None = None,
    abandoned_seconds: int = 600,
) -> dict[str, Any]:
    """Atomically claim an analysis retry in PostgreSQL and recover abandoned in-flight work."""
    client = get_supabase_client()
    if not client:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "claim_analysis_retry",
            {
                "p_original_id": original_id,
                "p_child_id": child_id,
                "p_resume_id": resume_id,
                "p_job_id": job_id,
                "p_country": country,
                "p_user_id": user_id,
                "p_reservation_id": reservation_id,
                "p_abandoned_seconds": max(1, int(abandoned_seconds)),
            },
        ).execute()
        return _unwrap_rpc_result(res, "claim_analysis_retry")
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_claim_analysis_retry.") from None


def db_reserve_guest_usage(ip_hash: str, ttl_hours: float = 24.0) -> dict[str, Any]:
    """Atomically check and reserve guest IP usage across workers."""
    client = get_supabase_client()
    if not client:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "reserve_guest_usage",
            {
                "p_ip_hash": ip_hash,
                "p_ttl_hours": float(ttl_hours),
            },
        ).execute()
        return _unwrap_rpc_result(res, "reserve_guest_usage")
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_reserve_guest_usage.") from None


def db_release_guest_usage(
    ip_hash: str,
    prev_last_analysis_at_iso: str | None = None,
) -> dict[str, Any]:
    """Atomically release or rollback guest IP usage in PostgreSQL."""
    client = get_supabase_client()
    if not client:
        raise DatabasePersistenceError("Supabase client is not initialized.")
    try:
        res = client.rpc(
            "release_guest_usage",
            {
                "p_ip_hash": ip_hash,
                "p_prev_last_analysis_at": prev_last_analysis_at_iso,
            },
        ).execute()
        return _unwrap_rpc_result(res, "release_guest_usage")
    except DatabasePersistenceError:
        raise
    except Exception:
        raise DatabasePersistenceError("Persistence operation failed: db_release_guest_usage.") from None


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
    except Exception:
        logger.warning("Optional embedding persistence failed.")
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
    except Exception:
        logger.warning("Optional embedding persistence failed.")
        return False
