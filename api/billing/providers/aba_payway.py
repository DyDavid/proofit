"""ABA PayWay / Bakong KHQR Billing Provider.

Integrates dynamic KHQR payment generation and real-time transaction verification
via ABA PayWay Developer Suite (https://developer.payway.com.kh).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx

from api.billing.providers.base import CheckoutStatus, CreatedProviderSession
from api.config import settings

logger = logging.getLogger(__name__)


def compute_aba_hash(data: str, api_key: str) -> str:
    """Generate Base64-encoded HMAC-SHA512 hash required by ABA PayWay."""
    digest = hmac.new(
        api_key.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha512,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


class AbaPayWayProvider:
    name: Literal["aba_payway"] = "aba_payway"

    def __init__(
        self,
        merchant_id: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.merchant_id = merchant_id or settings.aba_payway_merchant_id or ""
        self.api_key = api_key or settings.aba_payway_api_key or ""
        self.base_url = (base_url or settings.aba_payway_base_url or "https://checkout-sandbox.payway.com.kh").rstrip("/")

    def create_session(
        self,
        *,
        checkout_session_id: str,
        user_id: str,
        user_email: str,
        plan_id: str,
        plan_name: str,
        amount_cents: int,
        currency: str,
    ) -> CreatedProviderSession:
        """Request a dynamic KHQR code from ABA PayWay or fallback to static card."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=30)

        # Unique transaction reference (max 20 characters alphanumeric)
        ts_part = f"{int(now.timestamp())}"[-8:]
        rand_part = uuid.uuid4().hex[:6]
        tran_id = f"pf{ts_part}{rand_part}"[:20]

        amount_str = f"{amount_cents / 100:.2f}"
        req_time = now.strftime("%Y%m%d%H%M%S")

        # Fallback values
        fallback_session: CreatedProviderSession = {
            "provider_ref": tran_id,
            "checkout_url": None,
            "expires_at": expires_at,
            "qr_string": None,
            "qr_image": "/aba-khqr.jpg",
            "deeplink": None,
        }

        if not self.merchant_id or not self.api_key:
            logger.info("ABA PayWay credentials not configured; using static card fallback.")
            return fallback_session

        # 19 fields in exact order for /generate-qr hash
        items = ""
        first_name = "Proofit"
        last_name = "User"
        email = user_email or "billing@proofit.online"
        phone = ""
        purchase_type = "purchase"
        payment_option = "abapay_khqr"
        callback_url = ""
        return_deeplink = ""
        currency_code = currency.upper() if currency else "USD"
        custom_fields = ""
        return_params = ""
        payout = ""
        lifetime = "30"
        qr_image_template = "template3_color"

        raw_hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{tran_id}"
            f"{amount_str}"
            f"{items}"
            f"{first_name}"
            f"{last_name}"
            f"{email}"
            f"{phone}"
            f"{purchase_type}"
            f"{payment_option}"
            f"{callback_url}"
            f"{return_deeplink}"
            f"{currency_code}"
            f"{custom_fields}"
            f"{return_params}"
            f"{payout}"
            f"{lifetime}"
            f"{qr_image_template}"
        )
        signature = compute_aba_hash(raw_hash_str, self.api_key)

        payload = {
            "req_time": req_time,
            "merchant_id": self.merchant_id,
            "tran_id": tran_id,
            "amount": amount_str,
            "items": items,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "purchase_type": purchase_type,
            "payment_option": payment_option,
            "callback_url": callback_url,
            "return_deeplink": return_deeplink,
            "currency": currency_code,
            "custom_fields": custom_fields,
            "return_params": return_params,
            "payout": payout,
            "lifetime": int(lifetime),
            "qr_image_template": qr_image_template,
            "hash": signature,
        }

        endpoint = f"{self.base_url}/api/payment-gateway/v1/payments/generate-qr"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(endpoint, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    qr_image = data.get("qrImage") or "/aba-khqr.jpg"
                    qr_string = data.get("qrString")
                    deeplink = data.get("abapay_deeplink")
                    return {
                        "provider_ref": tran_id,
                        "checkout_url": None,
                        "expires_at": expires_at,
                        "qr_string": qr_string,
                        "qr_image": qr_image,
                        "deeplink": deeplink,
                    }
                logger.warning(
                    "ABA PayWay generate-qr returned status %s: %s",
                    res.status_code,
                    res.text[:200],
                )
        except Exception as e:
            logger.warning("ABA PayWay generate-qr connection failed: %s", e)

        return fallback_session

    def get_status(self, provider_ref: str) -> CheckoutStatus:
        """Query real-time status of transaction via check-transaction-2 API."""
        if not self.merchant_id or not self.api_key:
            return "pending"

        req_time = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        raw_hash_str = f"{req_time}{self.merchant_id}{provider_ref}"
        signature = compute_aba_hash(raw_hash_str, self.api_key)

        payload = {
            "req_time": req_time,
            "merchant_id": self.merchant_id,
            "tran_id": provider_ref,
            "hash": signature,
        }

        endpoint = f"{self.base_url}/api/payment-gateway/v1/payments/check-transaction-2"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(endpoint, json=payload)
                if res.status_code == 200:
                    body = res.json()
                    data = body.get("data") or {}
                    payment_status = str(data.get("payment_status", "")).upper()
                    payment_code = data.get("payment_status_code")

                    if payment_status == "APPROVED" or payment_code == 0:
                        return "paid"
                    if (
                        payment_status in ("REFUNDED", "CANCELLED", "FAILED", "EXPIRED")
                        or payment_code in (2, 3, 4)
                    ):
                        return "expired"
                    return "pending"
        except Exception as e:
            logger.warning("ABA PayWay check-transaction-2 error: %s", e)

        return "pending"
