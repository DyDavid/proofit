"""`POST /api/jobs` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).

Accepts `{text}` or `{url}`. Content-hash caching (PROJECT_SPEC.md §9 rule 4 —
never re-normalize the same JD) works for both today; real URL *fetching*
(`engine.ingest.fetch_jd`) is Phase 3 — in mock mode a URL is hashed and
stored as-is, not retrieved.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from api.store import store

router = APIRouter()


class JobIn(BaseModel):
    text: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> JobIn:
        if bool(self.text) == bool(self.url):
            raise ValueError("Provide exactly one of text or url.")
        return self


@router.post("/jobs")
async def submit_job(payload: JobIn) -> dict:
    if payload.text is not None:
        if len(payload.text.strip()) < 40:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "JOB_TEXT_TOO_SHORT",
                    "message": "Paste the full job post, including the requirements section.",
                },
            )
        record, cached = store.add_job(payload.text, source="text")
    else:
        assert payload.url is not None
        record, cached = store.add_job(payload.url, source="url")

    return {"job_id": record.id, "cached": cached}
