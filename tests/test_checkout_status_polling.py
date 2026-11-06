"""Payment polling uses mocked Stripe and independent workers sharing a DB double."""

import copy
import importlib.util
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import stripe
from fastapi.testclient import TestClient
from test_multiworker_concurrency import SharedDatabaseBackend

from api.auth import CurrentUser, get_current_user
from api.billing import service
from api.billing.providers.stripe_sandbox import StripeSandboxProvider
from api.config import Settings, settings
from api.db import DatabasePersistenceError
from api.errors import ApiError
from api.limiter import SlidingWindowRateLimiter, reset_rate_limits
from api.main import app


class PollingDatabase(SharedDatabaseBackend):
    """Model the new atomic RPC contracts, including database time and fencing."""

    def __init__(self):
        super().__init__()
        self.status_hits = {}
        self.calls = []
        self.bad_result = None

    def _execute_rpc(self, name, params):
        if self.fail_all or name in self.fail_rpc_names:
            raise RuntimeError("private database details")
        if self.bad_result == name:
            return SimpleNamespace(data={"invalid": True})
        with self._db_lock:
            self.calls.append(name)
            now = self._now()
            if name == "admit_checkout_status":
                self.status_hits = {user: hits for user, hits in self.status_hits.items()
                                    if hits and hits[-1] > now - timedelta(minutes=1)}
                hits = [hit for hit in self.status_hits.get(params["p_user_id"], [])
                        if hit > now - timedelta(minutes=1)]
                allowed = len(hits) < params["p_limit"]
                if allowed:
                    hits.append(now)
                    self.status_hits[params["p_user_id"]] = hits
                return SimpleNamespace(data={"allowed": allowed})
            if name in ("claim_checkout_status_refresh", "finish_checkout_status_refresh"):
                row = self.checkout_sessions[params["p_session_id"]]
                assert row["user_id"] == params["p_user_id"]
                refresh = False
                if name == "claim_checkout_status_refresh":
                    fresh = bool(row.get("status_refresh_after") and datetime.fromisoformat(row["status_refresh_after"]) > now)
                    leased = bool(row.get("status_refresh_until") and datetime.fromisoformat(row["status_refresh_until"]) > now)
                    if row["status"] == "pending":
                        if row["provider"] == "stripe_sandbox" and row["provider_ref"] and not fresh and not leased:
                            row.update(status_refresh_token=params["p_token"], status_refresh_error=False,
                                       status_refresh_until=(now + timedelta(seconds=params["p_lease_seconds"])).isoformat())
                            refresh = True
                        elif datetime.fromisoformat(row["expires_at"]) <= now and not leased:
                            row.update(status="expired", status_refresh_error=False)
                elif row.get("status_refresh_token") == params["p_token"]:
                    if row["status"] == "pending":
                        if params["p_status"] == "paid":
                            row.update(status="paid", paid_at=now.isoformat())
                        elif params["p_status"] == "expired" or datetime.fromisoformat(row["expires_at"]) <= now:
                            row["status"] = "expired"
                    row.update(status_refresh_after=(now + timedelta(seconds=params["p_cache_seconds"])).isoformat(),
                               status_refresh_token=None, status_refresh_until=None,
                               status_refresh_error=row["status"] == "pending" and params["p_status"] == "error")
                return SimpleNamespace(data={"refresh": refresh, "session": copy.deepcopy(row),
                                             "provider_error": row["status"] == "pending" and row.get("status_refresh_error", False)})
        return super()._execute_rpc(name, params)


def _record(user="poll-user", sid="checkout", ref="cs_test_poll"):
    return service.CheckoutSessionRecord(id=sid, user_id=user, plan_id="pass", amount_cents=500,
                                         currency="USD", status="pending", provider="stripe_sandbox", provider_ref=ref)


def _row(rec):
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in asdict(rec).items()}


@pytest.fixture
def polling(monkeypatch):
    user = CurrentUser(id="poll-user", email="poll@example.test")
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 30)
    monkeypatch.setattr(settings, "checkout_status_cache_seconds", 5)
    provider = MagicMock(return_value="pending")
    monkeypatch.setattr(StripeSandboxProvider, "get_status", provider)
    rec = _record()
    service._cache_checkout_session(rec, persisted=False)
    return rec, provider


@pytest.fixture
def workers(polling, monkeypatch):
    rec, provider = polling
    backend = PollingDatabase()
    backend.now_override = datetime.now(UTC)
    backend.checkout_sessions[rec.id] = _row(rec)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: backend)
    monkeypatch.setattr("api.limiter.get_supabase_client", lambda: backend)
    modules = []
    for index in range(2):
        # Separate globals, checkout caches and Python locks, as in separate workers.
        name = f"api.billing._poll_test_worker_{index}"
        spec = importlib.util.spec_from_file_location(name, service.__file__)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "get_supabase_client", lambda: backend)
        modules.append(module)
    assert modules[0]._reservations_lock is not modules[1]._reservations_lock
    return modules, backend, rec, provider


