"""Phase 3 tests: Pricing plans and subscription status API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from api.billing.service import set_test_subscription
from api.config import settings
from api.main import app

TEST_JWT_SECRET = "phase3-test-jwt-secret-key-with-at-least-32-bytes"


def _make_token(user_id: str, email: str = "student@example.com") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def test_get_billing_plans_returns_three_tiers() -> None:
    client = TestClient(app)
    res = client.get("/api/billing/plans")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) == 3

    free, pass_plan, campus = plans
    assert free["id"] == "free"
    assert free["price_cents"] == 0
    assert free["price_display"] == "$0"
    assert free["limits"]["analyses"] == 3
    assert free["limits"]["rewrites"] == 1
    assert free["limits"]["saved_resumes"] == 1

    assert pass_plan["id"] == "pass"
    assert pass_plan["recommended"] is True
    assert pass_plan["price_cents"] == 500
    assert pass_plan["price_display"] == "$5"
    assert pass_plan["limits"]["analyses"] == 50
    assert pass_plan["limits"]["rewrites"] == 30
    assert pass_plan["limits"]["saved_resumes"] == 10

    assert campus["id"] == "campus"
    assert campus["price_cents"] is None
    assert campus["price_display"] == "Custom"
    assert campus["limits"]["analyses"] is None
    assert campus["limits"]["rewrites"] is None


def test_get_subscription_requires_auth() -> None:
    client = TestClient(app)
    res = client.get("/api/billing/subscription")
    assert res.status_code == 401


def test_get_subscription_defaults_to_free(monkeypatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    client = TestClient(app)
    token = _make_token("user-free-1")

    res = client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["plan_id"] == "free"
    assert body["active_until"] is None
    assert body["usage"]["analysis"] == {"used": 0, "limit": 3}
    assert body["usage"]["rewrite"] == {"used": 0, "limit": 1}


def test_get_subscription_active_pass_and_expiry(monkeypatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    client = TestClient(app)
    user_id = "user-pass-1"
    token = _make_token(user_id)

    future_end = datetime.now(UTC) + timedelta(days=30)
    set_test_subscription(user_id=user_id, plan_id="pass", active_until=future_end)

    res = client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["plan_id"] == "pass"
    assert body["active_until"] is not None
    assert body["usage"]["analysis"] == {"used": 0, "limit": 50}
    assert body["usage"]["rewrite"] == {"used": 0, "limit": 30}


def test_get_subscription_expired_pass_reverts_to_free(monkeypatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    client = TestClient(app)
    user_id = "user-expired-1"
    token = _make_token(user_id)

    past_end = datetime.now(UTC) - timedelta(days=1)
    set_test_subscription(user_id=user_id, plan_id="pass", active_until=past_end)

    res = client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["plan_id"] == "free"
    assert body["active_until"] is None
