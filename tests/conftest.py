"""Pytest configuration ensuring tests default to isolated mock mode.

Developers may have `ENGINE_MODE=live` and live credentials in their local
`.env`. Tests should run deterministically in mock mode by default unless a
test explicitly patches `settings.engine_mode = "live"` or calls
`_run_live_analysis` directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.auth import _parse_trusted_proxy_networks
from api.billing.service import reset_billing_memory
from api.config import settings
from api.limiter import reset_rate_limits
from api.store import store
from engine.ingest import cache as ingest_cache


@pytest.fixture(autouse=True)
def _default_mock_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENGINE_MODE", "mock")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(settings, "engine_mode", "mock")
    monkeypatch.setattr(settings, "persistence_mode", "offline")
    monkeypatch.setattr(settings, "supabase_url", None)
    monkeypatch.setattr(settings, "mock_delay_seconds", 0.01)
    monkeypatch.setattr(settings, "enforce_guest_limit", False)
    monkeypatch.setattr(settings, "enforce_auth_on_rewrites", False)
    monkeypatch.setattr(settings, "enforce_quotas", False)
    monkeypatch.setattr(settings, "billing_provider", "mock")
    monkeypatch.setattr(settings, "turnstile_secret_key", None)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.setattr(settings, "trusted_proxies", "")
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    _parse_trusted_proxy_networks.cache_clear()
    monkeypatch.setattr(ingest_cache, "CACHE_DIR", tmp_path / ".cache")
    store.guest_ip_usage.clear()
    reset_billing_memory()
    reset_rate_limits()
