"""Phase 1 Regression Tests: Prevent cross-user resume data leak via shared fixtures.

Verifies:
1. Independent result objects for every analysis (both live and mock modes).
2. No mutation of shared fixtures (`_FIXTURES`, `_BASELINES`) or nested objects (`job`, `resume`, `results`).
3. Safe failure responses (`status="failed"`, `match=None`, `baseline=None`, typed `error` envelope) that never leak another user's resume, job information, or results.
4. Clear separation between sample results (mock mode) and failed real analyses (live mode) — failed live analyses are never silently presented as `status="done"` with sample results.
5. Failures at every processing stage (missing records, `normalize_resume`, `normalize_jd`, `run_match`, `run_baseline`, cross-field validation).
6. Repeated failures and retries without state contamination.
7. Concurrent requests across multiple users and threads without race conditions or cross-user leakage.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api.billing.service import reset_billing_memory
from api.config import settings
from api.main import app
from api.routes.analyses import _run_live_analysis
from api.store import (
    _BASELINES,
    _FIXTURE_ROTATION,
    _FIXTURES,
    _load_baseline_fixture,
    _load_fixture,
    store,
)
from engine.normalize.schema import Evidence, Job, Match, Requirement, Resume

client = TestClient(app)

TEST_JWT_SECRET = "phase1-leak-regression-test-jwt-secret-32-bytes-minimum"

USER_A_ID = "user_alpha_synthetic_001"
USER_A_EMAIL = "alpha.synthetic@example.test"
USER_A_MARKER = "SYNTHETIC_PRIVATE_MARKER_ALPHA_RESUME_9001"
USER_A_JOB_MARKER = "SYNTHETIC_PRIVATE_MARKER_ALPHA_JOB_9002"

USER_B_ID = "user_bravo_synthetic_002"
USER_B_EMAIL = "bravo.synthetic@example.test"
USER_B_MARKER = "SYNTHETIC_PRIVATE_MARKER_BRAVO_RESUME_7001"
USER_B_JOB_MARKER = "SYNTHETIC_PRIVATE_MARKER_BRAVO_JOB_7002"


def _make_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _auth_headers(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id, email)}"}


def _snapshot_fixtures() -> dict[str, Any]:
    """Take a serialized snapshot of all in-memory golden fixtures and baselines."""
    return {
        "fixtures": {
            name: _FIXTURES[name].model_dump(mode="json") for name in _FIXTURE_ROTATION
        },
        "baselines": {
            name: _BASELINES[name].model_dump(mode="json") for name in _FIXTURE_ROTATION
        },
    }


def _assert_fixtures_unchanged(snapshot_before: dict[str, Any]) -> None:
    """Verify that global fixtures match both the pre-test snapshot and fresh disk reads."""
    snapshot_after = _snapshot_fixtures()
    assert snapshot_after == snapshot_before, "Shared in-memory fixtures were mutated!"

    for name in _FIXTURE_ROTATION:
        fresh_match = _load_fixture(name).model_dump(mode="json")
        fresh_base = _load_baseline_fixture(name).model_dump(mode="json")
        assert snapshot_after["fixtures"][name] == fresh_match
        assert snapshot_after["baselines"][name] == fresh_base

    serialized = json.dumps(snapshot_after)
    assert USER_A_MARKER not in serialized
    assert USER_A_JOB_MARKER not in serialized
    assert USER_B_MARKER not in serialized
    assert USER_B_JOB_MARKER not in serialized


def _build_synthetic_resume(marker: str) -> Resume:
    base = _load_fixture("fresh_grad_strong_fit").resume
    assert base is not None
    copy_res = base.model_copy(deep=True)
    copy_res.candidate_summary = f"Synthetic Candidate Summary for {marker}"
    copy_res.evidence = [
        Evidence(
            id=ev.id,
            source_line=f"{ev.source_line} [{marker}]",
            evidence_type=ev.evidence_type,
            skills=[*ev.skills, marker],
            duration_months=ev.duration_months,
            team_size=ev.team_size,
            outcome=ev.outcome,
        )
        for ev in copy_res.evidence
    ]
    return copy_res


def _build_synthetic_job(marker: str) -> Job:
    base = _load_fixture("fresh_grad_strong_fit").job
    assert base is not None
    copy_job = base.model_copy(deep=True)
    copy_job.title = f"Position {marker}"
    copy_job.company = f"Company {marker}"
    copy_job.requirements = [
        Requirement(
            id=req.id,
            text=f"{req.text} ({marker})",
            category=req.category,
            priority=req.priority,
            normalized_skill=req.normalized_skill,
            display_order=req.display_order,
        )
        for req in copy_job.requirements
    ]
    return copy_job


def _build_synthetic_match(job: Job, resume: Resume) -> Match:
    base = _load_fixture("fresh_grad_strong_fit").model_copy(deep=True)
    base.job = job.model_copy(deep=True)
    base.resume = resume.model_copy(deep=True)
    return base


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "turnstile_secret_key", None)
    monkeypatch.setattr(settings, "enforce_quotas", False)
    monkeypatch.setattr(settings, "enforce_guest_limit", False)
    monkeypatch.setattr(settings, "mock_delay_seconds", 0.0)
    # Mock database client so no external Supabase call can ever happen
    monkeypatch.setattr("api.store.get_supabase_client", lambda: None)
    monkeypatch.setattr("api.routes.analyses.get_supabase_client", lambda: None)
    monkeypatch.setattr("api.db.get_supabase_client", lambda: None)
    reset_billing_memory()
    store.analyses.clear()
    store.resumes.clear()
    store.jobs.clear()
    store.jobs_by_hash.clear()
    store._picked_fixture_names.clear()
    store.guest_ip_usage.clear()
    yield


def test_pick_fixture_and_pick_baseline_return_independent_deep_copies() -> None:
    """Mutating a returned fixture or its nested objects must never affect subsequent calls."""
    snapshot = _snapshot_fixtures()

    m1 = store.pick_fixture("fresh_grad_strong_fit")
    m2 = store.pick_fixture("fresh_grad_strong_fit")
    assert m1 is not m2
    assert m1.job is not m2.job
    assert m1.resume is not m2.resume
    assert m1.results is not m2.results

    # Mutate m1 and its nested objects heavily
    assert m1.resume is not None and m1.job is not None
    m1.coverage_score = 1.23
    m1.resume.candidate_summary = USER_A_MARKER
    m1.resume.evidence[0].source_line = USER_A_MARKER
    m1.job.title = USER_A_JOB_MARKER
    m1.results[0].reasoning = USER_A_MARKER

    # m2 and subsequent calls must be completely unaffected
    m3 = store.pick_fixture("fresh_grad_strong_fit")
    assert m3.coverage_score != 1.23
    assert USER_A_MARKER not in json.dumps(m2.model_dump(mode="json"))
    assert USER_A_MARKER not in json.dumps(m3.model_dump(mode="json"))

    b1 = store.pick_baseline("fresh_grad_strong_fit")
    b2 = store.pick_baseline("fresh_grad_strong_fit")
    assert b1 is not b2
    assert b1.results is not b2.results
    b1.coverage_score = 9.99
    b1.results[0].matched_terms.append(USER_A_MARKER)

    b3 = store.pick_baseline("fresh_grad_strong_fit")
    assert b3.coverage_score != 9.99
    assert USER_A_MARKER not in json.dumps(b2.model_dump(mode="json"))
    assert USER_A_MARKER not in json.dumps(b3.model_dump(mode="json"))

    _assert_fixtures_unchanged(snapshot)


@pytest.mark.parametrize(
    "failure_stage",
    [
        "missing_resume",
        "normalize_resume",
        "normalize_jd",
        "run_match",
        "run_baseline",
    ],
)
def test_live_failure_at_any_stage_never_leaks_user_a_data_to_user_b(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    """When User A's live analysis fails at any stage, User A gets status='failed' with no sample fallback,
    shared fixtures are untouched, and User B never sees User A's synthetic private markers."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    snapshot = _snapshot_fixtures()

    headers_a = _auth_headers(USER_A_ID, USER_A_EMAIL)
    headers_b = _auth_headers(USER_B_ID, USER_B_EMAIL)

    res_a = store.add_resume(
        filename="alpha.pdf",
        content_type="application/pdf",
        size=128,
        raw_text=f"Private resume for {USER_A_MARKER}",
        user_id=USER_A_ID,
    )
    job_a, _ = store.add_job(
        raw=f"Angkor Digital hiring engineer {USER_A_JOB_MARKER} " + ("x" * 40),
        source="text",
    )

    res_b = store.add_resume(
        filename="bravo.pdf",
        content_type="application/pdf",
        size=128,
        raw_text=f"Private resume for {USER_B_MARKER}",
        user_id=USER_B_ID,
    )
    job_b, _ = store.add_job(
        raw=f"Angkor Digital hiring engineer {USER_B_JOB_MARKER} " + ("y" * 40),
        source="text",
    )

    norm_res_a = _build_synthetic_resume(USER_A_MARKER)
    norm_job_a = _build_synthetic_job(USER_A_JOB_MARKER)
    norm_res_b = _build_synthetic_resume(USER_B_MARKER)
    norm_job_b = _build_synthetic_job(USER_B_JOB_MARKER)

    analysis_a = store.create_analysis(res_a.id, job_a.id, "cambodia", user_id=USER_A_ID)
    if failure_stage == "missing_resume":
        store.resumes.pop(res_a.id, None)

    def _mock_norm_resume(data: bytes, filename: str) -> Resume:
        if filename == "alpha.pdf":
            if failure_stage == "normalize_resume":
                raise RuntimeError(f"Resume parse failure on {USER_A_MARKER}")
            return norm_res_a
        return norm_res_b

    def _mock_norm_jd(raw_text: str) -> Job:
        if USER_A_JOB_MARKER in raw_text:
            if failure_stage == "normalize_jd":
                raise RuntimeError(f"JD parse failure on {USER_A_JOB_MARKER}")
            return norm_job_a
        return norm_job_b

    def _mock_run_match(job: Job, resume: Resume) -> Match:
        if USER_A_MARKER in (resume.candidate_summary or ""):
            if failure_stage == "run_match":
                raise RuntimeError(f"LLM match failure while processing {USER_A_MARKER}")
            return _build_synthetic_match(job, resume)
        if failure_stage == "run_match":
            # Also let User B fail in a follow-up check or succeed
            return _build_synthetic_match(job, resume)
        return _build_synthetic_match(job, resume)

    orig_run_baseline = _load_baseline_fixture("fresh_grad_strong_fit")

    def _mock_run_baseline(job: Job, resume: Resume):
        if USER_A_MARKER in (resume.candidate_summary or "") and failure_stage == "run_baseline":
            raise RuntimeError(f"Baseline failure on {USER_A_MARKER}")
        return orig_run_baseline.model_copy(deep=True)

    with (
        patch("engine.normalize.normalize_resume", side_effect=_mock_norm_resume),
        patch("engine.normalize.normalize_jd", side_effect=_mock_norm_jd),
        patch("engine.match.run_match", side_effect=_mock_run_match),
        patch("engine.match.run_baseline", side_effect=_mock_run_baseline),
    ):
        asyncio.run(_run_live_analysis(analysis_a.id))

    # 1. Verify User A's analysis failed cleanly and is NOT marked "done" with sample results
    resp_a = client.get(f"/api/analyses/{analysis_a.id}", headers=headers_a)
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    assert body_a["status"] == "failed"
    assert body_a["match"] is None
    assert body_a["baseline"] is None
    assert body_a["error"] is not None
    assert body_a["error"]["code"] == "ENGINE_FAILED"
    assert body_a["error"]["error_id"].startswith("err_")
    # Raw exception message containing USER_A_MARKER must not be echoed in error envelope
    assert USER_A_MARKER not in json.dumps(body_a)
    assert USER_A_JOB_MARKER not in json.dumps(body_a)

    # 2. Verify User B cannot read User A's failed analysis directly
    resp_cross = client.get(f"/api/analyses/{analysis_a.id}", headers=headers_b)
    assert resp_cross.status_code == 403

    # 3. Verify User B's subsequent failed live analysis does not receive User A's data
    analysis_b_fail = store.create_analysis(res_b.id, job_b.id, "cambodia", user_id=USER_B_ID)
    with (
        patch("engine.normalize.normalize_resume", return_value=norm_res_b),
        patch("engine.normalize.normalize_jd", return_value=norm_job_b),
        patch("engine.match.run_match", side_effect=RuntimeError("User B also failed")),
    ):
        asyncio.run(_run_live_analysis(analysis_b_fail.id))

    resp_b_fail = client.get(f"/api/analyses/{analysis_b_fail.id}", headers=headers_b)
    assert resp_b_fail.status_code == 200
    body_b_fail = resp_b_fail.json()
    assert body_b_fail["status"] == "failed"
    assert body_b_fail["match"] is None
    assert body_b_fail["baseline"] is None
    serialized_b_fail = json.dumps(body_b_fail)
    assert USER_A_MARKER not in serialized_b_fail
    assert USER_A_JOB_MARKER not in serialized_b_fail

    # 4. Verify User B's subsequent mock analysis (sample results) does not contain User A's data
    monkeypatch.setattr(settings, "engine_mode", "mock")
    post_b_mock = client.post(
        "/api/analyses",
        json={"resume_id": res_b.id, "job_id": job_b.id, "country": "cambodia"},
        headers=headers_b,
    )
    assert post_b_mock.status_code == 202
    mock_id = post_b_mock.json()["analysis_id"]
    resp_b_mock = client.get(f"/api/analyses/{mock_id}", headers=headers_b)
    assert resp_b_mock.status_code == 200
    body_b_mock = resp_b_mock.json()
    assert body_b_mock["status"] == "done"
    serialized_b_mock = json.dumps(body_b_mock)
    assert USER_A_MARKER not in serialized_b_mock
    assert USER_A_JOB_MARKER not in serialized_b_mock

    # 5. Verify shared fixtures remain completely unchanged
    _assert_fixtures_unchanged(snapshot)


