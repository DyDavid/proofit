"""Billing API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from api.auth import CurrentUser, get_current_user
from api.billing.plans import PlanDefinition, list_plans
from api.billing.service import (
    CheckoutCreatedOut,
    CheckoutCreateIn,
    CheckoutStatusOut,
    SubscriptionOut,
    create_checkout,
    get_checkout_status,
    get_checkout_status_by_ref,
    get_subscription_summary,
    simulate_mock_payment,
)
from api.billing.webhooks import process_stripe_webhook

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
    """Create a pending checkout session through the active provider."""
    return create_checkout(
        user_id=user.id,
        user_email=user.email or "",
        plan_id=body.plan_id,
    )


@router.get("/checkout/by-ref/{provider_ref}", response_model=CheckoutStatusOut)
def get_checkout_by_ref(
    provider_ref: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CheckoutStatusOut:
    """Look up checkout session status by provider reference (e.g. cs_test_...)."""
    return get_checkout_status_by_ref(provider_ref=provider_ref, user_id=user.id)


@router.get("/checkout/{session_id}", response_model=CheckoutStatusOut)
def get_checkout(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CheckoutStatusOut:
    """Return checkout session status with late-webhook fallback for Stripe."""
    return get_checkout_status(session_id=session_id, user_id=user.id)


@router.post("/checkout/{session_id}/simulate", response_model=CheckoutStatusOut)
def post_simulate_checkout(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CheckoutStatusOut:
    """Simulate payment completion (available when BILLING_PROVIDER is mock or aba_payway in test mode)."""
    return simulate_mock_payment(session_id=session_id, user_id=user.id)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict[str, str]:
    """Stripe webhook receiver (verified via Stripe-Signature header, no user JWT)."""
    return await process_stripe_webhook(request)
