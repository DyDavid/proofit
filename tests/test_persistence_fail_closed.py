"""Required persistence must never become an empty local usage ledger on failure."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api import db
from api.auth import CurrentUser, get_current_user, get_optional_user
from api.billing import service
from api.config import settings
from api.errors import ApiError
from api.main import app
from api.quota import reserve_quota
from api.store import Store, store


@pytest.fixture
def required_db(monkeypatch):
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "persistence_mode", "required")
    monkeypatch.setattr(settings, "supabase_url", "https://synthetic.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "SYNTHETIC_SERVER_KEY")
    for field in ("supabase_service_role_key", "supabase_key"):
        monkeypatch.setattr(settings, field, None)
    for name in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(db, "_supabase_client", None)
    monkeypatch.setattr(db, "_supabase_client_config", None)
    factory = MagicMock()
    monkeypatch.setattr("supabase.create_client", factory)
    return factory


@pytest.mark.parametrize("engine,mode", [("mock", "required"), ("live", "offline")])
def test_explicit_offline_mode_is_the_only_local_fallback(required_db, monkeypatch, engine, mode):
    monkeypatch.setattr(settings, "engine_mode", engine)
    monkeypatch.setattr(settings, "persistence_mode", mode)
    monkeypatch.setattr(settings, "supabase_url", "invalid-placeholder")
    monkeypatch.setattr(settings, "supabase_service_key", None)
    assert db.validate_persistence_config() is None
    assert db.get_supabase_client() is None
    monkeypatch.setattr(settings, "enforce_quotas", True)
    assert reserve_quota("offline-user", "analysis")
    assert service._usage_reservations
    required_db.assert_not_called()


@pytest.mark.parametrize("url,key", [
    (None, None), (None, "key"), ("https://synthetic.supabase.co", None),
    ("invalid", "key"), ("https://REPLACE_ME.supabase.co", "key"),
    ("https://synthetic.supabase.co", "REPLACE_ME"),
    ("https://user:secret@synthetic.supabase.co", "key"),
])
def test_bad_configuration_rejected_at_startup_and_on_requests(required_db, monkeypatch, url, key):
    monkeypatch.setattr(settings, "supabase_url", url)
    monkeypatch.setattr(settings, "supabase_service_key", key)
    with pytest.raises(db.DatabasePersistenceError):
        db.get_supabase_client()
    with pytest.raises(db.DatabasePersistenceError), TestClient(app):
        pass
    required_db.assert_not_called()


def test_service_role_alias_and_client_cache_are_safe(required_db, monkeypatch):
    monkeypatch.setattr(settings, "supabase_service_key", None)
    monkeypatch.setattr(settings, "supabase_service_role_key", "SYNTHETIC_ROLE_KEY")
    assert db.get_supabase_client() is required_db.return_value
    assert db.get_supabase_client() is required_db.return_value
    required_db.assert_called_once_with("https://synthetic.supabase.co", "SYNTHETIC_ROLE_KEY")


@pytest.mark.parametrize("failure", ["initialization", "query"])
@pytest.mark.parametrize("operation", ["create", "retry", "rewrite", "guest_create", "guest_retry", "subscription"])
def test_affected_requests_fail_safely_without_scheduling_work(required_db, monkeypatch, caplog, failure, operation):
    monkeypatch.setattr(settings, "enforce_quotas", True)
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    user = None if operation.startswith("guest") else CurrentUser(id="required-user", email="user@example.test")
    monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: user)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    # Seed isolated cache entries while the database accessor is explicitly mocked out.
    with patch("api.store.get_supabase_client", return_value=None):
        resume = store.add_resume("resume.txt", "application/pdf", 1, data=b"x", user_id=user.id if user else None)
        job, _ = store.add_job("Synthetic software engineer job requiring Python and database skills.", source="text")
        original = store.create_analysis(resume.id, job.id, "KH", user_id=user.id if user else None)
        original.status = "done"
        original.match = store.pick_fixture(job.id)
    secret = "SYNTHETIC_SERVER_KEY https://provider.invalid/private-token"
    if failure == "initialization":
        required_db.side_effect = RuntimeError(secret)
    else:
        # All chained table operations and RPCs raise on execute.
        query = MagicMock()
        for method in ("select", "eq", "gt", "gte", "lte", "order", "limit", "maybe_single"):
            getattr(query, method).return_value = query
        query.execute.side_effect = RuntimeError(secret)
        required_db.return_value.table.return_value = query
        required_db.return_value.rpc.return_value.execute.side_effect = RuntimeError(secret)
    runner = AsyncMock()
    detector = MagicMock()
    monkeypatch.setattr("api.routes.analyses._run_live_analysis", runner)
    monkeypatch.setattr("api.routes.analyses.detect_hidden_strengths", detector)
    before = set(store.analyses)
    with TestClient(app) as client:
        if operation in ("create", "guest_create"):
            response = client.post("/api/analyses", json={"resume_id": resume.id, "job_id": job.id, "country": "KH"})
        elif operation in ("retry", "guest_retry"):
            response = client.post(f"/api/analyses/{original.id}/retry")
        elif operation == "rewrite":
            response = client.post(f"/api/analyses/{original.id}/rewrites")
        else:
            response = client.get("/api/billing/subscription")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "SYNTHETIC_SERVER_KEY" not in response.text + caplog.text
    assert "private-token" not in response.text + caplog.text
    assert set(store.analyses) == before
    assert not service._usage_reservations
    assert not service._usage_events
    runner.assert_not_called()
    detector.assert_not_called()


def test_initializer_recovers_without_creating_local_usage(required_db, monkeypatch):
    monkeypatch.setattr(settings, "enforce_quotas", True)
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.gt.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    client.rpc.return_value.execute.return_value.data = {"allowed": True}
    required_db.side_effect = [RuntimeError("synthetic failure"), client]
    with pytest.raises(ApiError) as unavailable:
        reserve_quota("recovering-user", "analysis")
    assert unavailable.value.status_code == 503
    assert not service._usage_reservations
    assert reserve_quota("recovering-user", "analysis", reservation_id="same-reservation") == "same-reservation"
    assert not service._usage_reservations
    assert client.rpc.call_args.args[0] == "reserve_user_quota"
    assert client.rpc.call_args.args[1]["p_reservation_id"] == "same-reservation"


def test_unknown_commit_outcome_is_retried_with_same_id(required_db):
    committed = set()
    rpc = required_db.return_value.rpc
    calls = []

    def execute():
        calls.append(rpc.call_args.kwargs if rpc.call_args.kwargs else rpc.call_args.args[1])
        committed.add(calls[-1]["p_reservation_id"])
        if len(calls) == 1:
            raise RuntimeError("response lost after commit")
        result = MagicMock()
        result.data = {"committed": True, "status": "already_committed"}
        return result

    rpc.return_value.execute.side_effect = execute
    with pytest.raises(db.DatabasePersistenceError):
        service.commit_usage_reservation("stable-id", "user", "analysis")
    assert not service._usage_events
    service.commit_usage_reservation("stable-id", "user", "analysis")
    assert committed == {"stable-id"}
    assert not service._usage_events
    assert service._finalized_reservations["stable-id"] == "committed"


def test_all_workers_reject_initialization_failure(required_db, monkeypatch):
    monkeypatch.setattr(settings, "enforce_quotas", True)
    required_db.side_effect = RuntimeError("synthetic failure")

    def reserve(_):
        try:
            reserve_quota("same-user", "analysis")
        except ApiError as exc:
            return exc.status_code
        return 200

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(reserve, range(8))) == [503] * 8
    assert not service._usage_reservations


def test_failed_counts_writes_and_guest_releases_do_not_use_local_cache(required_db):
    client = required_db.return_value
    client.table.return_value.select.return_value.eq.return_value.execute.side_effect = RuntimeError("synthetic failure")
    isolated = Store()
    with pytest.raises(db.DatabasePersistenceError):
        isolated.count_user_resumes("user")
    client.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("synthetic failure")
    with pytest.raises(db.DatabasePersistenceError):
        isolated.add_resume("r.txt", "application/pdf", 1, data=b"x", user_id="user")
    assert not isolated.resumes
    with pytest.raises(db.DatabasePersistenceError):
        isolated.create_analysis("r", "j", "KH", user_id="user")
    assert not isolated.analyses
    isolated.guest_ip_usage["synthetic-hash"] = service.datetime.now(service.UTC)
    client.rpc.return_value.execute.side_effect = RuntimeError("synthetic failure")
    with pytest.raises(db.DatabasePersistenceError):
        isolated.release_guest_ip_usage("synthetic-hash")
    assert "synthetic-hash" in isolated.guest_ip_usage
