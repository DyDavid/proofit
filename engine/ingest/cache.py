"""Content-hash deduplication caching module for ingestion and LLM calls.

PROJECT_SPEC.md §9 Rule 4: Never re-normalize the same JD or re-fetch the same URL.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parents[2] / "data" / ".cache"


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def get_cached_text(key: str) -> str | None:
    """Retrieve raw text from content hash cache by key URL or raw text hash."""
    cache_path = _ensure_cache_dir() / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("text")
        except Exception as err:
            logger.warning("Failed to read cache file %s: %s", cache_path, err)
    return None


def save_cached_text(key: str, text: str) -> None:
    """Store raw text into content hash cache."""
    cache_path = _ensure_cache_dir() / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"key": key, "text": text}, f, ensure_ascii=False, indent=2)
    except Exception as err:
        logger.warning("Failed to save cache file %s: %s", cache_path, err)
