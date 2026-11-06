"""Billing service: checkout sessions, idempotent plan granting, status polling, and usage.

Concurrency & Persistence Model
-------------------------------
1. **Multi-Worker Persistent Mode** (`get_supabase_client() is not None`):
   Quota checking, reservation creation, completion (`commit`), and cancellation (`release`)
   are coordinated across all server processes / worker instances through atomic PostgreSQL
   RPCs (`reserve_user_quota`, `commit_usage_reservation`, `release_usage_reservation`) using
   transactional advisory locks (`pg_advisory_xact_lock`) and row-level locking (`FOR UPDATE`).
   When database persistence is configured, any database error during quota check or
   reservation raises `DatabasePersistenceError` (failing closed) and NEVER falls back to
   process-local memory.

2. **Single-Process Fallback Mode** (`get_supabase_client() is None`):
   Used only in `ENGINE_MODE=mock` or offline local development without Supabase credentials.
   Synchronizes requests within a single Python OS process using `_reservations_lock`
   (`threading.RLock`). Multi-worker deployments MUST configure Supabase persistence.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from api.billing.plans import PLANS, PlanId
from api.billing.providers.base import BillingProvider
from api.billing.providers.mock import MockProvider
from api.billing.providers.stripe_sandbox import StripeSandboxProvider
from api.config import settings
from api.db import (
    DatabasePersistenceError,
    db_billing_rpc,
    db_commit_usage_reservation,
    db_release_usage_reservation,
    db_reserve_user_quota,
    get_supabase_client,
)

logger = logging.getLogger(__name__)


class UsageBucket(BaseModel):
    used: int
    limit: int | None


class UsageSummary(BaseModel):
    analysis: UsageBucket
    rewrite: UsageBucket


class SubscriptionOut(BaseModel):
    plan_id: PlanId
    active_until: datetime | None = None
    usage: UsageSummary


class CheckoutCreateIn(BaseModel):
    plan_id: str


class CheckoutCreatedOut(BaseModel):
    session_id: str
    provider: Literal["stripe_sandbox", "mock"]
    amount_cents: int
    currency: str
    expires_at: datetime
    checkout_url: str | None = None


class CheckoutStatusOut(BaseModel):
    session_id: str
    provider: Literal["stripe_sandbox", "mock"]
    provider_ref: str | None = None
    plan_id: str
    amount_cents: int
    currency: str
    status: Literal["pending", "paid", "expired", "canceled"]
    expires_at: datetime
    paid_at: datetime | None = None
    active_until: datetime | None = None


@dataclass
class CheckoutSessionRecord:
    id: str
    user_id: str
    plan_id: Literal["pass"]
    amount_cents: int
    currency: str
    status: Literal["pending", "paid", "expired", "canceled"]
    provider: Literal["stripe_sandbox", "mock"]
    provider_ref: str | None = None
    checkout_url: str | None = None
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )
    paid_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status_refresh_after: datetime | None = None
    status_refresh_until: datetime | None = None
    status_refresh_token: str | None = None
    status_refresh_error: bool = False


@dataclass
class SubscriptionRecord:
    id: str
    user_id: str
    plan_id: Literal["pass", "campus"]
    current_period_start: datetime
    current_period_end: datetime
    provider: str = "mock"
    checkout_session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class UsageEventRecord:
    user_id: str
    kind: Literal["analysis", "rewrite"]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class UsageReservationRecord:
    id: str
    user_id: str
    kind: Literal["analysis", "rewrite"]
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10)
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# In-memory store for single-process tests and offline fallback (when get_supabase_client() is None)
_checkout_sessions: dict[str, CheckoutSessionRecord] = {}
_subscriptions: list[SubscriptionRecord] = []
_usage_events: list[UsageEventRecord] = []
_usage_reservations: dict[str, UsageReservationRecord] = {}
_finalized_reservations: dict[str, Literal["committed", "released"]] = {}
_reservations_lock = threading.RLock()
_stripe_events: set[str] = set()


def reset_billing_memory() -> None:
    """Clear in-memory billing state (used by test fixtures)."""
    with _reservations_lock:
        _checkout_sessions.clear()
        _subscriptions.clear()
        _usage_events.clear()
        _usage_reservations.clear()
        _finalized_reservations.clear()
        _stripe_events.clear()


def get_active_provider() -> BillingProvider:
    if settings.billing_provider == "stripe_sandbox":
        return StripeSandboxProvider()
    return MockProvider()


def set_test_subscription(
    user_id: str,
    plan_id: Literal["pass", "campus"] = "pass",
    active_until: datetime | None = None,
    active_from: datetime | None = None,
    checkout_session_id: str | None = None,
) -> SubscriptionRecord:
    """Helper to seed an active subscription in memory (and shared DB if configured) for tests."""
    now = datetime.now(UTC)
    rec = SubscriptionRecord(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_id=plan_id,
        current_period_start=active_from or now,
        current_period_end=active_until or (now + timedelta(days=30)),
        provider="mock",
        checkout_session_id=checkout_session_id,
    )
    _subscriptions.append(rec)
    client = get_supabase_client()
    if client is not None:
        with contextlib.suppress(Exception):
            client.table("subscriptions").insert(
                {
                    "id": rec.id,
                    "user_id": rec.user_id,
                    "plan_id": rec.plan_id,
                    "current_period_start": rec.current_period_start.isoformat(),
                    "current_period_end": rec.current_period_end.isoformat(),
                    "provider": rec.provider,
                    "checkout_session_id": rec.checkout_session_id,
                    "created_at": rec.created_at.isoformat(),
                }
            ).execute()
    return rec


def get_test_subscriptions_for_user(user_id: str) -> list[SubscriptionRecord]:
    return [s for s in _subscriptions if s.user_id == user_id]


def _get_subscription_for_user(user_id: str, *, include_future: bool = False) -> SubscriptionRecord | None:
    now = datetime.now(UTC)
    client = get_supabase_client()
    if client is not None:
        try:
            query = (
                client.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .gt("current_period_end", now.isoformat())
            )
            if not include_future:
                query = query.lte("current_period_start", now.isoformat())
            res = query.order("current_period_end", desc=True).limit(1).execute()
            if res.data:
                return _row_to_subscription(res.data[0])
            return None
        except Exception:
            raise DatabasePersistenceError("Subscription lookup failed.") from None

    active = [
        s
        for s in _subscriptions
        if s.user_id == user_id and s.current_period_end > now
        and (include_future or s.current_period_start <= now)
    ]
    if not active:
        return None
    active.sort(key=lambda s: s.current_period_end, reverse=True)
    return active[0]


def _get_active_subscription_for_user(user_id: str) -> SubscriptionRecord | None:
    return _get_subscription_for_user(user_id)


def _get_latest_subscription_for_user(user_id: str) -> SubscriptionRecord | None:
    """Include queued renewals when scheduling another paid pass or showing expiry."""
    return _get_subscription_for_user(user_id, include_future=True)


def _row_to_subscription(row: dict) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=str(row["id"]), user_id=str(row["user_id"]), plan_id=row["plan_id"],
        current_period_start=datetime.fromisoformat(row["current_period_start"]),
        current_period_end=datetime.fromisoformat(row["current_period_end"]),
        provider=row.get("provider", "mock"), checkout_session_id=row.get("checkout_session_id"),
    )


def _count_usage(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
    since: datetime,
) -> int:
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("usage_events")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("kind", kind)
                .gte("created_at", since.isoformat())
                .execute()
            )
            if res.count is not None:
                return int(res.count)
            return len(res.data or [])
        except Exception:
            raise DatabasePersistenceError("Usage count query failed.") from None

    return sum(
        1
        for ev in _usage_events
        if ev.user_id == user_id and ev.kind == kind and ev.created_at >= since
    )


def record_usage_event(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
) -> None:
    """Record a usage event after a successful analysis or rewrite."""
    now = datetime.now(UTC)
    client = get_supabase_client()
    if client is not None:
        try:
            client.table("usage_events").insert(
                {
                    "user_id": user_id,
                    "kind": kind,
                    "created_at": now.isoformat(),
                }
            ).execute()
        except Exception:
            raise DatabasePersistenceError("Usage recording failed.") from None
        return

    with _reservations_lock:
        _usage_events.append(UsageEventRecord(user_id=user_id, kind=kind, created_at=now))


def _clean_expired_reservations() -> None:
    now = datetime.now(UTC)
    expired = [rid for rid, r in _usage_reservations.items() if r.expires_at <= now]
    for rid in expired:
        _usage_reservations.pop(rid, None)
        if _finalized_reservations.get(rid) != "committed":
            _finalized_reservations[rid] = "released"


def _count_active_reservations(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
    since: datetime | None = None,
) -> int:
    now = datetime.now(UTC)
    client = get_supabase_client()
    if client is not None:
        try:
            query = (
                client.table("usage_reservations")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("kind", kind)
                .eq("status", "active")
                .gt("expires_at", now.isoformat())
            )
            if since is not None:
                query = query.gte("created_at", since.isoformat())
            res = query.execute()
            if res.count is not None:
                return int(res.count)
            return len(res.data or [])
        except Exception:
            raise DatabasePersistenceError("Active reservation count failed.") from None

    with _reservations_lock:
        _clean_expired_reservations()
        return sum(
            1
            for r in _usage_reservations.values()
            if r.user_id == user_id
            and r.kind == kind
            and r.expires_at > now
            and (since is None or r.created_at >= since)
        )


def get_user_quota_window_and_limit(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
) -> tuple[PlanId, int | None, datetime]:
    """Return `(plan_id, limit, window_start)` for `user_id` and `kind`."""
    now = datetime.now(UTC)
    active_sub = _get_active_subscription_for_user(user_id)
    if active_sub is not None:
        plan_id: PlanId = active_sub.plan_id
        window_start = active_sub.current_period_start
    else:
        plan_id = "free"
        window_start = now - timedelta(days=30)

    plan_def = PLANS[plan_id]
    limit = plan_def.limits.analyses if kind == "analysis" else plan_def.limits.rewrites
    return plan_id, limit, window_start


def atomic_reserve_quota(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
    reservation_id: str | None = None,
) -> tuple[bool, str, int | None]:
    """Atomically verify quota and reserve a slot across workers (when DB is active)
    or under the single-process lock (when running in offline fallback mode).

    Returns `(allowed, reservation_id, limit)`.
    Raises `DatabasePersistenceError` if persistence is configured and fails.
    """
    rid = reservation_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    ttl_seconds = max(1.0, float(settings.reservation_ttl_seconds))
    expires = now + timedelta(seconds=ttl_seconds)

    _plan_id, limit, window_start = get_user_quota_window_and_limit(user_id, kind)

    client = get_supabase_client()
    if client is not None:
        rpc_res = db_reserve_user_quota(
            user_id=user_id,
            kind=kind,
            reservation_id=rid,
            limit=limit,
            window_start_iso=window_start.isoformat(),
            expires_at_iso=expires.isoformat(),
        )
        allowed = bool(rpc_res.get("allowed", False))
        return allowed, rid, limit

    # Single-process fallback mode (documented: only when Supabase persistence is not configured)
    with _reservations_lock:
        _clean_expired_reservations()
        existing = _usage_reservations.get(rid)
        if existing is not None and existing.expires_at > now:
            return True, rid, limit

        used = _count_usage(user_id, kind, window_start) + _count_active_reservations(
            user_id, kind, window_start
        )
        if limit is not None and used >= limit:
            return False, rid, limit

        rec = UsageReservationRecord(
            id=rid,
            user_id=user_id,
            kind=kind,
            created_at=now,
            expires_at=expires,
        )
        _usage_reservations[rid] = rec
        _finalized_reservations.pop(rid, None)
        return True, rid, limit


def create_usage_reservation(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
    reservation_id: str | None = None,
) -> str:
    rid = reservation_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    ttl_seconds = max(1.0, float(settings.reservation_ttl_seconds))
    expires = now + timedelta(seconds=ttl_seconds)

    client = get_supabase_client()
    if client is not None:
        _plan_id, limit, window_start = get_user_quota_window_and_limit(user_id, kind)
        rpc_res = db_reserve_user_quota(
            user_id=user_id,
            kind=kind,
            reservation_id=rid,
            limit=limit,
            window_start_iso=window_start.isoformat(),
            expires_at_iso=expires.isoformat(),
        )
        if not rpc_res.get("allowed", False):
            raise DatabasePersistenceError(f"Reservation rejected by database: {rpc_res}")
        return rid

    rec = UsageReservationRecord(
        id=rid,
        user_id=user_id,
        kind=kind,
        created_at=now,
        expires_at=expires,
    )
    with _reservations_lock:
        _clean_expired_reservations()
        _usage_reservations[rid] = rec
        _finalized_reservations.pop(rid, None)
    return rid


def commit_usage_reservation(
    reservation_id: str | None,
    user_id: str | None,
    kind: Literal["analysis", "rewrite"],
) -> None:
    """Idempotently commit an in-flight reservation into a single permanent usage event."""
    client = get_supabase_client()
    if client is not None:
        db_commit_usage_reservation(reservation_id, user_id, kind)
        with _reservations_lock:
            if reservation_id:
                _usage_reservations.pop(reservation_id, None)
                _finalized_reservations[reservation_id] = "committed"
        return

    with _reservations_lock:
        _clean_expired_reservations()
        if reservation_id:
            state = _finalized_reservations.get(reservation_id)
            if state == "committed":
                return  # Idempotent: already committed
            if state == "released":
                return  # Already released: do not commit
            popped = _usage_reservations.pop(reservation_id, None)
            if popped is None:
                return
            _finalized_reservations[reservation_id] = "committed"
            target_user = user_id or popped.user_id
            if target_user:
                _usage_events.append(
                    UsageEventRecord(user_id=target_user, kind=kind, created_at=datetime.now(UTC))
                )
        elif user_id:
            _usage_events.append(
                UsageEventRecord(user_id=user_id, kind=kind, created_at=datetime.now(UTC))
            )


def release_usage_reservation(
    reservation_id: str | None,
    user_id: str | None,
    kind: Literal["analysis", "rewrite"],
) -> None:
    """Idempotently release an active reservation without recording usage."""
    client = get_supabase_client()
    if client is not None:
        if reservation_id:
            db_release_usage_reservation(reservation_id)
        with _reservations_lock:
            if reservation_id:
                _usage_reservations.pop(reservation_id, None)
                if _finalized_reservations.get(reservation_id) != "committed":
                    _finalized_reservations[reservation_id] = "released"
        return

    with _reservations_lock:
        if reservation_id:
            state = _finalized_reservations.get(reservation_id)
            if state == "committed":
                return  # Already committed: cannot release
            if state == "released":
                return  # Idempotent: already released
            _usage_reservations.pop(reservation_id, None)
            _finalized_reservations[reservation_id] = "released"


def get_subscription_summary(user_id: str) -> SubscriptionOut:
    """Return the user's active plan, expiry, and usage in the current window."""
    now = datetime.now(UTC)

    from api.auth import get_user_email
    from api.config import is_admin_email

    user_email = get_user_email(user_id)
    if is_admin_email(user_email):
        analysis_used = _count_usage(user_id, "analysis", now - timedelta(days=365))
        rewrite_used = _count_usage(user_id, "rewrite", now - timedelta(days=365))
        return SubscriptionOut(
            plan_id="campus",
            active_until=None,
            usage=UsageSummary(
                analysis=UsageBucket(used=analysis_used, limit=None),
                rewrite=UsageBucket(used=rewrite_used, limit=None),
            ),
        )

    active_sub = _get_active_subscription_for_user(user_id)

    if active_sub is not None:
        plan_id: PlanId = active_sub.plan_id
        active_until = active_sub.current_period_end
        window_start = active_sub.current_period_start
    else:
        plan_id = "free"
        active_until = None
        window_start = now - timedelta(days=30)

    plan_def = PLANS[plan_id]
    analysis_used = _count_usage(user_id, "analysis", window_start) + _count_active_reservations(user_id, "analysis", window_start)
    rewrite_used = _count_usage(user_id, "rewrite", window_start) + _count_active_reservations(user_id, "rewrite", window_start)

    return SubscriptionOut(
        plan_id=plan_id,
        active_until=active_until,
        usage=UsageSummary(
            analysis=UsageBucket(
                used=analysis_used,
                limit=plan_def.limits.analyses,
            ),
            rewrite=UsageBucket(
                used=rewrite_used,
                limit=plan_def.limits.rewrites,
            ),
        ),
    )


