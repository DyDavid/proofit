"""Phase 4 Multi-Worker Concurrency & Persistence Safety Tests.

Verifies that retries, user quotas, guest IP limits, idempotent reservation
completion/release, abandoned work recovery, stale cache invalidation, and
fail-closed persistence errors are safe across multiple independent workers
sharing database persistence (without sharing Python process locks).
"""

from __future__ import annotations

import concurrent.futures
import copy
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.billing import service as billing_service
from api.billing.service import (
    commit_usage_reservation,
    get_subscription_summary,
    release_usage_reservation,
    reset_billing_memory,
)
from api.config import settings
from api.errors import ApiError
from api.limiter import enforce_operation_attempt_limit, reset_rate_limits
from api.quota import check_quota, release_quota, reserve_quota
from api.store import Store

# ============================================================================
# Shared Persistence Test Double (Models PostgreSQL Tables + Phase 4 RPCs)
# ============================================================================


class _MockExecuteResult:
    def __init__(self, data: Any = None, count: int | None = None) -> None:
        self.data = data
        self.count = count


class _SharedTableQuery:
    """Thread-safe PostgREST table query builder backed by SharedDatabaseBackend."""

    def __init__(self, backend: SharedDatabaseBackend, table_name: str) -> None:
        self._backend = backend
        self._table = table_name
        self._op: str = "select"
        self._payload: Any = None
        self._count_mode: str | None = None
        self._maybe_single: bool = False
        self._filters: list[tuple[str, str, Any]] = []
        self._order_col: str | None = None
        self._order_desc: bool = False
        self._limit_val: int | None = None

    def select(self, _columns: str = "*", count: str | None = None) -> _SharedTableQuery:
        self._op = "select"
        self._count_mode = count
        return self

    def insert(self, payload: Any) -> _SharedTableQuery:
        self._op = "insert"
        self._payload = copy.deepcopy(payload)
        return self

    def upsert(self, payload: Any) -> _SharedTableQuery:
        self._op = "upsert"
        self._payload = copy.deepcopy(payload)
        return self

    def update(self, payload: dict[str, Any]) -> _SharedTableQuery:
        self._op = "update"
        self._payload = copy.deepcopy(payload)
        return self

    def delete(self) -> _SharedTableQuery:
        self._op = "delete"
        return self

    def eq(self, col: str, val: Any) -> _SharedTableQuery:
        self._filters.append(("eq", col, val))
        return self

    def gt(self, col: str, val: Any) -> _SharedTableQuery:
        self._filters.append(("gt", col, val))
        return self

    def gte(self, col: str, val: Any) -> _SharedTableQuery:
        self._filters.append(("gte", col, val))
        return self

    def lte(self, col: str, val: Any) -> _SharedTableQuery:
        self._filters.append(("lte", col, val))
        return self

    def in_(self, col: str, vals: list[Any]) -> _SharedTableQuery:
        self._filters.append(("in", col, list(vals)))
        return self

    def order(self, col: str, desc: bool = False) -> _SharedTableQuery:
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int) -> _SharedTableQuery:
        self._limit_val = n
        return self

    def maybe_single(self) -> _SharedTableQuery:
        self._maybe_single = True
        return self

    def execute(self) -> _MockExecuteResult:
        return self._backend._execute_table(self)


class _SharedRpcCall:
    def __init__(self, backend: SharedDatabaseBackend, fn_name: str, params: dict[str, Any]) -> None:
        self._backend = backend
        self._fn_name = fn_name
        self._params = copy.deepcopy(params)

    def execute(self) -> _MockExecuteResult:
        return self._backend._execute_rpc(self._fn_name, self._params)


