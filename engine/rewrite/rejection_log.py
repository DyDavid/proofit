"""Rejection log for recording validator failures.

Every validator failure is recorded so that rejection rates can be analyzed in evaluation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


_REJECTION_LOG: list[dict[str, Any]] = []


def log_rejection(
    requirement_id: str,
    suggested_phrasing: str,
    violations: list[dict[str, str] | str],
    evidence_ids: list[str],
    retry_succeeded: bool = False,
) -> dict[str, Any]:
    """Logs a rejected rewrite attempt."""
    entry = {
        "requirement_id": requirement_id,
        "suggested_phrasing": suggested_phrasing,
        "violations": violations,
        "evidence_ids": evidence_ids,
        "retry_succeeded": retry_succeeded,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    _REJECTION_LOG.append(entry)
    return entry


def get_rejection_logs() -> list[dict[str, Any]]:
    """Returns all logged rejections."""
    return list(_REJECTION_LOG)


def clear_rejection_logs() -> None:
    """Clears the in-memory rejection logs (useful for tests)."""
    _REJECTION_LOG.clear()
