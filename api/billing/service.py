"""Billing service: Direct Individual Bakong KHQR orders, NBC verification, atomic fulfillment, and quotas."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from api.billing.bakong_client import BakongOfficialClient, BakongVerificationResult
from api.billing.khqr import (
    CurrencyCode,
    build_individual_khqr,
    decode_and_validate_khqr,
    generate_bill_number,
)
from api.billing.plans import PLANS, PlanId
from api.config import settings
from api.db import get_supabase_client

logger = logging.getLogger("proofit.billing")

CheckoutStatusLiteral = Literal["unpaid", "paid", "expired"]


class UsageBucket(BaseModel):
    used: int
    limit: int | None


class UsageSummary(BaseModel):
    analysis: UsageBucket
    rewrite: UsageBucket


class SubscriptionOut(BaseModel):
    plan_id: PlanId
    active_until: datetime | None = None
    usage: UsageSummary


class CheckoutCreateIn(BaseModel):
    plan_id: str = "pass"


class CheckoutCreatedOut(BaseModel):
    session_id: str
    bill_number: str
    amount_minor: int
    amount_cents: int
    currency: CurrencyCode
    recipient_name: str
    recipient_bakong_id: str
    qr_payload: str
    qr_md5: str
    status: CheckoutStatusLiteral = "unpaid"
    expires_at: datetime


class CheckoutStatusOut(BaseModel):
    session_id: str
    plan_id: str
    bill_number: str
    amount_minor: int
    amount_cents: int
    currency: CurrencyCode
    recipient_name: str
    qr_payload: str
    qr_md5: str
    status: CheckoutStatusLiteral
    expires_at: datetime
    paid_at: datetime | None = None
    active_until: datetime | None = None
    nbc_transaction_hash: str | None = None
    verification_error: str | None = None
    verification_message: str | None = None


@dataclass
class CheckoutSessionRecord:
    id: str
    user_id: str
    plan_id: Literal["pass"]
    bill_number: str
    amount_minor: int
    currency: CurrencyCode
    recipient_bakong_id: str
    qr_payload: str
    qr_md5: str
    status: CheckoutStatusLiteral = "unpaid"
    nbc_transaction_hash: str | None = None
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(seconds=300)
    )
    paid_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SubscriptionRecord:
    id: str
    user_id: str
    plan_id: Literal["pass", "campus"]
    current_period_start: datetime
    current_period_end: datetime
    checkout_session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class UsageEventRecord:
    user_id: str
    kind: Literal["analysis", "rewrite"]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# In-memory store and synchronization locks
_fulfillment_lock = threading.RLock()
_checkout_sessions: dict[str, CheckoutSessionRecord] = {}
_subscriptions: list[SubscriptionRecord] = []
_usage_events: list[UsageEventRecord] = []
_last_recheck_monotonic: dict[str, float] = {}

RECHECK_MIN_INTERVAL_SECONDS = 2.0


def reset_billing_memory() -> None:
    """Clear in-memory billing state (used by test fixtures)."""
    with _fulfillment_lock:
        _checkout_sessions.clear()
        _subscriptions.clear()
        _usage_events.clear()
        _last_recheck_monotonic.clear()


def set_test_subscription(
    user_id: str,
    plan_id: Literal["pass", "campus"] = "pass",
    active_until: datetime | None = None,
    active_from: datetime | None = None,
    checkout_session_id: str | None = None,
) -> SubscriptionRecord:
    """Helper to seed an active subscription in memory for tests."""
    now = datetime.now(UTC)
    rec = SubscriptionRecord(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_id=plan_id,
        current_period_start=active_from or now,
        current_period_end=active_until or (now + timedelta(days=30)),
        checkout_session_id=checkout_session_id,
    )
    with _fulfillment_lock:
        _subscriptions.append(rec)
    return rec


def get_test_subscriptions_for_user(user_id: str) -> list[SubscriptionRecord]:
    with _fulfillment_lock:
        return [s for s in _subscriptions if s.user_id == user_id]


def _get_active_subscription_for_user(user_id: str) -> SubscriptionRecord | None:
    now = datetime.now(UTC)
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("subscriptions")
                .select("*")
                .eq("user_id", user_id)
                .gt("current_period_end", now.isoformat())
                .order("current_period_end", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                return SubscriptionRecord(
                    id=str(row["id"]),
                    user_id=str(row["user_id"]),
                    plan_id=row["plan_id"],
                    current_period_start=datetime.fromisoformat(row["current_period_start"]),
                    current_period_end=datetime.fromisoformat(row["current_period_end"]),
                    checkout_session_id=row.get("checkout_session_id"),
                )
        except Exception:
            pass

    with _fulfillment_lock:
        active = [
            s
            for s in _subscriptions
            if s.user_id == user_id and s.current_period_end > now
        ]
        if not active:
            return None
        active.sort(key=lambda s: s.current_period_end, reverse=True)
        return active[0]


def _count_usage(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
    since: datetime,
) -> int:
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("usage_events")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("kind", kind)
                .gte("created_at", since.isoformat())
                .execute()
            )
            if res.count is not None:
                return int(res.count)
        except Exception:
            pass

    with _fulfillment_lock:
        return sum(
            1
            for ev in _usage_events
            if ev.user_id == user_id and ev.kind == kind and ev.created_at >= since
        )


def record_usage_event(
    user_id: str,
    kind: Literal["analysis", "rewrite"],
) -> None:
    """Record a usage event after a successful analysis or rewrite."""
    now = datetime.now(UTC)
    with _fulfillment_lock:
        _usage_events.append(UsageEventRecord(user_id=user_id, kind=kind, created_at=now))
    client = get_supabase_client()
    if client is not None:
        with contextlib.suppress(Exception):
            client.table("usage_events").insert(
                {
                    "user_id": user_id,
                    "kind": kind,
                    "created_at": now.isoformat(),
                }
            ).execute()


def get_subscription_summary(user_id: str) -> SubscriptionOut:
    """Return the user's active plan, expiry, and usage in the current window."""
    now = datetime.now(UTC)

    from api.auth import get_user_email
    from api.config import is_admin_email

    user_email = get_user_email(user_id)
    if is_admin_email(user_email):
        analysis_used = _count_usage(user_id, "analysis", now - timedelta(days=365))
        rewrite_used = _count_usage(user_id, "rewrite", now - timedelta(days=365))
        return SubscriptionOut(
            plan_id="campus",
            active_until=None,
            usage=UsageSummary(
                analysis=UsageBucket(used=analysis_used, limit=None),
                rewrite=UsageBucket(used=rewrite_used, limit=None),
            ),
        )

    active_sub = _get_active_subscription_for_user(user_id)

    if active_sub is not None:
        plan_id: PlanId = active_sub.plan_id
        active_until = active_sub.current_period_end
        window_start = active_sub.current_period_start
    else:
        plan_id = "free"
        active_until = None
        window_start = now - timedelta(days=30)

    plan_def = PLANS[plan_id]
    analysis_used = _count_usage(user_id, "analysis", window_start)
    rewrite_used = _count_usage(user_id, "rewrite", window_start)

    return SubscriptionOut(
        plan_id=plan_id,
        active_until=active_until,
        usage=UsageSummary(
            analysis=UsageBucket(
                used=analysis_used,
                limit=plan_def.limits.analyses,
            ),
            rewrite=UsageBucket(
                used=rewrite_used,
                limit=plan_def.limits.rewrites,
            ),
        ),
    )


