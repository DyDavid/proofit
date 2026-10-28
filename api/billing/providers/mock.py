"""Offline MockProvider for local dev, demos, and deterministic tests."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from api.billing.providers.base import CheckoutStatus, CreatedProviderSession


class MockProvider:
    name: Literal["stripe_sandbox", "mock"] = "mock"

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
        return {
            "provider_ref": f"mock_{secrets.token_hex(8)}",
            "checkout_url": None,
            "expires_at": datetime.now(UTC) + timedelta(minutes=30),
        }

    def get_status(self, provider_ref: str) -> CheckoutStatus:
        return "pending"

