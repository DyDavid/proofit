"""Pytest configuration ensuring tests default to isolated mock mode.

Developers may have `ENGINE_MODE=live` and live credentials in their local
`.env`. Tests should run deterministically in mock mode by default unless a
test explicitly patches `settings.engine_mode = "live"` or calls
`_run_live_analysis` directly.
"""

from __future__ import annotations

import pytest

from api.billing.service import reset_billing_memory
from api.config import settings
from api.store import store


@pytest.fixture(autouse=True)
def _default_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_MODE", "mock")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(settings, "engine_mode", "mock")
    monkeypatch.setattr(settings, "supabase_url", None)
    monkeypatch.setattr(settings, "mock_delay_seconds", 0.01)
    monkeypatch.setattr(settings, "enforce_guest_limit", False)
    monkeypatch.setattr(settings, "enforce_auth_on_rewrites", False)
    monkeypatch.setattr(settings, "enforce_quotas", False)
    monkeypatch.setattr(settings, "bakong_api_base_url", "https://sit-api-bakong.nbc.gov.kh")
    monkeypatch.setattr(settings, "bakong_live_enabled", False)
    monkeypatch.setattr(settings, "turnstile_secret_key", None)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    store.guest_ip_usage.clear()
    reset_billing_memory()