def _save_checkout_session(rec: CheckoutSessionRecord) -> None:
    with _fulfillment_lock:
        _checkout_sessions[rec.id] = rec
    client = get_supabase_client()
    if client is not None:
        with contextlib.suppress(Exception):
            client.table("checkout_sessions").upsert(
                {
                    "id": rec.id,
                    "user_id": rec.user_id,
                    "plan_id": rec.plan_id,
                    "bill_number": rec.bill_number,
                    "amount_minor": rec.amount_minor,
                    "currency": rec.currency,
                    "recipient_bakong_id": rec.recipient_bakong_id,
                    "qr_payload": rec.qr_payload,
                    "qr_md5": rec.qr_md5,
                    "status": rec.status,
                    "nbc_transaction_hash": rec.nbc_transaction_hash,
                    "expires_at": rec.expires_at.isoformat(),
                    "paid_at": rec.paid_at.isoformat() if rec.paid_at else None,
                    "created_at": rec.created_at.isoformat(),
                }
            ).execute()


def _row_to_checkout_session(row: dict) -> CheckoutSessionRecord:
    raw_status = str(row.get("status", "unpaid"))
    if raw_status == "pending":
        status_val: CheckoutStatusLiteral = "unpaid"
    elif raw_status in ("paid", "expired", "unpaid"):
        status_val = raw_status  # type: ignore[assignment]
    else:
        status_val = "expired"

    amount_minor = int(row.get("amount_minor") or row.get("amount_cents") or 500)
    currency_val: CurrencyCode = "KHR" if row.get("currency") == "KHR" else "USD"

    rec = CheckoutSessionRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        plan_id="pass",
        bill_number=str(row.get("bill_number") or row["id"]),
        amount_minor=amount_minor,
        currency=currency_val,
        recipient_bakong_id=str(row.get("recipient_bakong_id") or settings.bakong_account_id),
        qr_payload=str(row.get("qr_payload") or ""),
        qr_md5=str(row.get("qr_md5") or ""),
        status=status_val,
        nbc_transaction_hash=row.get("nbc_transaction_hash"),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        paid_at=datetime.fromisoformat(row["paid_at"]) if row.get("paid_at") else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )
    with _fulfillment_lock:
        _checkout_sessions[rec.id] = rec
    return rec


