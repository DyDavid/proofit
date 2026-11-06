"""Phase 2 Tests: Keep live analyses responsive and safely bounded.

Verifies:
1. Other HTTP/async requests remain responsive during slow blocking live analyses.
2. Resume normalization reuses safely extracted `raw_text` without reparsing original files,
   and any file parsing strictly goes through the supervised child-process parser.
3. Concurrent live analyses (`max_concurrent_analyses`) and queued work (`max_queued_analyses`)
   are bounded; excess requests fail fast with 429 RATE_LIMITED without burning quota.
4. External calls and overall pipeline execution enforce deadlines without hanging on stuck threads.
5. Failures (exceptions, parser timeouts, external call deadlines, queue saturation) leave
   consistent analysis status, quota, guest usage, and concurrency supervisor state.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api.billing.service import get_subscription_summary, reset_billing_memory
from api.config import settings
from api.main import app
from api.routes.analyses import (
    _analysis_supervisor,
    _run_live_analysis,
    get_analysis,
)
from api.store import _load_baseline_fixture, _load_fixture, store
from engine.normalize import normalize_resume
from engine.normalize.normalizer import (
    clear_normalizer_cache,
    normalize_resume_file,
)
from engine.normalize.normalizer import (
    normalize_resume_text as _real_normalize_resume_text,
)
from engine.normalize.parser import (
    DecompressionLimitError,
    ParserConcurrencyError,
    ParserTimeoutError,
    run_parser_in_process_with_timeout,
)
from engine.normalize.schema import Job, Match, Resume

client = TestClient(app)

TEST_JWT_SECRET = "phase2-responsive-bounds-test-jwt-secret-32-bytes-min"
USER_ID = "user_phase2_bounded_01"
USER_EMAIL = "bounded.user@example.test"


def _make_token(user_id: str = USER_ID, email: str = USER_EMAIL) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _auth_headers(user_id: str = USER_ID, email: str = USER_EMAIL) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id, email)}"}


def _clear_store() -> None:
    store.resumes.clear()
    store.jobs.clear()
    store.jobs_by_hash.clear()
    store.analyses.clear()
    store.guest_ip_usage.clear()


@pytest.fixture(autouse=True)
def _clean_phase2_state(monkeypatch: pytest.MonkeyPatch):
    _clear_store()
    reset_billing_memory()
    clear_normalizer_cache()
    _analysis_supervisor.reset_stats()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "turnstile_secret_key", None)
    monkeypatch.setattr(settings, "enforce_quotas", True)
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    yield
    _clear_store()
    reset_billing_memory()
    clear_normalizer_cache()


# ── 1. Event Loop Responsiveness During Slow Blocking Analysis ──────────────


def test_other_requests_remain_responsive_during_slow_live_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While `_run_live_analysis` executes blocking synchronous work, the event loop
    must remain free to serve concurrent requests with low latency."""
    monkeypatch.setattr(settings, "engine_mode", "live")

    fixture = _load_fixture("fresh_grad_strong_fit")
    base_fixture = _load_baseline_fixture("fresh_grad_strong_fit")

    res_rec = store.add_resume(
        filename="candidate.pdf",
        content_type="application/pdf",
        size=128,
        raw_text="Candidate with Python and FastAPI project experience.",
        user_id=USER_ID,
    )
    job_rec, _ = store.add_job(
        raw="Backend Engineer role requiring Python, FastAPI, and SQL skills.",
        source="text",
    )
    analysis_rec = store.create_analysis(
        res_rec.id, job_rec.id, "cambodia", user_id=USER_ID
    )

    entered_match = threading.Event()

    def _slow_blocking_match(job: Job, resume: Resume) -> Match:
        entered_match.set()
        # Synchronous OS-thread sleep that would freeze the event loop if run on it
        time.sleep(0.35)
        m = fixture.model_copy(deep=True)
        m.job = job.model_copy(deep=True)
        m.resume = resume.model_copy(deep=True)
        return m

    async def _exercise_event_loop() -> None:
        analysis_task = asyncio.create_task(_run_live_analysis(analysis_rec.id))

        # Wait asynchronously until the worker thread enters the blocking match call
        deadline = time.monotonic() + 2.0
        while not entered_match.is_set():
            assert time.monotonic() < deadline, "Worker did not enter run_match in time"
            await asyncio.sleep(0.005)

        # Issue 5 concurrent poll calls on the same event loop while _slow_blocking_match sleeps
        latencies: list[float] = []
        for _ in range(5):
            t0 = time.monotonic()
            poll_res = await get_analysis(analysis_rec.id, user=None)
            # Note: analysis_rec has user_id=USER_ID; pass matching CurrentUser
            latencies.append(time.monotonic() - t0)
            assert poll_res is not None

        await analysis_task

    from api.auth import CurrentUser

    current_user = CurrentUser(id=USER_ID, email=USER_EMAIL)

    async def _exercise_with_auth() -> list[float]:
        analysis_task = asyncio.create_task(_run_live_analysis(analysis_rec.id))

        deadline = time.monotonic() + 2.0
        while not entered_match.is_set():
            assert time.monotonic() < deadline, "Worker did not enter run_match in time"
            await asyncio.sleep(0.005)

        latencies: list[float] = []
        for _ in range(5):
            t0 = time.monotonic()
            # Yield to the event loop and invoke the async route handler directly
            await asyncio.sleep(0)
            payload = await get_analysis(analysis_rec.id, user=current_user)
            elapsed = time.monotonic() - t0
            latencies.append(elapsed)
            assert payload["status"] == "running"
            assert payload["stage"] == "matching_requirements"

        await analysis_task
        return latencies

    with (
        patch(
            "engine.normalize.normalize_jd",
            return_value=fixture.job.model_copy(deep=True),
        ),
        patch("engine.match.run_match", side_effect=_slow_blocking_match),
        patch(
            "engine.match.run_baseline",
            return_value=base_fixture.model_copy(deep=True),
        ),
    ):
        poll_latencies = asyncio.run(_exercise_with_auth())

    # Every poll during the 350ms blocking sleep must complete in well under 80ms
    for lat in poll_latencies:
        assert lat < 0.08, f"Event loop was blocked! Poll took {lat:.3f}s"

    final_rec = store.get_analysis(analysis_rec.id)
    assert final_rec is not None
    assert final_rec.status == "done"
    assert final_rec.match is not None


