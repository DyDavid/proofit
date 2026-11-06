"""Authentication rejects bad input locally and bounds all remote verification work."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from api import auth
from api.config import settings
from api.main import app
from engine.execution import BoundedWorkPool

SECRET = "mock-jwt-secret-for-unit-testing-only-64-characters-long-xxxxxxxxxxx"


@pytest.fixture(autouse=True)
def auth_isolation(monkeypatch):
    auth._get_jwks_client.cache_clear()
    monkeypatch.setattr(auth, "_auth_pool", BoundedWorkPool("test-auth"))
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "auth_requests_per_min", 120)
    monkeypatch.setattr(settings, "auth_global_requests_per_min", 1200)
    yield
    auth._get_jwks_client.cache_clear()


def token(algorithm="HS256", key=SECRET, kid=None, **claims):
    return jwt.encode({"sub": "owner", "aud": "authenticated", "email": "owner@example.test",
                       "exp": int(time.time()) + 3600, **claims}, key, algorithm=algorithm,
                      headers={"kid": kid} if kid else None)


@pytest.mark.parametrize("bad", ["malformed", "oversized", "unsupported", "expired", "no-expiry", "bad-payload", "empty-bearer"])
def test_bad_tokens_rejected_without_admission_or_provider_work(monkeypatch, bad):
    admit = MagicMock()
    monkeypatch.setattr(auth, "admit_request", admit)
    remote = MagicMock()
    monkeypatch.setattr(auth, "_get_jwks_client", remote)
    values = {"malformed": "not-jwt", "oversized": "a" * 8193,
              "unsupported": token("HS384"), "expired": token(exp=1),
              "no-expiry": token(exp=None), "bad-payload": "eyJhbGciOiJFUzI1NiJ9.e30.invalid", "empty-bearer": ""}
    response = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + values[bad]})
    assert response.status_code == 401
    admit.assert_not_called()
    remote.assert_not_called()


def test_invalid_supported_tokens_eventually_hit_preverification_budget(monkeypatch):
    monkeypatch.setattr(settings, "auth_requests_per_min", 2)
    bad = token(key="a different secret" * 4)
    client = TestClient(app)
    assert [client.get("/api/auth/me", headers={"Authorization": "Bearer " + bad}).status_code for _ in range(3)] == [401, 401, 429]


def _jwks(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    public = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    public.update(kid="known", use="sig", alg="ES256")
    fetch = MagicMock(return_value={"keys": [public]})
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch)
    monkeypatch.setattr(settings, "supabase_url", "https://auth.example.test")
    return private, public, fetch


def test_random_key_ids_share_refresh_cooldown_and_key_rotation_recovers(monkeypatch):
    private, public, fetch = _jwks(monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(auth, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    client = TestClient(app)
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + token("ES256", private, "known")}).status_code == 200
    for index in range(12):
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + token("ES256", private, f"unknown-{index}")}).status_code == 401
    assert fetch.call_count == 1
    fetch.return_value = {"keys": [{**public, "kid": "rotated"}]}
    clock[0] = settings.auth_jwks_refresh_seconds
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + token("ES256", private, "rotated")}).status_code == 200
    assert fetch.call_count == 2
    # A removed signing key must not survive forever in an independent key LRU.
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + token("ES256", private, "known")}).status_code == 401


def test_failed_key_fetches_are_cooled_down_then_recover(monkeypatch):
    private, public, fetch = _jwks(monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(auth, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    fetch.side_effect = OSError("private network details")
    bearer = token("ES256", private, "known")
    client = TestClient(app)
    for _ in range(3):
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer " + bearer})
        assert response.status_code == 503
        assert "private" not in response.text
    assert fetch.call_count == 1
    clock[0] += settings.auth_jwks_refresh_seconds
    fetch.side_effect = None
    fetch.return_value = {"keys": [public]}
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + bearer}).status_code == 200


def test_auth_timeout_keeps_capacity_until_work_finishes(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = auth._decode_with_hs256

    def slow_decode(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(auth, "_decode_with_hs256", slow_decode)
    monkeypatch.setattr(settings, "auth_timeout_seconds", 0.05)
    monkeypatch.setattr(settings, "max_concurrent_auth", 1)
    bearer = token()
    client = TestClient(app)
    try:
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + bearer}).status_code == 503
        assert entered.is_set()
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + bearer}).status_code == 429
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while auth._auth_pool.active:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    monkeypatch.setattr(settings, "auth_timeout_seconds", 5)
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + bearer}).status_code == 200


def test_concurrent_key_fetches_contact_provider_once(monkeypatch):
    private, public, fetch = _jwks(monkeypatch)
    entered, release = threading.Event(), threading.Event()

    def slow_fetch():
        entered.set()
        assert release.wait(5)
        return {"keys": [public]}

    fetch.side_effect = slow_fetch
    monkeypatch.setattr(settings, "max_concurrent_auth", 2)
    bearer = token("ES256", private, "known")
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(lambda: asyncio.run(auth.verify_bearer_token(bearer, "one")))
        try:
            assert entered.wait(5)
            second = pool.submit(lambda: asyncio.run(auth.verify_bearer_token(bearer, "two")))
            deadline = time.monotonic() + 3
            while auth._auth_pool.active < 2:
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + bearer}).status_code == 429
        finally:
            release.set()
        assert first.result(timeout=5).id == second.result(timeout=5).id == "owner"
    assert fetch.call_count == 1


@pytest.mark.parametrize("status,expected", [(200, 200), (401, 401), (500, 503)])
def test_auth_api_fallback_has_explicit_timeout_and_safe_errors(monkeypatch, status, expected):
    monkeypatch.setattr(settings, "supabase_jwt_secret", None)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setattr(auth, "validate_persistence_config", lambda: ("https://auth.example.test", "mock-service-key"))
    response = httpx.Response(status, json={"id": "owner", "email": "owner@example.test"})
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(auth.httpx, "Client", factory)
    result = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + token()})
    assert result.status_code == expected
    assert factory.call_args.kwargs["timeout"] == settings.auth_provider_timeout_seconds
    assert "mock-service-key" not in result.text