@pytest.mark.parametrize("route", ["checkout", "by-ref/cs_test_poll", "alternate"])
def test_rapid_polling_is_cached_and_account_limited(polling, monkeypatch, route):
    rec, provider = polling
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 3)
    with TestClient(app) as client:
        for index in range(4):
            path = "by-ref/cs_test_poll" if route == "alternate" and index % 2 else route
            if path == "alternate":
                path = rec.id
            response = client.get(f"/api/billing/checkout/{path}")
            assert response.status_code == (200 if index < 3 else 429)
    assert provider.call_count == 1


@pytest.mark.parametrize("path", ["checkout", "by-ref/cs_test_poll", "missing", "by-ref/missing"])
def test_ownership_checked_before_refresh_or_disclosure(polling, monkeypatch, path):
    rec, provider = polling
    rec.user_id = "someone-else"
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 1)
    with TestClient(app) as client:
        response = client.get(f"/api/billing/checkout/{path}")
        assert response.status_code == 404
        assert "cs_test_poll" not in response.text
        assert "someone-else" not in response.text
        assert client.get("/api/billing/checkout/by-ref/missing").status_code == 429
    provider.assert_not_called()


def test_concurrent_workers_share_budget_and_cache(workers, monkeypatch):
    modules, backend, rec, provider = workers
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 4)
    entered, release = threading.Event(), threading.Event()

    def slow_status(ref):
        entered.set()
        assert release.wait(5)
        return "pending"

    provider.side_effect = slow_status
    with ThreadPoolExecutor(max_workers=6) as pool:
        first = pool.submit(modules[0].get_checkout_status, rec.id, rec.user_id)
        try:
            assert entered.wait(5)
            # Other worker responds using stored status while the provider call is in flight.
            results = list(pool.map(lambda _: modules[1].get_checkout_status_by_ref(rec.provider_ref, rec.user_id), range(3)))
            assert all(result.status == "pending" for result in results)
            with pytest.raises(ApiError) as blocked:
                modules[1].get_checkout_status(rec.id, rec.user_id)
            assert blocked.value.status_code == 429
        finally:
            release.set()
        assert first.result(timeout=5).status == "pending"
    assert provider.call_count == 1
    reset_rate_limits()
    modules[1].reset_billing_memory()
    with pytest.raises(ApiError):
        modules[1].get_checkout_status_by_ref(rec.provider_ref, rec.user_id)
    backend.now_override += timedelta(minutes=1)
    assert modules[1].get_checkout_status(rec.id, rec.user_id).status == "pending"
    assert provider.call_count == 2


def test_cache_expires_at_configured_deadline_across_workers(workers):
    modules, backend, rec, provider = workers
    modules[0].get_checkout_status(rec.id, rec.user_id)
    modules[1].reset_billing_memory()
    backend.now_override += timedelta(seconds=4)
    modules[1].get_checkout_status_by_ref(rec.provider_ref, rec.user_id)
    assert provider.call_count == 1
    backend.now_override += timedelta(seconds=1)
    modules[1].get_checkout_status_by_ref(rec.provider_ref, rec.user_id)
    assert provider.call_count == 2


def test_provider_failures_have_shared_cooldown_then_recover(workers):
    modules, backend, rec, provider = workers
    provider.side_effect = RuntimeError("private Stripe error")
    for module in modules * 2:
        with pytest.raises(ApiError) as error:
            module.get_checkout_status(rec.id, rec.user_id)
        assert error.value.status_code == 503
        assert "private" not in error.value.message
    assert provider.call_count == 1
    backend.now_override += timedelta(seconds=5)
    provider.side_effect = None
    provider.return_value = "paid"
    assert modules[1].get_checkout_status_by_ref(rec.provider_ref, rec.user_id).status == "paid"
    assert len(backend.subscriptions) == 1


@pytest.mark.parametrize("path", ["checkout", "by-ref/cs_test_poll"])
@pytest.mark.parametrize("rpc", ["admit_checkout_status", "claim_checkout_status_refresh", "finish_checkout_status_refresh", "grant_checkout_pass"])
@pytest.mark.parametrize("malformed", [False, True])
def test_database_coordination_failures_return_safe_503(polling, monkeypatch, rpc, malformed, path):
    rec, provider = polling
    backend = PollingDatabase()
    backend.checkout_sessions[rec.id] = _row(rec)
    if malformed:
        backend.bad_result = rpc
    else:
        backend.fail_rpc_names.add(rpc)
    provider.return_value = "paid"
    monkeypatch.setattr(service, "get_supabase_client", lambda: backend)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: backend)
    monkeypatch.setattr("api.limiter.get_supabase_client", lambda: backend)
    with TestClient(app) as client:
        response = client.get(f"/api/billing/checkout/{path}")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "private" not in response.text
    assert provider.call_count == (0 if rpc in ("admit_checkout_status", "claim_checkout_status_refresh") else 1)
    assert not service._subscriptions
    assert not backend.status_hits or len(backend.status_hits[rec.user_id]) == 1