def _cache_checkout_session(rec: CheckoutSessionRecord, *, persisted: bool) -> None:
    """Bound the cache; offline pending sessions must not be evicted and recreated."""
    now = datetime.now(UTC)
    with _reservations_lock:
        stale = [sid for sid, old in _checkout_sessions.items()
                 if old.expires_at < now - timedelta(days=1)
                 and (persisted or old.status_refresh_until is None or old.status_refresh_until <= now)]
        for sid in stale:
            _checkout_sessions.pop(sid, None)
        cap = max(1, settings.checkout_cache_max_entries)
        while rec.id not in _checkout_sessions and len(_checkout_sessions) >= cap:
            evictable = [old for old in _checkout_sessions.values()
                         if persisted or ((old.status != "pending" or old.expires_at <= now)
                                          and (old.status_refresh_until is None or old.status_refresh_until <= now))]
            if not evictable:
                from api.errors import ApiError

                raise ApiError(429, "RATE_LIMITED", "Checkout is busy. Please try again later.")
            oldest = min(evictable, key=lambda item: item.created_at)
            _checkout_sessions.pop(oldest.id)
        _checkout_sessions[rec.id] = rec


def _save_checkout_session(rec: CheckoutSessionRecord) -> None:
    client = get_supabase_client()
    if client is not None:
        try:
            client.table("checkout_sessions").upsert(
                {
                    "id": rec.id,
                    "user_id": rec.user_id,
                    "plan_id": rec.plan_id,
                    "amount_cents": rec.amount_cents,
                    "currency": rec.currency,
                    "status": rec.status,
                    "provider": rec.provider,
                    "provider_ref": rec.provider_ref,
                    "checkout_url": rec.checkout_url,
                    "expires_at": rec.expires_at.isoformat(),
                    "paid_at": rec.paid_at.isoformat() if rec.paid_at else None,
                    "created_at": rec.created_at.isoformat(),
                }
            ).execute()
        except Exception:
            raise DatabasePersistenceError("Checkout persistence failed.") from None
    _cache_checkout_session(rec, persisted=client is not None)


