"""Official NBC Bakong Open API client (`/v1/check_transaction_by_md5`).

Strictly communicates only with the two official NBC hosts:
- SIT (development): https://sit-api-bakong.nbc.gov.kh
- Production:        https://api-bakong.nbc.gov.kh

Never uses third-party relays, proxies, or unverified endpoints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from api.billing.khqr import CurrencyCode, parse_amount_to_minor
from api.config import TRUSTED_BAKONG_API_HOSTS, settings

logger = logging.getLogger("proofit.billing.bakong")

VerificationOutcome = Literal[
    "verified_paid",
    "unpaid",
    "auth_error",
    "transient_error",
    "manual_review",
]


@dataclass(frozen=True)
class BakongVerificationResult:
    outcome: VerificationOutcome
    nbc_transaction_hash: str | None = None
    to_account_id: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def _normalize_currency(raw_currency: Any) -> CurrencyCode | None:
    if not isinstance(raw_currency, str):
        return None
    val = raw_currency.strip().upper()
    if val in ("USD", "840"):
        return "USD"
    if val in ("KHR", "116"):
        return "KHR"
    return None


class BakongOfficialClient:
    """Direct HTTP client for official NBC Bakong transaction verification by MD5."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        resolved_base = (
            settings.bakong_api_base_url if base_url is None else base_url
        ).strip().rstrip("/")
        if resolved_base not in TRUSTED_BAKONG_API_HOSTS:
            raise ValueError(
                f"Untrusted Bakong API host {resolved_base!r}. "
                f"Only official NBC hosts {sorted(TRUSTED_BAKONG_API_HOSTS)} are permitted."
            )
        self.base_url = resolved_base
        self.token = (settings.bakong_token if token is None else token or "").strip()
        if self.token.lower().startswith("rbk"):
            raise ValueError(
                "Relay tokens ('rbk...') are prohibited; use an official NBC Bakong token."
            )
        self.timeout_seconds = timeout_seconds

    def check_transaction_by_md5(
        self,
        *,
        qr_md5: str,
        expected_recipients: set[str],
        expected_amount_minor: int,
        expected_currency: CurrencyCode,
    ) -> BakongVerificationResult:
        """Query NBC `POST /v1/check_transaction_by_md5` and validate transaction fields."""
        clean_md5 = qr_md5.strip().lower()
        if len(clean_md5) != 32 or any(c not in "0123456789abcdef" for c in clean_md5):
            raise ValueError(f"Invalid 32-char MD5 hex string: {qr_md5!r}.")

        if not self.token:
            logger.error(
                "bakong_token_expired_or_invalid reason=missing_token base_url=%s",
                self.base_url,
            )
            return BakongVerificationResult(
                outcome="auth_error",
                error_code="bakong_token_expired_or_invalid",
                error_message="Payment verification is currently unavailable; please contact support.",
            )

        url = f"{self.base_url}/v1/check_transaction_by_md5"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, json={"md5": clean_md5}, headers=headers)
        except httpx.RequestError as exc:
            logger.warning(
                "bakong_api_transport_error base_url=%s error=%s",
                self.base_url,
                type(exc).__name__,
            )
            return BakongVerificationResult(
                outcome="transient_error",
                error_code="bakong_unreachable",
                error_message="Still verifying payment with Bakong. Retrying shortly.",
            )

        status_code = response.status_code

        if status_code == 401:
            logger.error(
                "bakong_token_expired_or_invalid http_status=401 base_url=%s "
                "action=renew_bakong_token",
                self.base_url,
            )
            return BakongVerificationResult(
                outcome="auth_error",
                error_code="bakong_token_expired_or_invalid",
                error_message="Payment verification unavailable; contact support.",
            )

        if status_code == 403:
            logger.error(
                "bakong_api_forbidden http_status=403 base_url=%s "
                "hint=check_host_region_or_ip_allowlist",
                self.base_url,
            )
            return BakongVerificationResult(
                outcome="transient_error",
                error_code="bakong_forbidden",
                error_message="Payment verification unavailable from this network region.",
            )

        if status_code == 429 or status_code >= 500:
            logger.warning(
                "bakong_api_transient_http http_status=%d base_url=%s",
                status_code,
                self.base_url,
            )
            return BakongVerificationResult(
                outcome="transient_error",
                error_code="bakong_temporarily_unavailable",
                error_message="Still verifying payment with Bakong. Please wait.",
            )

        try:
            body = response.json()
        except ValueError:
            logger.warning(
                "bakong_api_invalid_json http_status=%d base_url=%s",
                status_code,
                self.base_url,
            )
            return BakongVerificationResult(
                outcome="transient_error",
                error_code="bakong_invalid_response",
                error_message="Still verifying payment with Bakong.",
            )

        if not isinstance(body, dict):
            return BakongVerificationResult(
                outcome="transient_error",
                error_code="bakong_invalid_response",
                error_message="Still verifying payment with Bakong.",
            )

        # Check for NBC token-expired errorCode 6 inside JSON body
        error_code_num = body.get("errorCode")
        if error_code_num == 6:
            logger.error(
                "bakong_token_expired_or_invalid error_code=6 base_url=%s "
                "action=renew_bakong_token",
                self.base_url,
            )
            return BakongVerificationResult(
                outcome="auth_error",
                error_code="bakong_token_expired_or_invalid",
                error_message="Payment verification unavailable; contact support.",
            )

        response_code = body.get("responseCode")
        data = body.get("data")

        # responseCode != 0 or missing data means transaction not found / still unpaid
        if status_code != 200 or response_code != 0 or not data:
            return BakongVerificationResult(outcome="unpaid")

        if not isinstance(data, dict):
            logger.error("bakong_manual_review reason=non_dict_data md5=%s", clean_md5)
            return BakongVerificationResult(
                outcome="manual_review",
                error_code="incomplete_transaction_data",
                error_message="Transaction requires manual verification.",
            )

        tx_hash_raw = data.get("hash")
        to_account_raw = data.get("toAccountId")
        currency_raw = data.get("currency")
        amount_raw = data.get("amount")

        if (
            not isinstance(tx_hash_raw, str)
            or not tx_hash_raw.strip()
            or not isinstance(to_account_raw, str)
            or not to_account_raw.strip()
            or currency_raw is None
            or amount_raw is None
        ):
            logger.error(
                "bakong_manual_review reason=missing_required_fields md5=%s fields=%s",
                clean_md5,
                list(data.keys()),
            )
            return BakongVerificationResult(
                outcome="manual_review",
                error_code="incomplete_transaction_data",
                error_message="Transaction response missing required verification fields; routed for manual review.",
            )

        tx_hash = tx_hash_raw.strip()
        to_account = to_account_raw.strip()
        normalized_currency = _normalize_currency(currency_raw)

        if normalized_currency != expected_currency:
            logger.error(
                "bakong_manual_review reason=currency_mismatch md5=%s got=%r expected=%r",
                clean_md5,
                currency_raw,
                expected_currency,
            )
            return BakongVerificationResult(
                outcome="manual_review",
                nbc_transaction_hash=tx_hash,
                to_account_id=to_account,
                currency=str(currency_raw),
                error_code="payment_currency_mismatch",
                error_message="Payment currency did not match the order; routed for manual review.",
            )

        try:
            paid_minor = parse_amount_to_minor(amount_raw, expected_currency)
        except ValueError:
            logger.error(
                "bakong_manual_review reason=invalid_amount md5=%s amount=%r",
                clean_md5,
                amount_raw,
            )
            return BakongVerificationResult(
                outcome="manual_review",
                nbc_transaction_hash=tx_hash,
                to_account_id=to_account,
                currency=normalized_currency,
                error_code="payment_amount_invalid",
                error_message="Payment amount could not be verified; routed for manual review.",
            )

        if paid_minor != expected_amount_minor:
            logger.error(
                "bakong_manual_review reason=amount_mismatch md5=%s got=%d expected=%d",
                clean_md5,
                paid_minor,
                expected_amount_minor,
            )
            return BakongVerificationResult(
                outcome="manual_review",
                nbc_transaction_hash=tx_hash,
                to_account_id=to_account,
                amount_minor=paid_minor,
                currency=normalized_currency,
                error_code="payment_amount_mismatch",
                error_message="Paid amount did not match order total; routed for manual review.",
            )

        normalized_recipients = {r.strip().lower() for r in expected_recipients if r and r.strip()}
        if to_account.lower() not in normalized_recipients:
            logger.error(
                "bakong_manual_review reason=recipient_mismatch md5=%s got=%r expected=%r",
                clean_md5,
                to_account,
                sorted(normalized_recipients),
            )
            return BakongVerificationResult(
                outcome="manual_review",
                nbc_transaction_hash=tx_hash,
                to_account_id=to_account,
                amount_minor=paid_minor,
                currency=normalized_currency,
                error_code="payment_recipient_mismatch",
                error_message="Payment recipient did not match order; routed for manual review.",
            )

        return BakongVerificationResult(
            outcome="verified_paid",
            nbc_transaction_hash=tx_hash,
            to_account_id=to_account,
            amount_minor=paid_minor,
            currency=normalized_currency,
        )