# ── 2. Supervised Parsing & Reuse of Extracted Text ─────────────────────────


def test_live_analysis_reuses_extracted_raw_text_without_reparsing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `res_rec.raw_text` was already extracted at upload time, live analysis
    must reuse `raw_text` and never reparse `res_rec.data`."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setenv("ENGINE_MODE", "mock")

    fixture = _load_fixture("fresh_grad_strong_fit")
    base_fixture = _load_baseline_fixture("fresh_grad_strong_fit")

    res_rec = store.add_resume(
        filename="uploaded.pdf",
        content_type="application/pdf",
        size=256,
        data=b"%PDF-1.4 binary bytes that should not be reparsed",
        raw_text="Pre-extracted safe resume text with Python and SQL skills.",
        user_id=USER_ID,
    )
    job_rec, _ = store.add_job(
        raw="Software engineer position requiring Python and SQL.",
        source="text",
    )
    analysis_rec = store.create_analysis(
        res_rec.id, job_rec.id, "cambodia", user_id=USER_ID
    )

    with (
        patch(
            "engine.normalize.normalizer.run_parser_in_process_with_timeout",
            side_effect=AssertionError("Should not reparse file when raw_text exists!"),
        ) as mock_sup_parser,
        patch(
            "engine.normalize.parser.parse_resume_bytes",
            side_effect=AssertionError("Should never call unsupervised parse_resume_bytes!"),
        ) as mock_raw_parser,
        patch(
            "engine.normalize.normalizer.normalize_resume_text",
            wraps=_real_normalize_resume_text,
        ) as spy_norm_text,
        patch(
            "engine.normalize.normalize_jd",
            return_value=fixture.job.model_copy(deep=True),
        ),
        patch(
            "engine.match.run_match",
            return_value=fixture.model_copy(deep=True),
        ),
        patch(
            "engine.match.run_baseline",
            return_value=base_fixture.model_copy(deep=True),
        ),
    ):
        asyncio.run(_run_live_analysis(analysis_rec.id))

        assert spy_norm_text.call_count == 1
        assert spy_norm_text.call_args[0][0] == res_rec.raw_text
        assert mock_sup_parser.call_count == 0
        assert mock_raw_parser.call_count == 0

    done = store.get_analysis(analysis_rec.id)
    assert done is not None
    assert done.status == "done"


