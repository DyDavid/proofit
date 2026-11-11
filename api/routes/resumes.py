"""`POST /api/resumes` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).

Mock mode does not parse the file — it only validates type/size and hands
back an id. Real extraction (`engine.normalize.normalize_resume`) is Person
A's, wired in when `ENGINE_MODE=live` (Phase 2 CP2).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, UploadFile

from api.auth import CurrentUser, get_optional_user
from api.config import settings
from api.errors import ApiError
from api.quota import check_saved_resumes_quota
from api.store import store

logger = logging.getLogger(__name__)

router = APIRouter()

ACCEPTED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("/resumes")
async def upload_resume(
    file: UploadFile = File(...),  # noqa: B008 (FastAPI DI convention)
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
) -> dict:
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

    if user is not None:
        check_saved_resumes_quota(user.id, store.count_user_resumes(user.id))

    from engine.normalize.parser import parse_resume_bytes

    try:
        raw_text = parse_resume_bytes(body, file.filename or "resume.pdf")
    except Exception as err:
        logger.warning("Resume text extraction failed: %s", err)
        raw_text = None

    record = store.add_resume(
        filename=file.filename or "resume",
        content_type=file.content_type,
        size=len(body),
        data=body,
        raw_text=raw_text,
        user_id=user.id if user else None,
    )
    return {"resume_id": record.id}