def test_paid_activation_retries_without_another_provider_call(workers):
    modules, backend, rec, provider = workers
    provider.return_value = "paid"
    backend.fail_rpc_names.add("grant_checkout_pass")
    with pytest.raises(DatabasePersistenceError):
        modules[0].get_checkout_status(rec.id, rec.user_id)
    assert backend.checkout_sessions[rec.id]["status"] == "paid"
    backend.fail_rpc_names.clear()
    for module in modules * 2:
        result = module.get_checkout_status_by_ref(rec.provider_ref, rec.user_id)
        assert result.status == "paid" and result.active_until is not None
    assert provider.call_count == len(backend.subscriptions) == 1


def test_simultaneous_status_admission_is_atomic_across_workers(workers, monkeypatch):
    modules, backend, rec, provider = workers
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 5)
    barrier = threading.Barrier(12)

    def poll(index):
        barrier.wait(timeout=5)
        module = modules[index % 2]
        try:
            if index % 2:
                module.get_checkout_status_by_ref(rec.provider_ref, rec.user_id)
            else:
                module.get_checkout_status(rec.id, rec.user_id)
            return True
        except ApiError as error:
            assert error.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(poll, range(12))) == 5
    assert len(backend.status_hits[rec.user_id]) == 5
    assert provider.call_count == 1


def test_limit_is_per_account_across_checkouts_and_applies_to_admins(workers, monkeypatch):
    modules, backend, rec, provider = workers
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 1)
    monkeypatch.setattr(settings, "admin_emails", "poll@example.test")
    second = _record(sid="second-checkout", ref="cs_test_second")
    other = _record(user="other-user", sid="other-checkout", ref="cs_test_other")
    for record in (second, other):
        backend.checkout_sessions[record.id] = _row(record)
    modules[0].get_checkout_status(rec.id, rec.user_id)
    with pytest.raises(ApiError) as blocked:
        modules[1].get_checkout_status_by_ref(second.provider_ref, rec.user_id)
    assert blocked.value.status_code == 429
    assert modules[1].get_checkout_status(other.id, other.user_id).status == "pending"
    assert provider.call_count == 2


def test_failed_completion_preserves_lease_until_recovery(workers):
    modules, backend, rec, provider = workers
    backend.fail_rpc_names.add("finish_checkout_status_refresh")
    provider.return_value = "paid"
    with pytest.raises(DatabasePersistenceError):
        modules[0].get_checkout_status(rec.id, rec.user_id)
    backend.fail_rpc_names.clear()
    assert modules[1].get_checkout_status_by_ref(rec.provider_ref, rec.user_id).status == "pending"
    assert provider.call_count == 1
    backend.now_override += timedelta(seconds=51)
    assert modules[1].get_checkout_status(rec.id, rec.user_id).status == "paid"
    assert provider.call_count == 2
    assert len(backend.subscriptions) == 1


@pytest.mark.parametrize("path", ["checkout", "by-ref/cs_test_poll"])
def test_required_database_initialization_failure_does_not_use_local_cache(polling, monkeypatch, path):
    _, provider = polling
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "persistence_mode", "required")
    monkeypatch.setattr(settings, "supabase_url", "invalid-url")
    # No lifespan: exercise request-time outage handling independently of startup validation.
    response = TestClient(app).get(f"/api/billing/checkout/{path}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    provider.assert_not_called()


@pytest.mark.parametrize("path", ["checkout", "by-ref/cs_test_poll"])
def test_required_checkout_lookup_failure_is_safe(polling, monkeypatch, path):
    _, provider = polling
    backend = PollingDatabase()
    monkeypatch.setattr(service, "get_supabase_client", lambda: backend)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: backend)
    monkeypatch.setattr("api.limiter.get_supabase_client", lambda: backend)
    monkeypatch.setattr(backend, "_execute_table", MagicMock(side_effect=RuntimeError("private database details")))
    response = TestClient(app).get(f"/api/billing/checkout/{path}")
    assert response.status_code == 503
    assert "private" not in response.text
    provider.assert_not_called()