def _parse_iso(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=UTC)
    s = str(val).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class SharedDatabaseBackend:
    """Thread-safe shared database simulating PostgreSQL row locks, advisory locks,
    and the SQL functions defined in `004_phase4_multiworker_concurrency.sql`.
    """

    analyses: dict[str, dict[str, Any]] = field(default_factory=dict)
    resumes: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    subscriptions: list[dict[str, Any]] = field(default_factory=list)
    usage_events: list[dict[str, Any]] = field(default_factory=list)
    usage_reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    guest_ip_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    checkout_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    operation_attempts: dict[str, list[datetime]] = field(default_factory=dict)
    fail_all: bool = False
    fail_rpc_names: set[str] = field(default_factory=set)
    now_override: datetime | None = None
    _db_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def _now(self) -> datetime:
        return self.now_override or datetime.now(UTC)

    def table(self, name: str) -> _SharedTableQuery:
        return _SharedTableQuery(self, name)

    def rpc(self, fn_name: str, params: dict[str, Any]) -> _SharedRpcCall:
        return _SharedRpcCall(self, fn_name, params)

    def _matches(self, row: dict[str, Any], filters: list[tuple[str, str, Any]]) -> bool:
        for op, col, val in filters:
            rv = row.get(col)
            if op == "eq":
                if rv != val:
                    return False
            elif op == "gt":
                if rv is None or _parse_iso(rv) <= _parse_iso(val):
                    return False
            elif op == "gte":
                if rv is None or _parse_iso(rv) < _parse_iso(val):
                    return False
            elif op == "lte":
                if rv is None or _parse_iso(rv) > _parse_iso(val):
                    return False
            elif op == "in" and rv not in val:
                return False
        return True

    def _get_rows(self, table: str) -> list[dict[str, Any]]:
        if table == "analyses":
            return list(self.analyses.values())
        if table == "resumes":
            return list(self.resumes.values())
        if table == "jobs":
            return list(self.jobs.values())
        if table == "subscriptions":
            return list(self.subscriptions)
        if table == "usage_events":
            return list(self.usage_events)
        if table == "usage_reservations":
            return list(self.usage_reservations.values())
        if table == "guest_ip_usage":
            return list(self.guest_ip_usage.values())
        if table == "checkout_sessions":
            return list(self.checkout_sessions.values())
        return []

    def _execute_table(self, q: _SharedTableQuery) -> _MockExecuteResult:
        if self.fail_all:
            raise RuntimeError(f"Simulated database outage on table {q._table}")

        with self._db_lock:
            now_iso = self._now().isoformat()
            if q._op == "select":
                rows = [
                    copy.deepcopy(r)
                    for r in self._get_rows(q._table)
                    if self._matches(r, q._filters)
                ]
                if q._order_col:
                    rows.sort(
                        key=lambda r: r.get(q._order_col) or "",
                        reverse=q._order_desc,
                    )
                if q._limit_val is not None:
                    rows = rows[: q._limit_val]
                if q._maybe_single:
                    return _MockExecuteResult(data=rows[0] if rows else None)
                return _MockExecuteResult(
                    data=rows,
                    count=len(rows) if q._count_mode == "exact" else None,
                )

            if q._op in ("insert", "upsert"):
                items = q._payload if isinstance(q._payload, list) else [q._payload]
                for item in items:
                    row = copy.deepcopy(item)
                    row.setdefault("created_at", now_iso)
                    if q._table == "analyses":
                        self.analyses[str(row["id"])] = row
                    elif q._table == "resumes":
                        self.resumes[str(row["id"])] = row
                    elif q._table == "jobs":
                        self.jobs[str(row["id"])] = row
                    elif q._table == "subscriptions":
                        self.subscriptions.append(row)
                    elif q._table == "usage_events":
                        res_id = row.get("reservation_id")
                        if res_id and any(
                            e.get("reservation_id") == res_id for e in self.usage_events
                        ):
                            continue
                        self.usage_events.append(row)
                    elif q._table == "usage_reservations":
                        self.usage_reservations[str(row["id"])] = row
                    elif q._table == "guest_ip_usage":
                        self.guest_ip_usage[str(row["ip_hash"])] = row
                    elif q._table == "checkout_sessions":
                        self.checkout_sessions[str(row["id"])] = row
                return _MockExecuteResult(data=items)

            if q._op == "update":
                updated = []
                for row in self._get_rows(q._table):
                    if self._matches(row, q._filters):
                        row.update(copy.deepcopy(q._payload))
                        updated.append(copy.deepcopy(row))
                return _MockExecuteResult(data=updated)

            if q._op == "delete":
                if q._table == "guest_ip_usage":
                    to_del = [
                        k
                        for k, v in self.guest_ip_usage.items()
                        if self._matches(v, q._filters)
                    ]
                    for k in to_del:
                        self.guest_ip_usage.pop(k, None)
                return _MockExecuteResult(data=[])

            return _MockExecuteResult(data=[])

    def _execute_rpc(self, fn_name: str, params: dict[str, Any]) -> _MockExecuteResult:
        if self.fail_all or fn_name in self.fail_rpc_names:
            raise RuntimeError(f"Simulated database RPC failure in {fn_name}")

        with self._db_lock:
            now = self._now()
            now_iso = now.isoformat()

            if fn_name == "reserve_analysis_attempt":
                subject = params["p_subject"]
                attempts = [ts for ts in self.operation_attempts.get(subject, [])
                            if ts > now - timedelta(hours=1)]
                allowed = len(attempts) < params["p_limit"]
                if allowed:
                    attempts.append(now)
                self.operation_attempts[subject] = attempts
                return _MockExecuteResult(data={"allowed": allowed})

            if fn_name == "reserve_checkout_session":
                for row in self.checkout_sessions.values():
                    if (row["user_id"] == params["p_user_id"] and row["provider"] == params["p_provider"]
                            and row["status"] == "pending" and _parse_iso(row["expires_at"]) > now):
                        return _MockExecuteResult(data={"created": False, "session": copy.deepcopy(row)})
                row = {
                    "id": params["p_session_id"], "user_id": params["p_user_id"], "plan_id": "pass",
                    "amount_cents": params["p_amount_cents"], "currency": params["p_currency"],
                    "status": "pending", "provider": params["p_provider"], "provider_ref": None,
                    "checkout_url": None, "expires_at": (now + timedelta(minutes=30)).isoformat(),
                    "created_at": now_iso, "paid_at": None,
                }
                self.checkout_sessions[row["id"]] = row
                return _MockExecuteResult(data={"created": True, "session": copy.deepcopy(row)})

            if fn_name == "grant_checkout_pass":
                session = self.checkout_sessions[params["p_session_id"]]
                if session["status"] != "paid":
                    raise RuntimeError("Checkout is not paid")
                for sub in self.subscriptions:
                    if sub.get("checkout_session_id") == session["id"]:
                        return _MockExecuteResult(data={"subscription": copy.deepcopy(sub)})
                start = max([now] + [_parse_iso(s["current_period_end"]) for s in self.subscriptions
                                     if s["user_id"] == session["user_id"]])
                sub = {
                    "id": f"sub-{len(self.subscriptions)}", "user_id": session["user_id"],
                    "plan_id": "pass", "current_period_start": start.isoformat(),
                    "current_period_end": (start + timedelta(days=params["p_period_days"])).isoformat(),
                    "provider": session["provider"], "checkout_session_id": session["id"],
                }
                self.subscriptions.append(sub)
                return _MockExecuteResult(data={"subscription": copy.deepcopy(sub)})

            if fn_name == "reserve_user_quota":
                user_id = str(params["p_user_id"])
                kind = str(params["p_kind"])
                rid = str(params["p_reservation_id"])
                limit = params.get("p_limit")
                window_start = _parse_iso(params["p_window_start"])
                expires_at_iso = str(params["p_expires_at"])

                existing = self.usage_reservations.get(rid)
                if (
                    existing
                    and existing["status"] == "active"
                    and _parse_iso(existing["expires_at"]) > now
                ):
                    return _MockExecuteResult(
                        data={"allowed": True, "reservation_id": rid, "idempotent": True}
                    )

                # Auto-expire old reservations for this user
                for r in self.usage_reservations.values():
                    if (
                        r["user_id"] == user_id
                        and r["kind"] == kind
                        and r["status"] == "active"
                        and _parse_iso(r["expires_at"]) <= now
                    ):
                        r["status"] = "released"

                if limit is None:
                    self.usage_reservations[rid] = {
                        "id": rid,
                        "user_id": user_id,
                        "kind": kind,
                        "status": "active",
                        "created_at": now_iso,
                        "expires_at": expires_at_iso,
                    }
                    return _MockExecuteResult(
                        data={"allowed": True, "reservation_id": rid, "used": 0, "limit": None}
                    )

                used_events = sum(
                    1
                    for ev in self.usage_events
                    if ev["user_id"] == user_id
                    and ev["kind"] == kind
                    and _parse_iso(ev["created_at"]) >= window_start
                )
                active_res = sum(
                    1
                    for r in self.usage_reservations.values()
                    if r["user_id"] == user_id
                    and r["kind"] == kind
                    and r["status"] == "active"
                    and _parse_iso(r["expires_at"]) > now
                    and _parse_iso(r["created_at"]) >= window_start
                )
                total = used_events + active_res
                if total >= int(limit):
                    return _MockExecuteResult(
                        data={
                            "allowed": False,
                            "code": "quota_exceeded",
                            "used": total,
                            "limit": int(limit),
                        }
                    )

                self.usage_reservations[rid] = {
                    "id": rid,
                    "user_id": user_id,
                    "kind": kind,
                    "status": "active",
                    "created_at": now_iso,
                    "expires_at": expires_at_iso,
                }
                return _MockExecuteResult(
                    data={
                        "allowed": True,
                        "reservation_id": rid,
                        "used": total + 1,
                        "limit": int(limit),
                    }
                )

            if fn_name == "commit_usage_reservation":
                rid = params.get("p_reservation_id")
                user_id = params.get("p_user_id")
                kind = str(params.get("p_kind") or "analysis")

                if rid is not None:
                    res_row = self.usage_reservations.get(str(rid))
                    if res_row is None:
                        if user_id and not any(
                            e.get("reservation_id") == rid for e in self.usage_events
                        ):
                            self.usage_events.append(
                                {
                                    "user_id": str(user_id),
                                    "kind": kind,
                                    "reservation_id": str(rid),
                                    "created_at": now_iso,
                                }
                            )
                        return _MockExecuteResult(
                            data={"committed": True, "status": "untracked_committed"}
                        )
                    if res_row["status"] == "committed":
                        return _MockExecuteResult(
                            data={"committed": True, "status": "already_committed"}
                        )
                    if res_row["status"] == "released":
                        return _MockExecuteResult(
                            data={"committed": False, "status": "already_released"}
                        )
                    res_row["status"] = "committed"
                    if not any(e.get("reservation_id") == rid for e in self.usage_events):
                        self.usage_events.append(
                            {
                                "user_id": res_row["user_id"],
                                "kind": res_row["kind"],
                                "reservation_id": str(rid),
                                "created_at": now_iso,
                            }
                        )
                    return _MockExecuteResult(data={"committed": True, "status": "committed"})

                if user_id:
                    self.usage_events.append(
                        {"user_id": str(user_id), "kind": kind, "created_at": now_iso}
                    )
                return _MockExecuteResult(data={"committed": True, "status": "direct_event"})

            if fn_name == "release_usage_reservation":
                rid = params.get("p_reservation_id")
                if rid is None:
                    return _MockExecuteResult(data={"released": True, "status": "no_reservation"})
                res_row = self.usage_reservations.get(str(rid))
                if res_row is None:
                    return _MockExecuteResult(data={"released": True, "status": "not_found"})
                if res_row["status"] == "committed":
                    return _MockExecuteResult(
                        data={"released": False, "status": "already_committed"}
                    )
                if res_row["status"] == "released":
                    return _MockExecuteResult(
                        data={"released": True, "status": "already_released"}
                    )
                res_row["status"] = "released"
                return _MockExecuteResult(data={"released": True, "status": "released"})

            if fn_name == "claim_analysis_retry":
                orig_id = str(params["p_original_id"])
                child_id = str(params["p_child_id"])
                abandoned_secs = max(1, int(params.get("p_abandoned_seconds", 600)))
                cutoff = now - timedelta(seconds=abandoned_secs)

                orig = self.analyses.get(orig_id)
                if orig is None:
                    return _MockExecuteResult(
                        data={"success": False, "code": "ANALYSIS_NOT_FOUND"}
                    )

                if orig["status"] in ("queued", "running"):
                    if _parse_iso(orig["created_at"]) <= cutoff:
                        orig["status"] = "failed"
                        orig["error_message"] = "Analysis timed out or was abandoned."
                        orig_res_id = orig.get("reservation_id")
                        if (
                            orig_res_id
                            and orig_res_id in self.usage_reservations
                            and self.usage_reservations[orig_res_id]["status"] == "active"
                        ):
                            self.usage_reservations[orig_res_id]["status"] = "released"
                    else:
                        return _MockExecuteResult(
                            data={
                                "success": False,
                                "code": "ANALYSIS_IN_PROGRESS",
                                "message": "Cannot retry an analysis that is still queued or running.",
                            }
                        )

                retried_by = orig.get("retried_by")
                if retried_by:
                    child = self.analyses.get(str(retried_by))
                    if child and child["status"] in ("queued", "running"):
                        if _parse_iso(child["created_at"]) > cutoff:
                            return _MockExecuteResult(
                                data={
                                    "success": False,
                                    "code": "ANALYSIS_IN_PROGRESS",
                                    "message": "A retry for this analysis is already in progress.",
                                    "active_retry_id": child["id"],
                                }
                            )
                        # Abandoned child: mark failed and release its active reservation
                        child["status"] = "failed"
                        child["error_message"] = "Analysis timed out or was abandoned."
                        c_res_id = child.get("reservation_id")
                        if (
                            c_res_id
                            and c_res_id in self.usage_reservations
                            and self.usage_reservations[c_res_id]["status"] == "active"
                        ):
                            self.usage_reservations[c_res_id]["status"] = "released"

                new_row = {
                    "id": child_id,
                    "resume_id": params.get("p_resume_id") or orig["resume_id"],
                    "job_id": params.get("p_job_id") or orig["job_id"],
                    "country": params.get("p_country") or orig["country"],
                    "status": "queued",
                    "user_id": params.get("p_user_id") or orig.get("user_id"),
                    "reservation_id": params.get("p_reservation_id"),
                    "retried_by": None,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
                self.analyses[child_id] = new_row
                orig["retried_by"] = child_id
                orig["updated_at"] = now_iso
                return _MockExecuteResult(
                    data={"success": True, "analysis_id": child_id, "status": "queued"}
                )

            if fn_name == "reserve_guest_usage":
                ip_hash = str(params["p_ip_hash"])
                ttl_hours = max(0.01, float(params.get("p_ttl_hours", 24.0)))
                cutoff = now - timedelta(hours=ttl_hours)

                rec = self.guest_ip_usage.get(ip_hash)
                prev_ts = None
                if rec is not None:
                    last_at = _parse_iso(rec["last_analysis_at"])
                    if last_at > cutoff:
                        return _MockExecuteResult(
                            data={
                                "allowed": False,
                                "last_analysis_at": rec["last_analysis_at"],
                            }
                        )
                    prev_ts = rec["last_analysis_at"]

                self.guest_ip_usage[ip_hash] = {
                    "ip_hash": ip_hash,
                    "last_analysis_at": now_iso,
                }
                return _MockExecuteResult(
                    data={
                        "allowed": True,
                        "last_analysis_at": now_iso,
                        "prev_last_analysis_at": prev_ts,
                    }
                )

            if fn_name == "release_guest_usage":
                ip_hash = str(params["p_ip_hash"])
                prev_iso = params.get("p_prev_last_analysis_at")
                if prev_iso is not None:
                    self.guest_ip_usage[ip_hash] = {
                        "ip_hash": ip_hash,
                        "last_analysis_at": str(prev_iso),
                    }
                else:
                    self.guest_ip_usage.pop(ip_hash, None)
                return _MockExecuteResult(data={"released": True})

            raise ValueError(f"Unknown RPC function: {fn_name}")


@pytest.fixture(autouse=True)
def _setup_phase4_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enforce_quotas", True)
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    monkeypatch.setattr(settings, "analysis_abandoned_timeout_seconds", 600.0)
    monkeypatch.setattr(settings, "reservation_ttl_seconds", 600.0)
    reset_billing_memory()


# ============================================================================
# 1. Duplicate Active Retries Across Independent Workers
# ============================================================================


def test_independent_workers_prevent_duplicate_active_retries() -> None:
    """Two or more independent worker Store instances (each with its own Python
    lock and local memory cache) attempting to retry the same original analysis
    concurrently must result in exactly ONE active retry in shared persistence.
    """
    shared_db = SharedDatabaseBackend()
    # Create 4 completely separate worker Store instances (4 separate locks & caches)
    workers = [Store() for _ in range(4)]

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.store.get_supabase_client", return_value=shared_db
    ):
        # Worker 0 seeds the original completed analysis
        orig = workers[0].create_analysis(
            resume_id="res_shared",
            job_id="job_shared",
            country="cambodia",
            user_id="user-retry-race",
            is_guest=False,
        )
        workers[0].update_analysis(orig.id, status="done")

        # Warm all 4 workers' local caches so every worker initially sees retried_by=None
        for w in workers:
            cached = w.get_analysis(orig.id)
            assert cached is not None
            assert cached.status == "done"
            assert cached.retried_by is None

        barrier = threading.Barrier(len(workers))

        def _worker_retry(worker_store: Store) -> tuple[str, str]:
            barrier.wait(timeout=5.0)
            try:
                child = worker_store.create_retry(orig.id, user_id="user-retry-race")
                assert child is not None
                return ("created", child.id)
            except ApiError as exc:
                return (f"error_{exc.status_code}", exc.code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as pool:
            futures = [pool.submit(_worker_retry, w) for w in workers]
            outcomes = [f.result() for f in futures]

        created = [cid for status, cid in outcomes if status == "created"]
        rejected = [code for status, code in outcomes if status == "error_409"]

        assert len(created) == 1, f"Expected 1 retry, got outcomes: {outcomes}"
        assert len(rejected) == 3
        assert all(code == "ANALYSIS_IN_PROGRESS" for code in rejected)

        # Shared database has only the original + the single winning retry child
        assert len(shared_db.analyses) == 2
        assert shared_db.analyses[orig.id]["retried_by"] == created[0]


# ============================================================================
# 2. Simultaneous Quota Checking & Reservation Across Workers
# ============================================================================


def test_simultaneous_quota_reservations_across_workers_enforce_limit() -> None:
    """Free plan allows 3 analyses. After 2 are committed, 5 concurrent requests
    across workers compete for the 1 remaining slot. Exactly 1 must succeed and
    4 must fail with HTTP 402 quota_exceeded.
    """
    shared_db = SharedDatabaseBackend()
    user_id = "00000000-0000-0000-0000-000000000001"

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.billing.service.get_supabase_client", return_value=shared_db
    ):
        # Seed 2 already-committed analysis usage events (limit is 3 on free plan -> 1 slot left)
        for _ in range(2):
            r_seed = reserve_quota(user_id, "analysis")
            commit_usage_reservation(r_seed, user_id, "analysis")
        assert get_subscription_summary(user_id).usage.analysis.used == 2

        barrier = threading.Barrier(5)

        def _attempt_reserve() -> tuple[str, str | int]:
            barrier.wait(timeout=5.0)
            try:
                rid = reserve_quota(user_id, "analysis")
                assert rid is not None
                return ("reserved", rid)
            except HTTPException as exc:
                return ("rejected", exc.status_code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_attempt_reserve) for _ in range(5)]
            results = [f.result() for f in futures]

        reserved = [val for kind, val in results if kind == "reserved"]
        rejected = [val for kind, val in results if kind == "rejected"]

        assert len(reserved) == 1
        assert rejected == [402, 402, 402, 402]
        assert get_subscription_summary(user_id).usage.analysis.used == 3