def test_normalize_resume_file_cannot_bypass_supervised_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `normalize_resume_file` or `normalize_resume` is called without pre-extracted
    `raw_text`, it must route through `run_parser_in_process_with_timeout` and enforce
    parser timeouts, concurrency limits, and decompression bounds."""
    monkeypatch.setenv("ENGINE_MODE", "mock")

    with patch(
        "engine.normalize.normalizer.run_parser_in_process_with_timeout",
        wraps=run_parser_in_process_with_timeout,
    ) as spy_supervised:
        resume = normalize_resume_file(
            b"Candidate resume text with React and TypeScript.", "resume.txt"
        )
        assert isinstance(resume, Resume)
        assert spy_supervised.call_count == 1

    # Also verify that when a ResumeRecord has raw_text=None and only raw bytes,
    # live analysis parses via the supervised parser and respects parser failures.
    monkeypatch.setattr(settings, "engine_mode", "live")
    res_rec = store.add_resume(
        filename="unparsed.pdf",
        content_type="application/pdf",
        size=64,
        data=b"Fallback resume bytes without pre-extracted raw_text",
        raw_text=None,
        user_id=USER_ID,
    )
    job_rec, _ = store.add_job(
        raw="Developer role requiring React and TypeScript skills.",
        source="text",
    )
    analysis_rec = store.create_analysis(
        res_rec.id, job_rec.id, "cambodia", user_id=USER_ID
    )

    with patch(
        "engine.normalize.normalizer.run_parser_in_process_with_timeout",
        side_effect=ParserTimeoutError("Supervised parser timed out", pid=99999),
    ) as mock_supervised:
        asyncio.run(_run_live_analysis(analysis_rec.id))
        assert mock_supervised.call_count == 1

    failed = store.get_analysis(analysis_rec.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.match is None
    assert failed.error is not None
    assert failed.error["code"] == "ENGINE_FAILED"


@pytest.mark.parametrize(
    "parser_exc",
    [
        ParserTimeoutError("Document parsing timed out after 8.00s", pid=12345),
        ParserConcurrencyError("Maximum concurrent document parses (3) exceeded."),
        DecompressionLimitError("DOCX total uncompressed size exceeds limit."),
    ],
)
def test_parser_supervision_errors_propagate_through_normalize_resume(
    parser_exc: Exception,
) -> None:
    """Timeout, concurrency, and decompression errors from the supervised parser
    must never be swallowed or bypassed by `normalize_resume`."""
    with (
        patch(
            "engine.normalize.normalizer.run_parser_in_process_with_timeout",
            side_effect=parser_exc,
        ),
        pytest.raises(type(parser_exc)),
    ):
        normalize_resume(b"PK\x03\x04fake-archive", "resume.docx")


# ── 3. Bounded Concurrent Analyses and Queued Work ──────────────────────────


def test_concurrent_analyses_and_queued_work_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At most `max_concurrent_analyses` run simultaneously, at most `max_queued_analyses`
    wait in the queue, and excess submissions are rejected with 429 RATE_LIMITED
    without consuming user quota or guest usage."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "max_concurrent_analyses", 2)
    monkeypatch.setattr(settings, "max_queued_analyses", 1)
    _analysis_supervisor.reset_stats()

    fixture = _load_fixture("fresh_grad_strong_fit")
    base_fixture = _load_baseline_fixture("fresh_grad_strong_fit")

    res_rec = store.add_resume(
        filename="cv.pdf",
        content_type="application/pdf",
        size=100,
        raw_text="Candidate resume text",
        user_id=USER_ID,
    )
    job_rec, _ = store.add_job(
        raw="Job description text with sufficient length for validation.",
        source="text",
    )

    two_running = threading.Barrier(3, timeout=3.0)
    release_workers = threading.Event()

    def _gated_match(job: Job, resume: Resume) -> Match:
        if not release_workers.is_set():
            with contextlib.suppress(threading.BrokenBarrierError):
                two_running.wait()
        release_workers.wait(timeout=3.0)
        m = fixture.model_copy(deep=True)
        m.job = job.model_copy(deep=True)
        m.resume = resume.model_copy(deep=True)
        return m

    import contextlib

    rec1 = store.create_analysis(res_rec.id, job_rec.id, "cambodia", user_id=USER_ID)
    rec2 = store.create_analysis(res_rec.id, job_rec.id, "cambodia", user_id=USER_ID)
    rec3 = store.create_analysis(res_rec.id, job_rec.id, "cambodia", user_id=USER_ID)

    with (
        patch(
            "engine.normalize.normalize_resume",
            return_value=fixture.resume.model_copy(deep=True),
        ),
        patch(
            "engine.normalize.normalize_jd",
            return_value=fixture.job.model_copy(deep=True),
        ),
        patch("engine.match.run_match", side_effect=_gated_match),
        patch(
            "engine.match.run_baseline",
            return_value=base_fixture.model_copy(deep=True),
        ),
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool,
    ):
        fut1 = pool.submit(lambda: asyncio.run(_run_live_analysis(rec1.id)))
        fut2 = pool.submit(lambda: asyncio.run(_run_live_analysis(rec2.id)))

        # Wait until both rec1 and rec2 are actively inside _gated_match
        two_running.wait()
        assert _analysis_supervisor.active_count == 2

        # Submit rec3: it should enter the queue and wait since active_count == 2
        fut3 = pool.submit(lambda: asyncio.run(_run_live_analysis(rec3.id)))
        deadline = time.monotonic() + 2.0
        while _analysis_supervisor.queued_count < 1:
            assert time.monotonic() < deadline
            time.sleep(0.01)

        assert _analysis_supervisor.active_count == 2
        assert _analysis_supervisor.queued_count == 1
        assert store.get_analysis(rec3.id).status == "queued"

        # Now active (2) + queued (1) == 3 (capacity full!).
        # A 4th request via POST /api/analyses must be rejected with 429 RATE_LIMITED
        # and must NOT burn quota for a new user.
        other_user = "user_overflow_check"
        other_res = store.add_resume(
            filename="other.pdf",
            content_type="application/pdf",
            size=100,
            raw_text="Other user resume",
            user_id=other_user,
        )
        resp_overflow = client.post(
            "/api/analyses",
            json={"resume_id": other_res.id, "job_id": job_rec.id, "country": "cambodia"},
            headers=_auth_headers(other_user, "overflow@example.test"),
        )
        assert resp_overflow.status_code == 429
        assert resp_overflow.json()["error"]["code"] == "RATE_LIMITED"

        # Verify no quota was consumed for the rejected user
        summary = get_subscription_summary(other_user)
        assert summary.usage.analysis.used == 0

        # Release the workers and let rec1, rec2, rec3 complete
        release_workers.set()
        fut1.result(timeout=3.0)
        fut2.result(timeout=3.0)
        fut3.result(timeout=3.0)

    assert _analysis_supervisor.peak_active <= 2
    assert _analysis_supervisor.active_count == 0
    assert _analysis_supervisor.queued_count == 0
    for r in (rec1, rec2, rec3):
        done = store.get_analysis(r.id)
        assert done is not None
        assert done.status == "done"


# ── 4. External Call Deadlines &Consistent Failure/Quota Accounting ─────────


def test_external_call_deadline_prevents_indefinitely_running_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an external call hangs beyond `external_call_timeout_seconds`, the analysis
    must abort promptly at the deadline, set `status='failed'`, and release reserved quota."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "external_call_timeout_seconds", 0.12)
    monkeypatch.setattr(settings, "analysis_timeout_seconds", 1.0)

    fixture = _load_fixture("fresh_grad_strong_fit")

    res_rec = store.add_resume(
        filename="cv.pdf",
        content_type="application/pdf",
        size=100,
        raw_text="Candidate resume text",
        user_id=USER_ID,
    )
    job_rec, _ = store.add_job(
        raw="Job description text with sufficient length for validation.",
        source="text",
    )

    unblock_hung = threading.Event()

    def _hung_match(job: Job, resume: Resume) -> Match:
        unblock_hung.wait(timeout=2.0)
        return fixture.model_copy(deep=True)

    t0 = time.monotonic()
    with (
        patch(
            "engine.normalize.normalize_resume",
            return_value=fixture.resume.model_copy(deep=True),
        ),
        patch(
            "engine.normalize.normalize_jd",
            return_value=fixture.job.model_copy(deep=True),
        ),
        patch("engine.match.run_match", side_effect=_hung_match),
    ):
        resp = client.post(
            "/api/analyses",
            json={"resume_id": res_rec.id, "job_id": job_rec.id, "country": "cambodia"},
            headers=_auth_headers(USER_ID, USER_EMAIL),
        )
    elapsed = time.monotonic() - t0
    unblock_hung.set()

    assert resp.status_code == 202
    aid = resp.json()["analysis_id"]

    # Must return promptly around the 0.12s deadline, not wait the full 2.0s sleep
    assert elapsed < 0.8, f"Hung call was not cut off by deadline (took {elapsed:.2f}s)"

    failed = store.get_analysis(aid)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.match is None
    assert failed.baseline is None
    assert failed.error is not None
    assert failed.error["code"] == "ENGINE_FAILED"

    # Quota reservation must be released on deadline failure
    summary = get_subscription_summary(USER_ID)
    assert summary.usage.analysis.used == 0
    assert _analysis_supervisor.active_count == 0
    assert _analysis_supervisor.queued_count == 0


def test_guest_and_user_failures_leave_consistent_status_and_quota_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a guest or authenticated analysis fails (including on timeout),
    guest IP usage and user quota reservations are consistently released."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "external_call_timeout_seconds", 0.1)

    guest_res = store.add_resume(
        filename="guest.pdf",
        content_type="application/pdf",
        size=100,
        raw_text="Guest candidate resume text",
        user_id=None,
    )
    job_rec, _ = store.add_job(
        raw="Job description text with sufficient length for validation.",
        source="text",
    )

    # 1. Guest analysis fails due to normalization error -> guest IP usage is released
    with patch(
        "engine.normalize.normalize_jd",
        side_effect=RuntimeError("Upstream LLM failure"),
    ):
        resp1 = client.post(
            "/api/analyses",
            json={"resume_id": guest_res.id, "job_id": job_rec.id, "country": "cambodia"},
        )
    assert resp1.status_code == 202
    aid1 = resp1.json()["analysis_id"]
    rec1 = store.get_analysis(aid1)
    assert rec1 is not None
    assert rec1.status == "failed"
    assert rec1.match is None
    assert rec1.baseline is None
    assert rec1.error is not None
    assert rec1.error["code"] == "ENGINE_FAILED"

    # Because the first guest analysis failed and released its IP slot, the guest can submit again!
    fixture = _load_fixture("fresh_grad_strong_fit")
    base_fixture = _load_baseline_fixture("fresh_grad_strong_fit")
    with (
        patch(
            "engine.normalize.normalize_resume",
            return_value=fixture.resume.model_copy(deep=True),
        ),
        patch(
            "engine.normalize.normalize_jd",
            return_value=fixture.job.model_copy(deep=True),
        ),
        patch(
            "engine.match.run_match",
            return_value=fixture.model_copy(deep=True),
        ),
        patch(
            "engine.match.run_baseline",
            return_value=base_fixture.model_copy(deep=True),
        ),
    ):
        resp2 = client.post(
            "/api/analyses",
            json={"resume_id": guest_res.id, "job_id": job_rec.id, "country": "cambodia"},
        )
    assert resp2.status_code == 202
    aid2 = resp2.json()["analysis_id"]
    rec2 = store.get_analysis(aid2)
    assert rec2 is not None
    assert rec2.status == "done"
    assert rec2.match is not None


def test_retry_analysis_respects_queue_bound_and_queue_timeout_releases_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`POST /api/analyses/{id}/retry` rejects when the live queue is saturated without
    burning quota, and a queued analysis that times out waiting for a slot fails cleanly
    and releases its quota reservation."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    monkeypatch.setattr(settings, "max_concurrent_analyses", 1)
    monkeypatch.setattr(settings, "max_queued_analyses", 1)

    fixture = _load_fixture("fresh_grad_strong_fit")
    base_fixture = _load_baseline_fixture("fresh_grad_strong_fit")

    res_rec = store.add_resume(
        filename="retry.pdf",
        content_type="application/pdf",
        size=100,
        raw_text="Retry candidate resume text",
        user_id=USER_ID,
    )
    job_rec, _ = store.add_job(
        raw="Job description text with sufficient length for validation.",
        source="text",
    )

    # Create a failed analysis owned by USER_ID that is eligible for retry
    failed_orig = store.create_analysis(
        res_rec.id, job_rec.id, "cambodia", user_id=USER_ID
    )
    store.update_analysis(
        failed_orig.id,
        status="failed",
        error={"code": "ENGINE_FAILED", "message": "Failed", "error_id": "err_1"},
    )

    active_started = threading.Event()
    release_active = threading.Event()

    def _blocking_match(job: Job, resume: Resume) -> Match:
        active_started.set()
        release_active.wait(timeout=3.0)
        m = fixture.model_copy(deep=True)
        m.job = job.model_copy(deep=True)
        m.resume = resume.model_copy(deep=True)
        return m

    rec_active = store.create_analysis(
        res_rec.id, job_rec.id, "cambodia", user_id="other_u1"
    )
    rec_queued = store.create_analysis(
        res_rec.id, job_rec.id, "cambodia", user_id="other_u2"
    )
    # Give rec_queued a quota reservation and very short overall timeout so it times out in queue
    from api.quota import reserve_quota

    rec_queued.reservation_id = reserve_quota("other_u2", "analysis")

    with (
        patch(
            "engine.normalize.normalize_resume",
            return_value=fixture.resume.model_copy(deep=True),
        ),
        patch(
            "engine.normalize.normalize_jd",
            return_value=fixture.job.model_copy(deep=True),
        ),
        patch("engine.match.run_match", side_effect=_blocking_match),
        patch(
            "engine.match.run_baseline",
            return_value=base_fixture.model_copy(deep=True),
        ),
        concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool,
    ):
        fut_active = pool.submit(
            lambda: asyncio.run(_run_live_analysis(rec_active.id))
        )
        assert active_started.wait(timeout=2.0)

        # Shorten analysis_timeout_seconds for the queued job
        monkeypatch.setattr(settings, "analysis_timeout_seconds", 0.15)
        fut_queued = pool.submit(
            lambda: asyncio.run(_run_live_analysis(rec_queued.id))
        )

        deadline = time.monotonic() + 1.0
        while _analysis_supervisor.queued_count < 1 and not fut_queued.done():
            assert time.monotonic() < deadline
            time.sleep(0.005)

        # While active=1 and queued=1, retry must be rejected with 429 RATE_LIMITED
        if _analysis_supervisor.in_flight_count >= 2:
            retry_resp = client.post(
                f"/api/analyses/{failed_orig.id}/retry",
                headers=_auth_headers(USER_ID, USER_EMAIL),
            )
            assert retry_resp.status_code == 429
            assert retry_resp.json()["error"]["code"] == "RATE_LIMITED"
            assert get_subscription_summary(USER_ID).usage.analysis.used == 0

        # Wait for rec_queued to time out waiting in the queue
        fut_queued.result(timeout=2.0)
        queued_after = store.get_analysis(rec_queued.id)
        assert queued_after is not None
        assert queued_after.status == "failed"
        assert queued_after.error is not None
        assert queued_after.error["code"] == "ENGINE_FAILED"
        # Quota reservation for other_u2 must be released after queue timeout
        assert get_subscription_summary("other_u2").usage.analysis.used == 0

        release_active.set()
        fut_active.result(timeout=2.0)

    assert _analysis_supervisor.active_count == 0
    assert _analysis_supervisor.queued_count == 0