def _load_checkout_session_by_id(session_id: str) -> CheckoutSessionRecord | None:
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("checkout_sessions")
                .select("*")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return _row_to_checkout_session(res.data[0])
        except Exception:
            raise DatabasePersistenceError("Checkout lookup failed.") from None
        return None
    with _reservations_lock:
        return _checkout_sessions.get(session_id)


def _load_checkout_session_by_ref(provider_ref: str) -> CheckoutSessionRecord | None:
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("checkout_sessions")
                .select("*")
                .eq("provider_ref", provider_ref)
                .limit(1)
                .execute()
            )
            if res.data:
                return _row_to_checkout_session(res.data[0])
        except Exception:
            raise DatabasePersistenceError("Checkout lookup failed.") from None
        return None
    with _reservations_lock:
        for rec in _checkout_sessions.values():
            if rec.provider_ref == provider_ref:
                return rec
    return None


def _row_to_checkout_session(row: dict, *, cache: bool = True) -> CheckoutSessionRecord:
    rec = CheckoutSessionRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        plan_id=row["plan_id"],
        amount_cents=int(row["amount_cents"]),
        currency=str(row["currency"]),
        status=row["status"],
        provider=row["provider"],
        provider_ref=row.get("provider_ref"),
        checkout_url=row.get("checkout_url"),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        paid_at=datetime.fromisoformat(row["paid_at"]) if row.get("paid_at") else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        status_refresh_after=datetime.fromisoformat(row["status_refresh_after"]) if row.get("status_refresh_after") else None,
        status_refresh_until=datetime.fromisoformat(row["status_refresh_until"]) if row.get("status_refresh_until") else None,
        status_refresh_token=row.get("status_refresh_token"),
        status_refresh_error=row.get("status_refresh_error", False),
    )
    if cache:
        _cache_checkout_session(rec, persisted=True)
    return rec