# ============================================================================
# 3. Stale Worker Cache Invalidation & Cross-Worker State Visibility
# ============================================================================


def test_stale_worker_cache_sees_other_worker_updates() -> None:
    """When Worker 1 updates an analysis or creates a retry in shared persistence,
    Worker 2 (holding a stale in-memory AnalysisRecord) must refresh from shared
    persistence rather than acting on stale state.
    """
    shared_db = SharedDatabaseBackend()
    worker_1 = Store()
    worker_2 = Store()

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.store.get_supabase_client", return_value=shared_db
    ):
        orig = worker_1.create_analysis(
            resume_id="res_1",
            job_id="job_1",
            country="cambodia",
            user_id="user-cache-test",
        )
        worker_1.update_analysis(orig.id, status="done")

        # Worker 2 loads original into its local cache while retried_by is None
        w2_view = worker_2.get_analysis(orig.id)
        assert w2_view is not None
        assert w2_view.status == "done"
        assert w2_view.retried_by is None

        # Worker 1 starts a retry (updates shared_db, but not worker_2's RAM)
        retry_child = worker_1.create_retry(orig.id, user_id="user-cache-test")
        assert retry_child is not None
        worker_1.update_analysis(retry_child.id, status="running", stage="reading_resume")

        # Worker 2 fetches original: must see updated retried_by from shared_db
        w2_refreshed = worker_2.get_analysis(orig.id)
        assert w2_refreshed is not None
        assert w2_refreshed.retried_by == retry_child.id

        # Worker 2 tries to create a duplicate retry: must be rejected with 409
        with pytest.raises(ApiError) as exc_info:
            worker_2.create_retry(orig.id, user_id="user-cache-test")
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "ANALYSIS_IN_PROGRESS"

        # Worker 1 finishes retry_child; Worker 2 polls retry_child and sees "done"
        worker_1.update_analysis(retry_child.id, status="done")
        w2_child_view = worker_2.get_analysis(retry_child.id)
        assert w2_child_view is not None
        assert w2_child_view.status == "done"


