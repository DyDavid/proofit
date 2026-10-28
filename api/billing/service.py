"""Billing service: current plan resolution and usage summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from api.billing.plans import PLANS, PlanId
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


# In-memory store for tests / offline mode (and fallback before Phase 4 DB migration)
_subscriptions: list[SubscriptionRecord] = []
_usage_events: list[UsageEventRecord] = []


def reset_billing_memory() -> None:
    """Clear in-memory billing state (used by test fixtures)."""
    _subscriptions.clear()
    _usage_events.clear()


def set_test_subscription(
    user_id: str,
    plan_id: Literal["pass", "campus"] = "pass",
    active_until: datetime | None = None,
    active_from: datetime | None = None,
) -> SubscriptionRecord:
    """Helper to seed an active subscription in memory for tests."""
    now = datetime.now(UTC)
    rec = SubscriptionRecord(
        id=f"sub_{len(_subscriptions) + 1}",
        user_id=user_id,
        plan_id=plan_id,
        current_period_start=active_from or now,
        current_period_end=active_until or (now + timedelta(days=30)),
        provider="mock",
    )
    _subscriptions.append(rec)
    return rec


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
            # Table may not exist yet before Phase 4 migration; fall back to in-memory
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


def get_subscription_summary(user_id: str) -> SubscriptionOut:
    """Return the user's active plan, expiry, and usage in the current window."""
    now = datetime.now(UTC)
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
