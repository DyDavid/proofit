"""Pytest configuration ensuring tests default to isolated mock mode.

Developers may have `ENGINE_MODE=live` and live credentials in their local
`.env`. Tests should run deterministically in mock mode by default unless a
test explicitly patches `settings.engine_mode = "live"` or calls
`_run_live_analysis` directly.
"""

from __future__ import annotations

import pytest

from api.config import settings


@pytest.fixture(autouse=True)
def _default_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_MODE", "mock")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(settings, "engine_mode", "mock")
    monkeypatch.setattr(settings, "supabase_url", None)
    monkeypatch.setattr(settings, "mock_delay_seconds", 0.01)
