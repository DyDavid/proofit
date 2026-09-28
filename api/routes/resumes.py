"""`POST /api/resumes` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).

Mock mode does not parse the file — it only validates type/size and hands
back an id. Real extraction (`engine.normalize.normalize_resume`) is Person
A's, wired in when `ENGINE_MODE=live` (Phase 2 CP2).
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from api.config import settings
from api.errors import ApiError
from api.store import store

router = APIRouter()

ACCEPTED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("/resumes")
async def upload_resume(file: UploadFile = File(...)) -> dict:  # noqa: B008 (FastAPI DI convention)
    if file.content_type not in ACCEPTED_CONTENT_TYPES:
        raise ApiError(
            status_code=415,
            code="RESUME_BAD_TYPE",
            message=f"Unsupported content type: {file.content_type!r}",
        )

    body = await file.read()
    if len(body) > settings.max_upload_bytes:
        raise ApiError(
            status_code=413,
            code="RESUME_TOO_LARGE",
            message=f"Upload exceeds {settings.max_upload_bytes} bytes.",
        )

    record = store.add_resume(
        filename=file.filename or "resume",
        content_type=file.content_type,
        size=len(body),
        data=body,
    )
    return {"resume_id": record.id}

