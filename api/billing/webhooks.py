"""Stripe webhook handler (`POST /api/billing/webhooks/stripe`)."""

from __future__ import annotations

import stripe
from fastapi import HTTPException, Request

from api.billing.service import (
    handle_stripe_checkout_completed,
    handle_stripe_checkout_expired,
    record_stripe_event_once,
)
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

    if not record_stripe_event_once(event_id, event_type):
        return {"status": "duplicate_ignored"}

    data_obj = (event.get("data") or {}).get("object") or {}

    if event_type == "checkout.session.completed":
        if data_obj.get("payment_status") == "paid":
            provider_ref = str(data_obj.get("id") or "")
            metadata = data_obj.get("metadata") or {}
            amount_total = data_obj.get("amount_total")
            if provider_ref:
                handle_stripe_checkout_completed(
                    provider_ref=provider_ref,
                    metadata=metadata,
                    amount_total=int(amount_total) if amount_total is not None else None,
                )
    elif event_type == "checkout.session.expired":
        provider_ref = str(data_obj.get("id") or "")
        if provider_ref:
            handle_stripe_checkout_expired(provider_ref=provider_ref)

    return {"status": "ok"}

