"""Settings loaded from the environment / `.env` (see `.env.example`).

Field names match `.env.example` exactly so the two files never drift.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field
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
    # Live deployments require persistence unless offline operation is explicit.
    persistence_mode: Literal["required", "offline"] = "required"

    guest_ip_salt: str = "proofit-default-guest-salt"
    enforce_guest_limit: bool = True
    enforce_auth_on_rewrites: bool = True
    turnstile_secret_key: str | None = None

    billing_provider: Literal["disabled", "stripe_sandbox", "mock"] = "mock"
    app_environment: Literal["local", "demo", "production"] = "local"
    allow_mock_payments: bool = False
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    site_url: str = "http://localhost:3000"
    enforce_quotas: bool = True
    admin_emails: str = "dydavid168@gmail.com"

    # Phase 3 resource exhaustion limits
    max_response_bytes: int = 2 * 1024 * 1024
    max_docx_decompressed_bytes: int = 10 * 1024 * 1024
    parser_timeout_seconds: float = 8.0
    max_concurrent_parses: int = 3
    parser_memory_limit_mb: int = Field(default=256, ge=64, le=2048)
    parser_startup_timeout_seconds: float = Field(default=20, ge=1, le=60)
    max_pdf_decompressed_bytes: int = Field(default=10 * 1024 * 1024, ge=65536, le=64 * 1024 * 1024)
    url_cache_max_entries: int = 500
    url_cache_ttl_hours: int = 24
    guest_record_ttl_hours: int = 24
    rate_limit_resumes_per_min: int = 15
    rate_limit_jobs_per_min: int = 20
    rate_limit_fetch_per_min: int = 10
    fetch_timeout_seconds: float = 15.0
    max_concurrent_fetches: int = 4
    rewrite_timeout_seconds: float = 60.0
    max_concurrent_rewrites: int = 2

    # Phase 4 client IP forwarding trust
    trusted_proxies: str = ""

    # Phase 2 live analysis concurrency and execution bounds
    max_concurrent_analyses: int = 3
    max_queued_analyses: int = 10
    analysis_timeout_seconds: float = 60.0
    external_call_timeout_seconds: float = 25.0
    # Admission attempts are separate from refundable success quotas.
    analysis_attempts_per_hour: int = 10
    guest_analysis_attempts_per_hour: int = 3
    rewrite_attempts_per_hour: int = 10
    checkout_attempts_per_hour: int = 10
    checkout_cache_max_entries: int = 500
    checkout_status_requests_per_min: int = Field(default=30, ge=0, le=10000)
    checkout_status_cache_seconds: int = Field(default=5, ge=1, le=300)
    checkout_status_provider_timeout_seconds: int = Field(default=10, ge=1, le=30)
    webhook_cache_max_entries: int = Field(default=1000, ge=1, le=10000)
    job_requests_per_min: int = Field(default=20, ge=0, le=10000)
    job_global_requests_per_min: int = Field(default=120, ge=0, le=10000)
    job_unused_max_entries: int = Field(default=500, ge=1, le=10000)
    job_unused_retention_hours: int = Field(default=24, ge=1, le=168)
    auth_requests_per_min: int = Field(default=120, ge=0, le=10000)
    auth_global_requests_per_min: int = Field(default=1200, ge=0, le=10000)
    max_concurrent_auth: int = Field(default=4, ge=1, le=32)
    auth_timeout_seconds: float = Field(default=5, ge=0.1, le=30)
    auth_provider_timeout_seconds: float = Field(default=3, ge=0.1, le=10)
    auth_jwks_refresh_seconds: int = Field(default=30, ge=1, le=300)

    # Phase 4 multi-worker coordination & abandoned work recovery bounds
    analysis_abandoned_timeout_seconds: float = 600.0
    reservation_ttl_seconds: float = 600.0


def is_admin_email(email: str | None) -> bool:
    """Check if the email has unlimited superuser privileges."""
    if not email:
        return False
    admins = [e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()]
    return email.strip().lower() in admins


def validate_billing_config(cfg: Settings | None = None) -> None:
    """Refuse to start if a non-test Stripe key is configured."""
    active = cfg or settings
    production = active.app_environment == "production" or os.getenv("RENDER") == "true" or os.getenv("VERCEL") == "1"
    if production and (active.allow_mock_payments or active.billing_provider == "mock"):
        raise RuntimeError("Production requires disabled or Stripe sandbox billing, with mock payments disabled.")
    if production and (active.engine_mode != "live" or active.persistence_mode != "required"):
        raise RuntimeError("Production requires live engine mode and required database persistence.")
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
