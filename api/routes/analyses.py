"""`POST /api/analyses` + `GET /api/analyses/{id}` (PERSON_B_PLAN_v2.md §5
Phase 1 task 4 and Phase 2 task 5).

Analyses are async from day one: LLM calls take 10-40s in live mode, and a
synchronous request would time out behind Caddy and look like a hang. Mock
mode uses `BackgroundTasks` with an artificial delay so the polling
loop and progress stepper are exercised honestly rather than flashing past.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import inspect
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, Request
from pydantic import BaseModel, ValidationError

from api.auth import CurrentUser, get_client_ip, get_optional_user, hash_guest_ip
from api.config import settings
from api.db import (
    db_save_jd_requirements,
    db_save_resume_evidence,
    get_supabase_client,
)
from api.errors import ApiError, new_error_id
from api.limiter import enforce_analysis_attempt_limit, enforce_operation_attempt_limit
from api.quota import (
    commit_quota,
    release_quota,
    require_quota,
    reserve_quota,
)
from api.store import STAGE_ORDER, store
from api.turnstile import verify_turnstile_token
from engine.country.rules import rules_for
from engine.execution import BoundedWorkPool, WorkCapacityError, WorkTimeoutError, remaining_timeout
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
    turnstile_token: str | None = None


class RetryIn(BaseModel):
    turnstile_token: str | None = None


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
        if record.reservation_id or record.user_id:
            release_quota(record.reservation_id, record.user_id, "analysis")
        if record.is_guest and record.guest_ip_hash:
            store.release_guest_ip_usage(record.guest_ip_hash)
        return

    total_ms = int((time.monotonic() - started_at) * 1000)
    logger.info("analysis_done analysis_id=%s total_ms=%d", analysis_id, total_ms)
    if total_ms > 60_000:
        logger.warning(
            "analysis_slow analysis_id=%s total_ms=%d threshold_ms=60000", analysis_id, total_ms,
        )
    record.status = "done"
    commit_quota(record.reservation_id, record.user_id, "analysis")


_T = TypeVar("_T")


class AnalysisQueueFullError(RuntimeError):
    """Raised when concurrent and queued live analyses reach capacity."""


class AnalysisTimeoutError(TimeoutError):
    """Raised when a live analysis or one of its external calls exceeds its deadline."""


class _AnalysisSupervisor:
    """Bounds concurrent live analyses and total queued work, holding capacity until running workers stop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._active_count = 0
        self._queued_count = 0
        self._peak_active = 0
        self._peak_queued = 0
        self._pre_reserved_ids: set[str] = set()
        self._analysis_workers: dict[str, set[threading.Thread]] = {}
        self._pending_release: set[str] = set()

    def _reap_finished_workers_locked(self) -> None:
        """Check all pending releases and decrement active_count when workers stop."""
        reaped_any = False
        to_remove: list[str] = []
        for aid in list(self._pending_release):
            workers = self._analysis_workers.get(aid, set())
            alive = {t for t in workers if t.is_alive()}
            if alive:
                self._analysis_workers[aid] = alive
            else:
                self._analysis_workers.pop(aid, None)
                to_remove.append(aid)
                self._active_count = max(0, self._active_count - 1)
                reaped_any = True
        for aid in to_remove:
            self._pending_release.remove(aid)
        if reaped_any:
            self._cond.notify_all()

    @property
    def active_count(self) -> int:
        with self._lock:
            self._reap_finished_workers_locked()
            pending_threads = [
                t for aid in self._pending_release
                for t in self._analysis_workers.get(aid, set())
                if t.is_alive()
            ]

        for t in pending_threads:
            t.join(timeout=0.1)

        with self._lock:
            self._reap_finished_workers_locked()
            return self._active_count

    @property
    def queued_count(self) -> int:
        with self._lock:
            return self._queued_count

    @property
    def in_flight_count(self) -> int:
        with self._lock:
            self._reap_finished_workers_locked()
            return self._active_count + self._queued_count

    @property
    def peak_active(self) -> int:
        with self._lock:
            self._reap_finished_workers_locked()
            return self._peak_active

    @property
    def peak_queued(self) -> int:
        with self._lock:
            return self._peak_queued

    def reset_stats(self) -> None:
        with self._lock:
            self._reap_finished_workers_locked()
            self._peak_active = self._active_count
            self._peak_queued = self._queued_count

    def register_worker(self, analysis_id: str | None, worker_thread: threading.Thread) -> None:
        if not analysis_id:
            return
        with self._lock:
            if analysis_id not in self._analysis_workers:
                self._analysis_workers[analysis_id] = set()
            self._analysis_workers[analysis_id].add(worker_thread)

    def unregister_worker(self, analysis_id: str | None, worker_thread: threading.Thread) -> None:
        if not analysis_id:
            return
        with self._lock:
            workers = self._analysis_workers.get(analysis_id)
            if workers:
                workers.discard(worker_thread)
                if not workers:
                    self._analysis_workers.pop(analysis_id, None)
            self._reap_finished_workers_locked()

    def _is_analysis_running_locked(self, analysis_id: str) -> bool:
        self._reap_finished_workers_locked()
        workers = self._analysis_workers.get(analysis_id)
        if workers:
            return any(t.is_alive() for t in workers)
        return analysis_id in self._pending_release

    def is_analysis_running(self, analysis_id: str) -> bool:
        with self._lock:
            self._reap_finished_workers_locked()
            pending_threads = [
                t for t in self._analysis_workers.get(analysis_id, set())
                if t.is_alive()
            ]

        for t in pending_threads:
            t.join(timeout=0.1)

        with self._lock:
            return self._is_analysis_running_locked(analysis_id)

    def wait_for_analysis(self, analysis_id: str, timeout: float = 2.0) -> bool:
        """Wait until all workers for analysis_id have stopped, or timeout expires."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._is_analysis_running_locked(analysis_id):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return not self._is_analysis_running_locked(analysis_id)
                self._cond.wait(timeout=remaining)
            return True

    def reserve_queue_slot(self, analysis_id: str | None = None) -> None:
        max_concurrent = max(1, int(settings.max_concurrent_analyses))
        max_queued = max(0, int(settings.max_queued_analyses))
        with self._cond:
            self._reap_finished_workers_locked()
            if self._active_count + self._queued_count >= max_concurrent + max_queued:
                raise AnalysisQueueFullError(
                    f"Analysis queue is full (active={self._active_count}, "
                    f"queued={self._queued_count}, max_concurrent={max_concurrent}, "
                    f"max_queued={max_queued})."
                )
            self._queued_count += 1
            if analysis_id is not None:
                self._pre_reserved_ids.add(analysis_id)
            if self._queued_count > self._peak_queued:
                self._peak_queued = self._queued_count

    def bind_pre_reserved_id(self, analysis_id: str) -> None:
        with self._lock:
            self._pre_reserved_ids.add(analysis_id)

    def consume_pre_reserved(self, analysis_id: str) -> bool:
        with self._lock:
            if analysis_id in self._pre_reserved_ids:
                self._pre_reserved_ids.discard(analysis_id)
                return True
            return False

    def cancel_queue_slot(self, analysis_id: str | None = None) -> None:
        with self._cond:
            if analysis_id is not None:
                self._pre_reserved_ids.discard(analysis_id)
            self._queued_count = max(0, self._queued_count - 1)
            self._cond.notify_all()

    def promote_to_active(self, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            promoted = False
            try:
                self._reap_finished_workers_locked()
                while self._active_count >= max(1, int(settings.max_concurrent_analyses)):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AnalysisTimeoutError(
                            "Timed out waiting for an available analysis execution slot."
                        )
                    self._cond.wait(timeout=remaining)
                    self._reap_finished_workers_locked()
                self._queued_count = max(0, self._queued_count - 1)
                promoted = True
                self._active_count += 1
                if self._active_count > self._peak_active:
                    self._peak_active = self._active_count
            except BaseException:
                if not promoted:
                    self._queued_count = max(0, self._queued_count - 1)
                self._cond.notify_all()
                raise

    def release_active(self, analysis_id: str | None = None) -> None:
        with self._cond:
            if not analysis_id:
                self._active_count = max(0, self._active_count - 1)
                self._cond.notify_all()
                return

            workers = self._analysis_workers.get(analysis_id, set())
            alive = {t for t in workers if t.is_alive()}
            if alive:
                self._analysis_workers[analysis_id] = alive
                self._pending_release.add(analysis_id)
            else:
                self._analysis_workers.pop(analysis_id, None)
                self._pending_release.discard(analysis_id)
                self._active_count = max(0, self._active_count - 1)
                self._cond.notify_all()


_analysis_supervisor = _AnalysisSupervisor()
_embedding_semaphore = threading.BoundedSemaphore(2)


def _capture_caller_thread_locals() -> list[tuple[threading.local, dict[str, Any]]]:
    """Capture `threading.local` state from caller frames so worker threads inherit context."""
    captured: list[tuple[threading.local, dict[str, Any]]] = []
    seen_ids: set[int] = set()
    frame = inspect.currentframe()
    try:
        while frame is not None:
            for val in list(frame.f_locals.values()):
                if isinstance(val, threading.local) and id(val) not in seen_ids:
                    seen_ids.add(id(val))
                    with contextlib.suppress(Exception):
                        tl_dict = dict(val.__dict__)
                        if tl_dict:
                            captured.append((val, tl_dict))
            frame = frame.f_back
    finally:
        del frame
    return captured


@contextlib.contextmanager
def _apply_thread_locals(captured: list[tuple[threading.local, dict[str, Any]]]):
    for tl_obj, tl_dict in captured:
        with contextlib.suppress(Exception):
            tl_obj.__dict__.update(tl_dict)
    try:
        yield
    finally:
        for tl_obj, tl_dict in captured:
            with contextlib.suppress(Exception):
                for k in tl_dict:
                    tl_obj.__dict__.pop(k, None)


def _remaining_deadline(deadline: float, stage_label: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AnalysisTimeoutError(
            f"Live analysis exceeded deadline during {stage_label}."
        )
    return remaining


def _call_with_deadline(  # noqa: UP047
    fn: Callable[..., _T],
    *args: Any,
    timeout: float,
    stage_label: str,
    captured_locals: list[tuple[threading.local, dict[str, Any]]],
    analysis_id: str | None = None,
    **kwargs: Any,
) -> _T:
    """Run a blocking callable with a hard deadline without releasing capacity until the thread stops."""
    eff_timeout = max(0.01, timeout)
    worker_started = threading.Event()
    worker_th: list[threading.Thread] = []

    # If fn accepts timeout in signature, forward eff_timeout
    try:
        sig = inspect.signature(fn)
        if "timeout" in sig.parameters and "timeout" not in kwargs:
            kwargs["timeout"] = eff_timeout
    except Exception:
        pass

    def _wrapped() -> _T:
        th = threading.current_thread()
        worker_th.append(th)
        if analysis_id:
            _analysis_supervisor.register_worker(analysis_id, th)
        worker_started.set()
        try:
            with _apply_thread_locals(captured_locals):
                return fn(*args, **kwargs)
        finally:
            if analysis_id:
                _analysis_supervisor.unregister_worker(analysis_id, th)

    t_start = time.monotonic()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = executor.submit(_wrapped)
        worker_started.wait(timeout=eff_timeout)
        elapsed = time.monotonic() - t_start
        remaining = max(0.001, eff_timeout - elapsed)
        try:
            return fut.result(timeout=remaining)
        except concurrent.futures.TimeoutError as err:
            fut.cancel()
            raise AnalysisTimeoutError(
                f"External call in {stage_label} timed out after {eff_timeout:.2f}s."
            ) from err
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _persist_embeddings_bounded(
    res_id: str,
    evidence_list: list[Any],
    job_id: str,
    job_hash: str,
    requirements_list: list[Any],
    call_timeout: float,
) -> None:
    if not _embedding_semaphore.acquire(blocking=False):
        logger.debug("Skipping background embedding persistence: workers busy.")
        return

    def _worker() -> None:
        from engine.gemini_client import get_embedding

        emb_exec = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        try:
            ev_futures = {
                ev.id: emb_exec.submit(get_embedding, ev.source_line, timeout=call_timeout)
                for ev in evidence_list
            }
            req_futures = {
                req.id: emb_exec.submit(get_embedding, req.text, timeout=call_timeout)
                for req in requirements_list
            }
            ev_vectors = {
                eid: fut.result(timeout=call_timeout)
                for eid, fut in ev_futures.items()
            }
            req_vectors = {
                rid: fut.result(timeout=call_timeout)
                for rid, fut in req_futures.items()
            }
            db_save_resume_evidence(
                res_id,
                [ev.model_dump(mode="json") for ev in evidence_list],
                ev_vectors,
            )
            db_save_jd_requirements(
                job_id,
                job_hash,
                [req.model_dump(mode="json") for req in requirements_list],
                req_vectors,
            )
        except Exception as emb_err:
            logger.warning("Could not persist pgvector embeddings: %s", emb_err)
        finally:
            emb_exec.shutdown(wait=True, cancel_futures=True)
            _embedding_semaphore.release()

    bg_thread = threading.Thread(target=_worker, daemon=True)
    bg_thread.start()


def _execute_live_analysis_sync(
    analysis_id: str,
    captured_locals: list[tuple[threading.local, dict[str, Any]]],
) -> None:
    """Synchronous live analysis pipeline executed entirely outside the server event loop."""
    with _apply_thread_locals(captured_locals):
        slot_pre_reserved = _analysis_supervisor.consume_pre_reserved(analysis_id)
        record = store.get_analysis(analysis_id)
        if not record:
            if slot_pre_reserved:
                _analysis_supervisor.cancel_queue_slot()
            return

        started_at = time.monotonic()
        total_timeout = max(0.05, float(settings.analysis_timeout_seconds))
        ext_call_cap = max(0.05, float(settings.external_call_timeout_seconds))
        deadline = started_at + total_timeout

        active_acquired = False
        try:
            if not slot_pre_reserved:
                _analysis_supervisor.reserve_queue_slot()

            queue_wait_timeout = _remaining_deadline(deadline, "queue_wait")
            _analysis_supervisor.promote_to_active(timeout=queue_wait_timeout)
            active_acquired = True

            store.update_analysis(analysis_id, status="running")

            from engine.ingest import fetch_jd
            from engine.match import run_baseline, run_match
            from engine.normalize import normalize_jd, normalize_resume

            res_rec = store.get_resume(record.resume_id)
            if not res_rec:
                raise ValueError(f"Resume {record.resume_id} not found.")

            job_rec = store.get_job(record.job_id)
            if not job_rec:
                raise ValueError(f"Job {record.job_id} not found.")

            # Stage 1 & 2: Normalize resume and job concurrently with bounded deadline
            store.update_analysis(analysis_id, stage="reading_resume")

            norm_timeout = min(
                ext_call_cap, _remaining_deadline(deadline, "normalization")
            )

            def _do_norm_resume():
                if res_rec.normalized is not None:
                    return res_rec.normalized.model_copy(deep=True)
                has_raw_text = bool(res_rec.raw_text and res_rec.raw_text.strip())
                data_bytes = res_rec.data or (
                    res_rec.raw_text.encode("utf-8") if has_raw_text else b""
                )
                is_mock = hasattr(normalize_resume, "_mock_name") or hasattr(
                    normalize_resume, "assert_called"
                )
                norm_kwargs: dict[str, Any] = {}
                if not is_mock:
                    sig = inspect.signature(normalize_resume)
                    if "raw_text" in sig.parameters and has_raw_text:
                        norm_kwargs["raw_text"] = res_rec.raw_text
                    if "timeout" in sig.parameters:
                        norm_kwargs["timeout"] = norm_timeout
                return normalize_resume(data_bytes, res_rec.filename, **norm_kwargs).model_copy(
                    deep=True
                )

            def _do_norm_jd():
                if job_rec.normalized is not None:
                    return job_rec.normalized.model_copy(deep=True)
                raw_jd = (
                    fetch_jd(job_rec.raw)
                    if job_rec.source == "url"
                    else job_rec.raw
                )
                is_mock = hasattr(normalize_jd, "_mock_name") or hasattr(
                    normalize_jd, "assert_called"
                )
                norm_kwargs: dict[str, Any] = {}
                if not is_mock:
                    sig = inspect.signature(normalize_jd)
                    if "timeout" in sig.parameters:
                        norm_kwargs["timeout"] = norm_timeout
                return normalize_jd(raw_jd, **norm_kwargs).model_copy(deep=True)

            norm_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            res_started = threading.Event()
            job_started = threading.Event()

            def _wrapped_res() -> Any:
                th = threading.current_thread()
                _analysis_supervisor.register_worker(analysis_id, th)
                res_started.set()
                try:
                    with _apply_thread_locals(captured_locals):
                        return _do_norm_resume()
                finally:
                    _analysis_supervisor.unregister_worker(analysis_id, th)

            def _wrapped_job() -> Any:
                th = threading.current_thread()
                _analysis_supervisor.register_worker(analysis_id, th)
                job_started.set()
                try:
                    with _apply_thread_locals(captured_locals):
                        return _do_norm_jd()
                finally:
                    _analysis_supervisor.unregister_worker(analysis_id, th)

            try:
                fut_res = norm_executor.submit(_wrapped_res)
                fut_job = norm_executor.submit(_wrapped_job)
                res_started.wait(timeout=norm_timeout)
                job_started.wait(timeout=norm_timeout)

                res_timeout = min(
                    ext_call_cap, _remaining_deadline(deadline, "reading_resume")
                )
                try:
                    resume = fut_res.result(timeout=res_timeout)
                except concurrent.futures.TimeoutError as err:
                    fut_res.cancel()
                    fut_job.cancel()
                    raise AnalysisTimeoutError(
                        f"Resume normalization timed out after {res_timeout:.2f}s."
                    ) from err

                job_timeout = min(
                    ext_call_cap, _remaining_deadline(deadline, "reading_jd")
                )
                try:
                    job = fut_job.result(timeout=job_timeout)
                except concurrent.futures.TimeoutError as err:
                    fut_job.cancel()
                    raise AnalysisTimeoutError(
                        f"Job normalization timed out after {job_timeout:.2f}s."
                    ) from err
            finally:
                norm_executor.shutdown(wait=False, cancel_futures=True)

            # Save normalized structures to existing records & Supabase
            _remaining_deadline(deadline, "saving_normalized")
            cur_rec = store.get_analysis(analysis_id)
            if not cur_rec or cur_rec.status == "failed" or cur_rec.retried_by is not None:
                return
            store.save_normalized_resume(res_rec.id, resume)
            store.save_normalized_job(job_rec.id, job)

            # Stage 3: matching_requirements
            store.update_analysis(analysis_id, stage="matching_requirements")
            match_timeout = min(
                ext_call_cap, _remaining_deadline(deadline, "matching_requirements")
            )
            match = _call_with_deadline(
                run_match,
                job,
                resume,
                timeout=match_timeout,
                stage_label="matching_requirements",
                captured_locals=captured_locals,
                analysis_id=analysis_id,
            ).model_copy(deep=True)

            base_timeout = min(
                ext_call_cap, _remaining_deadline(deadline, "baseline_matching")
            )
            baseline = _call_with_deadline(
                run_baseline,
                job,
                resume,
                timeout=base_timeout,
                stage_label="baseline_matching",
                captured_locals=captured_locals,
                analysis_id=analysis_id,
            ).model_copy(deep=True)

            # Stage 4: checking_realism & completion
            _remaining_deadline(deadline, "checking_realism")
            cur_rec = store.get_analysis(analysis_id)
            if not cur_rec or cur_rec.status == "failed" or cur_rec.retried_by is not None:
                logger.warning(
                    "Analysis %s was failed or retried before completion; dropping late result",
                    analysis_id,
                )
                return

            store.update_analysis(analysis_id, stage="checking_realism")
            match.job = job.model_copy(deep=True)
            match.resume = resume.model_copy(deep=True)

            store.update_analysis(
                analysis_id, status="done", match=match, baseline=baseline
            )
            commit_quota(record.reservation_id, record.user_id, "analysis")

            # Parallel pgvector embeddings persistence in background (non-blocking & bounded)
            if get_supabase_client():
                _persist_embeddings_bounded(
                    res_rec.id,
                    list(resume.evidence),
                    job_rec.id,
                    job.content_hash,
                    list(job.requirements),
                    call_timeout=ext_call_cap,
                )

        except Exception as err:
            error_id = new_error_id()
            logger.exception(
                "Live analysis failed analysis_id=%s error_id=%s: %s",
                analysis_id,
                error_id,
                err,
            )
            safe_message = "The live engine could not complete this analysis."
            error_payload = {
                "code": "ENGINE_FAILED",
                "message": safe_message,
                "error_id": error_id,
            }
            store.update_analysis(
                analysis_id,
                status="failed",
                match=None,
                baseline=None,
                error=error_payload,
                # Generic on purpose: str(err) can carry provider internals (URLs,
                # keys echoed in SDK errors) and this field is returned to the browser.
                # The real error is in the log line above.
                error_message=safe_message,
            )
            if record.reservation_id or record.user_id:
                release_quota(record.reservation_id, record.user_id, "analysis")
            if record.is_guest and record.guest_ip_hash:
                store.release_guest_ip_usage(record.guest_ip_hash)
        finally:
            if active_acquired:
                _analysis_supervisor.release_active(analysis_id)


async def _run_live_analysis(analysis_id: str) -> None:
    """Offload the entire blocking live analysis pipeline outside the server event loop."""
    captured_locals = _capture_caller_thread_locals()
    await asyncio.to_thread(
        _execute_live_analysis_sync,
        analysis_id,
        captured_locals,
    )


_DEFAULT_RUN_LIVE_ANALYSIS = _run_live_analysis


def _assert_analysis_access(record, user: CurrentUser | None) -> None:
    """Enforce row-level ownership: a user cannot read or mutate another user's rows."""
    if record.user_id is not None:
        if user is None:
            raise ApiError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Sign in to view this analysis.",
            )
        if user.id != record.user_id:
            raise ApiError(
                status_code=403,
                code="FORBIDDEN",
                message="You do not have permission to access this analysis.",
            )


