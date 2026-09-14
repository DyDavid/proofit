"""`POST /api/analyses` + `GET /api/analyses/{id}` (PERSON_B_PLAN_v2.md §5
Phase 1 task 4).

Analyses are async from day one: LLM calls take 10-40s in live mode, and a
synchronous request would time out behind Caddy and look like a hang. Mock
mode uses `BackgroundTasks` with an artificial delay so the polling
loop and progress stepper are exercised honestly rather than flashing past.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from api.config import settings
from api.store import STAGE_ORDER, store

router = APIRouter()


class AnalysisIn(BaseModel):
    resume_id: str
    job_id: str
    country: str


async def _run_mock_analysis(analysis_id: str) -> None:
    record = store.analyses[analysis_id]
    record.status = "running"
    per_stage = settings.mock_delay_seconds / len(STAGE_ORDER)
    for stage in STAGE_ORDER:
        record.stage = stage
        await asyncio.sleep(per_stage)

    record.match = store.pick_fixture(record.job_id)
    record.status = "done"


@router.post("/analyses", status_code=202)
async def create_analysis(payload: AnalysisIn, background_tasks: BackgroundTasks) -> dict:
    if payload.resume_id not in store.resumes:
        raise HTTPException(
            status_code=404,
            detail={"code": "RESUME_NOT_FOUND", "message": "Unknown resume_id."},
        )
    if payload.job_id not in store.jobs:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Unknown job_id."},
        )

    record = store.create_analysis(payload.resume_id, payload.job_id, payload.country)
    background_tasks.add_task(_run_mock_analysis, record.id)
    return {"analysis_id": record.id, "status": record.status}


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    record = store.analyses.get(analysis_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ANALYSIS_NOT_FOUND", "message": "Unknown analysis_id."},
        )

    return {
        "status": record.status,
        "stage": record.stage,
        "match": record.match.model_dump(mode="json") if record.match else None,
    }
