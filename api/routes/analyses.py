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
import time

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, ValidationError

from api.config import settings
from api.db import (
    db_save_jd_requirements,
    db_save_resume_evidence,
    get_supabase_client,
)
from api.errors import ApiError, new_error_id
from api.store import STAGE_ORDER, store
from engine.country.rules import rules_for
from engine.normalize.schema import HiddenStrength, Match
from engine.rewrite.detect import detect_hidden_strengths
from engine.rewrite.generate import generate_rewrite
from engine.rewrite.llm import RateLimitedError as RewriteRateLimitedError
from engine.rewrite.validate import validate_rewrite

logger = logging.getLogger(__name__)

router = APIRouter()

logger = logging.getLogger("proofit.analyses")


class AnalysisIn(BaseModel):
    resume_id: str
    job_id: str
    country: str


class AnalysisSummary(BaseModel):
    analysis_id: str
    job_title: str
    company: str | None
    coverage: float
    realism_verdict: str
    created_at: str


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


async def _run_live_analysis(analysis_id: str) -> None:
    record = store.get_analysis(analysis_id)
    if not record:
        return
    store.update_analysis(analysis_id, status="running")

    job = None
    resume = None
    try:
        from concurrent.futures import ThreadPoolExecutor

        from engine.gemini_client import get_embedding
        from engine.ingest import fetch_jd
        from engine.match import run_match
        from engine.normalize import normalize_jd, normalize_resume

        res_rec = store.get_resume(record.resume_id)
        if not res_rec:
            raise ValueError(f"Resume {record.resume_id} not found.")

        job_rec = store.get_job(record.job_id)
        if not job_rec:
            raise ValueError(f"Job {record.job_id} not found.")

        # Stage 1 & 2: Normalize resume and job concurrently in parallel threads
        store.update_analysis(analysis_id, stage="reading_resume")

        def _do_norm_resume():
            if res_rec.normalized is not None:
                return res_rec.normalized
            data_bytes = res_rec.data or (res_rec.raw_text.encode("utf-8") if res_rec.raw_text else b"")
            return normalize_resume(data_bytes, res_rec.filename)


        def _do_norm_jd():
            if job_rec.normalized is not None:
                return job_rec.normalized
            raw_jd = fetch_jd(job_rec.raw) if job_rec.source == "url" else job_rec.raw
            return normalize_jd(raw_jd)

        with ThreadPoolExecutor(max_workers=4) as executor:
            fut_res = executor.submit(_do_norm_resume)
            fut_job = executor.submit(_do_norm_jd)
            resume = fut_res.result()
            job = fut_job.result()

        res_rec.normalized = resume
        job_rec.normalized = job

        # Save to db/cache in background
        store.add_resume(
            filename=res_rec.filename,
            content_type=res_rec.content_type,
            size=res_rec.size,
            data=res_rec.data,
            raw_text=res_rec.raw_text,
            normalized=resume,
        )
        store.add_job(raw=job_rec.raw, source=job_rec.source, normalized=job)

        # Stage 3: matching_requirements
        store.update_analysis(analysis_id, stage="matching_requirements")
        match = run_match(job, resume)

        # Stage 4: checking_realism
        store.update_analysis(analysis_id, stage="checking_realism")
        match.job = job
        match.resume = resume

        store.update_analysis(analysis_id, status="done", match=match)

        # Parallel pgvector embeddings persistence in background (non-blocking)
        if get_supabase_client():
            try:
                def _fetch_all_embeddings():
                    with ThreadPoolExecutor(max_workers=8) as emb_exec:
                        ev_futures = {ev.id: emb_exec.submit(get_embedding, ev.source_line) for ev in resume.evidence}
                        req_futures = {req.id: emb_exec.submit(get_embedding, req.text) for req in job.requirements}
                        ev_vectors = {eid: fut.result() for eid, fut in ev_futures.items()}
                        req_vectors = {rid: fut.result() for rid, fut in req_futures.items()}

                    db_save_resume_evidence(
                        res_rec.id,
                        [ev.model_dump(mode="json") for ev in resume.evidence],
                        ev_vectors,
                    )
                    db_save_jd_requirements(
                        job_rec.id,
                        job.content_hash,
                        [req.model_dump(mode="json") for req in job.requirements],
                        req_vectors,
                    )

                with ThreadPoolExecutor(max_workers=1) as bg_writer:
                    bg_writer.submit(_fetch_all_embeddings)
            except Exception as emb_err:
                logger.warning("Could not persist pgvector embeddings: %s", emb_err)

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
            # Generic on purpose: str(err) can carry provider internals (URLs,
            # keys echoed in SDK errors) and this field is returned to the browser.
            # The real error is in the log line above.
            error_message="The live engine could not complete this analysis.",
        )