def test_repeated_failures_and_retries_preserve_isolation_and_release_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated live failures across retries must never corrupt fixtures, leak data, or leak quota."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    snapshot = _snapshot_fixtures()

    headers_a = _auth_headers(USER_A_ID, USER_A_EMAIL)
    headers_b = _auth_headers(USER_B_ID, USER_B_EMAIL)

    res_a = store.add_resume(
        filename="alpha.pdf",
        content_type="application/pdf",
        size=100,
        raw_text=USER_A_MARKER,
        user_id=USER_A_ID,
    )
    job_a, _ = store.add_job(
        raw=f"Angkor Digital software role {USER_A_JOB_MARKER} " + ("z" * 40),
        source="text",
    )

    norm_res_a = _build_synthetic_resume(USER_A_MARKER)
    norm_job_a = _build_synthetic_job(USER_A_JOB_MARKER)

    release_Watcher = MagicMock()
    monkeypatch.setattr("api.routes.analyses.release_quota", release_Watcher)

    with (
        patch("engine.normalize.normalize_resume", return_value=norm_res_a),
        patch("engine.normalize.normalize_jd", return_value=norm_job_a),
        patch("engine.match.run_match", side_effect=RuntimeError("Persistent LLM outage")),
    ):
        # Attempt 1
        post_1 = client.post(
            "/api/analyses",
            json={"resume_id": res_a.id, "job_id": job_a.id, "country": "cambodia"},
            headers=headers_a,
        )
        assert post_1.status_code == 202
        id_1 = post_1.json()["analysis_id"]
        body_1 = client.get(f"/api/analyses/{id_1}", headers=headers_a).json()
        assert body_1["status"] == "failed"
        assert body_1["match"] is None

        # Attempt 2 (Retry 1)
        retry_1 = client.post(f"/api/analyses/{id_1}/retry", headers=headers_a)
        assert retry_1.status_code == 202
        id_2 = retry_1.json()["analysis_id"]
        body_2 = client.get(f"/api/analyses/{id_2}", headers=headers_a).json()
        assert body_2["status"] == "failed"
        assert body_2["match"] is None

        # Attempt 3 (Retry 2)
        retry_2 = client.post(f"/api/analyses/{id_2}/retry", headers=headers_a)
        assert retry_2.status_code == 202
        id_3 = retry_2.json()["analysis_id"]
        body_3 = client.get(f"/api/analyses/{id_3}", headers=headers_a).json()
        assert body_3["status"] == "failed"
        assert body_3["match"] is None

    assert release_Watcher.call_count == 3

    # Failed analyses must NOT appear in completed analyses list
    list_a = client.get("/api/analyses", headers=headers_a).json()
    assert list_a == []
    list_b = client.get("/api/analyses", headers=headers_b).json()
    assert list_b == []

    _assert_fixtures_unchanged(snapshot)


