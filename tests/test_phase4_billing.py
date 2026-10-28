"""Phase 4 tests: Stripe sandbox, mock checkout, webhooks, idempotency, and quotas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

from api.billing.service import get_test_subscriptions_for_user
from api.config import Settings, settings, validate_billing_config
from api.main import app

TEST_JWT_SECRET = "phase4-test-jwt-secret-key-with-at-least-32-bytes"


def _make_token(user_id: str, email: str = "candidate@example.com") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def test_startup_safety_rejects_live_stripe_key() -> None:
    bad_cfg = Settings(
        billing_provider="stripe_sandbox",
        stripe_secret_key="sk_live_NEVER_ALLOW_THIS",
    )
    with pytest.raises(RuntimeError, match="Refusing to start"):
        validate_billing_config(bad_cfg)

    missing_cfg = Settings(
        billing_provider="stripe_sandbox",
        stripe_secret_key=None,
    )
    with pytest.raises(RuntimeError, match="Refusing to start"):
        validate_billing_config(missing_cfg)

    good_cfg = Settings(
        billing_provider="stripe_sandbox",
        stripe_secret_key="sk_test_sandbox_12345",
    )
    validate_billing_config(good_cfg)


def test_checkout_rejects_free_and_campus_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    client = TestClient(app)
    token = _make_token("user-plan-check")
    headers = {"Authorization": f"Bearer {token}"}

    for invalid_plan in ("free", "campus"):
        res = client.post(
            "/api/billing/checkout",
            json={"plan_id": invalid_plan},
            headers=headers,
        )
        assert res.status_code == 400


def test_mock_checkout_simulate_idempotent_and_extends_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "billing_provider", "mock")
    client = TestClient(app)
    user_id = "user-mock-buyer"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    # 1. Create first checkout session
    res = client.post(
        "/api/billing/checkout",
        json={"plan_id": "pass"},
        headers=headers,
    )
    assert res.status_code == 200
    created = res.json()
    assert created["provider"] == "mock"
    assert created["amount_cents"] == 500
    assert created["currency"] == "USD"
    assert created["checkout_url"] is None
    session_id = created["session_id"]

    # 2. Simulate payment twice -> must create only ONE subscription
    sim1 = client.post(f"/api/billing/checkout/{session_id}/simulate", headers=headers)
    assert sim1.status_code == 200
    assert sim1.json()["status"] == "paid"
    first_active_until = datetime.fromisoformat(sim1.json()["active_until"])

    sim2 = client.post(f"/api/billing/checkout/{session_id}/simulate", headers=headers)
    assert sim2.status_code == 200
    assert len(get_test_subscriptions_for_user(user_id)) == 1

    # 3. Buying a second pass while active extends end date by 30 days
    res2 = client.post(
        "/api/billing/checkout",
        json={"plan_id": "pass"},
        headers=headers,
    )
    session_id_2 = res2.json()["session_id"]
    sim_second = client.post(
        f"/api/billing/checkout/{session_id_2}/simulate",
        headers=headers,
    )
    assert sim_second.status_code == 200
    second_active_until = datetime.fromisoformat(sim_second.json()["active_until"])
    assert (second_active_until - first_active_until).days >= 29


def test_simulate_returns_404_when_provider_is_stripe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "billing_provider", "mock")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_make_token('user-sim-404')}"}

    created = client.post(
        "/api/billing/checkout",
        json={"plan_id": "pass"},
        headers=headers,
    ).json()

    monkeypatch.setattr(settings, "billing_provider", "stripe_sandbox")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123456")

    res = client.post(
        f"/api/billing/checkout/{created['session_id']}/simulate",
        headers=headers,
    )
    assert res.status_code == 404


def test_stripe_webhook_signature_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "billing_provider", "stripe_sandbox")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123456")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")

    import stripe

    monkeypatch.setattr(
        stripe.checkout.Session,
        "create",
        lambda **kwargs: SimpleNamespace(
            id="cs_test_webhook_1",
            url="https://checkout.stripe.com/c/pay/cs_test_webhook_1",
        ),
    )

    client = TestClient(app)
    user_id = "user-stripe-webhook"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    created = client.post(
        "/api/billing/checkout",
        json={"plan_id": "pass"},
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_webhook_1"

    # 1. Missing or invalid webhook signature -> 400 and grants nothing
    bad_wh = client.post(
        "/api/billing/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "invalid"},
    )
    assert bad_wh.status_code == 400
    assert len(get_test_subscriptions_for_user(user_id)) == 0

    # 2. Valid webhook event -> marks paid and grants pass
    fake_event = {
        "id": "evt_test_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_webhook_1",
                "payment_status": "paid",
                "amount_total": 500,
                "metadata": {
                    "user_id": user_id,
                    "plan_id": "pass",
                },
            }
        },
    }
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda payload, sig_header, secret: fake_event,
    )

    ok_wh = client.post(
        "/api/billing/webhooks/stripe",
        content=b'{"id":"evt_test_001"}',
        headers={"stripe-signature": "t=1,v1=valid"},
    )
    assert ok_wh.status_code == 200
    assert ok_wh.json()["status"] == "ok"
    assert len(get_test_subscriptions_for_user(user_id)) == 1

    # 3. Duplicate delivery of the same event -> ignored, no second subscription
    dup_wh = client.post(
        "/api/billing/webhooks/stripe",
        content=b'{"id":"evt_test_001"}',
        headers={"stripe-signature": "t=1,v1=valid"},
    )
    assert dup_wh.status_code == 200
    assert dup_wh.json()["status"] == "duplicate_ignored"
    assert len(get_test_subscriptions_for_user(user_id)) == 1


def test_stripe_late_webhook_fallback_grants_on_status_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "billing_provider", "stripe_sandbox")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123456")

    import stripe

    monkeypatch.setattr(
        stripe.checkout.Session,
        "create",
        lambda **kwargs: SimpleNamespace(
            id="cs_test_late_wh",
            url="https://checkout.stripe.com/c/pay/cs_test_late_wh",
        ),
    )
    monkeypatch.setattr(
        stripe.checkout.Session,
        "retrieve",
        lambda ref, api_key=None: SimpleNamespace(
            id=ref,
            payment_status="paid",
            status="complete",
        ),
    )

    client = TestClient(app)
    user_id = "user-late-webhook"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers)

    # Poll by provider_ref (as /billing/success?cs=cs_test_late_wh does)
    poll = client.get("/api/billing/checkout/by-ref/cs_test_late_wh", headers=headers)
    assert poll.status_code == 200
    assert poll.json()["status"] == "paid"
    assert poll.json()["active_until"] is not None
    assert len(get_test_subscriptions_for_user(user_id)) == 1


def test_free_user_quota_blocks_fourth_analysis_and_second_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "enforce_quotas", True)
    client = TestClient(app)
    user_id = "user-quota-free"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    # Upload 1st resume -> succeeds
    r1 = client.post(
        "/api/resumes",
        files={"file": ("resume1.pdf", b"%PDF-1.4 sample", "application/pdf")},
        headers=headers,
    )
    assert r1.status_code == 200
    resume_id = r1.json()["resume_id"]

    # Upload 2nd resume on Free plan -> 402 quota_exceeded
    r2 = client.post(
        "/api/resumes",
        files={"file": ("resume2.pdf", b"%PDF-1.4 sample 2", "application/pdf")},
        headers=headers,
    )
    assert r2.status_code == 402
    assert r2.json()["detail"]["code"] == "quota_exceeded"
    assert r2.json()["detail"]["kind"] == "saved_resumes"

    # Submit a job
    job_res = client.post(
        "/api/jobs",
        json={
            "text": (
                "Junior Data Analyst at Angkor Digital. Responsibilities include "
                "writing SQL queries, building Python dashboards, and presenting insights."
            )
        },
        headers=headers,
    )
    assert job_res.status_code == 200
    job_id = job_res.json()["job_id"]

    # Run 3 analyses on Free plan -> all 3 succeed and record usage
    for _ in range(3):
        a_res = client.post(
            "/api/analyses",
            json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
            headers=headers,
        )
        assert a_res.status_code == 202

    # 4th analysis in 30 days -> 402 quota_exceeded with upgrade_url: "/pricing"
    fourth = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
        headers=headers,
    )
    assert fourth.status_code == 402
    detail = fourth.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["kind"] == "analysis"
    assert detail["limit"] == 3
    assert detail["upgrade_url"] == "/pricing"
