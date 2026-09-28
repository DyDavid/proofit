"""`POST /api/jobs` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).

Accepts `{text}` or `{url}`. Content-hash caching (PROJECT_SPEC.md §9 rule 4 —
never re-normalize the same JD) works for both today; real URL *fetching*
(`engine.ingest.fetch_jd`) is Phase 3 — in mock mode a URL is hashed and
stored as-is, not retrieved.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from api.errors import ApiError
from api.store import store

router = APIRouter()

_BLOCKED_JOB_HOSTS: frozenset[str] = frozenset({"linkedin.com", "facebook.com"})


def _is_blocked_job_host(url: str) -> bool:
    """True if `url`'s host is linkedin.com/facebook.com or a subdomain of
    either (PROJECT_SPEC.md §9 rule 6). A pure string check on the URL as
    given — it never fetches anything, so it needs none of Person A's
    engine.ingest.fetch_jd (still NotImplementedError until CP2)."""
    host = (urlparse(url).hostname or "").lower()
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in _BLOCKED_JOB_HOSTS)


class JobIn(BaseModel):
    text: str | None = None
    url: str | None = None


class FetchUrlIn(BaseModel):
    url: str


@router.post("/jobs/fetch-url")
async def fetch_job_url(payload: FetchUrlIn) -> dict:
    url = payload.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_URL",
                "message": "Please enter a valid URL starting with http:// or https://.",
            },
        )

    from engine.ingest.cache import save_cached_text
    from engine.ingest.scraper import scrape_job_url

    try:
        raw_text = scrape_job_url(url)
        save_cached_text(url, raw_text)
        return {
            "url": url,
            "text": raw_text,
            "word_count": len(raw_text.split()),
        }
    except ValueError as val_err:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "JOB_URL_BLOCKED",
                "message": str(val_err),
            },
        ) from val_err
    except Exception as err:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "JOB_FETCH_FAILED",
                "message": f"Could not fetch job from URL: {err}",
            },
        ) from err


@router.post("/jobs")
async def submit_job(payload: JobIn) -> dict:
    # Stripped once, up front: a blank or whitespace-only field counts as "not
    # provided" everywhere below, so `{"text": "", "url": "https://..."}` is a
    # valid url submission rather than a XOR violation.
    text = payload.text.strip() if payload.text else ""
    url = payload.url.strip() if payload.url else ""

    if bool(text) == bool(url):
        # docs/errors.md JOB_EMPTY: covers blank text, neither given, and both given.
        raise ApiError(
            status_code=422,
            code="JOB_EMPTY",
            message="Provide exactly one of a non-blank text or url.",
        )

    if text:
        if len(text) < 40:
            raise ApiError(
                status_code=422,
                code="JOB_EMPTY",
                message="Job text is present but too short to be a real job post.",
            )
        record, cached = store.add_job(text, source="text")
    else:
        if _is_blocked_job_host(url):
            raise ApiError(
                status_code=422,
                code="JOB_URL_BLOCKED",
                message="Host is on the LinkedIn/Facebook blocklist (PROJECT_SPEC.md §9 rule 6).",
            )
        record, cached = store.add_job(url, source="url")

    return {"job_id": record.id, "cached": cached}
