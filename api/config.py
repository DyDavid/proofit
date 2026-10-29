"""Settings loaded from the environment / `.env` (see `.env.example`).

Field names match `.env.example` exactly so the two files never drift.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

TRUSTED_BAKONG_API_HOSTS = frozenset(
    {
        "https://sit-api-bakong.nbc.gov.kh",
        "https://api-bakong.nbc.gov.kh",
    }
)


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

    # Phase 4: Direct Individual Bakong KHQR (NBC Open API)
    bakong_token: str | None = None
    bakong_account_id: str = "abaakhppxxx@abaa"
    bakong_account_information: str | None = "012929221"
    bakong_acquiring_bank: str | None = "ABA Bank"
    bakong_merchant_name: str = "DY DAVID"
    bakong_merchant_city: str = "Phnom Penh"
    bakong_api_base_url: str = "https://sit-api-bakong.nbc.gov.kh"
    bakong_live_enabled: bool = False
    khqr_expiry_seconds: int = 300

    site_url: str = "http://localhost:3000"
    enforce_quotas: bool = True
    admin_emails: str = "dydavid168@gmail.com"


def is_admin_email(email: str | None) -> bool:
    """Check if the email has unlimited superuser privileges."""
    if not email:
        return False
    admins = [e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()]
    return email.strip().lower() in admins


def validate_billing_config(cfg: Settings | None = None) -> None:
    """Validate Direct Bakong KHQR configuration and reject untrusted hosts or relay tokens."""
    active = cfg or settings
    base_url = (active.bakong_api_base_url or "").strip().rstrip("/")
    if base_url not in TRUSTED_BAKONG_API_HOSTS:
        raise RuntimeError(
            "Refusing to start: BAKONG_API_BASE_URL must be one of the official NBC "
            f"hosts {sorted(TRUSTED_BAKONG_API_HOSTS)}, got {base_url!r}."
        )

    if active.khqr_expiry_seconds <= 0 or active.khqr_expiry_seconds > 600:
        raise RuntimeError(
            "Refusing to start: KHQR_EXPIRY_SECONDS must be between 1 and 600 seconds "
            f"(10 minutes maximum), got {active.khqr_expiry_seconds}."
        )

    token = (active.bakong_token or "").strip()
    if token.lower().startswith("rbk"):
        raise RuntimeError(
            "Refusing to start: third-party KHQR relay tokens ('rbk...') are prohibited. "
            "Use an official NBC Bakong developer token."
        )

    if active.bakong_live_enabled:
        acct = (active.bakong_account_id or "").strip()
        if not acct or "@" not in acct:
            raise RuntimeError(
                "Refusing to start: BAKONG_LIVE_ENABLED=true requires a valid "
                "BAKONG_ACCOUNT_ID (e.g. 'name@aba')."
            )
        if not token:
            raise RuntimeError(
                "Refusing to start: BAKONG_LIVE_ENABLED=true requires an official "
                "BAKONG_TOKEN."
            )


settings = Settings()
validate_billing_config(settings)
