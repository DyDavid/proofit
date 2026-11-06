"""Failure refunds must not reset the shared creation/retry admission budget."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from api.auth import CurrentUser, get_optional_user
from api.billing.service import get_subscription_summary
from api.config import settings
from api.db import DatabasePersistenceError, db_reserve_analysis_attempt
from api.errors import ApiError
from api.limiter import SlidingWindowRateLimiter, enforce_analysis_attempt_limit
from api.main import app
from api.quota import release_quota
from api.store import store


@pytest.mark.parametrize("authenticated", [True, False])
def test_refunded_creation_and_retry_share_attempt_budget(monkeypatch, authenticated):
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "enforce_quotas", True)
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    monkeypatch.setattr(settings, "analysis_attempts_per_hour", 2)
    monkeypatch.setattr(settings, "guest_analysis_attempts_per_hour", 2)
    user = CurrentUser(id="attempt-budget-user", email="audit@example.test") if authenticated else None
    monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: user)
    resume = store.add_resume("resume.txt", "application/pdf", 1, data=b"x", user_id=user.id if user else None)
    job, _ = store.add_job("Isolated job description requiring Python and software engineering.", source="text")
    started = []

    async def failed_analysis(analysis_id):
        started.append(analysis_id)
        rec = store.get_analysis(analysis_id)
        store.update_analysis(analysis_id, status="failed")
        release_quota(rec.reservation_id, rec.user_id, "analysis")
        if rec.guest_ip_hash:
            store.release_guest_ip_usage(rec.guest_ip_hash)

    monkeypatch.setattr("api.routes.analyses._run_live_analysis", failed_analysis)
    with TestClient(app) as client:
        payload = {"resume_id": resume.id, "job_id": job.id, "country": "KH"}
        first = client.post("/api/analyses", json=payload)
        assert first.status_code == 202
        second = client.post(f"/api/analyses/{first.json()['analysis_id']}/retry")
        assert second.status_code == 202
        # Switching between a new analysis and retrying cannot reset the budget.
        denied = client.post("/api/analyses", json=payload)
        assert denied.status_code == 429
        assert denied.json()["error"]["code"] == "RATE_LIMITED"
        retry_denied = client.post(f"/api/analyses/{second.json()['analysis_id']}/retry")
        assert retry_denied.status_code == 429
    assert len(started) == 2
    if user:
        assert get_subscription_summary(user.id).usage.analysis.used == 0
    else:
        assert not store.guest_ip_usage


def test_attempt_window_expires_and_does_not_evict_active_budgets(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("api.limiter.time", SimpleNamespace(monotonic=lambda: now[0]))
    limiter = SlidingWindowRateLimiter(max_buckets=1, evict_active=False)
    limiter.check("alice", 1, 3600)
    with pytest.raises(ApiError):
        limiter.check("bob", 1, 3600)
    with pytest.raises(ApiError):
        limiter.check("alice", 1, 3600)
    now[0] = 3600
    limiter.check("alice", 1, 3600)


def test_simultaneous_attempts_cannot_exceed_budget():
    limiter = SlidingWindowRateLimiter(evict_active=False)

    def attempt(_):
        try:
            limiter.check("same-user", 2, 3600)
            return True
        except ApiError:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(20))) == 2


def test_persisted_attempt_budget_and_failures_are_not_bypassed(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("api.limiter.get_supabase_client", lambda: client)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: client)
    request = Request({"type": "http", "client": ("198.51.100.1", 1234), "headers": []})
    user = CurrentUser(id="persistent-user")
    client.rpc.return_value.execute.return_value.data = {"allowed": False}
    with pytest.raises(ApiError) as denied:
        enforce_analysis_attempt_limit(request, user)
    assert denied.value.status_code == 429
    client.rpc.assert_called_with(
        "reserve_analysis_attempt", {"p_subject": "user:persistent-user", "p_limit": settings.analysis_attempts_per_hour}
    )
    client.rpc.return_value.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(ApiError) as unavailable:
        enforce_analysis_attempt_limit(request, user)
    assert unavailable.value.status_code == 503
    client.rpc.return_value.execute.side_effect = None
    client.rpc.return_value.execute.return_value.data = {"allowed": "true"}
    with pytest.raises(DatabasePersistenceError):
        db_reserve_analysis_attempt("user:persistent-user", 2)


def test_database_initialization_failure_does_not_reset_attempts(monkeypatch):
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "persistence_mode", "required")
    monkeypatch.setattr(settings, "supabase_url", "https://placeholder.supabase.co")
    monkeypatch.setattr("api.limiter.get_supabase_client", lambda: None)
    request = Request({"type": "http", "client": ("198.51.100.1", 1234), "headers": []})
    with pytest.raises(ApiError) as unavailable:
        enforce_analysis_attempt_limit(request, CurrentUser(id="persistent-user"))
    assert unavailable.value.status_code == 503
