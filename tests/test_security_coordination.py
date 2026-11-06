"""Shared admission, bounded durable jobs, and atomic webhook RPC contracts."""

import copy
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from test_multiworker_concurrency import SharedDatabaseBackend

from api import admission
from api.billing import service
from api.config import settings
from api.db import DatabasePersistenceError
from api.errors import ApiError
from api.main import app
from api.store import AnalysisRecord, Store


class SecurityDatabase(SharedDatabaseBackend):
    """Database double: locks and rollback belong to the DB, not worker Python locks."""

    def __init__(self):
        super().__init__()
        self.buckets = {}
        self.completed_events = set()
        self.fail_grant = False

    def _execute_rpc(self, name, p):
        if self.fail_all or name in self.fail_rpc_names:
            raise RuntimeError("private database error")
        with self._db_lock:
            now = self._now()
            if name == "admit_resource_request":
                self.buckets = {key: [ts for ts in hits if ts > now - timedelta(minutes=1)]
                                for key, hits in self.buckets.items()}
                key = p["p_scope"], p["p_subject"]
                global_key = p["p_scope"], "*"
                client = self.buckets.get(key, [])
                total = self.buckets.get(global_key, [])
                allowed = len(client) < p["p_limit"] and len(total) < p["p_global_limit"]
                if allowed:
                    self.buckets[key] = [*client, now]
                    self.buckets[global_key] = [*total, now]
                return SimpleNamespace(data={"allowed": allowed})
            if name == "submit_bounded_job":
                referenced = {a["job_id"] for a in self.analyses.values()}
                self.jobs = {key: row for key, row in self.jobs.items() if key in referenced
                             or datetime.fromisoformat(row["created_at"]) > now - timedelta(hours=p["p_retention_hours"])}
                for row in self.jobs.values():
                    if row["content_hash"] == p["p_hash"]:
                        return SimpleNamespace(data={"allowed": True, "cached": True, "job": copy.deepcopy(row)})
                if sum(key not in referenced for key in self.jobs) >= p["p_max_unused"]:
                    return SimpleNamespace(data={"allowed": False})
                row = {"id": p["p_id"], "content_hash": p["p_hash"], "raw": p["p_raw"],
                       "source": p["p_source"], "created_at": now.isoformat()}
                self.jobs[row["id"]] = row
                return SimpleNamespace(data={"allowed": True, "cached": False, "job": copy.deepcopy(row)})
            if name == "process_stripe_checkout_event":
                if p["p_event_id"] in self.completed_events:
                    return SimpleNamespace(data={"processed": False})
                before_sessions = copy.deepcopy(self.checkout_sessions)
                before_subs = copy.deepcopy(self.subscriptions)
                try:
                    row = next(r for r in self.checkout_sessions.values() if r["provider_ref"] == p["p_provider_ref"])
                    assert row["provider"] == "stripe_sandbox" and row["user_id"] == p["p_user_id"]
                    assert row["amount_cents"] == p["p_amount"]
                    row["status"] = "paid"
                    if self.fail_grant:
                        raise RuntimeError("transient grant failure")
                    super()._execute_rpc("grant_checkout_pass", {"p_session_id": row["id"], "p_period_days": 30})
                    self.completed_events.add(p["p_event_id"])
                    return SimpleNamespace(data={"processed": True})
                except Exception:
                    self.checkout_sessions = before_sessions
                    self.subscriptions = before_subs
                    raise
        return super()._execute_rpc(name, p)


@pytest.fixture
def database(monkeypatch):
    backend = SecurityDatabase()
    backend.now_override = datetime.now(UTC)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: backend)
    monkeypatch.setattr("api.store.get_supabase_client", lambda: backend)
    monkeypatch.setattr(admission, "get_supabase_client", lambda: backend)
    return backend


@pytest.mark.parametrize("scope", ["jobs", "auth"])
def test_shared_budget_is_atomic_and_survives_worker_memory_reset(database, scope):
    def request(_):
        try:
            admission.admit_request(scope, "same-client", 3, 10)
            return True
        except ApiError as exc:
            assert exc.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(request, range(16))) == 3
    admission.reset_admission()
    assert not request(None)
    assert len(database.buckets[scope, "same-client"]) == 3
    database.now_override += timedelta(minutes=1)
    assert request(None)
    assert not admission._buckets


def test_global_budgets_bound_many_clients_and_scopes_are_separate(database):
    admission.admit_request("jobs", "first", 10, 1)
    with pytest.raises(ApiError):
        admission.admit_request("jobs", "another", 10, 1)
    admission.admit_request("auth", "another", 10, 1)


@pytest.mark.parametrize("scope", ["auth", "jobs"])
@pytest.mark.parametrize("malformed", [False, True])
def test_required_admission_errors_fail_closed(database, monkeypatch, scope, malformed):
    if malformed:
        monkeypatch.setattr(admission, "db_billing_rpc", lambda *args: {"allowed": "yes"})
    else:
        database.fail_all = True
    with pytest.raises(DatabasePersistenceError):
        admission.admit_request(scope, "client", 2, 5)
    assert not admission._buckets


