"""Quota enforcement dependencies (`require_quota`) and usage recording (`record_usage`).

Multi-Worker Concurrency & Fallback
-----------------------------------
- When Supabase persistence is active (`get_supabase_client() is not None`), `reserve_quota`
  delegates to `atomic_reserve_quota`, which executes the PostgreSQL `reserve_user_quota`
  RPC under a transactional advisory lock (`pg_advisory_xact_lock`). Quota check and slot
  reservation occur in a single atomic database transaction across all workers.
- If persistence fails when configured, quota checks and reservations fail closed with
  HTTP 503 `SERVICE_UNAVAILABLE` rather than bypassing enforcement.
- When Supabase persistence is not configured (`ENGINE_MODE=mock` or offline local mode),
  `atomic_reserve_quota` falls back to process-local `threading.RLock` synchronization,
  which is supported for single-worker operation only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Depends, HTTPException

from api.auth import CurrentUser, get_optional_user, get_user_email
from api.billing.plans import PLANS
from api.billing.service import atomic_reserve_quota, get_subscription_summary
from api.config import is_admin_email, settings
from api.db import DatabasePersistenceError
from api.errors import ApiError

QuotaKind = Literal["analysis", "rewrite"]


def _raise_persistence_unavailable(exc: Exception) -> None:
    raise ApiError(
        status_code=503,
        code="SERVICE_UNAVAILABLE",
        message="Persistence service unavailable; cannot verify or reserve quota safely.",
    ) from exc


def check_quota(user_id: str, kind: QuotaKind) -> None:
    """Verify the user is within their plan quota for `kind`, or raise HTTP 402 (or 503 on DB error)."""
    if not settings.enforce_quotas:
        return

    # Superuser admin bypass: dydavid168@gmail.com has unlimited access
    if is_admin_email(get_user_email(user_id)):
        return

    try:
        summary = get_subscription_summary(user_id)
    except DatabasePersistenceError as exc:
        _raise_persistence_unavailable(exc)

    bucket = summary.usage.analysis if kind == "analysis" else summary.usage.rewrite
    if bucket.limit is not None and bucket.used >= bucket.limit:
        label = "analyses" if kind == "analysis" else "AI rewrites"
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "kind": kind,
                "limit": bucket.limit,
                "upgrade_url": "/pricing",
                "message": (
                    f"You have reached your limit of {bucket.limit} {label}. "
                    "Upgrade to the Job Hunt Pass for more."
                ),
            },
        )


def require_quota(kind: QuotaKind) -> Callable[[CurrentUser | None], None]:
    """FastAPI dependency enforcing quota on logged-in requests."""

    def _dependency(
        user: Annotated[CurrentUser | None, Depends(get_optional_user)],
    ) -> None:
        if user is not None:
            if user.is_admin:
                return
            check_quota(user.id, kind)

    return _dependency


def check_saved_resumes_quota(user_id: str, existing_count: int) -> None:
    """Verify the user has not exceeded their saved resumes limit, or raise HTTP 402."""
    if not settings.enforce_quotas:
        return

    if is_admin_email(get_user_email(user_id)):
        return

    try:
        summary = get_subscription_summary(user_id)
    except DatabasePersistenceError as exc:
        _raise_persistence_unavailable(exc)

    plan_def = PLANS[summary.plan_id]
    limit = plan_def.limits.saved_resumes
    if limit is not None and existing_count >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "kind": "saved_resumes",
                "limit": limit,
                "upgrade_url": "/pricing",
                "message": (
                    f"Your {plan_def.name} plan includes up to {limit} saved resume(s). "
                    "Upgrade to the Job Hunt Pass to save up to 10 resumes."
                ),
            },
        )


def record_usage(user_id: str | None, kind: QuotaKind) -> None:
    """Record a usage event after a successful analysis or rewrite."""
    if user_id:
        commit_quota(None, user_id, kind)


def reserve_quota(
    user_id: str,
    kind: QuotaKind,
    reservation_id: str | None = None,
    user: CurrentUser | None = None,
) -> str | None:
    """Atomically verify user quota and reserve a slot across workers (via DB RPC) or
    in-memory (single-worker fallback).
    Returns reservation_id on success, raises HTTP 402 if quota is exceeded, or fails
    closed with HTTP 503 if database persistence is configured and fails.
    Admin users bypass quota and return None.
    """
    if not settings.enforce_quotas:
        return None

    if (user is not None and user.is_admin) or is_admin_email(get_user_email(user_id)):
        return None

    try:
        allowed, rid, limit = atomic_reserve_quota(
            user_id, kind, reservation_id=reservation_id
        )
    except DatabasePersistenceError as exc:
        _raise_persistence_unavailable(exc)

    if not allowed:
        label = "analyses" if kind == "analysis" else "AI rewrites"
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "kind": kind,
                "limit": limit,
                "upgrade_url": "/pricing",
                "message": (
                    f"You have reached your limit of {limit} {label}. "
                    "Upgrade to the Job Hunt Pass for more."
                ),
            },
        )
    return rid


def commit_quota(
    reservation_id: str | None,
    user_id: str | None,
    kind: QuotaKind,
) -> None:
    """Commit an in-flight reservation into a permanent usage event."""
    from api.billing.service import commit_usage_reservation

    commit_usage_reservation(reservation_id, user_id, kind)


def release_quota(
    reservation_id: str | None,
    user_id: str | None,
    kind: QuotaKind,
) -> None:
    """Release an in-flight reservation without recording usage (e.g. on analysis failure)."""
    from api.billing.service import release_usage_reservation

    release_usage_reservation(reservation_id, user_id, kind)

