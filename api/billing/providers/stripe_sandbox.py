"""StripeSandboxProvider using the official `stripe` Python SDK (test keys only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import stripe

from api.billing.providers.base import CheckoutStatus, CreatedProviderSession
from api.config import settings, validate_billing_config


class StripeSandboxProvider:
    name: Literal["stripe_sandbox", "mock"] = "stripe_sandbox"

    def _api_key(self) -> str:
        validate_billing_config(settings)
        return (settings.stripe_secret_key or "").strip()

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
        api_key = self._api_key()
        expires_at = datetime.now(UTC) + timedelta(minutes=30)
        site_url = settings.site_url.rstrip("/")

        create_kwargs: dict[str, object] = {
            "api_key": api_key,
            "mode": "payment",
            "line_items": [
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": amount_cents,
                        "product_data": {
                            "name": f"{plan_name} (30 days)",
                        },
                    },
                    "quantity": 1,
                }
            ],
            "client_reference_id": user_id,
            "metadata": {
                "checkout_session_id": checkout_session_id,
                "user_id": user_id,
                "plan_id": plan_id,
            },
            "success_url": f"{site_url}/billing/success?cs={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{site_url}/billing/cancel",
            "expires_at": int(expires_at.timestamp()),
            "locale": "auto",
        }
        if user_email:
            create_kwargs["customer_email"] = user_email

        session = stripe.checkout.Session.create(**create_kwargs)  # type: ignore[arg-type]
        return {
            "provider_ref": str(session.id),
            "checkout_url": str(session.url) if session.url else None,
            "expires_at": expires_at,
        }

    def get_status(self, provider_ref: str) -> CheckoutStatus:
        api_key = self._api_key()
        session = stripe.checkout.Session.retrieve(provider_ref, api_key=api_key)
        payment_status = getattr(session, "payment_status", None)
        status = getattr(session, "status", None)
        if payment_status == "paid":
            return "paid"
        if status == "expired":
            return "expired"
        return "pending"