# ============================================================================
# 4. Consistent Guest Usage Enforcement Across Workers
# ============================================================================


def test_guest_usage_enforced_across_workers_and_released_on_failure() -> None:
    """Simultaneous guest requests across independent workers for the same IP hash
    allow only 1 slot. If that worker's analysis fails and releases the guest IP,
    another worker (even with a previously cached entry) allows the retry.
    """
    shared_db = SharedDatabaseBackend()
    workers = [Store() for _ in range(4)]
    ip_hash = "salted_guest_ip_hash_abc123"

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.store.get_supabase_client", return_value=shared_db
    ):
        barrier = threading.Barrier(len(workers))

        def _reserve_guest(w: Store) -> bool:
            barrier.wait(timeout=5.0)
            return w.reserve_guest_ip_usage(ip_hash)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as pool:
            results = [f.result() for f in [pool.submit(_reserve_guest, w) for w in workers]]

        assert results.count(True) == 1
        assert results.count(False) == 3

        # Worker 2 now has ip_hash cached locally as used
        assert workers[2].check_guest_ip_allowed(ip_hash) is False

        # Worker 0's guest analysis fails and releases the IP lock in shared persistence
        workers[0].release_guest_ip_usage(ip_hash)

        # Worker 2 (which had a stale local cache entry) must consult shared DB and allow retry
        assert workers[2].check_guest_ip_allowed(ip_hash) is True
        assert workers[2].reserve_guest_ip_usage(ip_hash) is True