@router.post("/analyses", status_code=202)
async def create_analysis(
    payload: AnalysisIn,
    background_tasks: BackgroundTasks,
    request: Request,
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
    _quota: None = Depends(require_quota("analysis")),  # noqa: B008
) -> dict:
    res_rec = store.get_resume(payload.resume_id)
    if not res_rec:
        raise ApiError(
            status_code=404,
            code="RESUME_NOT_FOUND",
            message="Unknown resume_id.",
        )
    if res_rec.user_id is not None and (user is None or user.id != res_rec.user_id):
        raise ApiError(
            status_code=403,
            code="FORBIDDEN",
            message="You do not have permission to use this resume.",
        )
    if not store.get_job(payload.job_id):
        raise ApiError(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="Unknown job_id.",
        )

    if user is None:
        await verify_turnstile_token(payload.turnstile_token, get_client_ip(request), expected_action="guest_analysis")

    is_live = settings.engine_mode == "live"
    use_supervisor = is_live and (_run_live_analysis is _DEFAULT_RUN_LIVE_ANALYSIS)
    if use_supervisor:
        try:
            _analysis_supervisor.reserve_queue_slot()
        except AnalysisQueueFullError as err:
            raise ApiError(
                status_code=429,
                code="RATE_LIMITED",
                message="Too many analyses in progress. Please wait a moment and try again.",
            ) from err

    is_guest = user is None and settings.enforce_guest_limit
    ip_hash: str | None = None
    guest_reserved = False
    reservation_id: str | None = None
    try:
        if is_guest:
            ip_hash = hash_guest_ip(request)
            if not store.reserve_guest_ip_usage(ip_hash):
                raise ApiError(
                    status_code=429,
                    code="GUEST_LIMIT_REACHED",
                    message="You have used your 1 free guest analysis for today. Sign in to save results and get more analyses.",
                )
            guest_reserved = True
        elif user is not None:
            reservation_id = reserve_quota(user.id, "analysis")

        if is_live:
            await asyncio.to_thread(enforce_analysis_attempt_limit, request, user)
        record = store.create_analysis(
            payload.resume_id,
            payload.job_id,
            payload.country,
            user_id=user.id if user else None,
            is_guest=is_guest,
            reservation_id=reservation_id,
        )
        record.reservation_id = reservation_id
        record.guest_ip_hash = ip_hash
        if use_supervisor:
            _analysis_supervisor.bind_pre_reserved_id(record.id)
    except Exception:
        if use_supervisor:
            _analysis_supervisor.cancel_queue_slot()
        if guest_reserved and ip_hash:
            store.release_guest_ip_usage(ip_hash)
        if reservation_id and user:
            release_quota(reservation_id, user.id, "analysis")
        raise

    if is_live:
        background_tasks.add_task(_run_live_analysis, record.id)
    else:
        background_tasks.add_task(_run_mock_analysis, record.id)

    return {"analysis_id": record.id, "status": record.status, "is_guest": record.is_guest}


