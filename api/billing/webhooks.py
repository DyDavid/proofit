"""Stripe webhook handler (`POST /api/billing/webhooks/stripe`)."""

from __future__ import annotations

import stripe
from fastapi import HTTPException, Request

from api.billing.service import process_stripe_event
from api.config import settings


async def process_stripe_webhook(request: Request) -> dict[str, str]:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = (settings.stripe_webhook_secret or "").strip()

    if not sig_header or not webhook_secret:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_webhook_signature",
                "message": "Missing Stripe webhook signature or webhook secret.",
            },
        )

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_webhook_signature",
                "message": "Invalid Stripe webhook signature.",
            },
        ) from exc

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if not event_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_webhook_event", "message": "Missing event ID."},
        )

    data_obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(data_obj, dict):
        raise HTTPException(400, detail="Invalid payment event")
    if not process_stripe_event(event_id, event_type, data_obj):
        return {"status": "duplicate_ignored"}
    return {"status": "ok"}

