"""Tests for ABA PayWay / KHQR billing provider and checkout lifecycle."""

from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.auth import CurrentUser, get_current_user
from api.billing.providers.aba_payway import AbaPayWayProvider, compute_aba_hash
from api.billing.service import reset_billing_memory
from api.main import app

client = TestClient(app)

MOCK_USER = CurrentUser(
    id="aba-tester-user-id",
    email="tester@proofit.online",
    role="authenticated",
)


def _override_auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER


def _clear_auth() -> None:
    app.dependency_overrides.pop(get_current_user, None)


def test_compute_aba_hash_matches_hmac_sha512():
    data = "20261028120000ec000002123456"
    key = "test_secret_api_key"
    expected = base64.b64encode(
        hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha512).digest()
    ).decode("utf-8")

    assert compute_aba_hash(data, key) == expected


def test_create_session_unconfigured_uses_static_card():
    provider = AbaPayWayProvider(merchant_id="", api_key="")
    session = provider.create_session(
        checkout_session_id="test_sess_1",
        user_id="user_123",
        user_email="user@test.com",
        plan_id="pass",
        plan_name="Job Hunt Pass",
        amount_cents=500,
        currency="USD",
    )

    assert session["provider_ref"].startswith("pf")
    assert session["qr_image"] == "/aba-khqr.jpg"
    assert session["checkout_url"] is None
    assert session["expires_at"] is not None


def test_create_session_success_with_payway_mock():
    provider = AbaPayWayProvider(
        merchant_id="ec000002",
        api_key="sandbox_key_123",
        base_url="https://checkout-sandbox.payway.com.kh",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "qrString": "00020101021230510016abaakhppxxx...",
        "qrImage": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg...",
        "abapay_deeplink": "abamobilebank://ababank.com?type=payway&qrcode=00020101...",
    }

    mock_http_client = MagicMock()
    mock_http_client.__enter__.return_value.post.return_value = mock_resp

    with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_http_client):
        session = provider.create_session(
            checkout_session_id="test_sess_2",
            user_id="user_123",
            user_email="user@test.com",
            plan_id="pass",
            plan_name="Job Hunt Pass",
            amount_cents=500,
            currency="USD",
        )

        assert session["qr_string"] == "00020101021230510016abaakhppxxx..."
        assert session["qr_image"] == "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."
        assert session["deeplink"] == "abamobilebank://ababank.com?type=payway&qrcode=00020101..."


def test_get_status_approved_returns_paid():
    provider = AbaPayWayProvider(merchant_id="ec000002", api_key="sandbox_key_123")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": {"code": "00", "message": "Success"},
        "data": {
            "payment_status": "APPROVED",
            "payment_status_code": 0,
            "payment_amount": 5.0,
        },
    }

    mock_http_client = MagicMock()
    mock_http_client.__enter__.return_value.post.return_value = mock_resp

    with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_http_client):
        status = provider.get_status("pf_tran_12345")
        assert status == "paid"


def test_get_status_pending_returns_pending():
    provider = AbaPayWayProvider(merchant_id="ec000002", api_key="sandbox_key_123")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": {"code": "00", "message": "Pending"},
        "data": {
            "payment_status": "PENDING",
            "payment_status_code": 1,
        },
    }

    mock_http_client = MagicMock()
    mock_http_client.__enter__.return_value.post.return_value = mock_resp

    with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_http_client):
        status = provider.get_status("pf_tran_12345")
        assert status == "pending"


def test_get_status_cancelled_returns_expired():
    provider = AbaPayWayProvider(merchant_id="ec000002", api_key="sandbox_key_123")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": {"code": "00", "message": "Cancelled"},
        "data": {
            "payment_status": "CANCELLED",
            "payment_status_code": 2,
        },
    }

    mock_http_client = MagicMock()
    mock_http_client.__enter__.return_value.post.return_value = mock_resp

    with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_http_client):
        status = provider.get_status("pf_tran_12345")
        assert status == "expired"


def test_aba_payway_end_to_end_flow(monkeypatch):
    reset_billing_memory()
    _override_auth()
    try:
        from api.config import settings

        monkeypatch.setattr(settings, "billing_provider", "aba_payway")
        monkeypatch.setattr(settings, "aba_payway_merchant_id", "ec000002")
        monkeypatch.setattr(settings, "aba_payway_api_key", "sandbox_key_123")

        mock_gen_resp = MagicMock()
        mock_gen_resp.status_code = 200
        mock_gen_resp.json.return_value = {
            "qrString": "00020101021230510016abaakhppxxx...",
            "qrImage": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg...",
            "abapay_deeplink": "abamobilebank://ababank.com?type=payway&qrcode=00020101...",
        }

        mock_client_gen = MagicMock()
        mock_client_gen.__enter__.return_value.post.return_value = mock_gen_resp

        # 1. Create checkout session
        with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_client_gen):
            res = client.post("/api/billing/checkout", json={"plan_id": "pass"})
            assert res.status_code == 200, res.text
            created = res.json()
            assert created["provider"] == "aba_payway"
            assert created["amount_cents"] == 500
            assert created["currency"] == "USD"
            assert created["qr_image"] == "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."
            assert created["deeplink"] is not None
            session_id = created["session_id"]

        # 2. Poll status while still pending
        mock_poll_pending = MagicMock()
        mock_poll_pending.status_code = 200
        mock_poll_pending.json.return_value = {
            "status": {"code": "00", "message": "Pending"},
            "data": {"payment_status": "PENDING", "payment_status_code": 1},
        }

        mock_client_pending = MagicMock()
        mock_client_pending.__enter__.return_value.post.return_value = mock_poll_pending

        with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_client_pending):
            res_pending = client.get(f"/api/billing/checkout/{session_id}")
            assert res_pending.status_code == 200
            assert res_pending.json()["status"] == "pending"

        # 3. Poll status when paid in ABA app -> auto activates pass!
        mock_poll_paid = MagicMock()
        mock_poll_paid.status_code = 200
        mock_poll_paid.json.return_value = {
            "status": {"code": "00", "message": "Approved"},
            "data": {"payment_status": "APPROVED", "payment_status_code": 0},
        }

        mock_client_paid = MagicMock()
        mock_client_paid.__enter__.return_value.post.return_value = mock_poll_paid

        with patch("api.billing.providers.aba_payway.httpx.Client", return_value=mock_client_paid):
            res_paid = client.get(f"/api/billing/checkout/{session_id}")
            assert res_paid.status_code == 200
            body = res_paid.json()
            assert body["status"] == "paid"
            assert body["paid_at"] is not None
            assert body["active_until"] is not None

        # 4. Verify subscription summary shows active pass
        sub_res = client.get("/api/billing/subscription")
        assert sub_res.status_code == 200
        sub_body = sub_res.json()
        assert sub_body["plan_id"] == "pass"
        assert sub_body["usage"]["analysis"]["limit"] == 50
        assert sub_body["usage"]["rewrite"]["limit"] == 30
    finally:
        _clear_auth()
        reset_billing_memory()