@router.post("/analyses", status_code=202)
async def create_analysis(payload: AnalysisIn, background_tasks: BackgroundTasks) -> dict:
    if not store.get_resume(payload.resume_id):
        raise ApiError(
            status_code=404,
            code="RESUME_NOT_FOUND",
            message="Unknown resume_id.",
        )
    if not store.get_job(payload.job_id):
        raise ApiError(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="Unknown job_id.",
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
        "error_message": record.error_message,
    }


@router.get("/analyses")
async def list_analyses(resume_id: str = Query(..., min_length=1)) -> list[AnalysisSummary]:
    summaries: list[AnalysisSummary] = []
    for record in store.analyses_for_resume(resume_id):
        assert record.match is not None  # guaranteed by analyses_for_resume's own filter
        job = record.match.job
        summaries.append(
            AnalysisSummary(
                analysis_id=record.id,
                job_title=job.title if job else "",
                company=job.company if job else None,
                coverage=record.match.coverage_required_only,
                realism_verdict=record.match.realism_verdict,
                created_at=record.created_at.isoformat(),
            )
        )
    return summaries


@router.post("/analyses/{analysis_id}/retry", status_code=202)
async def retry_analysis(analysis_id: str, background_tasks: BackgroundTasks) -> dict:
    record = store.create_retry(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")

    background_tasks.add_task(_run_mock_analysis, record.id)
    return {"analysis_id": record.id, "status": record.status}


def _append_hidden_strength(match: Match, hidden_strength: HiddenStrength) -> Match:
    """Re-validates the whole `Match` with the new `HiddenStrength` appended,
    rather than mutating `match.hidden_strengths` in place — a plain
    `list.append` would bypass `Match._references_resolve`, the exact
    integrity check that would catch a generated `HiddenStrength` citing an id
    that does not exist. schema.py's own stated philosophy: validation at
    parse time, so a violation cannot reach the API response."""
    updated = match.model_dump(mode="json")
    updated["hidden_strengths"] = [
        *updated["hidden_strengths"],
        hidden_strength.model_dump(mode="json"),
    ]
    return Match.model_validate(updated)


@router.post("/analyses/{analysis_id}/rewrites")
def create_rewrites(analysis_id: str) -> dict:
    """Runs the F5 pipeline for one completed analysis (PERSON_B_PLAN_v2.md §5
    Phase 3 task 6): detect candidates, generate a rewrite for each, validate
    it, retry generation+validation once on failure, log every failure, and
    append every accepted HiddenStrength to the stored match.

    Deliberately a plain `def`, not `async def`: every call inside this
    function (`detect_hidden_strengths`, `generate_rewrite`,
    `validate_rewrite`) is synchronous and ultimately blocks on the Gemini
    SDK's `generate_content()` — 10-40s in live mode, per this module's
    own docstring. An `async def` route runs directly on the event loop, so a
    blocking call here would freeze every other in-flight request, including
    the `GET /api/analyses/{id}` poll the Progress screen depends on. FastAPI
    runs a plain `def` route in a threadpool instead, so the LLM I/O blocks
    only that worker thread."""
    record = store.analyses.get(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")
    if record.status != "done" or record.match is None:
        raise ApiError(
            status_code=409,
            code="ANALYSIS_NOT_READY",
            message="Analysis has not finished; there is no match to run rewrites against.",
        )

    match = record.match
    resume = match.resume
    if resume is None or match.job is None:
        return {
            "hidden_strengths": [h.model_dump(mode="json") for h in match.hidden_strengths],
            "rejected_count": 0,
        }

    requirements_by_id = {r.id: r for r in match.job.requirements}
    evidence_by_id = {e.id: e for e in resume.evidence}

    # F6 (task 4c): country-toned rewrites. `record.country` carries
    # whichever of this codebase's three destination spellings the browser
    # originally sent (`AnalysisRecord.country`, api/store.py) — `rules_for`
    # is the one place that reconciles them. `None` for the UI's "other"
    # destination is a normal outcome, not an error (engine/country/rules.py),
    # so `tone_notes` is simply `None` and every rewrite generates exactly as
    # it did before F6 existed.
    country_rules = rules_for(record.country)
    tone_notes = country_rules.tone_notes if country_rules else None

    rejected_count = 0
    try:
        candidates = detect_hidden_strengths(match, resume)
        for candidate in candidates:
            requirement = requirements_by_id.get(candidate.requirement_id)
            anchor = evidence_by_id.get(candidate.evidence_id)
            if requirement is None or anchor is None:
                continue

            accepted = None
            first_failure = None
            for attempt in range(2):
                rewrite = generate_rewrite(requirement, [anchor], tone_notes)
                result = validate_rewrite(rewrite, resume.evidence)
                if result.ok:
                    accepted = rewrite
                    break
                failure = store.log_rewrite_rejection(
                    analysis_id=analysis_id,
                    requirement_id=candidate.requirement_id,
                    evidence_id=candidate.evidence_id,
                    suggested_phrasing=rewrite.suggested_phrasing,
                    violations=result.as_log_violations,
                    retry_succeeded=False,
                )
                if attempt == 0:
                    first_failure = failure

            if accepted is None:
                rejected_count += 1
                continue

            try:
                hidden_strength = HiddenStrength(
                    requirement_id=candidate.requirement_id,
                    evidence_id=candidate.evidence_id,
                    current_phrasing=anchor.source_line,
                    suggested_phrasing=accepted.suggested_phrasing,
                    facts_used=accepted.facts_used,
                    changed_words=accepted.changed_words,
                )
                match = _append_hidden_strength(match, hidden_strength)
            except ValidationError as exc:
                # validate_rewrite's two layers judge the *phrasing*; neither
                # guarantees `facts_used` actually contains the anchor's own
                # evidence_id (precheck_rewrite can pass with zero checkable
                # tokens, and the LLM layer is never asked about facts_used at
                # all). HiddenStrength's own `_cites_its_own_evidence` validator
                # is the last line of defence against that — treat a failure
                # there exactly like any other validator rejection rather than
                # letting it crash the endpoint with a raw, unenveloped 500.
                rejected_count += 1
                store.log_rewrite_rejection(
                    analysis_id=analysis_id,
                    requirement_id=candidate.requirement_id,
                    evidence_id=candidate.evidence_id,
                    suggested_phrasing=accepted.suggested_phrasing,
                    violations=[{"claim": "facts_used/evidence_id integrity", "reason": str(exc)}],
                    retry_succeeded=False,
                )
                continue

            # Only flip the first failure's `retry_succeeded` once the retry's
            # HiddenStrength has actually made it into `match` — validation
            # passing (above) is necessary but not sufficient: the `except
            # ValidationError` branch above can still reject this same
            # candidate on the integrity check, and `continue`s past this
            # line before reaching it. `RewriteRejection` is "a report figure
            # for the evaluation chapter" (api/store.py) — a `True` logged
            # before the outcome is actually known would misreport it.
            if first_failure is not None:
                first_failure.retry_succeeded = True
    except RewriteRateLimitedError as exc:
        logger.warning("Rewrite request rate-limited: %s", exc)
        raise ApiError(
            status_code=429,
            code="RATE_LIMITED",
            message="The rewrite service is busy. Try again in a minute.",
        ) from exc
    except Exception as exc:
        # Generic on purpose: provider errors can echo keys or URLs, and this
        # message is returned to the browser. The real error is in the log.
        logger.exception("Rewrite generation failed")
        raise ApiError(
            status_code=500,
            code="ENGINE_FAILED",
            message="The analysis didn't finish. Try again.",
        ) from exc

    record.match = match
    return {
        "hidden_strengths": [h.model_dump(mode="json") for h in match.hidden_strengths],
        "rejected_count": rejected_count,
    }
