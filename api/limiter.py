"""Sliding-window rate limiter for expensive public endpoints (Phase 3).

Bounds per-client request rates on `/api/resumes`, `/api/jobs/fetch-url`, and
`/api/jobs` while bounding internal memory via TTL pruning and LRU capacity caps.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

from fastapi import Request

from api.auth import CurrentUser, hash_guest_ip
from api.config import settings
from api.db import DatabasePersistenceError, db_reserve_analysis_attempt, get_supabase_client
from api.errors import ApiError

MAX_TRACKED_CLIENT_BUCKETS = 5_000


class SlidingWindowRateLimiter:
    """Thread-safe, memory-bounded sliding-window rate limiter."""

    def __init__(
        self, max_buckets: int = MAX_TRACKED_CLIENT_BUCKETS, *, evict_active: bool = True
    ) -> None:
        self._max_buckets = max_buckets
        self._evict_active = evict_active
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.RLock()

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> None:
        """Record a hit for `key` or raise `ApiError(429, 'RATE_LIMITED')` if over `limit`."""
        if limit <= 0:
            raise ApiError(
                status_code=429,
                code="RATE_LIMITED",
                message="Too many requests right now. Wait about a minute and try again.",
            )

        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is not None:
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= limit:
                    self._buckets.move_to_end(key)
                    raise ApiError(
                        status_code=429,
                        code="RATE_LIMITED",
                        message="Too many requests right now. Wait about a minute and try again.",
                    )
                bucket.append(now)
                self._buckets.move_to_end(key)
            else:
                # Evict expired or oldest LRU buckets if at capacity
                if len(self._buckets) >= self._max_buckets:
                    self._prune_expired_locked(cutoff)
                if len(self._buckets) >= self._max_buckets and not self._evict_active:
                    raise ApiError(
                        status_code=429,
                        code="RATE_LIMITED",
                        message="Too many analysis attempts. Please try again later.",
                    )
                while len(self._buckets) >= self._max_buckets:
                    self._buckets.popitem(last=False)
                self._buckets[key] = deque([now])

    def _prune_expired_locked(self, cutoff: float) -> None:
        empty_keys: list[str] = []
        for k, q in self._buckets.items():
            while q and q[0] <= cutoff:
                q.popleft()
            if not q:
                empty_keys.append(k)
        for k in empty_keys:
            self._buckets.pop(k, None)

    def reset(self) -> None:
        """Clear all rate-limit buckets (used in tests)."""
        with self._lock:
            self._buckets.clear()

    def bucket_count(self) -> int:
        with self._lock:
            return len(self._buckets)


rate_limiter = SlidingWindowRateLimiter()
analysis_attempt_limiter = SlidingWindowRateLimiter(evict_active=False)
operation_attempt_limiter = SlidingWindowRateLimiter(evict_active=False)


def reset_rate_limits() -> None:
    """Clear all in-memory rate limit state."""
    rate_limiter.reset()
    analysis_attempt_limiter.reset()
    operation_attempt_limiter.reset()


def enforce_operation_attempt_limit(operation: str, subject: str, limit: int) -> None:
    """Non-refundable hourly budget, including mock-mode rewrites and checkout.

    Use the existing server-only admission ledger with a separate namespace, so
    operation budgets cannot consume or reset each other's counters.
    """
    key = f"{operation}:{subject}"
    try:
        if get_supabase_client() is not None:
            allowed = limit > 0 and db_reserve_analysis_attempt(key, limit)
        else:
            operation_attempt_limiter.check(key, limit=limit, window_seconds=3600)
            return
    except DatabasePersistenceError:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Request limits could not be verified. Please try again later.") from None
    except ApiError as exc:
        raise ApiError(exc.status_code, exc.code, "Too many attempts in the past hour. Please try again later.") from None
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "Too many attempts in the past hour. Please try again later.")


def enforce_analysis_attempt_limit(request: Request, user: CurrentUser | None) -> None:
    """Consume a non-refundable hourly attempt shared by creation and retries.

    Persisted deployments coordinate across workers; intentionally offline deployments
    use a bounded single-process limiter. No attempt is refunded after admission.
    """
    subject = f"user:{user.id}" if user else f"guest:{hash_guest_ip(request)}"
    limit = settings.analysis_attempts_per_hour if user else settings.guest_analysis_attempts_per_hour
    if limit <= 0:
        allowed = False
    elif get_supabase_client() is not None:
        try:
            allowed = db_reserve_analysis_attempt(subject, limit)
        except DatabasePersistenceError as exc:
            raise ApiError(
                status_code=503,
                code="SERVICE_UNAVAILABLE",
                message="Analysis limits could not be verified. Please try again later.",
            ) from exc
    else:
        # A configured database failure must never silently reset the attempt budget.
        if settings.engine_mode != "mock" and settings.persistence_mode != "offline":
            raise ApiError(
                status_code=503,
                code="SERVICE_UNAVAILABLE",
                message="Analysis limits could not be verified. Please try again later.",
            )
        analysis_attempt_limiter.check(subject, limit=limit, window_seconds=3600)
        return
    if not allowed:
        raise ApiError(
            status_code=429,
            code="RATE_LIMITED",
            message="Too many analysis attempts in the past hour. Please try again later.",
        )


def enforce_endpoint_rate_limit(
    request: Request,
    scope_name: str,
    limit_getter: Callable[[], int],
    window_seconds: float = 60.0,
) -> None:
    """Check rate limit for `request` under `scope_name`."""
    ip_hash = hash_guest_ip(request)
    limit = limit_getter()
    rate_limiter.check(f"{scope_name}:{ip_hash}", limit=limit, window_seconds=window_seconds)

