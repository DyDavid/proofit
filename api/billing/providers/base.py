"""BillingProvider interface so Stripe sandbox, mock, or future KHQR plug in cleanly."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, TypedDict

CheckoutStatus = Literal["pending", "paid", "expired"]


class CreatedProviderSession(TypedDict):
    provider_ref: str
    checkout_url: str | None
    expires_at: datetime


class BillingProvider(Protocol):
    name: Literal["stripe_sandbox", "mock"]

    def create_session(
        self,
        *,
        checkout_session_id: str,
        user_id: str,
        user_email: str,
        plan_id: str,
        plan_name: str,
        amount_cents: int,
        currency: str,
    ) -> CreatedProviderSession:
        """Return {"provider_ref": str, "checkout_url": str | None, "expires_at": datetime}."""
        ...

    def get_status(self, provider_ref: str) -> CheckoutStatus:
        """Ask the provider directly. Used as a fallback if a webhook is late."""
        ...