@pytest.mark.parametrize("remote", ["pending", "expired"])
def test_webhook_paid_status_wins_over_inflight_poll(workers, remote):
    modules, backend, rec, provider = workers

    def webhook_during_poll(ref):
        modules[1].handle_stripe_checkout_completed(ref, {"user_id": rec.user_id}, 500)
        return remote

    provider.side_effect = webhook_during_poll
    result = modules[0].get_checkout_status(rec.id, rec.user_id)
    assert result.status == "paid" and result.active_until is not None
    assert backend.checkout_sessions[rec.id]["status"] == "paid"
    assert len(backend.subscriptions) == 1


def test_abandoned_lease_recovers_and_fences_old_worker(workers):
    modules, backend, rec, provider = workers
    snapshot, claimed, _ = modules[0]._claim_status_refresh(rec, "old-token")
    assert claimed
    assert modules[1].get_checkout_status(rec.id, rec.user_id).status == "pending"
    provider.assert_not_called()
    backend.now_override += timedelta(seconds=51)
    provider.return_value = "paid"
    assert modules[1].get_checkout_status(rec.id, rec.user_id).status == "paid"
    stale, _, _ = modules[0]._finish_status_refresh(snapshot, "old-token", "expired")
    assert stale.status == "paid"
    assert len(backend.subscriptions) == 1


@pytest.mark.parametrize("cached,remote", [(False, "pending"), (False, "paid"), (False, "error"), (True, "pending")])
def test_expiry_and_late_payment_handling(workers, cached, remote):
    modules, backend, rec, provider = workers
    if cached:
        modules[0].get_checkout_status(rec.id, rec.user_id)
    backend.checkout_sessions[rec.id]["expires_at"] = (backend._now() - timedelta(seconds=1)).isoformat()
    if remote == "error":
        provider.side_effect = RuntimeError("provider offline")
    else:
        provider.return_value = remote
    result = modules[1].get_checkout_status(rec.id, rec.user_id)
    assert result.status == ("paid" if remote == "paid" else "expired")
    assert provider.call_count == 1


def test_offline_cache_and_limiter_are_bounded(polling, monkeypatch):
    rec, provider = polling
    monkeypatch.setattr(settings, "checkout_cache_max_entries", 2)
    monkeypatch.setattr(settings, "checkout_status_requests_per_min", 100)
    for _ in range(20):
        service.get_checkout_status(rec.id, rec.user_id)
    assert provider.call_count == 1
    assert len(service._checkout_sessions) == 1
    limiter = SlidingWindowRateLimiter(max_buckets=2, evict_active=False)
    for user in ("one", "two"):
        limiter.check(user, 1)
    with pytest.raises(ApiError):
        limiter.check("three", 1)
    with pytest.raises(ApiError):
        limiter.check("one", 1)
    assert limiter.bucket_count() == 2


def test_offline_refreshes_are_coordinated_and_expire(polling, monkeypatch):
    rec, provider = polling
    clock = [datetime.now(UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(service, "datetime", Clock)
    entered, release = threading.Event(), threading.Event()

    def slow_status(ref):
        entered.set()
        assert release.wait(5)
        return "pending"

    provider.side_effect = slow_status
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.get_checkout_status, rec.id, rec.user_id)
        try:
            assert entered.wait(5)
            assert service.get_checkout_status_by_ref(rec.provider_ref, rec.user_id).status == "pending"
        finally:
            release.set()
        assert first.result(timeout=5).status == "pending"
    service.get_checkout_status(rec.id, rec.user_id)
    assert provider.call_count == 1
    clock[0] += timedelta(seconds=5)
    provider.side_effect = None
    provider.return_value = "paid"
    assert service.get_checkout_status(rec.id, rec.user_id).status == "paid"
    assert provider.call_count == 2
    assert len(service._subscriptions) == 1


def test_stripe_status_client_has_bounded_timeout_and_no_retries(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock_only")
    retrieve = MagicMock(return_value=SimpleNamespace(payment_status="paid", status="complete"))
    client = MagicMock(return_value=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(retrieve=retrieve))))
    transport = MagicMock()
    monkeypatch.setattr(stripe, "StripeClient", client)
    monkeypatch.setattr(stripe, "RequestsClient", transport)
    assert StripeSandboxProvider().get_status("cs_test_mock") == "paid"
    transport.assert_called_once_with(timeout=settings.checkout_status_provider_timeout_seconds)
    assert client.call_args.kwargs["max_network_retries"] == 0
    retrieve.assert_called_once_with("cs_test_mock")


@pytest.mark.parametrize("setting,value", [("checkout_status_requests_per_min", -1), ("checkout_status_requests_per_min", 10001),
                                           ("checkout_status_cache_seconds", 0), ("checkout_status_provider_timeout_seconds", 31)])
def test_polling_settings_validate_bounds(setting, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{setting: value})