# ============================================================================
# 5. Idempotent Reservation Completion and Release
# ============================================================================


def test_idempotent_reservation_commit_and_release_in_shared_persistence() -> None:
    """Repeated commits for the same reservation_id across workers must record
    strictly one usage event. Releasing an already-committed reservation must not
    cancel usage, and committing an already-released reservation must not charge.
    """
    shared_db = SharedDatabaseBackend()
    user_id = "00000000-0000-0000-0000-000000000005"

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.billing.service.get_supabase_client", return_value=shared_db
    ):
        rid_1 = reserve_quota(user_id, "analysis")
        assert rid_1 is not None

        # Commit the same reservation 3 times
        commit_usage_reservation(rid_1, user_id, "analysis")
        commit_usage_reservation(rid_1, user_id, "analysis")
        commit_usage_reservation(rid_1, user_id, "analysis")

        assert len(shared_db.usage_events) == 1
        assert get_subscription_summary(user_id).usage.analysis.used == 1

        # Attempting to release an already-committed reservation is a no-op
        release_usage_reservation(rid_1, user_id, "analysis")
        assert shared_db.usage_reservations[rid_1]["status"] == "committed"
        assert get_subscription_summary(user_id).usage.analysis.used == 1

        # Reserve a second slot and release it multiple times
        rid_2 = reserve_quota(user_id, "analysis")
        assert rid_2 is not None
        assert get_subscription_summary(user_id).usage.analysis.used == 2

        release_quota(rid_2, user_id, "analysis")
        release_quota(rid_2, user_id, "analysis")
        assert shared_db.usage_reservations[rid_2]["status"] == "released"
        assert get_subscription_summary(user_id).usage.analysis.used == 1

        # Attempting to commit an already-released reservation must not record usage
        commit_usage_reservation(rid_2, user_id, "analysis")
        assert len(shared_db.usage_events) == 1
        assert get_subscription_summary(user_id).usage.analysis.used == 1


