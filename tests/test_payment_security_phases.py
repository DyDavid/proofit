"""Simulation guards and retry-safe payment webhook processing."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import stripe
from fastapi.testclient import TestClient

from api.auth import CurrentUser, get_current_user
from api.billing import service
from api.billing.providers.stripe_sandbox import StripeSandboxProvider
from api.config import Settings, settings, validate_billing_config
from api.db import DatabasePersistenceError
from api.main import app


@pytest.fixture
def payment(monkeypatch):
    rec = service.CheckoutSessionRecord(id="secure-checkout", user_id="owner", plan_id="pass",
                                         amount_cents=500, currency="USD", status="pending", provider="mock",
                                         provider_ref="cs_test_security")
    service._cache_checkout_session(rec, persisted=False)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: CurrentUser(id="owner"))
    return rec


@pytest.mark.parametrize("change", ["disabled", "production", "stripe_record", "foreign", "expired", "canceled"])
def test_simulation_rejects_unsafe_requests(payment, monkeypatch, change):
    rec = payment
    before = rec.status
    expected = 404
    if change == "disabled":
        monkeypatch.setattr(settings, "allow_mock_payments", False)
    elif change == "production":
        monkeypatch.setattr(settings, "app_environment", "production")
    elif change == "stripe_record":
        rec.provider = "stripe_sandbox"
    elif change == "foreign":
        rec.user_id = "another-owner"
    else:
        rec.status = change
        before = change
        expected = 400
    response = TestClient(app).post(f"/api/billing/checkout/{rec.id}/simulate")
    assert response.status_code == expected
    assert rec.status == before
    assert not service._subscriptions


def test_pending_expired_simulation_is_rejected(payment):
    payment.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert TestClient(app).post(f"/api/billing/checkout/{payment.id}/simulate").status_code == 400
    assert payment.status == "expired"


def test_simulation_requires_authentication(payment):
    app.dependency_overrides.pop(get_current_user)
    assert TestClient(app).post(f"/api/billing/checkout/{payment.id}/simulate").status_code == 401


@pytest.mark.parametrize("allow,provider", [(True, "stripe_sandbox"), (False, "mock")])
def test_unsafe_production_billing_configuration_is_rejected(allow, provider):
    cfg = Settings(_env_file=None, app_environment="production", allow_mock_payments=allow,
                   billing_provider=provider, stripe_secret_key="sk_test_only")
    with pytest.raises(RuntimeError):
        validate_billing_config(cfg)


@pytest.mark.parametrize("engine,persistence", [("mock", "required"), ("live", "offline")])
def test_production_cannot_silently_use_local_coordination(engine, persistence):
    cfg = Settings(_env_file=None, app_environment="production", billing_provider="stripe_sandbox",
                   allow_mock_payments=False, stripe_secret_key="sk_test_only",
                   engine_mode=engine, persistence_mode=persistence)
    with pytest.raises(RuntimeError, match="database persistence"):
        validate_billing_config(cfg)


def test_safe_production_configuration_is_accepted():
    validate_billing_config(Settings(_env_file=None, app_environment="production", billing_provider="stripe_sandbox",
                                    allow_mock_payments=False, stripe_secret_key="sk_test_only",
                                    engine_mode="live", persistence_mode="required"))


def test_production_can_start_with_billing_disabled_and_no_stripe_key():
    validate_billing_config(Settings(_env_file=None, app_environment="production", billing_provider="disabled",
                                    stripe_secret_key=None, allow_mock_payments=False,
                                    engine_mode="live", persistence_mode="required"))


def test_disabled_billing_rejects_checkout_before_coordination_or_provider_work(payment, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "disabled")
    reservation = MagicMock()
    limit = MagicMock()
    provider = MagicMock()
    monkeypatch.setattr(service, "_reserve_checkout_session", reservation)
    monkeypatch.setattr("api.limiter.enforce_operation_attempt_limit", limit)
    monkeypatch.setattr(service, "StripeSandboxProvider", provider)
    response = TestClient(app).post("/api/billing/checkout", json={"plan_id": "pass"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    reservation.assert_not_called()
    limit.assert_not_called()
    provider.assert_not_called()
    assert not service._subscriptions


def test_disabled_billing_rejects_simulation_even_if_local_opt_in_is_left_enabled(payment, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "disabled")
    assert TestClient(app).post(f"/api/billing/checkout/{payment.id}/simulate").status_code == 404
    assert payment.status == "pending"
    assert not service._subscriptions


def test_pending_stripe_lookup_without_key_never_constructs_provider_client(monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "disabled")
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    client = MagicMock()
    monkeypatch.setattr(stripe, "StripeClient", client)
    with pytest.raises(RuntimeError, match="credentials"):
        StripeSandboxProvider().get_status("cs_test_historical")
    client.assert_not_called()


def test_disabled_billing_preserves_paid_status_and_idempotent_activation(payment, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "disabled")
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    payment.provider = "stripe_sandbox"
    payment.status = "paid"
    lookup = MagicMock()
    monkeypatch.setattr(StripeSandboxProvider, "get_status", lookup)
    for _ in range(2):
        response = TestClient(app).get(f"/api/billing/checkout/{payment.id}")
        assert response.status_code == 200
        assert response.json()["status"] == "paid"
        assert response.json()["active_until"] is not None
    assert len(service._subscriptions) == 1
    lookup.assert_not_called()


def _event(rec):
    return {"id": rec.provider_ref, "payment_status": "paid", "amount_total": 500,
            "currency": "usd", "metadata": {"user_id": rec.user_id}}


@pytest.mark.parametrize("failure", ["lookup", "save", "grant"])
def test_webhook_redelivery_retries_failed_processing(payment, monkeypatch, failure):
    payment.provider = "stripe_sandbox"
    data = _event(payment)
    target = {"lookup": "_load_checkout_session_by_ref", "save": "_save_checkout_session", "grant": "grant_plan"}[failure]
    original = getattr(service, target)
    calls = [0]

    def fail_once(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            raise DatabasePersistenceError("private failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, target, fail_once)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_mock")
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda **kwargs: {
        "id": "evt_retry", "type": "checkout.session.completed", "data": {"object": data},
    })
    client = TestClient(app)
    assert client.post("/api/billing/webhooks/stripe", content=b"{}", headers={"stripe-signature": "mock"}).status_code == 503
    assert "evt_retry" not in service._stripe_events
    for _ in range(2):
        assert client.post("/api/billing/webhooks/stripe", content=b"{}", headers={"stripe-signature": "mock"}).status_code == 200
    assert len(service._subscriptions) == 1


def test_simultaneous_webhooks_grant_once_and_bound_cache(payment, monkeypatch):
    payment.provider = "stripe_sandbox"
    monkeypatch.setattr(settings, "webhook_cache_max_entries", 2)
    barrier = threading.Barrier(6)

    def process(_):
        barrier.wait(timeout=5)
        return service.process_stripe_event("evt_same", "checkout.session.completed", _event(payment))

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(process, range(6))) == 1
    assert len(service._subscriptions) == 1
    for index in range(10):
        service.process_stripe_event(f"evt_{index}", "ignored", {})
    assert len(service._stripe_events) == 2
    service.process_stripe_event("evt_same", "checkout.session.completed", _event(payment))
    assert len(service._subscriptions) == 1


@pytest.mark.parametrize("field,value", [("amount_total", 1), ("currency", "eur"), ("metadata", {"user_id": "other"})])
def test_payment_details_are_validated_before_grant(payment, field, value):
    payment.provider = "stripe_sandbox"
    data = {**_event(payment), field: value}
    with pytest.raises(DatabasePersistenceError):
        service.process_stripe_event("evt_invalid", "checkout.session.completed", data)
    assert not service._subscriptions
    assert "evt_invalid" not in service._stripe_events


def test_required_webhook_coordination_never_falls_back(payment, monkeypatch):
    monkeypatch.setattr(service, "get_supabase_client", lambda: object())
    rpc = MagicMock(side_effect=DatabasePersistenceError("private failure"))
    monkeypatch.setattr(service, "db_billing_rpc", rpc)
    with pytest.raises(DatabasePersistenceError):
        service.process_stripe_event("evt_failed", "checkout.session.completed", _event(payment))
    assert not service._stripe_events
    assert not service._subscriptions