def _load_checkout_session_by_id(session_id: str) -> CheckoutSessionRecord | None:
    with _fulfillment_lock:
        if session_id in _checkout_sessions:
            return _checkout_sessions[session_id]
    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("checkout_sessions")
                .select("*")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return _row_to_checkout_session(res.data[0])
        except Exception:
            pass
    return None


def _is_tx_hash_used_by_other_session(tx_hash: str, current_session_id: str) -> bool:
    """Check whether `tx_hash` is already bound to a different checkout session."""
    clean_hash = tx_hash.strip()
    with _fulfillment_lock:
        for sess in _checkout_sessions.values():
            if sess.id != current_session_id and sess.nbc_transaction_hash == clean_hash:
                return True

    client = get_supabase_client()
    if client is not None:
        try:
            res = (
                client.table("checkout_sessions")
                .select("id")
                .eq("nbc_transaction_hash", clean_hash)
                .limit(1)
                .execute()
            )
            if res.data and str(res.data[0]["id"]) != current_session_id:
                return True
        except Exception:
            pass
    return False


def grant_plan(session: CheckoutSessionRecord) -> SubscriptionRecord:
    """Idempotently grant a 30-day pass for a confirmed paid checkout session.

    If a subscription already exists for `session.id`, returns it without
    creating a duplicate. If the user already has an active pass, extends
    from `max(now, latest active current_period_end)` + 30 days.
    """
    with _fulfillment_lock:
        for existing in _subscriptions:
            if existing.checkout_session_id == session.id:
                return existing

        client = get_supabase_client()
        if client is not None:
            try:
                res = (
                    client.table("subscriptions")
                    .select("*")
                    .eq("checkout_session_id", session.id)
                    .limit(1)
                    .execute()
                )
                if res.data:
                    row = res.data[0]
                    found = SubscriptionRecord(
                        id=str(row["id"]),
                        user_id=str(row["user_id"]),
                        plan_id=row["plan_id"],
                        current_period_start=datetime.fromisoformat(row["current_period_start"]),
                        current_period_end=datetime.fromisoformat(row["current_period_end"]),
                        checkout_session_id=str(row["checkout_session_id"]),
                    )
                    _subscriptions.append(found)
                    return found
            except Exception:
                pass

        now = datetime.now(UTC)
        latest_active = _get_active_subscription_for_user(session.user_id)
        if latest_active is not None and latest_active.current_period_end > now:
            period_start = latest_active.current_period_end
        else:
            period_start = now

        period_days = PLANS[session.plan_id].period_days
        period_end = period_start + timedelta(days=period_days)

        sub = SubscriptionRecord(
            id=str(uuid.uuid4()),
            user_id=session.user_id,
            plan_id=session.plan_id,
            current_period_start=period_start,
            current_period_end=period_end,
            checkout_session_id=session.id,
            created_at=now,
        )
        _subscriptions.append(sub)

        if client is not None:
            with contextlib.suppress(Exception):
                client.table("subscriptions").insert(
                    {
                        "id": sub.id,
                        "user_id": sub.user_id,
                        "plan_id": sub.plan_id,
                        "current_period_start": sub.current_period_start.isoformat(),
                        "current_period_end": sub.current_period_end.isoformat(),
                        "checkout_session_id": sub.checkout_session_id,
                        "created_at": sub.created_at.isoformat(),
                    }
                ).execute()

        return sub