# ============================================================================
# 6. Recovery and Expiry for Abandoned Work
# ============================================================================


def test_abandoned_retry_and_reservation_expire_and_recover() -> None:
    """If Worker 1 starts a retry with a quota reservation and then crashes
    (leaving the child analysis in `running` and reservation `active`), once the
    abandoned timeout elapses, Worker 2 must automatically recover the dead
    analysis, expire the stale reservation, and allow a new retry.
    """
    t0 = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
    shared_db = SharedDatabaseBackend(now_override=t0)
    worker_1 = Store()
    worker_2 = Store()
    user_id = "00000000-0000-0000-0000-000000000006"

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.store.get_supabase_client", return_value=shared_db
    ), patch("api.billing.service.get_supabase_client", return_value=shared_db):
        # 1. Create and finish initial analysis (consumes 1 of 2 free slots)
        r_init = reserve_quota(user_id, "analysis")
        orig = worker_1.create_analysis(
            "res_ab", "job_ab", "cambodia", user_id=user_id, reservation_id=r_init
        )
        worker_1.update_analysis(orig.id, status="done")
        commit_usage_reservation(r_init, user_id, "analysis")
        assert get_subscription_summary(user_id).usage.analysis.used == 1

        # 2. Worker 1 reserves the 2nd (last) quota slot and starts a retry, then crashes
        r_abandoned = reserve_quota(user_id, "analysis")
        abandoned_child = worker_1.create_retry(
            orig.id, user_id=user_id, reservation_id=r_abandoned
        )
        assert abandoned_child is not None
        worker_1.update_analysis(abandoned_child.id, status="running")

        # 3. 1 minute later (still within 10-minute timeout): Worker 2 cannot retry yet
        shared_db.now_override = t0 + timedelta(minutes=1)
        with pytest.raises(ApiError) as exc_info:
            worker_2.create_retry(orig.id, user_id=user_id)
        assert exc_info.value.status_code == 409

        # 4. 11 minutes later (past 10-minute abandoned timeout & reservation expiry):
        # Worker 2 can reserve quota again (stale reservation auto-expires) and retry!
        shared_db.now_override = t0 + timedelta(minutes=11)
        with patch("api.billing.service.datetime") as mock_dt, patch(
            "api.store.utcnow", return_value=shared_db.now_override
        ):
            mock_dt.now.return_value = shared_db.now_override
            mock_dt.fromisoformat = datetime.fromisoformat

            r_recovered = reserve_quota(user_id, "analysis")
            assert r_recovered is not None

            recovered_child = worker_2.create_retry(
                orig.id, user_id=user_id, reservation_id=r_recovered
            )
            assert recovered_child is not None
            assert recovered_child.id != abandoned_child.id

        # Dead child was transitioned to failed and its reservation released
        assert shared_db.analyses[abandoned_child.id]["status"] == "failed"
        assert shared_db.usage_reservations[r_abandoned]["status"] == "released"
        assert shared_db.analyses[orig.id]["retried_by"] == recovered_child.id


