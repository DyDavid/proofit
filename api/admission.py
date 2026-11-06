"""Bounded request budgets, atomic across persisted workers and explicit offline mode."""

import threading
import time
from collections import deque

from api.db import DatabasePersistenceError, db_billing_rpc, get_supabase_client
from api.errors import ApiError

_lock = threading.RLock()
_buckets: dict[tuple[str, str], deque[float]] = {}
MAX_BUCKETS_PER_SCOPE = 5000


def reset_admission() -> None:
    with _lock:
        _buckets.clear()


def admit_request(scope: str, subject: str, limit: int, global_limit: int) -> None:
    if get_supabase_client() is not None:
        result = db_billing_rpc("admit_resource_request", {
            "p_scope": scope, "p_subject": subject, "p_limit": limit,
            "p_global_limit": global_limit,
        })
        if not isinstance(result.get("allowed"), bool):
            raise DatabasePersistenceError("Invalid admission response")
        allowed = result["allowed"]
    else:
        with _lock:
            now = time.monotonic()
            for key in list(_buckets):
                if key[0] != scope:
                    continue
                bucket = _buckets[key]
                while bucket and bucket[0] <= now - 60:
                    bucket.popleft()
                if not bucket:
                    del _buckets[key]
            client = _buckets.get((scope, subject), deque())
            total = _buckets.get((scope, "*"), deque())
            capacity = ((scope, subject) in _buckets
                        or sum(key[0] == scope for key in _buckets) < MAX_BUCKETS_PER_SCOPE)
            allowed = capacity and len(client) < limit and len(total) < global_limit
            if allowed:
                client.append(now)
                total.append(now)
                _buckets[scope, subject] = client
                _buckets[scope, "*"] = total
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "Too many requests. Please try again shortly.")