def grant_plan(session: CheckoutSessionRecord) -> SubscriptionRecord:
    """Grant once, queuing early renewals after all previously purchased passes."""
    if session.status != "paid":
        raise DatabasePersistenceError("Cannot grant an unpaid checkout.")
    client = get_supabase_client()
    if client is not None:
        result = db_billing_rpc("grant_checkout_pass", {
            "p_session_id": session.id,
            "p_period_days": PLANS[session.plan_id].period_days,
        })
        try:
            sub = _row_to_subscription(result["subscription"])
            if sub.user_id != session.user_id or sub.checkout_session_id != session.id:
                raise ValueError("Wrong subscription owner")
        except Exception:
            raise DatabasePersistenceError("Invalid subscription grant response.") from None
        return sub

    with _reservations_lock:
        for existing in _subscriptions:
            if existing.checkout_session_id == session.id:
                return existing
        now = datetime.now(UTC)
        latest = _get_latest_subscription_for_user(session.user_id)
        period_start = max(now, latest.current_period_end) if latest else now
        sub = SubscriptionRecord(
            id=str(uuid.uuid4()), user_id=session.user_id, plan_id=session.plan_id,
            current_period_start=period_start,
            current_period_end=period_start + timedelta(days=PLANS[session.plan_id].period_days),
            provider=session.provider, checkout_session_id=session.id, created_at=now,
        )
        _subscriptions.append(sub)
        return sub