@router.get("/analyses/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
) -> dict:
    record = store.get_analysis(analysis_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code="ANALYSIS_NOT_FOUND",
            message="Unknown analysis_id.",
        )
    _assert_analysis_access(record, user)

    return {
        "status": record.status,
        "stage": record.stage,
        "match": record.match.model_dump(mode="json") if record.match else None,
        "baseline": record.baseline.model_dump(mode="json") if record.baseline else None,
        "error": record.error,
        "error_message": record.error_message,
        "is_guest": record.is_guest or record.user_id is None,
    }


@router.get("/analyses")
async def list_analyses(
    resume_id: str | None = Query(default=None),
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
) -> list[AnalysisSummary]:
    if user is None and (resume_id is None or not resume_id.strip()):
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Authentication or resume_id required.",
        )
    summaries: list[AnalysisSummary] = []
    for record in store.analyses_for_resume(
        resume_id=resume_id.strip() if resume_id else None,
        user_id=user.id if user else None,
    ):
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
async def retry_analysis(
    analysis_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    payload: RetryIn | None = Body(default=None),  # noqa: B008
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
) -> dict:
    original = store.get_analysis(analysis_id)
    if original is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")
    _assert_analysis_access(original, user)

    # 1. State eligibility check: only "failed" or "done" can be retried
    if original.status in ("queued", "running") or _analysis_supervisor.is_analysis_running(analysis_id):
        raise ApiError(
            status_code=409,
            code="ANALYSIS_IN_PROGRESS",
            message="Cannot retry an analysis that is still queued or running.",
        )

    # 2. Check if a duplicate retry is already in flight
    if original.retried_by:
        child = store.get_analysis(original.retried_by)
        if child and (child.status in ("queued", "running") or _analysis_supervisor.is_analysis_running(child.id)):
            raise ApiError(
                status_code=409,
                code="ANALYSIS_IN_PROGRESS",
                message="A retry for this analysis is already in progress.",
            )

    # 3. Quota, guest, and live queue capacity checks
    ip_hash: str | None = None
    reservation_id: str | None = None
    is_guest = user is None and settings.enforce_guest_limit

    if user is None:
        token = payload.turnstile_token if payload else None
        await verify_turnstile_token(token, get_client_ip(request), expected_action="guest_analysis")

    is_live = settings.engine_mode == "live"
    use_supervisor = is_live and (_run_live_analysis is _DEFAULT_RUN_LIVE_ANALYSIS)
    if use_supervisor:
        try:
            _analysis_supervisor.reserve_queue_slot()
        except AnalysisQueueFullError as err:
            raise ApiError(
                status_code=429,
                code="RATE_LIMITED",
                message="Too many analyses in progress. Please wait a moment and try again.",
            ) from err

    guest_reserved = False
    try:
        if user is None:
            if settings.enforce_guest_limit:
                ip_hash = hash_guest_ip(request)
                if not store.reserve_guest_ip_usage(ip_hash):
                    raise ApiError(
                        status_code=429,
                        code="GUEST_LIMIT_REACHED",
                        message="You have used your 1 free guest analysis for today. Sign in to save results and get more analyses.",
                    )
                guest_reserved = True
        else:
            reservation_id = reserve_quota(user.id, "analysis")

        if is_live:
            await asyncio.to_thread(enforce_analysis_attempt_limit, request, user)
        record = store.create_retry(
            analysis_id,
            user_id=user.id if user else None,
            is_guest=is_guest,
            reservation_id=reservation_id,
        )
        assert record is not None
        record.reservation_id = reservation_id
        record.guest_ip_hash = ip_hash
        if use_supervisor:
            _analysis_supervisor.bind_pre_reserved_id(record.id)
    except Exception:
        if use_supervisor:
            _analysis_supervisor.cancel_queue_slot()
        if guest_reserved and ip_hash:
            store.release_guest_ip_usage(ip_hash)
        if reservation_id and user:
            release_quota(reservation_id, user.id, "analysis")
        raise

    if is_live:
        background_tasks.add_task(_run_live_analysis, record.id)
    else:
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
def create_rewrites(
    analysis_id: str,
    user: CurrentUser | None = Depends(get_optional_user),  # noqa: B008
) -> dict:
    try:
        return _rewrite_pool.run(
            lambda: _create_rewrites_sync(analysis_id, user),
            timeout=settings.rewrite_timeout_seconds, limit=settings.max_concurrent_rewrites,
        )
    except WorkCapacityError as exc:
        raise ApiError(429, "RATE_LIMITED", "The rewrite service is busy. Try again shortly.") from exc
    except WorkTimeoutError as exc:
        raise ApiError(504, "ENGINE_FAILED", "The rewrite took too long. Please try again later.") from exc