def confirm_and_grant(
    rec: CheckoutSessionRecord,
    nbc_tx_hash: str,
) -> tuple[bool, str | None, str | None]:
    """Atomically transition `unpaid -> paid`, bind unique `nbc_tx_hash`, and grant Pass."""
    with _fulfillment_lock:
        if _is_tx_hash_used_by_other_session(nbc_tx_hash, rec.id):
            logger.error(
                "bakong_replay_rejected session_id=%s tx_hash=%s",
                rec.id,
                nbc_tx_hash,
            )
            return (
                False,
                "duplicate_transaction_hash",
                "This Bakong transaction has already been applied to another order.",
            )

        now = datetime.now(UTC)
        if rec.status == "paid":
            grant_plan(rec)
            return (True, None, None)

        rec.status = "paid"
        rec.paid_at = rec.paid_at or now
        rec.nbc_transaction_hash = nbc_tx_hash
        _save_checkout_session(rec)
        grant_plan(rec)
        return (True, None, None)


def create_checkout(
    user_id: str,
    user_email: str,  # noqa: ARG001
    plan_id: str,
) -> CheckoutCreatedOut:
    """Create a new Direct Individual Bakong KHQR order for `pass`."""
    if plan_id != "pass":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_plan",
                "message": "Only the 'pass' plan can be purchased via self-serve checkout.",
            },
        )

    base_url = (settings.bakong_api_base_url or "").strip().rstrip("/")
    if base_url == "https://api-bakong.nbc.gov.kh" and not settings.bakong_live_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "live_checkout_disabled",
                "message": (
                    "Live Bakong KHQR checkout is currently disabled pending operator "
                    "activation (BAKONG_LIVE_ENABLED=false)."
                ),
            },
        )

    recipient_id = (settings.bakong_account_id or "").strip()
    if not recipient_id or "@" not in recipient_id:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "bakong_not_configured",
                "message": "Bakong receiving account ID is not configured on the server.",
            },
        )

    plan_def = PLANS["pass"]
    assert plan_def.price_cents is not None
    amount_minor = int(plan_def.price_cents)
    currency: CurrencyCode = "KHR" if plan_def.currency == "KHR" else "USD"

    expiry_sec = max(60, min(600, int(settings.khqr_expiry_seconds)))
    now = datetime.now(UTC)
    bill_number = generate_bill_number("PASS")

    generated = build_individual_khqr(
        bakong_account_id=recipient_id,
        account_information=settings.bakong_account_information,
        acquiring_bank=settings.bakong_acquiring_bank,
        merchant_name=settings.bakong_merchant_name,
        merchant_city=settings.bakong_merchant_city,
        amount_minor=amount_minor,
        currency=currency,
        bill_number=bill_number,
        created_at=now,
        expiry_seconds=expiry_sec,
    )

    expires_at = datetime.fromtimestamp(generated.expires_at_ms / 1000.0, tz=UTC)
    session_id = str(uuid.uuid4())

    rec = CheckoutSessionRecord(
        id=session_id,
        user_id=user_id,
        plan_id="pass",
        bill_number=generated.bill_number,
        amount_minor=generated.amount_minor,
        currency=generated.currency,
        recipient_bakong_id=generated.recipient_bakong_id,
        qr_payload=generated.qr_payload,
        qr_md5=generated.qr_md5,
        status="unpaid",
        expires_at=expires_at,
        created_at=now,
    )
    _save_checkout_session(rec)

    return CheckoutCreatedOut(
        session_id=rec.id,
        bill_number=rec.bill_number,
        amount_minor=rec.amount_minor,
        amount_cents=rec.amount_minor,
        currency=rec.currency,
        recipient_name=settings.bakong_merchant_name,
        recipient_bakong_id=rec.recipient_bakong_id,
        qr_payload=rec.qr_payload,
        qr_md5=rec.qr_md5,
        status=rec.status,
        expires_at=rec.expires_at,
    )


