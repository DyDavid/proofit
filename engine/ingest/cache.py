"""Content-hash deduplication caching module for ingestion and LLM calls.

PROJECT_SPEC.md §9 Rule 4: Never re-normalize the same JD or re-fetch the same URL.
Phase 3 hardening: Bounds cache file count, individual entry size, and enforces TTL expiration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parents[2] / "data" / ".cache"
DEFAULT_CACHE_MAX_ENTRIES = 500
DEFAULT_CACHE_TTL_HOURS = 24
MAX_CACHED_TEXT_CHARS = 200_000

_cache_lock = threading.RLock()


def _get_cache_limits(
    max_entries: int | None = None,
    ttl_seconds: float | None = None,
) -> tuple[int, float]:
    eff_max = max_entries
    eff_ttl = ttl_seconds
    if eff_max is None or eff_ttl is None:
        try:
            from api.config import settings

            if eff_max is None:
                eff_max = int(settings.url_cache_max_entries)
            if eff_ttl is None:
                eff_ttl = float(settings.url_cache_ttl_hours) * 3600.0
        except Exception:
            if eff_max is None:
                eff_max = DEFAULT_CACHE_MAX_ENTRIES
            if eff_ttl is None:
                eff_ttl = DEFAULT_CACHE_TTL_HOURS * 3600.0
    return max(1, eff_max), max(1.0, eff_ttl)


def _ensure_cache_dir(cache_dir: Path | None = None) -> Path:
    target = cache_dir or CACHE_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def prune_url_cache(
    cache_dir: Path | None = None,
    *,
    max_entries: int | None = None,
    ttl_seconds: float | None = None,
) -> int:
    """Remove expired cache entries and evict oldest entries beyond `max_entries`.

    Returns the number of cache files removed.
    """
    target_dir = _ensure_cache_dir(cache_dir)
    eff_max, eff_ttl = _get_cache_limits(max_entries, ttl_seconds)
    now = time.time()
    cutoff = now - eff_ttl
    removed = 0

    with _cache_lock:
        valid_files: list[tuple[float, Path]] = []
        for path in target_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                cached_at = raw.get("cached_at")
                # Preserve committed repository seed files that lack a runtime `cached_at` stamp
                if cached_at is None:
                    continue
                ts = float(cached_at)
                if ts < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
                else:
                    valid_files.append((ts, path))
            except Exception:
                continue

        if len(valid_files) > eff_max:
            valid_files.sort(key=lambda item: item[0])
            excess = len(valid_files) - eff_max
            for _, old_path in valid_files[:excess]:
                try:
                    old_path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    continue

    return removed


def get_cached_text(
    key: str,
    *,
    cache_dir: Path | None = None,
    ttl_seconds: float | None = None,
) -> str | None:
    """Retrieve raw text from content hash cache by key URL or raw text hash, honoring TTL."""
    target_dir = _ensure_cache_dir(cache_dir)
    _, eff_ttl = _get_cache_limits(None, ttl_seconds)
    cache_path = target_dir / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"

    with _cache_lock:
        if not cache_path.exists():
            return None
        try:
            now = time.time()
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)

            cached_at = data.get("cached_at")
            if isinstance(cached_at, (int, float)) and (now - float(cached_at)) > eff_ttl:
                cache_path.unlink(missing_ok=True)
                return None

            text = data.get("text")
            return text if isinstance(text, str) else None
        except Exception as err:
            logger.warning("Failed to read cache file %s: %s", cache_path, err)
            return None


def save_cached_text(
    key: str,
    text: str,
    *,
    cache_dir: Path | None = None,
    max_entries: int | None = None,
    ttl_seconds: float | None = None,
) -> None:
    """Store raw text into content hash cache and enforce TTL + capacity bounds."""
    target_dir = _ensure_cache_dir(cache_dir)
    cache_path = target_dir / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"
    bounded_text = text[:MAX_CACHED_TEXT_CHARS] if len(text) > MAX_CACHED_TEXT_CHARS else text

    with _cache_lock:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"key": key, "text": bounded_text, "cached_at": time.time()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            prune_url_cache(
                target_dir,
                max_entries=max_entries,
                ttl_seconds=ttl_seconds,
            )
        except Exception as err:
            logger.warning("Failed to save cache file %s: %s", cache_path, err)
