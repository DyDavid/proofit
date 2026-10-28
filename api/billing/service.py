"""Billing service: checkout sessions, idempotent plan granting, status polling, and usage."""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from api.billing.plans import PLANS, PlanId
from api.billing.providers.base import BillingProvider
from api.billing.providers.mock import MockProvider
from api.billing.providers.stripe_sandbox import StripeSandboxProvider
from api.config import settings
from api.db import get_supabase_client


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


# In-memory store for tests and offline fallback
_checkout_sessions: dict[str, CheckoutSessionRecord] = {}
_subscriptions: list[SubscriptionRecord] = []
_usage_events: list[UsageEventRecord] = []
_stripe_events: set[str] = set()


def reset_billing_memory() -> None:
    """Clear in-memory billing state (used by test fixtures)."""
    _checkout_sessions.clear()
    _subscriptions.clear()
    _usage_events.clear()
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
    """Helper to seed an active subscription in memory for tests."""
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
    return rec


def get_test_subscriptions_for_user(user_id: str) -> list[SubscriptionRecord]:
    return [s for s in _subscriptions if s.user_id == user_id]


def _get_active_subscription_for_user(user_id: str) -> SubscriptionRecord | None:
    now = datetime.now(UTC)
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .gt("current_period_end", now.isoformat())
                .order("current_period_end", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                return SubscriptionRecord(
                    id=str(row["id"]),
                    user_id=str(row["user_id"]),
                    plan_id=row["plan_id"],
                    current_period_start=datetime.fromisoformat(row["current_period_start"]),
                    current_period_end=datetime.fromisoformat(row["current_period_end"]),
                    provider=row.get("provider", "mock"),
                    checkout_session_id=row.get("checkout_session_id"),
                )
        except Exception:
            pass

    active = [
        s
        for s in _subscriptions
        if s.user_id == user_id and s.current_period_end > now
    ]
    if not active:
        return None
    active.sort(key=lambda s: s.current_period_end, reverse=True)
    return active[0]


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
        except Exception:
            pass

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
    _usage_events.append(UsageEventRecord(user_id=user_id, kind=kind, created_at=now))
    client = get_supabase_client()
    if client is not None:
        with contextlib.suppress(Exception):
            client.table("usage_events").insert(
                {
                    "user_id": user_id,
                    "kind": kind,
                    "created_at": now.isoformat(),
                }
            ).execute()


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
    analysis_used = _count_usage(user_id, "analysis", window_start)
    rewrite_used = _count_usage(user_id, "rewrite", window_start)

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


def _save_checkout_session(rec: CheckoutSessionRecord) -> None:
    _checkout_sessions[rec.id] = rec
    client = get_supabase_client()
    if client is not None:
        with contextlib.suppress(Exception):
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


def _load_checkout_session_by_id(session_id: str) -> CheckoutSessionRecord | None:
    if session_id in _checkout_sessions:
        return _checkout_sessions[session_id]
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
            pass
    return None


def _load_checkout_session_by_ref(provider_ref: str) -> CheckoutSessionRecord | None:
    for rec in _checkout_sessions.values():
        if rec.provider_ref == provider_ref:
            return rec
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
            pass
    return None


def _row_to_checkout_session(row: dict) -> CheckoutSessionRecord:
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
    )
    _checkout_sessions[rec.id] = rec
    return rec


def grant_plan(session: CheckoutSessionRecord) -> SubscriptionRecord:
    """Idempotently grant a pass for a paid checkout session.

    If a subscription already exists for `session.id`, returns it without
    creating a duplicate. If the user already has an active pass, extends
    from `max(now, latest active current_period_end)` + 30 days.
    """
    for existing in _subscriptions:
        if existing.checkout_session_id == session.id:
            return existing

    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("subscriptions")
                .select("*")
                .eq("checkout_session_id", session.id)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                found = SubscriptionRecord(
                    id=str(row["id"]),
                    user_id=str(row["user_id"]),
                    plan_id=row["plan_id"],
                    current_period_start=datetime.fromisoformat(row["current_period_start"]),
                    current_period_end=datetime.fromisoformat(row["current_period_end"]),
                    provider=row.get("provider", session.provider),
                    checkout_session_id=str(row["checkout_session_id"]),
                )
                _subscriptions.append(found)
                return found
        except Exception:
            pass

    now = datetime.now(UTC)
    latest_active = _get_active_subscription_for_user(session.user_id)
    if latest_active is not None and latest_active.current_period_end > now:
        period_start = latest_active.current_period_end
    else:
        period_start = now

    period_days = PLANS[session.plan_id].period_days
    period_end = period_start + timedelta(days=period_days)

    sub = SubscriptionRecord(
        id=str(uuid.uuid4()),
        user_id=session.user_id,
        plan_id=session.plan_id,
        current_period_start=period_start,
        current_period_end=period_end,
        provider=session.provider,
        checkout_session_id=session.id,
        created_at=now,
    )
    _subscriptions.append(sub)

    if client is not None:
        with contextlib.suppress(Exception):
            client.table("subscriptions").insert(
                {
                    "id": sub.id,
                    "user_id": sub.user_id,
                    "plan_id": sub.plan_id,
                    "current_period_start": sub.current_period_start.isoformat(),
                    "current_period_end": sub.current_period_end.isoformat(),
                    "provider": sub.provider,
                    "checkout_session_id": sub.checkout_session_id,
                    "created_at": sub.created_at.isoformat(),
                }
            ).execute()

    return sub


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

    plan_def = PLANS["pass"]
    assert plan_def.price_cents is not None

    session_id = str(uuid.uuid4())
    provider = get_active_provider()
    created = provider.create_session(
        checkout_session_id=session_id,
        user_id=user_id,
        user_email=user_email,
        plan_id="pass",
        plan_name=plan_def.name,
        amount_cents=plan_def.price_cents,
        currency=plan_def.currency,
    )

    rec = CheckoutSessionRecord(
        id=session_id,
        user_id=user_id,
        plan_id="pass",
        amount_cents=plan_def.price_cents,
        currency=plan_def.currency,
        status="pending",
        provider=provider.name,
        provider_ref=created["provider_ref"],
        checkout_url=created["checkout_url"],
        expires_at=created["expires_at"],
    )
    _save_checkout_session(rec)

    return CheckoutCreatedOut(
        session_id=rec.id,
        provider=rec.provider,
        amount_cents=rec.amount_cents,
        currency=rec.currency,
        expires_at=rec.expires_at,
        checkout_url=rec.checkout_url,
    )


def _refresh_and_serialize_session(rec: CheckoutSessionRecord) -> CheckoutStatusOut:
    now = datetime.now(UTC)
    if rec.status == "pending":
        if rec.provider == "stripe_sandbox" and rec.provider_ref:
            try:
                provider = StripeSandboxProvider()
                remote_status = provider.get_status(rec.provider_ref)
                if remote_status == "paid":
                    rec.status = "paid"
                    rec.paid_at = rec.paid_at or now
                    _save_checkout_session(rec)
                    grant_plan(rec)
                elif remote_status == "expired":
                    rec.status = "expired"
                    _save_checkout_session(rec)
            except Exception:
                pass

        if rec.status == "pending" and now >= rec.expires_at:
            rec.status = "expired"
            _save_checkout_session(rec)

    active_sub = _get_active_subscription_for_user(rec.user_id)
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
    rec = _load_checkout_session_by_id(session_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "checkout_not_found", "message": "Checkout session not found."},
        )
    return _refresh_and_serialize_session(rec)


def get_checkout_status_by_ref(provider_ref: str, user_id: str) -> CheckoutStatusOut:
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
