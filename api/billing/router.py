"""Billing API endpoints for Direct Individual Bakong KHQR."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_current_user
from api.billing.plans import PlanDefinition, list_plans
from api.billing.service import (
    CheckoutCreatedOut,
    CheckoutCreateIn,
    CheckoutStatusOut,
    SubscriptionOut,
    create_checkout,
    get_checkout_status,
    get_subscription_summary,
    recheck_checkout_status,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[PlanDefinition])
def get_plans() -> list[PlanDefinition]:
    """Return authoritative plan definitions, prices, and limits."""
    return list_plans()


@router.get("/subscription", response_model=SubscriptionOut)
def get_subscription(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SubscriptionOut:
    """Return the authenticated user's active plan, expiry, and usage."""
    return get_subscription_summary(user.id)


@router.post("/checkout", response_model=CheckoutCreatedOut)
def post_checkout(
    body: CheckoutCreateIn,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CheckoutCreatedOut:
    """Create a new Direct Individual Bakong KHQR order for the 30-day Job Hunt Pass."""
    return create_checkout(
        user_id=user.id,
        user_email=user.email or "",
        plan_id=body.plan_id,
    )


@router.get("/checkout/{session_id}", response_model=CheckoutStatusOut)
def get_checkout(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CheckoutStatusOut:
    """Return checkout status for the order owner, verifying via official NBC API if due."""
    return get_checkout_status(session_id=session_id, user_id=user.id)


@router.post("/checkout/{session_id}/recheck", response_model=CheckoutStatusOut)
def post_recheck_checkout(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CheckoutStatusOut:
    """Rate-limited explicit server verification / reconciliation request."""
    return recheck_checkout_status(session_id=session_id, user_id=user.id)