def test_offline_admission_buckets_do_not_evict_active_limits(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(admission, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(admission, "MAX_BUCKETS_PER_SCOPE", 2)
    admission.admit_request("jobs", "one", 1, 10)
    for client in ("two", "one"):
        with pytest.raises(ApiError):
            admission.admit_request("jobs", client, 1, 10)
    clock[0] = 60
    admission.admit_request("jobs", "two", 1, 10)
    assert len(admission._buckets) == 2


def test_durable_job_capacity_and_dedup_are_atomic_across_stores(database, monkeypatch):
    monkeypatch.setattr(settings, "job_unused_max_entries", 2)
    workers = [Store() for _ in range(4)]

    def submit(index):
        try:
            return workers[index % 4].add_job(f"Unique software engineer description {index}", "text")[0]
        except ApiError as exc:
            assert exc.status_code == 429
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [row for row in pool.map(submit, range(12)) if row is not None]
    assert len(rows) == len(database.jobs) == 2
    record, cached = workers[3].add_job(rows[0].raw.upper(), "text")
    assert cached and record.id == rows[0].id


def test_expired_unused_jobs_are_removed_but_referenced_jobs_survive(database):
    first = Store()
    retained, _ = first.add_job("retained", "text")
    unused, _ = first.add_job("unused", "text")
    database.analyses["analysis"] = {"job_id": retained.id}
    database.now_override += timedelta(hours=25)
    Store().add_job("new", "text")
    assert retained.id in database.jobs
    assert unused.id not in database.jobs


def test_offline_cleanup_preserves_referenced_jobs_and_bounds_storage(monkeypatch):
    local = Store(max_jobs_cache=1)
    job, _ = local.add_job("retained", "text")
    job.created_at -= timedelta(days=2)
    local.analyses["analysis"] = AnalysisRecord(id="analysis", resume_id="resume", job_id=job.id,
                                               country="KH", user_id="owner", status="done")
    with pytest.raises(ApiError):
        local.add_job("another", "text")
    assert local.get_job(job.id) is job


def test_both_job_routes_share_admission_budget_before_fetch(monkeypatch):
    monkeypatch.setattr(settings, "job_requests_per_min", 1)
    client = TestClient(app)
    assert client.post("/api/jobs", json={"text": "A software engineering position requiring Python and SQL."}).status_code == 200
    assert client.post("/api/jobs/fetch-url", json={"url": "https://example.test/job"}).status_code == 429


def test_job_rpc_failure_does_not_populate_worker_cache(database):
    database.fail_rpc_names.add("submit_bounded_job")
    local = Store()
    with pytest.raises(DatabasePersistenceError):
        local.add_job("job text", "text")
    assert not local.jobs


def test_webhook_transaction_rolls_back_and_independent_worker_retries(database, monkeypatch):
    rec = service.CheckoutSessionRecord(id="checkout", user_id="owner", plan_id="pass", amount_cents=500,
                                         currency="USD", status="pending", provider="stripe_sandbox", provider_ref="cs_test")
    database.checkout_sessions[rec.id] = {"id": rec.id, "user_id": rec.user_id, "provider": rec.provider,
                                        "provider_ref": rec.provider_ref, "status": "pending", "amount_cents": 500}
    workers = []
    for index in range(2):
        name = f"api.billing._webhook_security_worker_{index}"
        spec = importlib.util.spec_from_file_location(name, service.__file__)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "get_supabase_client", lambda: database)
        workers.append(module)
    assert workers[0]._reservations_lock is not workers[1]._reservations_lock
    data = {"id": rec.provider_ref, "metadata": {"user_id": "owner"}, "amount_total": 500, "payment_status": "paid"}
    database.fail_grant = True
    with pytest.raises(DatabasePersistenceError):
        workers[0].process_stripe_event("evt", "checkout.session.completed", data)
    assert database.checkout_sessions[rec.id]["status"] == "pending"
    assert not database.completed_events and not database.subscriptions
    database.fail_grant = False
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda index: workers[index % 2].process_stripe_event("evt", "checkout.session.completed", data), range(8)))
    assert sum(results) == len(database.subscriptions) == 1
    assert not any(worker._stripe_events for worker in workers)


@pytest.mark.parametrize("response", [{}, {"processed": "true"}])
def test_malformed_webhook_rpc_is_not_acknowledged(database, monkeypatch, response):
    monkeypatch.setattr(service, "get_supabase_client", lambda: database)
    monkeypatch.setattr(service, "db_billing_rpc", MagicMock(return_value=response))
    with pytest.raises(DatabasePersistenceError):
        service.process_stripe_event("evt", "ignored", {})
    assert not service._stripe_events