def _reserve_checkout_session(
    user_id: str, provider: Literal["mock", "stripe_sandbox"],
) -> tuple[CheckoutSessionRecord, bool]:
    """Atomically reuse a pending checkout, or claim creation before provider I/O."""
    amount = PLANS["pass"].price_cents
    assert amount is not None
    rec = CheckoutSessionRecord(
        id=str(uuid.uuid4()), user_id=user_id, plan_id="pass", status="pending",
        amount_cents=amount, currency=PLANS["pass"].currency,
        provider=provider,
    )
    if get_supabase_client() is not None:
        result = db_billing_rpc("reserve_checkout_session", {
            "p_session_id": rec.id, "p_user_id": user_id, "p_provider": provider,
            "p_amount_cents": rec.amount_cents, "p_currency": rec.currency,
        })
        try:
            if not isinstance(result["created"], bool):
                raise ValueError("Invalid creation result")
            reserved = _row_to_checkout_session(result["session"], cache=False)
            if reserved.user_id != user_id or reserved.provider != provider or reserved.plan_id != "pass":
                raise ValueError("Invalid checkout owner")
        except Exception:
            raise DatabasePersistenceError("Invalid checkout reservation response.") from None
        _cache_checkout_session(reserved, persisted=True)
        return reserved, result["created"]

    with _reservations_lock:
        now = datetime.now(UTC)
        for old in _checkout_sessions.values():
            if (old.user_id == user_id and old.provider == provider
                    and old.status == "pending" and old.expires_at > now):
                return old, False
        _cache_checkout_session(rec, persisted=False)
        return rec, True


