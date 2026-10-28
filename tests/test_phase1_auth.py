"""Phase 1 Authentication, Row Ownership, and Guest IP Rate-Limit Tests."""

from __future__ import annotations

import time
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app
from api.store import store
from engine.normalize.schema import utcnow

client = TestClient(app)

TEST_JWT_SECRET = "test-supabase-hs256-jwt-secret-32-bytes-long!"


def _make_token(user_id: str, email: str = "student@aupp.edu.kh", exp_offset: int = 3600) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def _configure_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)


def test_auth_me_rejects_missing_or_invalid_token() -> None:
    res_missing = client.get("/api/auth/me")
    assert res_missing.status_code == 401
    assert res_missing.json()["error"]["code"] == "UNAUTHORIZED"

    res_bad = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res_bad.status_code == 401
    assert res_bad.json()["error"]["code"] == "UNAUTHORIZED"

    expired = _make_token("user-1", exp_offset=-60)
    res_exp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert res_exp.status_code == 401


def test_auth_me_returns_user_id_and_email_for_valid_token() -> None:
    token = _make_token("11111111-2222-3333-4444-555555555555", "alice@aupp.edu.kh")
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {
        "id": "11111111-2222-3333-4444-555555555555",
        "email": "alice@aupp.edu.kh",
    }


def test_user_cannot_read_or_mutate_another_users_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enforce_auth_on_rewrites", True)
    alice_token = _make_token("user-alice", "alice@aupp.edu.kh")
    bob_token = _make_token("user-bob", "bob@aupp.edu.kh")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Alice uploads a resume and runs an analysis
    res_id = client.post(
        "/api/resumes",
        files={"file": ("alice.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=alice_headers,
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 45}, headers=alice_headers).json()[
        "job_id"
    ]

    # Bob cannot create an analysis using Alice's resume
    bob_create = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=bob_headers,
    )
    assert bob_create.status_code == 403
    assert bob_create.json()["error"]["code"] == "FORBIDDEN"

    # Alice creates her analysis
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=alice_headers,
    ).json()["analysis_id"]

    # Alice can read her own analysis
    alice_get = client.get(f"/api/analyses/{analysis_id}", headers=alice_headers)
    assert alice_get.status_code == 200

    # Unauthenticated guest cannot read Alice's analysis (401)
    guest_get = client.get(f"/api/analyses/{analysis_id}")
    assert guest_get.status_code == 401

    # Bob cannot read, retry, or rewrite Alice's analysis (403)
    bob_get = client.get(f"/api/analyses/{analysis_id}", headers=bob_headers)
    assert bob_get.status_code == 403

    bob_retry = client.post(f"/api/analyses/{analysis_id}/retry", headers=bob_headers)
    assert bob_retry.status_code == 403

    bob_rewrite = client.post(f"/api/analyses/{analysis_id}/rewrites", headers=bob_headers)
    assert bob_rewrite.status_code == 403

    # History endpoint isolates Alice's and Bob's rows
    alice_hist = client.get("/api/analyses", headers=alice_headers).json()
    bob_hist = client.get("/api/analyses", headers=bob_headers).json()
    assert any(row["analysis_id"] == analysis_id for row in alice_hist)
    assert all(row["analysis_id"] != analysis_id for row in bob_hist)


def test_guest_gets_one_analysis_per_day_per_salted_ip_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enforce_guest_limit", True)
    monkeypatch.setattr(settings, "guest_ip_salt", "unit-test-salt")

    res_id = client.post(
        "/api/resumes",
        files={"file": ("guest.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 45}).json()["job_id"]

    ip_headers = {"X-Forwarded-For": "203.0.113.42, 10.0.0.1"}

    # 1st guest analysis succeeds and is flagged as guest (not saved to history)
    first = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=ip_headers,
    )
    assert first.status_code == 202
    assert first.json()["is_guest"] is True

    # Raw IP is never stored in guest_ip_usage
    assert "203.0.113.42" not in store.guest_ip_usage
    assert len(store.guest_ip_usage) == 1

    # Guest analysis is excluded from saved history
    hist = client.get(f"/api/analyses?resume_id={res_id}").json()
    assert hist == []

    # 2nd guest analysis from the same IP within 24h is rejected with GUEST_LIMIT_REACHED
    second = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=ip_headers,
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "GUEST_LIMIT_REACHED"

    # After 24h+ have elapsed, the same IP can run another guest analysis
    only_hash = next(iter(store.guest_ip_usage))
    store.guest_ip_usage[only_hash] = utcnow() - timedelta(hours=25)
    third = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers=ip_headers,
    )
    assert third.status_code == 202

