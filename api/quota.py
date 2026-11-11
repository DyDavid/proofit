"""Quota enforcement dependencies (`require_quota`) and usage recording (`record_usage`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Depends, HTTPException

from api.auth import CurrentUser, get_optional_user, get_user_email
from api.billing.plans import PLANS
from api.billing.service import get_subscription_summary, record_usage_event
from api.config import is_admin_email, settings

QuotaKind = Literal["analysis", "rewrite"]


def check_quota(user_id: str, kind: QuotaKind) -> None:
    """Verify the user is within their plan quota for `kind`, or raise HTTP 402."""
    if not settings.enforce_quotas:
        return

    # Superuser admin bypass: dydavid168@gmail.com has unlimited access
    if is_admin_email(get_user_email(user_id)):
        return

    summary = get_subscription_summary(user_id)
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

    summary = get_subscription_summary(user_id)
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
        record_usage_event(user_id, kind)
