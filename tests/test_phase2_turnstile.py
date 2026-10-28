"""Phase 2 Bot Protection (Cloudflare Turnstile) Tests."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app
from api.store import store

client = TestClient(app)

TEST_JWT_SECRET = "test-supabase-hs256-jwt-secret-32-bytes-long!"


class _FakeHttpxResponse:
    def __init__(self, json_body: dict[str, Any], status_code: int = 200) -> None:
        self._json = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._json


def _seed_inputs() -> tuple[str, str]:
    res_id = client.post(
        "/api/resumes",
        files={"file": ("guest.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 45}).json()["job_id"]
    return res_id, job_id


def test_guest_analysis_requires_turnstile_token_when_secret_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "turnstile_secret_key", "1x0000000000000000000000000000000AA")
    monkeypatch.setattr(settings, "enforce_guest_limit", True)

    res_id, job_id = _seed_inputs()
    res = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "CAPTCHA_FAILED"
    # Failed CAPTCHA must not consume the guest's 1-per-day IP quota
    assert len(store.guest_ip_usage) == 0


def test_guest_analysis_rejects_invalid_turnstile_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "turnstile_secret_key", "1x0000000000000000000000000000000AA")

    async def _fake_post(_self: object, _url: str, data: dict[str, str]) -> _FakeHttpxResponse:
        assert data["response"] == "bad-turnstile-token"
        return _FakeHttpxResponse({"success": False, "error-codes": ["invalid-input-response"]})

    res_id, job_id = _seed_inputs()
    with patch("httpx.AsyncClient.post", new=_fake_post):
        res = client.post(
            "/api/analyses",
            json={
                "resume_id": res_id,
                "job_id": job_id,
                "country": "cambodia",
                "turnstile_token": "bad-turnstile-token",
            },
        )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "CAPTCHA_FAILED"


def test_guest_analysis_succeeds_with_valid_turnstile_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "turnstile_secret_key", "1x0000000000000000000000000000000AA")
    captured: dict[str, str] = {}

    async def _fake_post(_self: object, _url: str, data: dict[str, str]) -> _FakeHttpxResponse:
        captured.update(data)
        return _FakeHttpxResponse({"success": True})

    res_id, job_id = _seed_inputs()
    with patch("httpx.AsyncClient.post", new=_fake_post):
        res = client.post(
            "/api/analyses",
            json={
                "resume_id": res_id,
                "job_id": job_id,
                "country": "cambodia",
                "turnstile_token": "valid-turnstile-token",
            },
            headers={"X-Forwarded-For": "198.51.100.77"},
        )
    assert res.status_code == 202
    assert captured["secret"] == "1x0000000000000000000000000000000AA"
    assert captured["response"] == "valid-turnstile-token"
    assert captured["remoteip"] == "198.51.100.77"


def test_authenticated_user_bypasses_guest_turnstile_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "turnstile_secret_key", "1x0000000000000000000000000000000AA")
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)

    token = jwt.encode(
        {
            "sub": "user-verified",
            "email": "verified@aupp.edu.kh",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    res_id, job_id = _seed_inputs()
    res = client.post(
        "/api/analyses",
        json={"resume_id": res_id, "job_id": job_id, "country": "cambodia"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 202

