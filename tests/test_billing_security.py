"""Regression coverage for renewal quotas, rewrite attempts and checkout flooding."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.auth import CurrentUser, get_current_user, get_optional_user
from api.billing import service
from api.billing.providers.mock import MockProvider
from api.config import settings
from api.db import DatabasePersistenceError
from api.errors import ApiError
from api.limiter import enforce_operation_attempt_limit
from api.main import app
from api.routes import analyses
from api.store import AnalysisRecord, Store
from engine.execution import WorkTimeoutError
from engine.rewrite.llm import RateLimitedError


@pytest.fixture
def security_env(monkeypatch):
    monkeypatch.setattr(settings, "enforce_quotas", True)
    monkeypatch.setattr(settings, "rewrite_attempts_per_hour", 3)
    monkeypatch.setattr(settings, "checkout_attempts_per_hour", 5)
    user = CurrentUser(id="billing-security-user", email="candidate@example.test")
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: user)
    isolated = Store()
    monkeypatch.setattr(analyses, "store", isolated)
    return user, isolated


def _buy_pass(user):
    created = service.create_checkout(user.id, user.email, "pass")
    service.simulate_mock_payment(created.session_id, user.id)
    return created


def _seed_analysis(local, user, analysis_id="security-analysis"):
    record = AnalysisRecord(
        id=analysis_id, user_id=user.id, resume_id="resume", job_id="job", country="KH",
        status="done", match=local.pick_fixture("fresh_grad_stretch"),
    )
    local.analyses[record.id] = record
    return record


def test_early_renewals_keep_current_quotas_until_next_period(security_env, monkeypatch):
    user, _ = security_env
    _buy_pass(user)
    for kind, limit in (("analysis", 50), ("rewrite", 30)):
        for _ in range(limit):
            service.commit_usage_reservation(None, user.id, kind)
    _buy_pass(user)
    _buy_pass(user)
    periods = service.get_test_subscriptions_for_user(user.id)
    assert len(periods) == 3
    assert periods[1].current_period_start == periods[0].current_period_end
    assert periods[2].current_period_start == periods[1].current_period_end
    summary = service.get_subscription_summary(user.id)
    assert summary.usage.analysis.used == 50
    assert summary.usage.rewrite.used == 30
    for kind in ("analysis", "rewrite"):
        assert service.atomic_reserve_quota(user.id, kind)[0] is False

    class NextPeriod(datetime):
        @classmethod
        def now(cls, tz=None):
            return periods[1].current_period_start

    monkeypatch.setattr(service, "datetime", NextPeriod)
    assert service.get_subscription_summary(user.id).usage.analysis.used == 0
    for _ in range(50):
        allowed, rid, _ = service.atomic_reserve_quota(user.id, "analysis")
        assert allowed
        service.commit_usage_reservation(rid, user.id, "analysis")
    assert service.atomic_reserve_quota(user.id, "analysis")[0] is False


def test_a_future_subscription_alone_does_not_activate_paid_quota(security_env):
    user, _ = security_env
    service.set_test_subscription(user.id, active_from=datetime.now(UTC) + timedelta(days=1))
    assert service.get_subscription_summary(user.id).plan_id == "free"


def test_paid_checkout_status_retries_failed_pass_activation(security_env, monkeypatch):
    user, _ = security_env
    checkout = service.create_checkout(user.id, user.email, "pass")
    original = service.grant_plan
    calls = [0]

    def fail_once(session):
        calls[0] += 1
        if calls[0] == 1:
            raise DatabasePersistenceError("Temporary grant failure")
        return original(session)

    monkeypatch.setattr(service, "grant_plan", fail_once)
    with pytest.raises(DatabasePersistenceError):
        service.simulate_mock_payment(checkout.session_id, user.id)
    assert not service._subscriptions
    assert service.get_checkout_status(checkout.session_id, user.id).status == "paid"
    assert service.get_subscription_summary(user.id).plan_id == "pass"
    service.get_checkout_status(checkout.session_id, user.id)
    assert len(service.get_test_subscriptions_for_user(user.id)) == 1


@pytest.mark.parametrize("error,status", [
    (WorkTimeoutError("timeout after provider work"), 504),
    (RuntimeError("provider failed"), 500),
    (RateLimitedError("upstream busy"), 429),
])
@pytest.mark.parametrize("admin", [False, True])
def test_failed_rewrites_refund_quota_but_eventually_block_attempts(security_env, monkeypatch, error, status, admin):
    user, local = security_env
    if admin:
        monkeypatch.setattr(settings, "admin_emails", user.email)
    record = _seed_analysis(local, user)
    detect = MagicMock(side_effect=error)
    monkeypatch.setattr(analyses, "detect_hidden_strengths", detect)
    with TestClient(app) as client:
        for _ in range(3):
            assert client.post(f"/api/analyses/{record.id}/rewrites").status_code == status
            assert service.get_subscription_summary(user.id).usage.rewrite.used == 0
        blocked = client.post(f"/api/analyses/{record.id}/rewrites")
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert detect.call_count == 3
    assert not service._usage_reservations
    assert not record.rewrite_in_progress


def test_cached_rewrites_do_not_spend_more_attempts(security_env, monkeypatch):
    user, local = security_env
    record = _seed_analysis(local, user)
    monkeypatch.setattr(settings, "rewrite_attempts_per_hour", 1)
    detect = MagicMock(return_value=[])
    monkeypatch.setattr(analyses, "detect_hidden_strengths", detect)
    with TestClient(app) as client:
        for _ in range(4):
            assert client.post(f"/api/analyses/{record.id}/rewrites").status_code == 200
        another = _seed_analysis(local, user, "another-analysis")
        assert client.post(f"/api/analyses/{another.id}/rewrites").status_code == 429
    assert detect.call_count == 1


def test_attempt_budgets_are_independent_and_reset_after_one_hour(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("api.limiter.time", SimpleNamespace(monotonic=lambda: clock[0]))
    enforce_operation_attempt_limit("rewrite", "user", 1)
    enforce_operation_attempt_limit("checkout", "user", 1)
    with pytest.raises(ApiError):
        enforce_operation_attempt_limit("rewrite", "user", 1)
    clock[0] = 3600
    enforce_operation_attempt_limit("rewrite", "user", 1)


def test_checkout_flood_reuses_pending_session_then_returns_429(security_env, monkeypatch):
    provider = MagicMock(wraps=MockProvider())
    provider.name = "mock"
    monkeypatch.setattr(service, "get_active_provider", lambda: provider)
    ids = set()
    with TestClient(app) as client:
        for _ in range(5):
            response = client.post("/api/billing/checkout", json={"plan_id": "pass"})
            assert response.status_code == 200
            ids.add(response.json()["session_id"])
        assert client.post("/api/billing/checkout", json={"plan_id": "pass"}).status_code == 429
    assert len(ids) == len(service._checkout_sessions) == 1
    assert provider.create_session.call_count == 1


def test_simultaneous_checkouts_call_provider_once(security_env, monkeypatch):
    user, _ = security_env
    entered, release = threading.Event(), threading.Event()
    mock = MockProvider()

    def slow_create(**kwargs):
        entered.set()
        assert release.wait(5)
        return mock.create_session(**kwargs)

    provider = MagicMock(name="provider")
    provider.name = "mock"
    provider.create_session.side_effect = slow_create
    monkeypatch.setattr(service, "get_active_provider", lambda: provider)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(service.create_checkout, user.id, user.email, "pass")
        try:
            assert entered.wait(5)
            responses = list(pool.map(lambda _: client.post("/api/billing/checkout", json={"plan_id": "pass"}), range(3)))
            assert [response.status_code for response in responses] == [409] * 3
        finally:
            release.set()
        created = first.result(timeout=5)
    assert provider.create_session.call_count == 1
    assert list(service._checkout_sessions) == [created.session_id]


def test_provider_failures_still_consume_checkout_attempts(security_env, monkeypatch):
    user, _ = security_env
    monkeypatch.setattr(settings, "checkout_attempts_per_hour", 2)
    provider = MagicMock()
    provider.name = "mock"
    provider.create_session.side_effect = RuntimeError("private provider details")
    monkeypatch.setattr(service, "get_active_provider", lambda: provider)
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post("/api/billing/checkout", json={"plan_id": "pass"})
            assert response.status_code == 503
            assert "private provider details" not in response.text
        assert client.post("/api/billing/checkout", json={"plan_id": "pass"}).status_code == 429
    assert provider.create_session.call_count == 2
    assert all(rec.status == "canceled" for rec in service._checkout_sessions.values())


def test_expired_pending_checkout_can_be_replaced(security_env):
    user, _ = security_env
    first = service.create_checkout(user.id, user.email, "pass")
    service._checkout_sessions[first.session_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second = service.create_checkout(user.id, user.email, "pass")
    assert first.session_id != second.session_id


def test_cache_stays_bounded_without_evicting_offline_pending_sessions(security_env, monkeypatch):
    user, _ = security_env
    monkeypatch.setattr(settings, "checkout_cache_max_entries", 2)
    first = service.create_checkout(user.id, user.email, "pass")
    service.create_checkout("another-user", "another@example.test", "pass")
    with pytest.raises(ApiError) as blocked:
        service.create_checkout("third-user", "third@example.test", "pass")
    assert blocked.value.status_code == 429
    assert service.create_checkout(user.id, user.email, "pass").session_id == first.session_id
    service.simulate_mock_payment(first.session_id, user.id)
    service.create_checkout("third-user", "third@example.test", "pass")
    assert len(service._checkout_sessions) == 2


@pytest.mark.parametrize("operation", ["rewrite", "checkout"])
def test_persisted_attempt_failure_returns_503_without_local_fallback(monkeypatch, operation):
    client = MagicMock()
    monkeypatch.setattr("api.limiter.get_supabase_client", lambda: client)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: client)
    client.rpc.return_value.execute.side_effect = RuntimeError("private provider details")
    with pytest.raises(ApiError) as error:
        enforce_operation_attempt_limit(operation, "user:alice", 2)
    assert error.value.status_code == 503
    assert "private provider details" not in error.value.message


@pytest.mark.parametrize("operation", ["reserve", "save", "grant"])
def test_billing_database_failures_do_not_create_local_state(monkeypatch, operation):
    client = MagicMock()
    monkeypatch.setattr(service, "get_supabase_client", lambda: client)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: client)
    client.rpc.return_value.execute.side_effect = RuntimeError("database unavailable")
    client.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("database unavailable")
    rec = service.CheckoutSessionRecord(id="checkout", user_id="user", plan_id="pass", amount_cents=500,
                                        currency="USD", status="paid", provider="mock")
    with pytest.raises(DatabasePersistenceError):
        if operation == "reserve":
            service._reserve_checkout_session("user", "mock")
        elif operation == "save":
            service._save_checkout_session(rec)
        else:
            service.grant_plan(rec)
    assert not service._checkout_sessions
    assert not service._subscriptions