def create_checkout(
    user_id: str,
    user_email: str,
    plan_id: str,
) -> CheckoutCreatedOut:
    """Create a pending checkout session for `pass` through the active provider."""
    if plan_id != "pass":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_plan",
                "message": "Only the 'pass' plan can be purchased via self-serve checkout.",
            },
        )

    from api.errors import ApiError
    from api.limiter import enforce_operation_attempt_limit

    enforce_operation_attempt_limit("checkout", f"user:{user_id}", settings.checkout_attempts_per_hour)
    provider = get_active_provider()
    rec, claimed = _reserve_checkout_session(user_id, provider.name)
    if not claimed and rec.provider_ref is None:
        raise HTTPException(409, detail={"code": "checkout_in_progress", "message": "Your checkout is being prepared. Please try again shortly."})
    if claimed:
        try:
            created = provider.create_session(
                checkout_session_id=rec.id, user_id=user_id, user_email=user_email,
                plan_id="pass", plan_name=PLANS["pass"].name,
                amount_cents=rec.amount_cents, currency=rec.currency,
            )
        except Exception:
            rec = replace(rec, status="canceled")
            _save_checkout_session(rec)
            raise ApiError(503, "SERVICE_UNAVAILABLE", "Payment service unavailable. Please try again later.") from None
        rec = replace(rec, provider_ref=created["provider_ref"], checkout_url=created["checkout_url"],
                      expires_at=created["expires_at"])
        _save_checkout_session(rec)

    return CheckoutCreatedOut(
        session_id=rec.id,
        provider=rec.provider,
        amount_cents=rec.amount_cents,
        currency=rec.currency,
        expires_at=rec.expires_at,
        checkout_url=rec.checkout_url,
    )