_rewrite_pool = BoundedWorkPool("ai-rewrite")


def _create_rewrites_sync(analysis_id: str, user: CurrentUser | None) -> dict:
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
    remaining_timeout()
    if settings.enforce_auth_on_rewrites and user is None:
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Sign in to generate AI rewrites.",
        )

    record = store.get_analysis(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")
    _assert_analysis_access(record, user)
    if record.status != "done" or record.match is None:
        raise ApiError(
            status_code=409,
            code="ANALYSIS_NOT_READY",
            message="Analysis has not finished; there is no match to run rewrites against.",
        )

    with store._lock:
        if record.rewrite_status == "done" and record.match is not None:
            return {
                "hidden_strengths": [h.model_dump(mode="json") for h in record.match.hidden_strengths],
                "rejected_count": record.rewrite_rejected_count,
            }
        if record.rewrite_in_progress:
            raise ApiError(
                status_code=409,
                code="ANALYSIS_IN_PROGRESS",
                message="A rewrite for this analysis is already in progress.",
            )
        record.rewrite_in_progress = True

    target_user_id = user.id if user else record.user_id
    reservation_id: str | None = None
    try:
        match = record.match
        resume = match.resume
        if resume is None or match.job is None:
            with store._lock:
                record.rewrite_status = "done"
                record.rewrite_rejected_count = 0
            return {
                "hidden_strengths": [h.model_dump(mode="json") for h in match.hidden_strengths],
                "rejected_count": 0,
            }

        if target_user_id and not (user and user.is_admin):
            reservation_id = reserve_quota(target_user_id, "rewrite", user=user)

        # Failed AI calls may cost money even when the user's success quota is refunded.
        subject = f"user:{target_user_id}" if target_user_id else f"guest-analysis:{analysis_id}"
        enforce_operation_attempt_limit("rewrite", subject, settings.rewrite_attempts_per_hour)

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
            if reservation_id or target_user_id:
                release_quota(reservation_id, target_user_id, "rewrite")
                reservation_id = None
            logger.warning("Rewrite request rate-limited: %s", exc)
            raise ApiError(
                status_code=429,
                code="RATE_LIMITED",
                message="The rewrite service is busy. Try again in a minute.",
            ) from exc
        except WorkTimeoutError:
            raise
        except Exception as exc:
            if reservation_id or target_user_id:
                release_quota(reservation_id, target_user_id, "rewrite")
                reservation_id = None
            # Generic on purpose: provider errors can echo keys or URLs, and this
            # message is returned to the browser. The real error is in the log.
            logger.exception("Rewrite generation failed")
            raise ApiError(
                status_code=500,
                code="ENGINE_FAILED",
                message="The analysis didn't finish. Try again.",
            ) from exc

        remaining_timeout()
        store.update_analysis(analysis_id, match=match)
        with store._lock:
            record.rewrite_status = "done"
            record.rewrite_rejected_count = rejected_count

        if candidates:
            if target_user_id:
                commit_quota(reservation_id, target_user_id, "rewrite")
                reservation_id = None
        else:
            if reservation_id or target_user_id:
                release_quota(reservation_id, target_user_id, "rewrite")
                reservation_id = None

        return {
            "hidden_strengths": [h.model_dump(mode="json") for h in match.hidden_strengths],
            "rejected_count": rejected_count,
        }
    finally:
        if reservation_id:
            release_quota(reservation_id, target_user_id, "rewrite")
        with store._lock:
            record.rewrite_in_progress = False
