"""`POST /api/analyses` + `GET /api/analyses/{id}` (PERSON_B_PLAN_v2.md §5
Phase 1 task 4 and Phase 2 task 5).

Analyses are async from day one: LLM calls take 10-40s in live mode, and a
synchronous request would time out behind Caddy and look like a hang. Mock
mode uses `BackgroundTasks` with an artificial delay so the polling
loop and progress stepper are exercised honestly rather than flashing past.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from api.config import settings
from api.db import (
    db_list_analyses,
    db_save_jd_requirements,
    db_save_resume_evidence,
    get_supabase_client,
)
from api.store import STAGE_ORDER, store

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalysisIn(BaseModel):
    resume_id: str
    job_id: str
    country: str


async def _run_mock_analysis(analysis_id: str) -> None:
    record = store.get_analysis(analysis_id)
    if not record:
        return
    store.update_analysis(analysis_id, status="running")

    per_stage = settings.mock_delay_seconds / len(STAGE_ORDER)
    for stage in STAGE_ORDER:
        store.update_analysis(analysis_id, stage=stage)
        await asyncio.sleep(per_stage)

    fixture_match = store.pick_fixture(record.job_id)
    store.update_analysis(analysis_id, status="done", match=fixture_match)


async def _run_live_analysis(analysis_id: str) -> None:
    record = store.get_analysis(analysis_id)
    if not record:
        return
    store.update_analysis(analysis_id, status="running")

    job = None
    resume = None
    try:
        from engine.gemini_client import get_embedding
        from engine.ingest import fetch_jd
        from engine.match import run_match
        from engine.normalize import normalize_jd, normalize_resume

        # Stage 1: reading_resume
        store.update_analysis(analysis_id, stage="reading_resume")
        res_rec = store.get_resume(record.resume_id)
        if not res_rec:
            raise ValueError(f"Resume {record.resume_id} not found.")

        if res_rec.normalized is not None:
            resume = res_rec.normalized
        else:
            resume = normalize_resume(res_rec.data or b"", res_rec.filename)
            res_rec.normalized = resume
            # Update resume in db
            store.add_resume(
                filename=res_rec.filename,
                content_type=res_rec.content_type,
                size=res_rec.size,
                data=res_rec.data,
                raw_text=res_rec.raw_text,
                normalized=resume,
            )

        # Stage 2: reading_job
        store.update_analysis(analysis_id, stage="reading_job")
        job_rec = store.get_job(record.job_id)
        if not job_rec:
            raise ValueError(f"Job {record.job_id} not found.")

        if job_rec.normalized is not None:
            job = job_rec.normalized
        else:
            raw_jd = fetch_jd(job_rec.raw) if job_rec.source == "url" else job_rec.raw
            job = normalize_jd(raw_jd)
            job_rec.normalized = job
            # Update job in db
            store.add_job(raw=job_rec.raw, source=job_rec.source, normalized=job)

        # Persist requirement and evidence embeddings if Supabase is connected
        if get_supabase_client():
            try:
                ev_vectors = {ev.id: get_embedding(ev.source_line) for ev in resume.evidence}
                db_save_resume_evidence(
                    res_rec.id,
                    [ev.model_dump(mode="json") for ev in resume.evidence],
                    ev_vectors,
                )
                req_vectors = {req.id: get_embedding(req.text) for req in job.requirements}
                db_save_jd_requirements(
                    job_rec.id,
                    job.content_hash,
                    [req.model_dump(mode="json") for req in job.requirements],
                    req_vectors,
                )
            except Exception as emb_err:
                logger.warning("Could not persist pgvector embeddings: %s", emb_err)

        # Stage 3: matching_requirements
        store.update_analysis(analysis_id, stage="matching_requirements")
        match = run_match(job, resume)

        # Stage 4: checking_realism
        store.update_analysis(analysis_id, stage="checking_realism")
        match.job = job
        match.resume = resume

        store.update_analysis(analysis_id, status="done", match=match)

    except Exception as err:
        logger.exception("Live analysis failed (%s). Generating fallback match.", err)
        fixture_match = store.pick_fixture(record.job_id)
        if job:
            fixture_match.job = job
        if resume:
            fixture_match.resume = resume
        store.update_analysis(
            analysis_id,
            status="done",
            match=fixture_match,
            error_message=str(err),
        )


@router.post("/analyses", status_code=202)
async def create_analysis(payload: AnalysisIn, background_tasks: BackgroundTasks) -> dict:
    res_rec = store.get_resume(payload.resume_id)
    if not res_rec:
        raise HTTPException(
            status_code=404,
            detail={"code": "RESUME_NOT_FOUND", "message": "Unknown resume_id."},
        )
    job_rec = store.get_job(payload.job_id)
    if not job_rec:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Unknown job_id."},
        )

    record = store.create_analysis(payload.resume_id, payload.job_id, payload.country)
    if settings.engine_mode == "live":
        background_tasks.add_task(_run_live_analysis, record.id)
    else:
        background_tasks.add_task(_run_mock_analysis, record.id)

    return {"analysis_id": record.id, "status": record.status}


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    record = store.get_analysis(analysis_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ANALYSIS_NOT_FOUND", "message": "Unknown analysis_id."},
        )

    return {
        "status": record.status,
        "stage": record.stage,
        "match": record.match.model_dump(mode="json") if record.match else None,
        "error_message": record.error_message,
    }


@router.post("/analyses/{analysis_id}/rewrites")
async def generate_rewrites_for_analysis(analysis_id: str) -> dict:
    record = store.get_analysis(analysis_id)
    if record is None or not record.match:
        raise HTTPException(
            status_code=404,
            detail={"code": "ANALYSIS_NOT_FOUND", "message": "Analysis or match not ready."},
        )

    match = record.match
    from engine.rewrite import detect_hidden_strengths, get_rejection_logs

    if match.job and match.resume:
        use_llm = settings.engine_mode == "live"
        strengths = detect_hidden_strengths(match, match.resume, use_llm=use_llm)
        match.hidden_strengths = strengths
        store.update_analysis(analysis_id, match=match)
        return {
            "hidden_strengths": [hs.model_dump(mode="json") for hs in strengths],
            "rejections_count": len(get_rejection_logs()),
        }
    return {"hidden_strengths": [], "rejections_count": len(get_rejection_logs())}


@router.get("/analyses")
async def list_analyses(resume_id: str | None = None) -> list[dict]:
    # Check Supabase first
    if get_supabase_client():
        db_rows = db_list_analyses(resume_id=resume_id)
        if db_rows:
            results = []
            for row in db_rows:
                m = row.get("match") or {}
                job_data = m.get("job") or {}
                results.append({
                    "id": row["id"],
                    "resume_id": row.get("resume_id"),
                    "job_id": row.get("job_id"),
                    "country": row.get("country", "KH"),
                    "status": row.get("status", "done"),
                    "job_title": job_data.get("title", "Unknown Job"),
                    "company": job_data.get("company"),
                    "coverage_score": m.get("coverage_score", 0.0),
                    "realism_verdict": m.get("realism_verdict", "stretch"),
                    "created_at": row.get("created_at"),
                })
            return results

    # Fallback to in-memory store
    results = []
    for a in store.analyses.values():
        if resume_id and a.resume_id != resume_id:
            continue
        m = a.match
        created_at_val = None
        if m and getattr(m, "generated_at", None):
            gen_at = m.generated_at
            if hasattr(gen_at, "isoformat"):
                created_at_val = gen_at.isoformat()
            else:
                created_at_val = str(gen_at)

        results.append({
            "id": a.id,
            "resume_id": a.resume_id,
            "job_id": a.job_id,
            "country": a.country,
            "status": a.status,
            "job_title": m.job.title if (m and m.job) else "Unknown Job",
            "company": m.job.company if (m and m.job) else None,
            "coverage_score": m.coverage_score if m else 0.0,
            "realism_verdict": m.realism_verdict if m else "stretch",
            "created_at": created_at_val,
        })
    return results
