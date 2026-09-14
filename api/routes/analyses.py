"""`POST /api/analyses` + `GET /api/analyses/{id}` (PERSON_B_PLAN_v2.md §5
Phase 1 task 4).

Analyses are async from day one: LLM calls take 10-40s in live mode, and a
synchronous request would time out behind Caddy and look like a hang. Mock
mode uses `BackgroundTasks` with an artificial delay so the polling
loop and progress stepper are exercised honestly rather than flashing past.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from api.config import settings
from api.errors import ApiError, new_error_id
from api.store import STAGE_ORDER, store

router = APIRouter()

logger = logging.getLogger("proofit.analyses")


class AnalysisIn(BaseModel):
    resume_id: str
    job_id: str
    country: str


async def _run_mock_analysis(analysis_id: str) -> None:
    record = store.analyses[analysis_id]
    record.status = "running"
    started_at = time.monotonic()
    per_stage = settings.mock_delay_seconds / len(STAGE_ORDER)
    try:
        for stage in STAGE_ORDER:
            record.stage = stage
            await asyncio.sleep(per_stage)
            logger.info(
                "analysis_stage analysis_id=%s stage=%s elapsed_ms=%d",
                analysis_id, stage, int((time.monotonic() - started_at) * 1000),
            )

        fixture_name = store.pick_fixture_name(record.job_id)
        record.match = store.pick_fixture(record.job_id)
        record.baseline = store.pick_baseline(fixture_name)
    except Exception as exc:  # noqa: BLE001 — this is the ENGINE_FAILED boundary, intentionally broad
        error_id = new_error_id()
        logger.warning(
            "analysis_failed analysis_id=%s error_id=%s message=%s", analysis_id, error_id, exc,
        )
        record.status = "failed"
        record.match = None
        record.baseline = None
        record.error = {"code": "ENGINE_FAILED", "message": str(exc), "error_id": error_id}
        return

    total_ms = int((time.monotonic() - started_at) * 1000)
    logger.info("analysis_done analysis_id=%s total_ms=%d", analysis_id, total_ms)
    if total_ms > 60_000:
        logger.warning(
            "analysis_slow analysis_id=%s total_ms=%d threshold_ms=60000", analysis_id, total_ms,
        )
    record.status = "done"


@router.post("/analyses", status_code=202)
async def create_analysis(payload: AnalysisIn, background_tasks: BackgroundTasks) -> dict:
    if payload.resume_id not in store.resumes:
        raise ApiError(
            status_code=404,
            code="RESUME_NOT_FOUND",
            message="Unknown resume_id.",
        )
    if payload.job_id not in store.jobs:
        raise ApiError(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="Unknown job_id.",
        )

    record = store.create_analysis(payload.resume_id, payload.job_id, payload.country)
    background_tasks.add_task(_run_mock_analysis, record.id)
    return {"analysis_id": record.id, "status": record.status}


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    record = store.analyses.get(analysis_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code="ANALYSIS_NOT_FOUND",
            message="Unknown analysis_id.",
        )

    return {
        "status": record.status,
        "stage": record.stage,
        "match": record.match.model_dump(mode="json") if record.match else None,
        "baseline": record.baseline.model_dump(mode="json") if record.baseline else None,
        "error": record.error,
    }


@router.post("/analyses/{analysis_id}/retry", status_code=202)
async def retry_analysis(analysis_id: str, background_tasks: BackgroundTasks) -> dict:
    record = store.create_retry(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")

    background_tasks.add_task(_run_mock_analysis, record.id)
    return {"analysis_id": record.id, "status": record.status}
