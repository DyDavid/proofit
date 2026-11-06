"""`POST /api/resumes` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).

Mock mode does not normalize the file via LLM — it validates type/size, runs
bounded text extraction off the event loop, and hands back an id. Real LLM
extraction (`engine.normalize.normalize_resume`) is wired in when
`ENGINE_MODE=live` (Phase 2 CP2).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile

from api.auth import CurrentUser, get_optional_user
from api.config import settings
from api.errors import ApiError
from api.limiter import enforce_endpoint_rate_limit
from api.quota import reserve_saved_resume_slot
from api.store import store
from engine.normalize.parser import (
    DecompressionLimitError,
    ParserConcurrencyError,
    ParserTimeoutError,
    parse_resume_bytes_async,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ACCEPTED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

UPLOAD_READ_CHUNK_BYTES = 64 * 1024  # 64 KB


async def _read_upload_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read `UploadFile` incrementally in chunks, aborting immediately if `max_bytes` is exceeded."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(
                status_code=413,
                code="RESUME_TOO_LARGE",
                message=f"Upload exceeds {max_bytes} bytes.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/resumes")
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 (FastAPI DI convention)
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
) -> dict:
    enforce_endpoint_rate_limit(
        request,
        "resumes",
        lambda: settings.rate_limit_resumes_per_min,
    )

    if file.content_type not in ACCEPTED_CONTENT_TYPES:
        raise ApiError(
            status_code=415,
            code="RESUME_BAD_TYPE",
            message=f"Unsupported content type: {file.content_type!r}",
        )

    body = await _read_upload_bounded(file, settings.max_upload_bytes)

    slot_id = await asyncio.to_thread(reserve_saved_resume_slot, user) if user else None
    saved = False
    try:
        result = await _parse_and_save(file, body, user, slot_id)
        saved = True
        return result
    finally:
        if slot_id is not None and not saved and user is not None:
            await asyncio.shield(asyncio.to_thread(store.release_resume_slot, user.id, slot_id))


async def _parse_and_save(
    file: UploadFile, body: bytes, user: CurrentUser | None, slot_id: str | None,
) -> dict:
    try:
        raw_text: str | None = await parse_resume_bytes_async(
            body,
            file.filename or "resume.pdf",
        )
    except DecompressionLimitError as err:
        logger.warning("Resume rejected due to decompression limit: %s", err)
        raise ApiError(
            status_code=413,
            code="RESUME_TOO_LARGE",
            message="Decompressed resume exceeds the maximum allowed size.",
        ) from err
    except ParserTimeoutError as err:
        logger.warning("Resume parsing timed out: %s", err)
        raise ApiError(
            status_code=422,
            code="RESUME_UNREADABLE",
            message="Resume parsing timed out.",
        ) from err
    except ParserConcurrencyError as err:
        logger.warning("Resume parsing concurrency limit reached: %s", err)
        raise ApiError(
            status_code=429,
            code="RATE_LIMITED",
            message="Too many requests right now. Wait about a minute and try again.",
        ) from err
    except Exception as err:
        logger.warning("Resume text extraction failed: %s", err)
        raise ApiError(422, "RESUME_UNREADABLE", "Could not read the resume. Please try another file.") from err

    record = await asyncio.to_thread(
        store.add_resume,
        filename=file.filename or "resume",
        content_type=file.content_type,
        size=len(body),
        data=body,
        raw_text=raw_text,
        user_id=user.id if user else None,
        slot_id=slot_id,
    )
    return {"resume_id": record.id}
