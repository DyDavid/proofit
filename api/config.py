"""Settings loaded from the environment / `.env` (see `.env.example`).

Field names match `.env.example` exactly so the two files never drift.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    engine_mode: Literal["mock", "live"] = "mock"
    app_version: str = "0.1.0"
    mock_delay_seconds: float = 1.5
    max_upload_bytes: int = 5 * 1024 * 1024
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_api_key: str | None = None

    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_key: str | None = None
    supabase_jwt_secret: str | None = None

    guest_ip_salt: str = "proofit-default-guest-salt"
    enforce_guest_limit: bool = True
    enforce_auth_on_rewrites: bool = True
    turnstile_secret_key: str | None = None

    billing_provider: Literal["stripe_sandbox", "mock"] = "mock"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    site_url: str = "http://localhost:3000"
    enforce_quotas: bool = True


def validate_billing_config(cfg: Settings | None = None) -> None:
    """Refuse to start if a non-test Stripe key is configured."""
    active = cfg or settings
    key = (active.stripe_secret_key or "").strip()
    if active.billing_provider == "stripe_sandbox":
        if not key or not (key.startswith("sk_test_") or key.startswith("rk_test_")):
            raise RuntimeError(
                "Refusing to start: BILLING_PROVIDER=stripe_sandbox requires a Stripe "
                "test secret key starting with 'sk_test_' or 'rk_test_'."
            )
    elif key and not (key.startswith("sk_test_") or key.startswith("rk_test_")):
        raise RuntimeError(
            "Refusing to start: STRIPE_SECRET_KEY must be a sandbox test key "
            "starting with 'sk_test_' or 'rk_test_'."
        )


settings = Settings()
validate_billing_config(settings)
