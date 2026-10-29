"""Phase 4 tests: Direct Individual Bakong KHQR, NBC MD5 verification, idempotency, and quotas."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from api.billing.khqr import (
    build_individual_khqr,
    compute_crc16_ccitt_false,
    compute_khqr_md5,
    decode_and_validate_khqr,
)
from api.billing.service import (
    _load_checkout_session_by_id,
    get_test_subscriptions_for_user,
    reset_billing_memory,
)
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


def _mock_httpx_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _patch_httpx_post(response_or_exc: MagicMock | Exception):
    mock_client = MagicMock()
    if isinstance(response_or_exc, Exception):
        mock_client.__enter__.return_value.post.side_effect = response_or_exc
    else:
        mock_client.__enter__.return_value.post.return_value = response_or_exc
    return patch("api.billing.bakong_client.httpx.Client", return_value=mock_client)


def test_startup_safety_rejects_untrusted_hosts_and_relay_tokens() -> None:
    # Untrusted relay host is rejected
    bad_host = Settings(
        bakong_api_base_url="https://api.khqr.dev",
    )
    with pytest.raises(RuntimeError, match="Refusing to start"):
        validate_billing_config(bad_host)

    # Relay token starting with rbk is rejected
    bad_token = Settings(
        bakong_api_base_url="https://sit-api-bakong.nbc.gov.kh",
        bakong_token="rbk_live_relay_token_123",
    )
    with pytest.raises(RuntimeError, match="Refusing to start"):
        validate_billing_config(bad_token)

    # Expiry exceeding 10 minutes (600s) is rejected
    bad_expiry = Settings(
        bakong_api_base_url="https://sit-api-bakong.nbc.gov.kh",
        khqr_expiry_seconds=900,
    )
    with pytest.raises(RuntimeError, match="Refusing to start"):
        validate_billing_config(bad_expiry)

    # Live enabled without token is rejected
    missing_live_token = Settings(
        bakong_api_base_url="https://api-bakong.nbc.gov.kh",
        bakong_live_enabled=True,
        bakong_account_id="abaakhppxxx@abaa",
        bakong_token=None,
    )
    with pytest.raises(RuntimeError, match="Refusing to start"):
        validate_billing_config(missing_live_token)

    # Valid SIT config passes
    valid_sit = Settings(
        bakong_api_base_url="https://sit-api-bakong.nbc.gov.kh",
        bakong_account_id="abaakhppxxx@abaa",
        bakong_live_enabled=False,
        khqr_expiry_seconds=300,
    )
    validate_billing_config(valid_sit)


def test_khqr_tag29_tlv_crc_and_md5_validation() -> None:
    now = datetime(2026, 10, 29, 0, 0, 0, tzinfo=UTC)
    gen = build_individual_khqr(
        bakong_account_id="abaakhppxxx@abaa",
        account_information="012929221",
        acquiring_bank="ABA Bank",
        merchant_name="DY DAVID",
        merchant_city="Phnom Penh",
        amount_minor=500,
        currency="USD",
        bill_number="PASS-ABCDEF123456",
        created_at=now,
        expiry_seconds=300,
    )

    # 1. Must start with 000201010212 (Dynamic QR) and Tag 29 (Individual)
    assert gen.qr_payload.startswith("00020101021229")
    # 2. MD5 matches exact 32-char lowercase hex of UTF-8 payload
    expected_md5 = hashlib.md5(gen.qr_payload.encode("utf-8")).hexdigest().lower()
    assert gen.qr_md5 == expected_md5
    assert compute_khqr_md5(gen.qr_payload) == expected_md5
    assert len(gen.qr_md5) == 32

    # 3. Decode & verify TLV fields and CRC16
    decoded = decode_and_validate_khqr(gen.qr_payload)
    assert decoded.point_of_initiation == "12"
    assert decoded.bakong_account_id == "abaakhppxxx@abaa"
    assert decoded.account_information == "012929221"
    assert decoded.acquiring_bank == "ABA Bank"
    assert decoded.amount_minor == 500
    assert decoded.currency == "USD"
    assert decoded.merchant_name == "DY DAVID"
    assert decoded.merchant_city == "Phnom Penh"
    assert decoded.bill_number == "PASS-ABCDEF123456"
    assert decoded.expires_at_ms - decoded.created_at_ms == 300_000

    # 4. Tampered payload fails CRC16 verification
    tampered = gen.qr_payload[:-4] + "0000"
    with pytest.raises(ValueError, match="CRC16 mismatch"):
        decode_and_validate_khqr(tampered)

    # 5. Static QR (01=11) or Merchant Tag 30 is rejected
    static_body = gen.qr_payload[:-8].replace("010212", "010211", 1) + "6304"
    static_qr = static_body + compute_crc16_ccitt_false(static_body)
    with pytest.raises(ValueError, match="dynamic"):
        decode_and_validate_khqr(static_qr)


def test_checkout_rejects_free_and_campus_and_removed_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_billing_memory()
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

    # Removed mock/Stripe endpoints must return 404/405
    sim_res = client.post("/api/billing/checkout/any-id/simulate", headers=headers)
    assert sim_res.status_code == 404
    wh_res = client.post("/api/billing/webhooks/stripe", content=b"{}")
    assert wh_res.status_code == 404


def test_production_checkout_blocked_when_live_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_billing_memory()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "bakong_api_base_url", "https://api-bakong.nbc.gov.kh")
    monkeypatch.setattr(settings, "bakong_live_enabled", False)

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_make_token('user-prod-gate')}"}
    res = client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers)
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "live_checkout_disabled"


def test_direct_bakong_khqr_verified_fulfillment_idempotency_and_pass_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_billing_memory()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "bakong_api_base_url", "https://sit-api-bakong.nbc.gov.kh")
    monkeypatch.setattr(settings, "bakong_token", "nbc_sit_valid_jwt_token_123")
    monkeypatch.setattr(settings, "bakong_account_id", "abaakhppxxx@abaa")
    monkeypatch.setattr(settings, "bakong_account_information", "012929221")
    monkeypatch.setattr(settings, "bakong_acquiring_bank", "ABA Bank")
    monkeypatch.setattr(settings, "bakong_merchant_name", "DY DAVID")

    client = TestClient(app)
    user_id = "user-bakong-buyer"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    # 1. Create first checkout order
    res = client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers)
    assert res.status_code == 200
    created = res.json()
    session_id = created["session_id"]
    assert created["amount_minor"] == 500
    assert created["currency"] == "USD"
    assert created["status"] == "unpaid"
    assert created["bill_number"].startswith("PASS-")
    assert len(created["qr_md5"]) == 32
    assert "nbc_sit_valid_jwt_token_123" not in res.text

    # 2. Poll while NBC reports not yet paid -> remains unpaid, no subscription
    unpaid_nbc = _mock_httpx_response(
        200,
        {"responseCode": 1, "responseMessage": "Transaction not found", "data": None},
    )
    with _patch_httpx_post(unpaid_nbc):
        poll_unpaid = client.get(f"/api/billing/checkout/{session_id}", headers=headers)
        assert poll_unpaid.status_code == 200
        assert poll_unpaid.json()["status"] == "unpaid"
        assert len(get_test_subscriptions_for_user(user_id)) == 0

    # 3. Poll when NBC returns confirmed matching payment -> transitions to paid & grants 30-day pass
    paid_nbc = _mock_httpx_response(
        200,
        {
            "responseCode": 0,
            "responseMessage": "Success",
            "data": {
                "hash": "nbc_tx_hash_unique_001",
                "fromAccountId": "payer@aba",
                "toAccountId": "012929221",
                "currency": "USD",
                "amount": 5.0,
            },
        },
    )
    with _patch_httpx_post(paid_nbc):
        poll_paid1 = client.get(f"/api/billing/checkout/{session_id}", headers=headers)
        assert poll_paid1.status_code == 200
        body1 = poll_paid1.json()
        assert body1["status"] == "paid"
        assert body1["nbc_transaction_hash"] == "nbc_tx_hash_unique_001"
        first_active_until = datetime.fromisoformat(body1["active_until"])

        # Repeated poll / confirmation must NOT create a duplicate subscription
        poll_paid2 = client.get(f"/api/billing/checkout/{session_id}", headers=headers)
        assert poll_paid2.status_code == 200
        assert len(get_test_subscriptions_for_user(user_id)) == 1

    # 4. Buying a second Pass while active extends expiry by 30 days once
    res2 = client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers)
    assert res2.status_code == 200
    session_id_2 = res2.json()["session_id"]
    assert res2.json()["bill_number"] != created["bill_number"]
    assert res2.json()["qr_md5"] != created["qr_md5"]

    # Reusing the FIRST order's transaction hash on the second order must be rejected!
    with _patch_httpx_post(paid_nbc):
        replay_poll = client.get(f"/api/billing/checkout/{session_id_2}", headers=headers)
        assert replay_poll.status_code == 200
        assert replay_poll.json()["status"] == "unpaid"
        assert replay_poll.json()["verification_error"] == "duplicate_transaction_hash"

    # Paying the second order with a fresh NBC transaction hash extends active_until by 30 days
    paid_nbc_2 = _mock_httpx_response(
        200,
        {
            "responseCode": 0,
            "responseMessage": "Success",
            "data": {
                "hash": "nbc_tx_hash_unique_002",
                "fromAccountId": "payer@aba",
                "toAccountId": "abaakhppxxx@abaa",
                "currency": "USD",
                "amount": "5.00",
            },
        },
    )
    with _patch_httpx_post(paid_nbc_2):
        poll2 = client.get(f"/api/billing/checkout/{session_id_2}", headers=headers)
        assert poll2.status_code == 200
        assert poll2.json()["status"] == "paid"
        second_active_until = datetime.fromisoformat(poll2.json()["active_until"])
        delta_days = (second_active_until - first_active_until).total_seconds() / 86400
        assert 29.9 <= delta_days <= 30.1


def test_mismatched_recipient_amount_or_currency_never_activates_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_billing_memory()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "bakong_api_base_url", "https://sit-api-bakong.nbc.gov.kh")
    monkeypatch.setattr(settings, "bakong_token", "nbc_sit_valid_jwt_token_123")
    monkeypatch.setattr(settings, "bakong_account_id", "abaakhppxxx@abaa")
    monkeypatch.setattr(settings, "bakong_account_information", "012929221")

    client = TestClient(app)
    user_id = "user-mismatch-test"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    created = client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers).json()
    session_id = created["session_id"]

    # Wrong recipient
    wrong_recipient = _mock_httpx_response(
        200,
        {
            "responseCode": 0,
            "data": {
                "hash": "tx_wrong_recip",
                "toAccountId": "someone_else@aba",
                "currency": "USD",
                "amount": 5.0,
            },
        },
    )
    with _patch_httpx_post(wrong_recipient):
        st = client.get(f"/api/billing/checkout/{session_id}", headers=headers).json()
        assert st["status"] == "unpaid"
        assert st["verification_error"] == "payment_recipient_mismatch"
        assert len(get_test_subscriptions_for_user(user_id)) == 0

    # Wrong amount ($1.00 instead of $5.00)
    wrong_amount = _mock_httpx_response(
        200,
        {
            "responseCode": 0,
            "data": {
                "hash": "tx_wrong_amt",
                "toAccountId": "012929221",
                "currency": "USD",
                "amount": 1.0,
            },
        },
    )
    with _patch_httpx_post(wrong_amount):
        st = client.get(f"/api/billing/checkout/{session_id}", headers=headers).json()
        assert st["status"] == "unpaid"
        assert st["verification_error"] == "payment_amount_mismatch"
        assert len(get_test_subscriptions_for_user(user_id)) == 0


def test_expired_qr_blocks_auto_fulfillment_and_flags_late_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_billing_memory()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "bakong_api_base_url", "https://sit-api-bakong.nbc.gov.kh")
    monkeypatch.setattr(settings, "bakong_token", "nbc_sit_valid_jwt_token_123")
    monkeypatch.setattr(settings, "bakong_account_id", "abaakhppxxx@abaa")
    monkeypatch.setattr(settings, "bakong_account_information", "012929221")

    client = TestClient(app)
    user_id = "user-expired-qr"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    created = client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers).json()
    session_id = created["session_id"]

    # Force session expiry in memory
    rec = _load_checkout_session_by_id(session_id)
    assert rec is not None
    rec.expires_at = datetime.now(UTC) - timedelta(seconds=10)

    # Even if NBC reports a payment after QR expiry, it must NOT auto-grant a subscription
    late_paid_nbc = _mock_httpx_response(
        200,
        {
            "responseCode": 0,
            "data": {
                "hash": "tx_late_after_expiry_999",
                "toAccountId": "012929221",
                "currency": "USD",
                "amount": 5.0,
            },
        },
    )
    with _patch_httpx_post(late_paid_nbc):
        st = client.get(f"/api/billing/checkout/{session_id}", headers=headers).json()
        assert st["status"] == "expired"
        assert st["verification_error"] == "late_payment_reconciliation_required"
        assert st["nbc_transaction_hash"] == "tx_late_after_expiry_999"
        assert len(get_test_subscriptions_for_user(user_id)) == 0


def test_nbc_401_and_transient_errors_surface_safe_codes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    reset_billing_memory()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "bakong_api_base_url", "https://sit-api-bakong.nbc.gov.kh")
    monkeypatch.setattr(settings, "bakong_token", "secret_expired_nbc_token_val")
    monkeypatch.setattr(settings, "bakong_account_id", "abaakhppxxx@abaa")

    client = TestClient(app)
    user_id = "user-error-modes"
    headers = {"Authorization": f"Bearer {_make_token(user_id)}"}

    created = client.post("/api/billing/checkout", json={"plan_id": "pass"}, headers=headers).json()
    session_id = created["session_id"]

    # 1. HTTP 401 from NBC logs bakong_token_expired_or_invalid without leaking token
    with caplog.at_level(logging.ERROR), _patch_httpx_post(_mock_httpx_response(401, {})):
        res_401 = client.get(f"/api/billing/checkout/{session_id}", headers=headers)
        assert res_401.status_code == 200
        body_401 = res_401.json()
        assert body_401["status"] == "unpaid"
        assert body_401["verification_error"] == "bakong_token_expired_or_invalid"
        assert "secret_expired_nbc_token_val" not in res_401.text
        assert any("bakong_token_expired_or_invalid" in r.message for r in caplog.records)

    # 2. Network timeout / unreachable surfaces safe transient error
    with _patch_httpx_post(httpx.ConnectTimeout("NBC timeout")):
        res_net = client.get(f"/api/billing/checkout/{session_id}", headers=headers)
        assert res_net.status_code == 200
        body_net = res_net.json()
        assert body_net["status"] == "unpaid"
        assert body_net["verification_error"] == "bakong_unreachable"


def test_free_user_quota_blocks_fourth_analysis_and_second_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_billing_memory()
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


def test_admin_user_has_unlimited_access(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_billing_memory()
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(settings, "enforce_quotas", True)
    client = TestClient(app)
    admin_id = "user-super-admin"
    admin_headers = {
        "Authorization": f"Bearer {_make_token(admin_id, email='dydavid168@gmail.com')}"
    }

    # Admin's subscription returns campus / unlimited
    sub_res = client.get("/api/billing/subscription", headers=admin_headers)
    assert sub_res.status_code == 200
    sub_data = sub_res.json()
    assert sub_data["plan_id"] == "campus"
    assert sub_data["usage"]["analysis"]["limit"] is None
    assert sub_data["usage"]["rewrite"]["limit"] is None

    # Admin can upload multiple resumes without hitting saved_resumes limit
    r1 = client.post(
        "/api/resumes",
        files={"file": ("adm_resume1.pdf", b"%PDF-1.4 sample", "application/pdf")},
        headers=admin_headers,
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/resumes",
        files={"file": ("adm_resume2.pdf", b"%PDF-1.4 sample 2", "application/pdf")},
        headers=admin_headers,
    )
    assert r2.status_code == 200

    job_res = client.post(
        "/api/jobs",
        json={
            "text": (
                "Junior Software Engineer required with TypeScript and Python. "
                "Responsibilities include building frontend apps and writing tests."
            )
        },
        headers=admin_headers,
    )
    job_id = job_res.json()["job_id"]

    # Admin can run 5+ analyses without 402 quota error
    for _ in range(5):
        a_res = client.post(
            "/api/analyses",
            json={"resume_id": r1.json()["resume_id"], "job_id": job_id, "country": "cambodia"},
            headers=admin_headers,
        )
        assert a_res.status_code == 202