def _expected_recipients_for_session(rec: CheckoutSessionRecord) -> set[str]:
    recipients = {rec.recipient_bakong_id}
    if settings.bakong_account_information and settings.bakong_account_information.strip():
        recipients.add(settings.bakong_account_information.strip())
    if rec.qr_payload:
        with contextlib.suppress(Exception):
            decoded = decode_and_validate_khqr(rec.qr_payload)
            recipients.add(decoded.bakong_account_id)
            if decoded.account_information:
                recipients.add(decoded.account_information)
    return recipients


def _verify_session_with_nbc(rec: CheckoutSessionRecord) -> BakongVerificationResult:
    client = BakongOfficialClient()
    return client.check_transaction_by_md5(
        qr_md5=rec.qr_md5,
        expected_recipients=_expected_recipients_for_session(rec),
        expected_amount_minor=rec.amount_minor,
        expected_currency=rec.currency,
    )


def _refresh_and_serialize_session(
    rec: CheckoutSessionRecord,
    *,
    force_nbc_check: bool = False,
) -> CheckoutStatusOut:
    with _fulfillment_lock:
        now = datetime.now(UTC)
        verification_error: str | None = None
        verification_message: str | None = None

        if rec.status == "paid":
            active_sub = _get_active_subscription_for_user(rec.user_id)
            return CheckoutStatusOut(
                session_id=rec.id,
                plan_id=rec.plan_id,
                bill_number=rec.bill_number,
                amount_minor=rec.amount_minor,
                amount_cents=rec.amount_minor,
                currency=rec.currency,
                recipient_name=settings.bakong_merchant_name,
                qr_payload=rec.qr_payload,
                qr_md5=rec.qr_md5,
                status="paid",
                expires_at=rec.expires_at,
                paid_at=rec.paid_at,
                active_until=active_sub.current_period_end if active_sub else None,
                nbc_transaction_hash=rec.nbc_transaction_hash,
            )

        is_past_deadline = now >= rec.expires_at

        if rec.status == "unpaid" and not is_past_deadline:
            nbc_res = _verify_session_with_nbc(rec)
            if nbc_res.outcome == "verified_paid" and nbc_res.nbc_transaction_hash:
                ok, err_code, err_msg = confirm_and_grant(rec, nbc_res.nbc_transaction_hash)
                if not ok:
                    verification_error = err_code
                    verification_message = err_msg
            elif nbc_res.outcome in ("auth_error", "transient_error", "manual_review"):
                verification_error = nbc_res.error_code
                verification_message = nbc_res.error_message

        elif rec.status == "unpaid" and is_past_deadline:
            # Deadline reached: transition to expired, run one final check for late payment reconciliation
            rec.status = "expired"
            nbc_res = _verify_session_with_nbc(rec)
            if nbc_res.outcome == "verified_paid" and nbc_res.nbc_transaction_hash:
                if not _is_tx_hash_used_by_other_session(nbc_res.nbc_transaction_hash, rec.id):
                    rec.nbc_transaction_hash = nbc_res.nbc_transaction_hash
                logger.warning(
                    "bakong_late_payment_reconciliation_required session_id=%s bill_number=%s tx_hash=%s",
                    rec.id,
                    rec.bill_number,
                    nbc_res.nbc_transaction_hash,
                )
                verification_error = "late_payment_reconciliation_required"
                verification_message = (
                    "Payment was detected after QR expiration and has been recorded for manual "
                    "reconciliation. Please contact support with your bill number; do not pay again."
                )
            else:
                verification_message = (
                    "Payment not confirmed — check your bank transaction history before paying again."
                )
            _save_checkout_session(rec)

        elif rec.status == "expired":
            if rec.nbc_transaction_hash:
                verification_error = "late_payment_reconciliation_required"
                verification_message = (
                    "Payment was detected after QR expiration and has been recorded for manual "
                    "reconciliation. Please contact support with your bill number; do not pay again."
                )
            elif force_nbc_check:
                nbc_res = _verify_session_with_nbc(rec)
                if nbc_res.outcome == "verified_paid" and nbc_res.nbc_transaction_hash:
                    if not _is_tx_hash_used_by_other_session(nbc_res.nbc_transaction_hash, rec.id):
                        rec.nbc_transaction_hash = nbc_res.nbc_transaction_hash
                        _save_checkout_session(rec)
                    logger.warning(
                        "bakong_late_payment_reconciliation_required session_id=%s bill_number=%s tx_hash=%s",
                        rec.id,
                        rec.bill_number,
                        nbc_res.nbc_transaction_hash,
                    )
                    verification_error = "late_payment_reconciliation_required"
                    verification_message = (
                        "Payment was detected after QR expiration and has been recorded for manual "
                        "reconciliation. Please contact support with your bill number; do not pay again."
                    )
                elif nbc_res.outcome in ("auth_error", "transient_error", "manual_review"):
                    verification_error = nbc_res.error_code
                    verification_message = nbc_res.error_message
                else:
                    verification_message = (
                        "Payment not confirmed — check your bank transaction history before paying again."
                    )
            else:
                verification_message = (
                    "Payment not confirmed — check your bank transaction history before paying again."
                )

        active_sub = _get_active_subscription_for_user(rec.user_id)
        return CheckoutStatusOut(
            session_id=rec.id,
            plan_id=rec.plan_id,
            bill_number=rec.bill_number,
            amount_minor=rec.amount_minor,
            amount_cents=rec.amount_minor,
            currency=rec.currency,
            recipient_name=settings.bakong_merchant_name,
            qr_payload=rec.qr_payload,
            qr_md5=rec.qr_md5,
            status=rec.status,
            expires_at=rec.expires_at,
            paid_at=rec.paid_at,
            active_until=active_sub.current_period_end if active_sub else None,
            nbc_transaction_hash=rec.nbc_transaction_hash,
            verification_error=verification_error,
            verification_message=verification_message,
        )


def get_checkout_status(session_id: str, user_id: str) -> CheckoutStatusOut:
    """Return checkout status for the authenticated order owner, querying NBC if due."""
    rec = _load_checkout_session_by_id(session_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "checkout_not_found", "message": "Checkout session not found."},
        )
    return _refresh_and_serialize_session(rec, force_nbc_check=False)


def recheck_checkout_status(session_id: str, user_id: str) -> CheckoutStatusOut:
    """Rate-limited explicit server verification / reconciliation request."""
    rec = _load_checkout_session_by_id(session_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "checkout_not_found", "message": "Checkout session not found."},
        )

    now_mono = time.monotonic()
    with _fulfillment_lock:
        last_mono = _last_recheck_monotonic.get(session_id)
        if last_mono is not None and (now_mono - last_mono) < RECHECK_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limited",
                    "message": "Please wait a few seconds before rechecking payment status.",
                },
            )
        _last_recheck_monotonic[session_id] = now_mono

    return _refresh_and_serialize_session(rec, force_nbc_check=True)