def _status_rpc_result(result: dict, expected: CheckoutSessionRecord) -> tuple[CheckoutSessionRecord, bool, bool]:
    """Reject malformed coordination responses rather than bypassing protection."""
    try:
        if not isinstance(result["refresh"], bool) or not isinstance(result["provider_error"], bool):
            raise ValueError("Invalid refresh result")
        rec = _row_to_checkout_session(result["session"], cache=False)
        if (rec.id != expected.id or rec.user_id != expected.user_id
                or rec.provider != expected.provider or rec.provider_ref != expected.provider_ref
                or rec.status not in ("pending", "paid", "expired", "canceled")
                or (result["refresh"] and (rec.status != "pending" or rec.provider != "stripe_sandbox" or not rec.provider_ref))):
            raise ValueError("Wrong checkout")
    except Exception:
        raise DatabasePersistenceError("Invalid checkout status response.") from None
    _cache_checkout_session(rec, persisted=True)
    return rec, result["refresh"], result["provider_error"]


def _claim_status_refresh(rec: CheckoutSessionRecord, token: str) -> tuple[CheckoutSessionRecord, bool, bool]:
    # Allow connect + read timeouts and scheduling margin before abandoned-claim recovery.
    lease_seconds = 2 * settings.checkout_status_provider_timeout_seconds + 30
    if get_supabase_client() is not None:
        current, refresh, provider_error = _status_rpc_result(db_billing_rpc("claim_checkout_status_refresh", {
            "p_session_id": rec.id, "p_user_id": rec.user_id,
            "p_token": token, "p_lease_seconds": lease_seconds,
        }), rec)
        if refresh and current.status_refresh_token != token:
            raise DatabasePersistenceError("Invalid checkout refresh claim.")
        return current, refresh, provider_error
    with _reservations_lock:
        current = _checkout_sessions.get(rec.id)
        if current is None or current.user_id != rec.user_id:
            raise DatabasePersistenceError("Checkout state unavailable.")
        now = datetime.now(UTC)
        leased = current.status_refresh_until is not None and current.status_refresh_until > now
        fresh = current.status_refresh_after is not None and current.status_refresh_after > now
        refresh = False
        if current.status == "pending":
            if current.provider == "stripe_sandbox" and current.provider_ref and not fresh and not leased:
                current.status_refresh_token = token
                current.status_refresh_until = now + timedelta(seconds=lease_seconds)
                current.status_refresh_error = False
                refresh = True
            elif current.expires_at <= now and not leased:
                current.status = "expired"
                current.status_refresh_error = False
        return replace(current), refresh, current.status == "pending" and current.status_refresh_error


def _finish_status_refresh(rec: CheckoutSessionRecord, token: str, status: str) -> tuple[CheckoutSessionRecord, bool, bool]:
    if get_supabase_client() is not None:
        current, refresh, provider_error = _status_rpc_result(db_billing_rpc("finish_checkout_status_refresh", {
            "p_session_id": rec.id, "p_user_id": rec.user_id, "p_token": token,
            "p_status": status, "p_cache_seconds": settings.checkout_status_cache_seconds,
        }), rec)
        if refresh:
            raise DatabasePersistenceError("Invalid checkout refresh completion.")
        return current, refresh, provider_error
    with _reservations_lock:
        current = _checkout_sessions.get(rec.id)
        if current is None or current.user_id != rec.user_id:
            raise DatabasePersistenceError("Checkout state unavailable.")
        now = datetime.now(UTC)
        if current.status_refresh_token == token:
            if current.status == "pending":
                if status == "paid":
                    current.status = "paid"
                    current.paid_at = current.paid_at or now
                elif status == "expired" or current.expires_at <= now:
                    current.status = "expired"
            current.status_refresh_after = now + timedelta(seconds=settings.checkout_status_cache_seconds)
            current.status_refresh_until = None
            current.status_refresh_token = None
            current.status_refresh_error = current.status == "pending" and status == "error"
        return replace(current), False, current.status == "pending" and current.status_refresh_error


