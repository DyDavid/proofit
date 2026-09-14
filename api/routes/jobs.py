"""`POST /api/jobs` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).

Accepts `{text}` or `{url}`. Content-hash caching (PROJECT_SPEC.md §9 rule 4 —
never re-normalize the same JD) works for both today; real URL *fetching*
(`engine.ingest.fetch_jd`) is Phase 3 — in mock mode a URL is hashed and
stored as-is, not retrieved.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.errors import ApiError
from api.store import store

router = APIRouter()


class JobIn(BaseModel):
    text: str | None = None
    url: str | None = None


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
        record, cached = store.add_job(url, source="url")

    return {"job_id": record.id, "cached": cached}
