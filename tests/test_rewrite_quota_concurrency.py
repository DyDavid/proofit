"""Phase 3 Regression Tests: Prevent concurrent rewrite quota bypass and duplicate processing.

Verifies:
1. Simultaneous requests at the quota boundary (4 concurrent requests for limit=1 -> 1x 200, 3x 402).
2. Duplicate in-flight generation prevention for the same analysis (409 ANALYSIS_IN_PROGRESS).
3. Successful completion commits reservation exactly once and caches completed result.
4. Failed generation (500 ENGINE_FAILED / 429 RATE_LIMITED) releases reservation and allows retry.
5. Rejected outputs commit reservation once and prevent repeated uncharged AI calls.
6. Requests with no rewrite candidates release reservation and mark analysis done to prevent repeated AI calls.
7. Admin exemptions, ownership checks, and error precedence (401/403/404/409 before 402).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api.billing.service import (
    _usage_reservations,
    commit_usage_reservation,
    create_usage_reservation,
    get_subscription_summary,
    reset_billing_memory,
)
from api.config import settings
from api.main import app
from api.store import AnalysisRecord, store
from engine.normalize.schema import Evidence, Job, Match, MatchResult, Requirement, Resume
from engine.rewrite import prompts
from engine.rewrite.llm import RateLimitedError
from engine.rewrite.models import HiddenStrengthCandidate, ValidationResult

client = TestClient(app)
TEST_JWT_SECRET = "phase3-rewrite-quota-test-jwt-secret-key-32bytes!"


def _make_token(user_id: str, email: str = "candidate@example.com") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _auth_header(user_id: str, email: str = "candidate@example.com") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id, email=email)}"}


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "engine_mode", "mock")
    monkeypatch.setattr(settings, "enforce_quotas", True)
    monkeypatch.setattr(settings, "enforce_auth_on_rewrites", True)
    reset_billing_memory()


def _seed_done_analysis(
    analysis_id: str,
    user_id: str | None = "user-1",
    country: str = "cambodia",
) -> str:
    job = Job(
        source_type="pasted",
        content_hash="deadbeef",
        title="Junior Developer",
        industry="Tech",
        seniority="entry",
        requirements=[
            Requirement(
                id="r1",
                text="Experience with React",
                category="hard_skill",
                priority="required",
            ),
        ],
    )
    resume = Resume(
        evidence=[
            Evidence(
                id="e1",
                source_line="Built a dashboard for a university course project.",
                evidence_type="project",
                skills=["React"],
            ),
        ],
    )
    match = Match(
        coverage_score=50.0,
        coverage_required_only=50.0,
        realism_verdict="stretch",
        results=[
            MatchResult(
                requirement_id="r1",
                verdict="partial",
                evidence_ids=["e1"],
                reasoning="close",
                confidence=0.6,
            ),
        ],
        job=job,
        resume=resume,
    )
    record = AnalysisRecord(
        id=analysis_id,
        resume_id="res_test",
        job_id="job_test",
        country=country,
        user_id=user_id,
    )
    record.status = "done"
    record.match = match
    store.analyses[record.id] = record
    return record.id


def _dispatch_call_structured(
    *,
    detect_response: dict[str, Any],
    generate_response: dict[str, Any],
    delay_seconds: float = 0.0,
) -> Callable[..., dict[str, Any]]:
    def _side_effect(*, tool_name: str, **_kwargs: object) -> dict[str, Any]:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        if tool_name == prompts.DETECT_TOOL_NAME:
            return detect_response
        if tool_name == prompts.GENERATE_TOOL_NAME:
            return generate_response
        raise AssertionError(f"unexpected tool_name in test stub: {tool_name}")

    return _side_effect


# ============================================================================
# 1. Simultaneous Requests at the Quota Boundary
# ============================================================================


def test_four_simultaneous_rewrite_requests_enforce_single_rewrite_quota(monkeypatch) -> None:
    """Confirmed issue reproduction & regression test:
    Four simultaneous rewrite requests for an account limited to 1 rewrite (Free plan)
    must result in exactly 1 success (200) and 3 quota rejections (402).
    """
    # Isolate quota coordination from the separate global processing-capacity limit.
    monkeypatch.setattr(settings, "max_concurrent_rewrites", 4)
    user_id = "user-concurrent-quota"
    headers = _auth_header(user_id, "concurrent@example.com")

    # Seed 4 distinct completed analyses for the same Free-tier user (limit = 1 rewrite)
    analysis_ids = [
        _seed_done_analysis(f"an_concurrent_quota_{i}", user_id=user_id)
        for i in range(4)
    ]

    ai_calls = 0
    ai_lock = threading.Lock()
    start_barrier = threading.Barrier(4, timeout=5.0)

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
        delay_seconds=0.05,
    )

    orig_reserve = __import__("api.quota", fromlist=["reserve_quota"]).reserve_quota

    def _synchronized_reserve(uid: str, kind: str, *args: Any, **kwargs: Any) -> str | None:
        # Synchronize all 4 threads right before quota reservation so they race simultaneously
        with contextlib.suppress(threading.BrokenBarrierError):
            start_barrier.wait()
        return orig_reserve(uid, kind, *args, **kwargs)

    def _counting_detect(match: Match, resume: Resume) -> list[HiddenStrengthCandidate]:
        nonlocal ai_calls
        with ai_lock:
            ai_calls += 1
        time.sleep(0.05)
        return [HiddenStrengthCandidate(requirement_id="r1", evidence_id="e1", rationale="Fits.")]

    def _worker(aid: str) -> tuple[int, dict[str, Any]]:
        resp = client.post(f"/api/analyses/{aid}/rewrites", headers=headers)
        return resp.status_code, resp.json()

    with (
        patch("api.routes.analyses.reserve_quota", side_effect=_synchronized_reserve),
        patch("api.routes.analyses.detect_hidden_strengths", side_effect=_counting_detect),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor,
    ):
        futures = [executor.submit(_worker, aid) for aid in analysis_ids]
        results = [f.result() for f in futures]

    statuses = [status for status, _ in results]
    assert statuses.count(200) == 1
    assert statuses.count(402) == 3

    for status, body in results:
        if status == 402:
            assert body["detail"]["code"] == "quota_exceeded"
            assert body["detail"]["kind"] == "rewrite"
            assert body["detail"]["limit"] == 1

    # Only 1 request was allowed to invoke the AI pipeline
    assert ai_calls == 1

    # Final usage is exactly 1 with no dangling active reservations
    summary = get_subscription_summary(user_id)
    assert summary.usage.rewrite.used == 1
    assert len(_usage_reservations) == 0


# ============================================================================
# 2. Duplicate In-Flight Requests for the Same Analysis
# ============================================================================


def test_duplicate_concurrent_requests_for_same_analysis_rejected() -> None:
    """Simultaneous requests targeting the same analysis_id must not run duplicate
    in-flight AI generation; 1 succeeds (200) and concurrent duplicates get 409.
    """
    user_id = "user-dup-inflight"
    headers = _auth_header(user_id, "dup@example.com")
    analysis_id = _seed_done_analysis("an_dup_inflight", user_id=user_id)

    entered_ai = threading.Event()
    release_ai = threading.Event()
    detect_calls = 0

    def _blocking_detect(match: Match, resume: Resume) -> list[HiddenStrengthCandidate]:
        nonlocal detect_calls
        detect_calls += 1
        entered_ai.set()
        release_ai.wait(timeout=5.0)
        return [HiddenStrengthCandidate(requirement_id="r1", evidence_id="e1", rationale="Fits.")]

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    )

    def _worker() -> tuple[int, dict[str, Any]]:
        resp = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        return resp.status_code, resp.json()

    with (
        patch("api.routes.analyses.detect_hidden_strengths", side_effect=_blocking_detect),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor,
    ):
        # Start the first request and wait until it is inside AI processing
        first_future = executor.submit(_worker)
        assert entered_ai.wait(timeout=5.0)

        # Fire 3 duplicate requests for the exact same analysis while first is in-flight
        dup_futures = [executor.submit(_worker) for _ in range(3)]
        dup_results = [f.result() for f in dup_futures]

        # Let the first request finish
        release_ai.set()
        first_status, first_body = first_future.result()

    assert first_status == 200
    assert len(first_body["hidden_strengths"]) == 1

    for status, body in dup_results:
        assert status == 409
        assert body["error"]["code"] == "ANALYSIS_IN_PROGRESS"

    assert detect_calls == 1
    summary = get_subscription_summary(user_id)
    assert summary.usage.rewrite.used == 1
    assert len(_usage_reservations) == 0


# ============================================================================
# 3. Successful Completion & Idempotent Subsequent Calls
# ============================================================================


def test_successful_completion_commits_once_and_caches_subsequent_calls() -> None:
    user_id = "user-success-cache"
    headers = _auth_header(user_id, "cache@example.com")
    analysis_id = _seed_done_analysis("an_success_cache", user_id=user_id)

    call_count = 0

    def _counting_stub(*, tool_name: str, **_kwargs: object) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if tool_name == prompts.DETECT_TOOL_NAME:
            return {"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."}
        if tool_name == prompts.GENERATE_TOOL_NAME:
            return {
                "suggested_phrasing": "Built a React dashboard for a university course project.",
                "facts_used": ["e1"],
            }
        raise AssertionError(f"unexpected tool_name: {tool_name}")

    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=_counting_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=_counting_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        res1 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res1.status_code == 200
        assert len(res1.json()["hidden_strengths"]) == 1
        first_call_count = call_count
        assert first_call_count == 2  # 1 detect + 1 generate

        # Second call to the same completed analysis returns cached results without calling AI
        res2 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res2.status_code == 200
        assert res2.json() == res1.json()
        assert call_count == first_call_count

    summary = get_subscription_summary(user_id)
    assert summary.usage.rewrite.used == 1


def test_commit_usage_reservation_is_idempotent() -> None:
    user_id = "user-idempotent-commit"
    rid = create_usage_reservation(user_id, "rewrite")
    assert get_subscription_summary(user_id).usage.rewrite.used == 1

    # First commit transitions reservation -> permanent usage event
    commit_usage_reservation(rid, user_id, "rewrite")
    assert get_subscription_summary(user_id).usage.rewrite.used == 1
    assert len(_usage_reservations) == 0

    # Second commit with the same reservation_id must be a no-op
    commit_usage_reservation(rid, user_id, "rewrite")
    assert get_subscription_summary(user_id).usage.rewrite.used == 1


# ============================================================================
# 4. Failed Generation Releases Reservation & Allows Retry
# ============================================================================


def test_failed_generation_releases_reservation_and_allows_retry() -> None:
    user_id = "user-fail-retry"
    headers = _auth_header(user_id, "fail@example.com")
    analysis_id = _seed_done_analysis("an_fail_retry", user_id=user_id)

    # 1. Rate-limited failure (429) releases reservation
    with patch(
        "api.routes.analyses.detect_hidden_strengths",
        side_effect=RateLimitedError("upstream 429"),
    ):
        res_429 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res_429.status_code == 429
        assert res_429.json()["error"]["code"] == "RATE_LIMITED"

    assert get_subscription_summary(user_id).usage.rewrite.used == 0
    assert len(_usage_reservations) == 0
    assert store.analyses[analysis_id].rewrite_in_progress is False
    assert store.analyses[analysis_id].rewrite_status is None

    # 2. Engine crash (500) releases reservation
    with patch(
        "api.routes.analyses.detect_hidden_strengths",
        side_effect=RuntimeError("unexpected provider crash"),
    ):
        res_500 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res_500.status_code == 500
        assert res_500.json()["error"]["code"] == "ENGINE_FAILED"

    assert get_subscription_summary(user_id).usage.rewrite.used == 0
    assert len(_usage_reservations) == 0
    assert store.analyses[analysis_id].rewrite_in_progress is False
    assert store.analyses[analysis_id].rewrite_status is None

    # 3. Subsequent retry on the same analysis succeeds and commits quota
    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    )
    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        res_ok = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res_ok.status_code == 200
        assert len(res_ok.json()["hidden_strengths"]) == 1

    assert get_subscription_summary(user_id).usage.rewrite.used == 1


# ============================================================================
# 5. Rejected Outputs & No-Candidate Handling (Preventing Unlimited Paid Calls)
# ============================================================================


def test_no_candidates_releases_quota_and_prevents_repeated_ai_calls() -> None:
    """When detect_hidden_strengths finds 0 candidates, the user is not charged,
    but the analysis is marked done so repeated requests do not trigger unlimited paid AI calls.
    """
    user_id = "user-no-candidates"
    headers = _auth_header(user_id, "nocand@example.com")
    analysis_id = _seed_done_analysis("an_no_candidates", user_id=user_id)

    detect_calls = 0

    def _empty_detect(match: Match, resume: Resume) -> list[HiddenStrengthCandidate]:
        nonlocal detect_calls
        detect_calls += 1
        return []

    with patch("api.routes.analyses.detect_hidden_strengths", side_effect=_empty_detect):
        # First call runs detection, finds 0 candidates, releases quota
        res1 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res1.status_code == 200
        assert res1.json() == {"hidden_strengths": [], "rejected_count": 0}
        assert detect_calls == 1
        assert get_subscription_summary(user_id).usage.rewrite.used == 0

        # Repeated calls return immediately without invoking AI detection again
        for _ in range(3):
            res_repeat = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
            assert res_repeat.status_code == 200
            assert res_repeat.json() == {"hidden_strengths": [], "rejected_count": 0}

        assert detect_calls == 1


def test_all_rejected_outputs_commits_quota_and_caches_result() -> None:
    """When candidates are found and generated by the LLM but rejected by validation,
    quota is committed once and repeated calls do not re-trigger AI generation.
    """
    user_id = "user-rejected-outputs"
    headers = _auth_header(user_id, "rejected@example.com")
    analysis_id = _seed_done_analysis("an_rejected_outputs", user_id=user_id)

    call_count = 0

    def _counting_stub(*, tool_name: str, **_kwargs: object) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if tool_name == prompts.DETECT_TOOL_NAME:
            return {"found": True, "evidence_id": "e1", "rationale": "Fits."}
        if tool_name == prompts.GENERATE_TOOL_NAME:
            return {
                "suggested_phrasing": "Worked professionally as a senior software engineer.",
                "facts_used": ["e1"],
            }
        raise AssertionError(f"unexpected tool_name: {tool_name}")

    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=_counting_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=_counting_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(
                ok=False,
                violations=[{"claim": "software engineer", "reason": "scope inflation"}],
            ),
        ),
    ):
        res1 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res1.status_code == 200
        assert res1.json() == {"hidden_strengths": [], "rejected_count": 1}
        assert call_count == 3  # 1 detect + 2 generate attempts
        assert get_subscription_summary(user_id).usage.rewrite.used == 1

        # Calling again returns cached result without calling LLM again
        res2 = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=headers)
        assert res2.status_code == 200
        assert res2.json() == {"hidden_strengths": [], "rejected_count": 1}
        assert call_count == 3


# ============================================================================
# 6. Admin Exemptions & Access/State Error Precedence
# ============================================================================


def test_admin_exempt_from_rewrite_quota() -> None:
    admin_id = "admin-user-id"
    admin_headers = _auth_header(admin_id, "dydavid168@gmail.com")

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    )

    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        for i in range(3):
            aid = _seed_done_analysis(f"an_admin_rewrite_{i}", user_id=admin_id)
            res = client.post(f"/api/analyses/{aid}/rewrites", headers=admin_headers)
            assert res.status_code == 200
            assert len(res.json()["hidden_strengths"]) == 1


def test_ownership_and_state_errors_take_precedence_over_quota() -> None:
    alice_id = "alice-id"
    bob_id = "bob-id"
    bob_headers = _auth_header(bob_id, "bob@example.com")

    # Exhaust Bob's rewrite quota first
    bob_aid = _seed_done_analysis("an_bob_1", user_id=bob_id)
    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "Fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    )
    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        r_bob = client.post(f"/api/analyses/{bob_aid}/rewrites", headers=bob_headers)
        assert r_bob.status_code == 200

    assert get_subscription_summary(bob_id).usage.rewrite.used == 1

    # 1. Unauthenticated request -> 401 UNAUTHORIZED
    alice_aid = _seed_done_analysis("an_alice_1", user_id=alice_id)
    res_unauth = client.post(f"/api/analyses/{alice_aid}/rewrites")
    assert res_unauth.status_code == 401
    assert res_unauth.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Unknown analysis -> 404 ANALYSIS_NOT_FOUND (even for quota-exhausted Bob)
    res_404 = client.post("/api/analyses/an_nonexistent/rewrites", headers=bob_headers)
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"

    # 3. Bob accessing Alice's analysis -> 403 FORBIDDEN (not 402!)
    res_403 = client.post(f"/api/analyses/{alice_aid}/rewrites", headers=bob_headers)
    assert res_403.status_code == 403
    assert res_403.json()["error"]["code"] == "FORBIDDEN"

    # 4. Analysis not ready -> 409 ANALYSIS_NOT_READY
    not_ready = AnalysisRecord(
        id="an_bob_queued",
        resume_id="res_test",
        job_id="job_test",
        country="cambodia",
        status="queued",
        user_id=bob_id,
    )
    store.analyses[not_ready.id] = not_ready
    res_409 = client.post(f"/api/analyses/{not_ready.id}/rewrites", headers=bob_headers)
    assert res_409.status_code == 409
    assert res_409.json()["error"]["code"] == "ANALYSIS_NOT_READY"

    # Alice's quota is still completely untouched
    assert get_subscription_summary(alice_id).usage.rewrite.used == 0
