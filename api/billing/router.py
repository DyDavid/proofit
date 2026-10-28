"""Billing API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_current_user
from api.billing.plans import PlanDefinition, list_plans
from api.billing.service import SubscriptionOut, get_subscription_summary

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