# ============================================================================
# 7. Safe Fail-Closed Behavior When Persistence Fails
# ============================================================================


def test_persistence_failure_fails_closed_without_bypassing_enforcement() -> None:
    """When database persistence is configured and a DB operation fails, workers
    must fail closed (HTTP 503 SERVICE_UNAVAILABLE) and never silently fall back
    to granting unmetered usage or creating uncoordinated retries.
    """
    shared_db = SharedDatabaseBackend()
    worker = Store()
    user_id = "00000000-0000-0000-0000-000000000007"

    with patch("api.db.get_supabase_client", return_value=shared_db), patch(
        "api.store.get_supabase_client", return_value=shared_db
    ), patch("api.billing.service.get_supabase_client", return_value=shared_db):
        orig = worker.create_analysis("res_f", "job_f", "cambodia", user_id=user_id)
        worker.update_analysis(orig.id, status="done")

        # Simulate database outage
        shared_db.fail_all = True

        # 1. Quota check fails closed with 503
        with pytest.raises(ApiError) as q_exc:
            check_quota(user_id, "analysis")
        assert q_exc.value.status_code == 503
        assert q_exc.value.code == "SERVICE_UNAVAILABLE"

        # 2. Quota reservation fails closed with 503
        with pytest.raises(ApiError) as r_exc:
            reserve_quota(user_id, "analysis")
        assert r_exc.value.status_code == 503
        assert r_exc.value.code == "SERVICE_UNAVAILABLE"

        # 3. Retry creation fails closed with 503
        shared_db.fail_all = False
        shared_db.fail_rpc_names.add("claim_analysis_retry")
        with pytest.raises(ApiError) as c_exc:
            worker.create_retry(orig.id, user_id=user_id)
        assert c_exc.value.status_code == 503
        assert c_exc.value.code == "SERVICE_UNAVAILABLE"
        shared_db.fail_rpc_names.clear()

        # 4. Guest IP reservation fails closed with 503
        shared_db.fail_rpc_names.add("reserve_guest_usage")
        with pytest.raises(ApiError) as g_exc:
            worker.reserve_guest_ip_usage("guest_hash_fail_closed")
        assert g_exc.value.status_code == 503
        assert g_exc.value.code == "SERVICE_UNAVAILABLE"


# ============================================================================
# 8. Documented Single-Process Fallback (When Persistence Is Not Configured)
# ============================================================================