def _refresh_and_serialize_session(rec: CheckoutSessionRecord) -> CheckoutStatusOut:
    from api.errors import ApiError

    token = str(uuid.uuid4())
    rec, refresh, provider_error = _claim_status_refresh(rec, token)
    if refresh:
        try:
            remote_status = StripeSandboxProvider().get_status(rec.provider_ref)
            if remote_status not in ("pending", "paid", "expired"):
                remote_status = "error"
        except Exception:
            remote_status = "error"
        # Persistence errors must propagate, including after a successful provider call.
        rec, _, provider_error = _finish_status_refresh(rec, token, remote_status)
    if provider_error:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Payment service unavailable. Please try again shortly.")

    # A paid status can have been saved before a transient grant failure.
    # The grant RPC is idempotent, so status polling can safely finish activation.
    if rec.status == "paid":
        grant_plan(rec)

    active_sub = _get_latest_subscription_for_user(rec.user_id)
    return CheckoutStatusOut(
        session_id=rec.id,
        provider=rec.provider,
        provider_ref=rec.provider_ref,
        plan_id=rec.plan_id,
        amount_cents=rec.amount_cents,
        currency=rec.currency,
        status=rec.status,
        expires_at=rec.expires_at,
        paid_at=rec.paid_at,
        active_until=active_sub.current_period_end if active_sub else None,
    )


def get_checkout_status(session_id: str, user_id: str) -> CheckoutStatusOut:
    from api.limiter import enforce_checkout_status_limit

    enforce_checkout_status_limit(user_id)
    rec = _load_checkout_session_by_id(session_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "checkout_not_found", "message": "Checkout session not found."},
        )
    return _refresh_and_serialize_session(rec)


def get_checkout_status_by_ref(provider_ref: str, user_id: str) -> CheckoutStatusOut:
    from api.limiter import enforce_checkout_status_limit

    enforce_checkout_status_limit(user_id)
    rec = _load_checkout_session_by_ref(provider_ref)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "checkout_not_found", "message": "Checkout session not found."},
        )
    return _refresh_and_serialize_session(rec)


def simulate_mock_payment(session_id: str, user_id: str) -> CheckoutStatusOut:
    """Mark a mock checkout session paid and grant the pass (mock provider only)."""
    if settings.billing_provider != "mock":
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Mock simulation is disabled."},
        )

    rec = _load_checkout_session_by_id(session_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "checkout_not_found", "message": "Checkout session not found."},
        )

    now = datetime.now(UTC)
    if rec.status == "pending" and now >= rec.expires_at:
        rec.status = "expired"
        _save_checkout_session(rec)
        raise HTTPException(
            status_code=400,
            detail={"code": "session_expired", "message": "Checkout session has expired."},
        )

    if rec.status != "paid":
        rec.status = "paid"
        rec.paid_at = now
        _save_checkout_session(rec)

    grant_plan(rec)
    return _refresh_and_serialize_session(rec)


def record_stripe_event_once(event_id: str, event_type: str) -> bool:
    """Return True if this Stripe event ID has not been processed yet."""
    if event_id in _stripe_events:
        return False

    client = get_supabase_client()
    if client is not None:
        try:
            existing = (
                client.table("stripe_events")
                .select("id")
                .eq("id", event_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                _stripe_events.add(event_id)
                return False
            client.table("stripe_events").insert(
                {
                    "id": event_id,
                    "type": event_type,
                    "received_at": datetime.now(UTC).isoformat(),
                }
            ).execute()
        except Exception:
            pass

    _stripe_events.add(event_id)
    return True


def handle_stripe_checkout_completed(
    provider_ref: str,
    metadata: dict[str, object] | None,
    amount_total: int | None,
) -> None:
    rec = _load_checkout_session_by_ref(provider_ref)
    if rec is None:
        return

    meta_user_id = str((metadata or {}).get("user_id") or "")
    if meta_user_id and meta_user_id != rec.user_id:
        return
    if amount_total is not None and int(amount_total) != rec.amount_cents:
        return

    now = datetime.now(UTC)
    if rec.status != "paid":
        rec.status = "paid"
        rec.paid_at = now
        _save_checkout_session(rec)

    grant_plan(rec)


def handle_stripe_checkout_expired(provider_ref: str) -> None:
    rec = _load_checkout_session_by_ref(provider_ref)
    if rec is None:
        return
    if rec.status == "pending":
        rec.status = "expired"
        _save_checkout_session(rec)