def test_concurrent_live_analyses_isolate_users_under_partial_and_total_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent requests from User A (failing and succeeding) and User B (failing and succeeding)
    must never cross-contaminate resume or job data or mutate shared fixtures."""
    monkeypatch.setattr(settings, "engine_mode", "live")
    snapshot = _snapshot_fixtures()

    res_a = store.add_resume(
        filename="alpha.pdf",
        content_type="application/pdf",
        size=100,
        raw_text=USER_A_MARKER,
        user_id=USER_A_ID,
    )
    job_a, _ = store.add_job(
        raw=f"Meridian Systems engineer {USER_A_JOB_MARKER} " + ("a" * 40),
        source="text",
    )

    res_b = store.add_resume(
        filename="bravo.pdf",
        content_type="application/pdf",
        size=100,
        raw_text=USER_B_MARKER,
        user_id=USER_B_ID,
    )
    job_b, _ = store.add_job(
        raw=f"Meridian Systems engineer {USER_B_JOB_MARKER} " + ("b" * 40),
        source="text",
    )

    norm_res_a = _build_synthetic_resume(USER_A_MARKER)
    norm_job_a = _build_synthetic_job(USER_A_JOB_MARKER)
    norm_res_b = _build_synthetic_resume(USER_B_MARKER)
    norm_job_b = _build_synthetic_job(USER_B_JOB_MARKER)
    base_fixture = _load_baseline_fixture("fresh_grad_stretch")

    # Create 8 concurrent analyses:
    # - 2 for User A that fail
    # - 2 for User A that succeed
    # - 2 for User B that fail
    # - 2 for User B that succeed
    tasks_meta: list[tuple[str, str, bool]] = []
    for _ in range(2):
        rec_a_fail = store.create_analysis(res_a.id, job_a.id, "cambodia", user_id=USER_A_ID)
        tasks_meta.append((rec_a_fail.id, USER_A_ID, True))

        rec_a_ok = store.create_analysis(res_a.id, job_a.id, "cambodia", user_id=USER_A_ID)
        tasks_meta.append((rec_a_ok.id, USER_A_ID, False))

        rec_b_fail = store.create_analysis(res_b.id, job_b.id, "cambodia", user_id=USER_B_ID)
        tasks_meta.append((rec_b_fail.id, USER_B_ID, True))

        rec_b_ok = store.create_analysis(res_b.id, job_b.id, "cambodia", user_id=USER_B_ID)
        tasks_meta.append((rec_b_ok.id, USER_B_ID, False))

    fail_ids = {aid for aid, _, should_fail in tasks_meta if should_fail}

    def _norm_resume_dispatch(data: bytes, filename: str) -> Resume:
        if filename == "alpha.pdf":
            return norm_res_a.model_copy(deep=True)
        return norm_res_b.model_copy(deep=True)

    def _norm_jd_dispatch(raw_text: str) -> Job:
        if USER_A_JOB_MARKER in raw_text:
            return norm_job_a.model_copy(deep=True)
        return norm_job_b.model_copy(deep=True)

    # Track which thread is running which analysis_id so run_match can selectively fail
    import threading

    thread_local = threading.local()

    def _thread_worker(analysis_id: str) -> None:
        thread_local.analysis_id = analysis_id
        asyncio.run(_run_live_analysis(analysis_id))

    def _selective_run_match(job: Job, resume: Resume) -> Match:
        aid = getattr(thread_local, "analysis_id", None)
        if aid in fail_ids:
            raise RuntimeError(f"Simulated concurrent failure for {aid}")
        return _build_synthetic_match(job, resume)

    def _selective_run_baseline(job: Job, resume: Resume):
        return base_fixture.model_copy(deep=True)

    with (
        patch("engine.normalize.normalize_resume", side_effect=_norm_resume_dispatch),
        patch("engine.normalize.normalize_jd", side_effect=_norm_jd_dispatch),
        patch("engine.match.run_match", side_effect=_selective_run_match),
        patch("engine.match.run_baseline", side_effect=_selective_run_baseline),
        concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool,
    ):
        futures = [pool.submit(_thread_worker, aid) for aid, _, _ in tasks_meta]
        for fut in concurrent.futures.as_completed(futures):
            fut.result()

    headers_a = _auth_headers(USER_A_ID, USER_A_EMAIL)
    headers_b = _auth_headers(USER_B_ID, USER_B_EMAIL)

    for aid, owner_id, should_fail in tasks_meta:
        headers = headers_a if owner_id == USER_A_ID else headers_b
        other_marker = USER_B_MARKER if owner_id == USER_A_ID else USER_A_MARKER
        other_job_marker = USER_B_JOB_MARKER if owner_id == USER_A_ID else USER_A_JOB_MARKER
        own_marker = USER_A_MARKER if owner_id == USER_A_ID else USER_B_MARKER
        own_job_marker = USER_A_JOB_MARKER if owner_id == USER_A_ID else USER_B_JOB_MARKER

        res = client.get(f"/api/analyses/{aid}", headers=headers)
        assert res.status_code == 200
        payload = res.json()
        serialized = json.dumps(payload)

        # Must NEVER contain the other user's markers
        assert other_marker not in serialized
        assert other_job_marker not in serialized

        if should_fail:
            assert payload["status"] == "failed"
            assert payload["match"] is None
            assert payload["baseline"] is None
            assert payload["error"]["code"] == "ENGINE_FAILED"
        else:
            assert payload["status"] == "done"
            assert payload["match"] is not None
            assert own_marker in serialized
            assert own_job_marker in serialized

    # Verify independent result objects across the successful analyses
    done_records = [
        store.get_analysis(aid)
        for aid, _, should_fail in tasks_meta
        if not should_fail
    ]
    for i in range(len(done_records)):
        for j in range(i + 1, len(done_records)):
            r1 = done_records[i]
            r2 = done_records[j]
            assert r1 is not None and r2 is not None
            assert r1.match is not r2.match
            assert r1.match.job is not r2.match.job
            assert r1.match.resume is not r2.match.resume
            assert r1.baseline is not r2.baseline

    _assert_fixtures_unchanged(snapshot)