def test_documented_single_process_in_memory_fallback_and_abandoned_recovery() -> None:
    """When get_supabase_client() is None (mock / offline fallback mode), the
    single-process store enforces duplicate retry checks, idempotent reservation
    commits/releases, and abandoned work recovery using process-local state.
    """
    t0 = datetime(2026, 11, 6, 15, 0, 0, tzinfo=UTC)
    local_store = Store()
    user_id = "user-fallback-mode"

    with patch("api.db.get_supabase_client", return_value=None), patch(
        "api.store.get_supabase_client", return_value=None
    ), patch("api.billing.service.get_supabase_client", return_value=None):
        with patch("api.store.utcnow", return_value=t0):
            orig = local_store.create_analysis(
                "res_fb", "job_fb", "cambodia", user_id=user_id
            )
            orig.status = "done"

            rid_1 = reserve_quota(user_id, "analysis")
            child_1 = local_store.create_retry(
                orig.id, user_id=user_id, reservation_id=rid_1
            )
            assert child_1 is not None
            child_1.status = "running"

            # Duplicate retry while child_1 is running (age = 0s) is rejected with 409
            with pytest.raises(ApiError) as dup_exc:
                local_store.create_retry(orig.id, user_id=user_id)
            assert dup_exc.value.status_code == 409

        # After 11 minutes, child_1 is abandoned -> recovered on next retry attempt
        t_later = t0 + timedelta(minutes=11)
        with patch("api.store.utcnow", return_value=t_later):
            child_2 = local_store.create_retry(orig.id, user_id=user_id)
            assert child_2 is not None
            assert child_2.id != child_1.id
            assert child_1.status == "failed"
            assert orig.retried_by == child_2.id
            # child_1's reservation was released during recovery
            assert get_subscription_summary(user_id).usage.analysis.used == 0


def test_current_quota_ignores_future_renewals_in_shared_database():
    backend = SharedDatabaseBackend()
    now = datetime.now(UTC)
    current = {
        "id": "current", "user_id": "renewing-user", "plan_id": "pass",
        "current_period_start": (now - timedelta(days=1)).isoformat(),
        "current_period_end": (now + timedelta(days=29)).isoformat(),
    }
    future = {
        **current, "id": "future", "current_period_start": current["current_period_end"],
        "current_period_end": (now + timedelta(days=59)).isoformat(),
    }
    backend.subscriptions.extend([current, future])
    backend.usage_events.extend({"user_id": "renewing-user", "kind": "analysis", "created_at": now.isoformat()}
                                for _ in range(50))
    with patch("api.billing.service.get_supabase_client", return_value=backend), patch("api.db.get_supabase_client", return_value=backend):
        assert billing_service._get_active_subscription_for_user("renewing-user").id == "current"
        assert billing_service._get_latest_subscription_for_user("renewing-user").id == "future"
        assert get_subscription_summary("renewing-user").usage.analysis.used == 50
        assert billing_service.atomic_reserve_quota("renewing-user", "analysis")[0] is False


@pytest.mark.parametrize("operation", ["rewrite", "checkout"])
def test_attempt_budget_is_shared_even_when_worker_memory_resets(operation):
    backend = SharedDatabaseBackend()

    def attempt(_):
        try:
            enforce_operation_attempt_limit(operation, "user:same-user", 2)
            return True
        except ApiError as exc:
            assert exc.status_code == 429
            return False

    with patch("api.limiter.get_supabase_client", return_value=backend), patch("api.db.get_supabase_client", return_value=backend):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(attempt, range(12))) == 2
        reset_rate_limits()
        assert attempt(None) is False
        backend.now_override = datetime.now(UTC) + timedelta(hours=1, seconds=1)
        assert attempt(None) is True


def test_checkout_claim_reuses_pending_session_across_workers():
    backend = SharedDatabaseBackend()
    with patch("api.billing.service.get_supabase_client", return_value=backend), patch("api.db.get_supabase_client", return_value=backend):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            reservations = list(pool.map(lambda _: billing_service._reserve_checkout_session("same-user", "mock"), range(12)))
        assert sum(claimed for _, claimed in reservations) == 1
        assert len({rec.id for rec, _ in reservations}) == 1
        first = reservations[0][0]
        ready = replace(first, provider_ref="mock-reference")
        billing_service._save_checkout_session(ready)
        reset_billing_memory()
        loaded, claimed = billing_service._reserve_checkout_session("same-user", "mock")
        assert not claimed
        assert loaded.id == ready.id and loaded.provider_ref == "mock-reference"


def test_paid_grants_are_idempotent_and_queue_periods_across_workers():
    backend = SharedDatabaseBackend()
    with patch("api.billing.service.get_supabase_client", return_value=backend), patch("api.db.get_supabase_client", return_value=backend):
        first, _ = billing_service._reserve_checkout_session("same-user", "mock")
        first = replace(first, status="paid")
        billing_service._save_checkout_session(first)
        second, _ = billing_service._reserve_checkout_session("same-user", "mock")
        second = replace(second, status="paid")
        billing_service._save_checkout_session(second)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            granted = list(pool.map(billing_service.grant_plan, [first, second] * 4))
        assert len({sub.id for sub in granted}) == len(backend.subscriptions) == 2
        periods = sorted(backend.subscriptions, key=lambda row: row["current_period_start"])
        assert periods[0]["current_period_end"] == periods[1]["current_period_start"]
        assert billing_service._get_active_subscription_for_user("same-user").id == periods[0]["id"]
        assert not billing_service._subscriptions  # Durable mode has no local grant fallback.

