"""Phase 2 Regression Tests: Enforce limits on analysis retries.

Verifies:
1. Ownership and unauthorized access (401/403/404).
2. Quota enforcement on retries (402 quota_exceeded; admin bypass).
3. Guest usage limits on retries (429 GUEST_LIMIT_REACHED).
4. Guest Turnstile CAPTCHA on retries (400 CAPTCHA_FAILED; auth bypass).
5. State eligibility and in-flight duplicate rejection (409 ANALYSIS_IN_PROGRESS).
6. Safe concurrent retries (simultaneous requests across threads).
7. Usage accounting integrity (commit on success, release on failure).
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api.billing.service import get_subscription_summary, reset_billing_memory
from api.config import settings
from api.main import app
from api.store import store

client = TestClient(app)
TEST_JWT_SECRET = "phase2-retry-test-jwt-secret-key-at-least-32-bytes"


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


class _FakeHttpxResponse:
    def __init__(self, json_body: dict[str, Any], status_code: int = 200) -> None:
        self._json = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._json


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "engine_mode", "mock")
    monkeypatch.setattr(settings, "turnstile_secret_key", None)
    monkeypatch.setattr(settings, "enforce_quotas", False)
    monkeypatch.setattr(settings, "enforce_guest_limit", False)
    reset_billing_memory()
    store.guest_ip_usage.clear()


def _seed_job_and_resume(headers: dict[str, str] | None = None) -> tuple[str, str]:
    r = client.post(
        "/api/resumes",
        files={"file": ("sample.pdf", b"%PDF-1.4 sample content", "application/pdf")},
        headers=headers,
    )
    assert r.status_code == 200
    res_id = r.json()["resume_id"]

    j = client.post(
        "/api/jobs",
        json={"text": "Software Engineer required with Python and FastAPI experience." * 2},
        headers=headers,
    )
    assert j.status_code == 200
    job_id = j.json()["job_id"]
    return res_id, job_id


# ============================================================================
# 1. Unauthorized Access & Ownership Checks
# ============================================================================

def test_retry_rejects_unauthorized_access() -> None:
    alice_headers = _auth_header("alice-user-id", "alice@example.com")
    bob_headers = _auth_header("bob-user-id", "bob@example.com")

    res_id, job_id = _seed_job_and_resume(alice_headers)
    create_res = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=alice_headers,
    )
    assert create_res.status_code == 202
    alice_analysis_id = create_res.json()["analysis_id"]

    # 1. Unknown analysis id -> 404 ANALYSIS_NOT_FOUND
    res_404 = client.post("/api/analyses/an_unknown_id/retry", headers=alice_headers)
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"

    # 2. Bob tries to retry Alice's analysis -> 403 FORBIDDEN
    res_bob = client.post(f"/api/analyses/{alice_analysis_id}/retry", headers=bob_headers)
    assert res_bob.status_code == 403
    assert res_bob.json()["error"]["code"] == "FORBIDDEN"

    # 3. Unauthenticated guest tries to retry Alice's analysis -> 401 UNAUTHORIZED
    res_guest = client.post(f"/api/analyses/{alice_analysis_id}/retry")
    assert res_guest.status_code == 401
    assert res_guest.json()["error"]["code"] == "UNAUTHORIZED"

    # 4. Alice can retry her own analysis -> 202 Accepted
    res_alice = client.post(f"/api/analyses/{alice_analysis_id}/retry", headers=alice_headers)
    assert res_alice.status_code == 202
    assert res_alice.json()["analysis_id"] != alice_analysis_id


# ============================================================================
# 2. Quota Enforcement on Retries
# ============================================================================

def test_retry_enforces_user_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enforce_quotas", True)
    user_headers = _auth_header("charlie-user-id", "charlie@example.com")

    res_id, job_id = _seed_job_and_resume(user_headers)

    # Free plan limit is 3 analyses. Run 3 analyses.
    analysis_ids: list[str] = []
    for _ in range(3):
        res = client.post(
            "/api/analyses",
            json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
            headers=user_headers,
        )
        assert res.status_code == 202
        analysis_ids.append(res.json()["analysis_id"])

    # Attempting a retry on Charlie's completed analysis -> 402 quota_exceeded
    retry_res = client.post(f"/api/analyses/{analysis_ids[0]}/retry", headers=user_headers)
    assert retry_res.status_code == 402
    detail = retry_res.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["kind"] == "analysis"
    assert detail["limit"] == 3
    assert detail["upgrade_url"] == "/pricing"


def test_retry_admin_bypasses_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enforce_quotas", True)
    admin_headers = _auth_header("admin-user-id", "dydavid168@gmail.com")

    res_id, job_id = _seed_job_and_resume(admin_headers)

    # Admin runs 4 analyses
    last_id = ""
    for _ in range(4):
        res = client.post(
            "/api/analyses",
            json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
            headers=admin_headers,
        )
        assert res.status_code == 202
        last_id = res.json()["analysis_id"]

    # Admin retries without quota failure
    retry_res = client.post(f"/api/analyses/{last_id}/retry", headers=admin_headers)
    assert retry_res.status_code == 202


# ============================================================================
# 3. Guest Limits on Retries
# ============================================================================

def test_retry_enforces_guest_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enforce_guest_limit", True)

    res_id, job_id = _seed_job_and_resume()

    # 1. First guest analysis succeeds
    res1 = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
    )
    assert res1.status_code == 202
    analysis_id = res1.json()["analysis_id"]

    # 2. Retrying after daily limit is exhausted -> 429 GUEST_LIMIT_REACHED
    retry_res = client.post(f"/api/analyses/{analysis_id}/retry")
    assert retry_res.status_code == 429
    assert retry_res.json()["error"]["code"] == "GUEST_LIMIT_REACHED"


# ============================================================================
# 4. Guest Turnstile CAPTCHA on Retries
# ============================================================================

def test_retry_enforces_guest_turnstile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "turnstile_secret_key", "1x0000000000000000000000000000000AA")
    monkeypatch.setattr(settings, "enforce_guest_limit", False)

    res_id, job_id = _seed_job_and_resume()

    # Seed analysis while bypassing verification momentarily
    monkeypatch.setattr(settings, "turnstile_secret_key", None)
    initial_res = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
    )
    assert initial_res.status_code == 202
    analysis_id = initial_res.json()["analysis_id"]
    monkeypatch.setattr(settings, "turnstile_secret_key", "1x0000000000000000000000000000000AA")

    # 1. Guest retry without Turnstile token -> 400 CAPTCHA_FAILED
    no_token_res = client.post(f"/api/analyses/{analysis_id}/retry")
    assert no_token_res.status_code == 400
    assert no_token_res.json()["error"]["code"] == "CAPTCHA_FAILED"

    # 2. Guest retry with invalid token -> 400 CAPTCHA_FAILED
    async def _fake_post_invalid(_self: object, _url: str, data: dict[str, str]) -> _FakeHttpxResponse:
        return _FakeHttpxResponse({"success": False, "error-codes": ["invalid-input-response"]})

    with patch("httpx.AsyncClient.post", new=_fake_post_invalid):
        bad_token_res = client.post(
            f"/api/analyses/{analysis_id}/retry",
            json={"turnstile_token": "bad-token"},
        )
        assert bad_token_res.status_code == 400
        assert bad_token_res.json()["error"]["code"] == "CAPTCHA_FAILED"

    # 3. Guest retry with valid token -> 202 Accepted
    async def _fake_post_valid(_self: object, _url: str, data: dict[str, str]) -> _FakeHttpxResponse:
        return _FakeHttpxResponse({"success": True, "action": "guest_analysis"})

    with patch("httpx.AsyncClient.post", new=_fake_post_valid):
        good_token_res = client.post(
            f"/api/analyses/{analysis_id}/retry",
            json={"turnstile_token": "good-token"},
        )
        assert good_token_res.status_code == 202

    # 4. Authenticated user retries -> bypasses Turnstile check without token
    auth_headers = _auth_header("auth-user-turnstile", "auth@example.com")
    auth_res = client.post(f"/api/analyses/{analysis_id}/retry", headers=auth_headers)
    assert auth_res.status_code == 202


# ============================================================================
# 5. Eligible States & In-Flight Rejection
# ============================================================================

def test_retry_rejects_ineligible_state() -> None:
    res_id, job_id = _seed_job_and_resume()
    record = store.create_analysis(res_id, job_id, "cambodia")

    # If original analysis is still queued or running -> 409 ANALYSIS_IN_PROGRESS
    record.status = "queued"
    res_queued = client.post(f"/api/analyses/{record.id}/retry")
    assert res_queued.status_code == 409
    assert res_queued.json()["error"]["code"] == "ANALYSIS_IN_PROGRESS"

    record.status = "running"
    res_running = client.post(f"/api/analyses/{record.id}/retry")
    assert res_running.status_code == 409
    assert res_running.json()["error"]["code"] == "ANALYSIS_IN_PROGRESS"

    # Terminal state 'done' is eligible
    record.status = "done"
    res_done = client.post(f"/api/analyses/{record.id}/retry")
    assert res_done.status_code == 202

    # Terminal state 'failed' is eligible
    record.status = "failed"
    res_failed = client.post(f"/api/analyses/{record.id}/retry")
    assert res_failed.status_code == 202


def test_retry_rejects_duplicate_inflight_retry() -> None:
    res_id, job_id = _seed_job_and_resume()
    original = store.create_analysis(res_id, job_id, "cambodia")
    original.status = "done"

    # Spawn a child retry that is currently running
    child = store.create_analysis(res_id, job_id, "cambodia")
    child.status = "running"
    original.retried_by = child.id

    # Attempting to retry original while child is still running -> 409 ANALYSIS_IN_PROGRESS
    res_dup = client.post(f"/api/analyses/{original.id}/retry")
    assert res_dup.status_code == 409
    assert res_dup.json()["error"]["code"] == "ANALYSIS_IN_PROGRESS"
    assert "already in progress" in res_dup.json()["error"]["message"]

    # Once child completes or fails, original can be retried again
    child.status = "done"
    res_ok = client.post(f"/api/analyses/{original.id}/retry")
    assert res_ok.status_code == 202


# ============================================================================
# 6. Simultaneous Concurrent Retries (Thread-Safety)
# ============================================================================

def test_concurrent_retries_prevent_duplicate_inflight() -> None:
    res_id, job_id = _seed_job_and_resume()
    original = store.create_analysis(res_id, job_id, "cambodia")
    original.status = "done"

    def _threaded_retry(aid: str) -> tuple[int, dict[str, Any]]:
        resp = client.post(f"/api/analyses/{aid}/retry")
        return resp.status_code, resp.json()

    # Launch 6 concurrent retry attempts for the same analysis
    # To test race conditions, make child remain "running"
    def _create_running_retry(aid: str, **kwargs: Any) -> Any:
        with store._lock:
            # Let store check in-flight under lock
            if original.status in ("queued", "running"):
                from api.errors import ApiError
                raise ApiError(409, "ANALYSIS_IN_PROGRESS", "in progress")
            if original.retried_by:
                child = store.get_analysis(original.retried_by)
                if child and child.status in ("queued", "running"):
                    from api.errors import ApiError
                    raise ApiError(409, "ANALYSIS_IN_PROGRESS", "already in progress")
            child = store.create_analysis(original.resume_id, original.job_id, original.country)
            child.status = "running"
            original.retried_by = child.id
            return child

    with (
        patch.object(store, "create_retry", side_effect=_create_running_retry),
        concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor,
    ):
        futures = [executor.submit(_threaded_retry, original.id) for _ in range(6)]
        results = [f.result() for f in futures]

    statuses = [status for status, _ in results]
    # Exactly one request must succeed with 202, all other 5 must be rejected with 409
    assert statuses.count(202) == 1
    assert statuses.count(409) == 5


# ============================================================================
# 7. Usage Accounting: Commits on Success, Releases on Failure
# ============================================================================

def test_usage_accounting_commits_on_success_and_releases_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enforce_quotas", True)
    user_id = "accounting-user-id"
    user_headers = _auth_header(user_id, "acc@example.com")

    res_id, job_id = _seed_job_and_resume(user_headers)

    # 1. Run 1 initial analysis -> usage becomes 1
    res1 = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=user_headers,
    )
    assert res1.status_code == 202
    analysis_id = res1.json()["analysis_id"]

    summary = get_subscription_summary(user_id)
    assert summary.usage.analysis.used == 1

    # 2. Retry succeeds -> usage becomes 2 (no double-counting)
    retry_res = client.post(f"/api/analyses/{analysis_id}/retry", headers=user_headers)
    assert retry_res.status_code == 202
    child_id = retry_res.json()["analysis_id"]

    summary2 = get_subscription_summary(user_id)
    assert summary2.usage.analysis.used == 2

    # 3. Simulate failure on next retry (e.g. backend/engine crash)
    # The quota reservation must be released, so usage stays at 2
    with patch("api.store.store.pick_fixture", side_effect=RuntimeError("AI model crashed")):
        failed_retry_res = client.post(f"/api/analyses/{child_id}/retry", headers=user_headers)
        assert failed_retry_res.status_code == 202
        failed_id = failed_retry_res.json()["analysis_id"]

        failed_record = store.analyses[failed_id]
        assert failed_record.status == "failed"
        assert failed_record.error["code"] == "ENGINE_FAILED"

    # Usage must NOT have incremented on failure
    summary3 = get_subscription_summary(user_id)
    assert summary3.usage.analysis.used == 2
