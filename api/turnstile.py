"""Cloudflare Turnstile server-side token verification (Phase 2).

Protects the guest analysis endpoint when `TURNSTILE_SECRET_KEY` is configured.
"""

from __future__ import annotations

import logging
import os

import httpx

from api.config import settings
from api.errors import ApiError

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def get_turnstile_secret() -> str | None:
    secret = settings.turnstile_secret_key or os.getenv("TURNSTILE_SECRET_KEY")
    if not secret or not secret.strip() or "REPLACE_ME" in secret:
        return None
    return secret.strip()


async def verify_turnstile_token(token: str | None, remote_ip: str | None = None) -> None:
    """Verify a Cloudflare Turnstile token if `TURNSTILE_SECRET_KEY` is set.

    Raises `ApiError(400, "CAPTCHA_FAILED")` when the secret is configured and the
    token is missing, invalid, or rejected by Cloudflare.
    """
    secret = get_turnstile_secret()
    if not secret:
        return

    if not token or not token.strip():
        raise ApiError(
            status_code=400,
            code="CAPTCHA_FAILED",
            message="Security check required. Please complete the CAPTCHA and try again.",
        )

    payload: dict[str, str] = {
        "secret": secret,
        "response": token.strip(),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(TURNSTILE_VERIFY_URL, data=payload)
            res.raise_for_status()
            body = res.json()
    except Exception as err:
        logger.warning("Turnstile siteverify request failed: %s", err)
        raise ApiError(
            status_code=400,
            code="CAPTCHA_FAILED",
            message="Could not verify security check. Please try again.",
        ) from err

    if not isinstance(body, dict) or body.get("success") is not True:
        logger.info("Turnstile verification rejected: %s", body.get("error-codes") if isinstance(body, dict) else body)
        raise ApiError(
            status_code=400,
            code="CAPTCHA_FAILED",
            message="Security verification failed. Please refresh and try again.",
        )

