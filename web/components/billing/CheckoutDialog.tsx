"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
  createCheckoutSession,
  getCheckoutSession,
  notifySubscriptionUpdated,
  recheckCheckoutSession,
  type CheckoutCreatedResponse,
  type PlanDefinition,
} from "@/lib/billing/api";
import { KhqrCodeSvg } from "@/components/billing/KhqrCodeSvg";

type DialogStep = "review" | "waiting" | "success" | "expired" | "error";

export interface CheckoutDialogProps {
  open: boolean;
  plan: PlanDefinition;
  isExtending?: boolean;
  onClose: () => void;
  onCompleted: () => void;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "30 days from today";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "30 days from today";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function remainingSeconds(expiresAtIso: string | null | undefined): number {
  if (!expiresAtIso) return 0;
  return Math.max(
    0,
    Math.floor((new Date(expiresAtIso).getTime() - Date.now()) / 1000),
  );
}

function formatSeconds(totalSec: number): string {
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function formatMinorAmount(amountMinor: number, currency: string): string {
  if (currency === "KHR") return amountMinor.toLocaleString("en-US");
  return (amountMinor / 100).toFixed(2);
}

const FOCUSABLE =
  'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

export function CheckoutDialog({
  open,
  plan,
  isExtending = false,
  onClose,
  onCompleted,
}: CheckoutDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const [mounted, setMounted] = useState(false);
  const [step, setStep] = useState<DialogStep>("review");
  const [inFlight, setInFlight] = useState<boolean>(false);
  const [session, setSession] = useState<CheckoutCreatedResponse | null>(null);
  const [activeUntil, setActiveUntil] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [verificationCode, setVerificationCode] = useState<string | null>(null);
  const [verificationMsg, setVerificationMsg] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number>(300);
  const [totalSeconds, setTotalSeconds] = useState<number>(300);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (open) {
      setStep("review");
      setInFlight(false);
      setSession(null);
      setActiveUntil(null);
      setErrorMsg(null);
      setVerificationCode(null);
      setVerificationMsg(null);
      setSecondsLeft(300);
      setCopied(false);
    }
  }, [open]);

  // Lock page scroll while the dialog is open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Focus trap + Escape handling
  useEffect(() => {
    if (!open) return;
    const container = dialogRef.current;
    container?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (!inFlight) {
          e.preventDefault();
          onClose();
        }
        return;
      }
      if (e.key === "Tab" && container) {
        const nodes = Array.from(
          container.querySelectorAll<HTMLElement>(FOCUSABLE),
        );
        if (nodes.length === 0) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, inFlight, step, onClose]);

  // Countdown + poll our own FastAPI status endpoint while the QR is live
  useEffect(() => {
    if (!open || step !== "waiting" || !session) return;
    const activeSessionId = session.session_id;
    const activeExpiresAt = session.expires_at;
    let cancelled = false;

    async function pollOnce() {
      try {
        const st = await getCheckoutSession(activeSessionId);
        if (cancelled) return;
        setVerificationCode(st.verification_error ?? null);
        setVerificationMsg(st.verification_message ?? null);
        if (st.status === "paid") {
          setActiveUntil(st.active_until);
          setStep("success");
          notifySubscriptionUpdated();
          onCompleted();
        } else if (st.status === "expired") {
          setStep("expired");
        }
      } catch {
        if (!cancelled) {
          setVerificationCode("transient_network_error");
          setVerificationMsg("Connection hiccup — still checking…");
        }
      }
    }

    setSecondsLeft(remainingSeconds(activeExpiresAt));
    const timer = window.setInterval(() => {
      const rem = remainingSeconds(activeExpiresAt);
      setSecondsLeft(rem);
      if (rem === 0) {
        window.clearInterval(timer);
        void pollOnce().then(() => {
          if (!cancelled) {
            setStep((prev) => (prev === "waiting" ? "expired" : prev));
          }
        });
      }
    }, 1000);

    const poller = window.setInterval(() => void pollOnce(), 3500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearInterval(poller);
    };
  }, [open, step, session, onCompleted]);

  if (!open || !mounted) return null;

  async function handleStartCheckout() {
    setInFlight(true);
    setErrorMsg(null);
    setVerificationCode(null);
    setVerificationMsg(null);
    try {
      const created = await createCheckoutSession("pass");
      const secs = remainingSeconds(created.expires_at) || 300;
      setSession(created);
      setTotalSeconds(secs);
      setSecondsLeft(secs);
      setStep("waiting");
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Could not create a Bakong KHQR order. Please try again.",
      );
      setStep("error");
    } finally {
      setInFlight(false);
    }
  }

  async function handleManualRecheck() {
    if (!session) return;
    setInFlight(true);
    try {
      const st = await recheckCheckoutSession(session.session_id);
      setVerificationCode(st.verification_error ?? null);
      setVerificationMsg(st.verification_message ?? null);
      if (st.status === "paid") {
        setActiveUntil(st.active_until);
        setStep("success");
        notifySubscriptionUpdated();
        onCompleted();
      } else if (st.status === "expired") {
        setStep("expired");
      }
    } catch (err) {
      setVerificationMsg(
        err instanceof Error ? err.message : "Still verifying payment…",
      );
    } finally {
      setInFlight(false);
    }
  }

  async function handleCopyBill() {
    if (!session?.bill_number || !navigator?.clipboard) return;
    try {
      await navigator.clipboard.writeText(session.bill_number);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard failure
    }
  }

  const amountText = session
    ? `$${formatMinorAmount(session.amount_minor, session.currency)} ${session.currency}`
    : "$5.00 USD";
  const progressPct =
    totalSeconds > 0 ? Math.round((secondsLeft / totalSeconds) * 100) : 0;
  const lowTime = secondsLeft <= 60;

  function renderStatus() {
    if (verificationCode === "bakong_token_expired_or_invalid") {
      return (
        <div
          role="status"
          data-testid="checkout-verification-status"
          className="flex items-start gap-2.5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3.5 py-3 text-xs text-ink"
        >
          <span aria-hidden className="mt-0.5 text-amber-600">
            ⚠
          </span>
          <div>
            <p className="font-semibold">Automatic confirmation is offline</p>
            <p className="mt-0.5 text-ink-2">
              We can&apos;t confirm payments automatically right now. Please
              don&apos;t pay yet — contact support if you already did, and keep
              your bill number.
            </p>
          </div>
        </div>
      );
    }
    if (verificationCode) {
      return (
        <div
          role="status"
          data-testid="checkout-verification-status"
          className="flex items-start gap-2.5 rounded-xl border border-rule bg-paper-2 px-3.5 py-3 text-xs text-ink-2"
        >
          <span className="mt-1 inline-block h-2 w-2 shrink-0 animate-pulse rounded-full bg-amber-500" />
          <span>{verificationMsg || "Still verifying…"}</span>
        </div>
      );
    }
    return (
      <div
        role="status"
        data-testid="checkout-verification-status"
        className="flex items-center gap-2.5 rounded-xl border border-rule bg-paper-2 px-3.5 py-3 text-xs font-medium text-ink-2"
      >
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
        </span>
        <span>Waiting for payment — this updates automatically.</span>
      </div>
    );
  }

  const dialog = (
    <div
      className="fixed inset-0 z-[100] overflow-y-auto bg-ink/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget && !inFlight) onClose();
      }}
    >
      <div
        className="flex min-h-full items-center justify-center p-4 sm:p-6"
        onClick={(e) => {
          if (e.target === e.currentTarget && !inFlight) onClose();
        }}
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="checkout-dialog-title"
          className={`relative w-full rounded-2xl border border-rule bg-surface-raised shadow-2xl ${
            step === "waiting" ? "max-w-3xl" : "max-w-md"
          }`}
        >
          {/* Close (X) */}
          <button
            type="button"
            aria-label="Close checkout"
            disabled={inFlight}
            onClick={onClose}
            className="absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full text-ink-3 hover:bg-paper-2 hover:text-ink disabled:opacity-50"
          >
            ✕
          </button>

          {step === "review" && (
            <div className="p-6">
              <h2
                id="checkout-dialog-title"
                className="pr-8 font-serif text-xl font-bold text-ink"
              >
                {isExtending ? "Extend Job Hunt Pass" : "Get Job Hunt Pass"}
              </h2>
              <p className="mt-1 text-sm text-ink-2">
                One-time 30-day pass. Does not auto-renew.
              </p>

              <dl className="mt-5 divide-y divide-rule rounded-xl border border-rule bg-paper/60 px-4 text-sm">
                <div className="flex items-center justify-between gap-4 py-3">
                  <dt className="text-ink-3">Plan</dt>
                  <dd className="text-right font-medium text-ink">
                    {plan.name}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4 py-3">
                  <dt className="text-ink-3">Duration</dt>
                  <dd className="text-right font-medium text-ink">
                    {plan.period_days} days
                    {isExtending ? " (added to current pass)" : ""}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4 py-3">
                  <dt className="text-ink-3">Included</dt>
                  <dd className="text-right font-medium text-ink">
                    50 analyses · 30 rewrites · 10 resumes
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4 py-3">
                  <dt className="text-ink-3">Pay with</dt>
                  <dd className="text-right font-medium text-ink">
                    ABA Mobile / any KHQR bank app
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-4 py-3">
                  <dt className="font-medium text-ink">Total</dt>
                  <dd className="font-serif text-lg font-bold text-ink">
                    $5.00 USD
                  </dd>
                </div>
              </dl>

              <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-xs text-ink">
                <span aria-hidden className="text-amber-600">
                  ⚠
                </span>
                <span>
                  This is a <strong>real bank transfer</strong>. Your QR code
                  will be valid for 5 minutes.
                </span>
              </p>

              <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  disabled={inFlight}
                  onClick={onClose}
                  className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={inFlight}
                  onClick={() => void handleStartCheckout()}
                  data-testid="checkout-continue-btn"
                  className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2 disabled:opacity-50"
                >
                  {inFlight ? "Generating QR…" : "Confirm & show QR code"}
                </button>
              </div>
            </div>
          )}

          {step === "waiting" && session && (
            <div className="grid md:grid-cols-[auto_1fr]">
              {/* Left: QR panel */}
              <div className="flex flex-col items-center justify-center gap-4 rounded-t-2xl border-b border-rule bg-paper/70 p-6 md:rounded-l-2xl md:rounded-tr-none md:border-b-0 md:border-r">
                <KhqrCodeSvg
                  qrPayload={session.qr_payload}
                  recipientName={session.recipient_name}
                  amountDisplay={formatMinorAmount(
                    session.amount_minor,
                    session.currency,
                  )}
                  currency={session.currency}
                  billNumber={session.bill_number}
                />

                {/* Countdown */}
                <div className="w-56">
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="text-ink-3">QR expires in</span>
                    <span
                      data-testid="checkout-countdown"
                      className={`font-mono text-sm font-bold ${
                        lowTime ? "text-red-600" : "text-ink"
                      }`}
                    >
                      {formatSeconds(secondsLeft)}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-track">
                    <div
                      className={`h-full rounded-full transition-[width] duration-1000 ease-linear ${
                        lowTime ? "bg-red-500" : "bg-accent"
                      }`}
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Right: instructions + status */}
              <div className="flex flex-col p-6">
                <h2
                  id="checkout-dialog-title"
                  className="pr-8 font-serif text-xl font-bold text-ink"
                >
                  Scan to pay {amountText}
                </h2>
                <p className="mt-1 text-sm text-ink-2">
                  Real bank transfer to {session.recipient_name}.
                </p>

                <ol className="mt-5 space-y-3 text-sm text-ink">
                  {[
                    "Open ABA Mobile or any KHQR banking app.",
                    "Tap Scan QR and point your camera at the code.",
                    `Check the payee is ${session.recipient_name} and the amount is ${amountText}, then confirm.`,
                  ].map((text, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-tint font-mono text-xs font-bold text-accent">
                        {i + 1}
                      </span>
                      <span className="pt-0.5">{text}</span>
                    </li>
                  ))}
                </ol>

                <dl className="mt-5 divide-y divide-rule rounded-xl border border-rule px-3.5 text-xs">
                  <div className="flex items-center justify-between gap-3 py-2.5">
                    <dt className="text-ink-3">Payee</dt>
                    <dd className="font-medium text-ink">
                      {session.recipient_name}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 py-2.5">
                    <dt className="text-ink-3">Amount</dt>
                    <dd className="font-medium text-ink">{amountText}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 py-2.5">
                    <dt className="text-ink-3">Bill number</dt>
                    <dd className="flex items-center gap-2">
                      <span className="font-mono text-ink">
                        {session.bill_number}
                      </span>
                      <button
                        type="button"
                        onClick={() => void handleCopyBill()}
                        className="rounded px-1.5 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-tint"
                      >
                        {copied ? "Copied" : "Copy"}
                      </button>
                    </dd>
                  </div>
                </dl>

                <div className="mt-4">{renderStatus()}</div>

                <div className="mt-auto flex flex-col-reverse gap-3 pt-5 sm:flex-row sm:justify-between">
                  <button
                    type="button"
                    disabled={inFlight}
                    onClick={onClose}
                    className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={inFlight}
                    onClick={() => void handleManualRecheck()}
                    data-testid="checkout-recheck-btn"
                    className="rounded-lg border border-accent px-4 py-2.5 text-sm font-semibold text-accent hover:bg-accent-tint disabled:opacity-50"
                  >
                    {inFlight ? "Checking…" : "I've paid — check now"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {step === "success" && (
            <div className="p-6 text-center" data-testid="checkout-success-view">
              <div className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-full bg-accent-tint text-xl text-accent">
                ✓
              </div>
              <h2
                id="checkout-dialog-title"
                className="mt-3 font-serif text-xl font-bold text-ink"
              >
                Payment confirmed — Pass activated
              </h2>
              <p className="mt-1 text-sm text-ink-2">
                Active until{" "}
                <span className="font-semibold text-ink">
                  {formatDate(activeUntil)}
                </span>
                . Your 50 analyses and 30 AI rewrites are ready.
              </p>
              <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-center">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2"
                >
                  Close
                </button>
                <Link
                  href="/dashboard"
                  className="rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-ink-2"
                >
                  Go to dashboard ↗
                </Link>
              </div>
            </div>
          )}

          {step === "expired" && (
            <div className="p-6" data-testid="checkout-expired-view">
              <h2
                id="checkout-dialog-title"
                className="pr-8 font-serif text-xl font-bold text-ink"
              >
                QR code expired
              </h2>
              <p className="mt-2 text-sm text-ink-2">
                {verificationMsg ||
                  "Payment not confirmed — check your bank transaction history before paying again."}
              </p>
              {session?.bill_number && (
                <p className="mt-3 rounded-lg bg-paper-2 px-3 py-2 font-mono text-xs text-ink-2">
                  Bill #{session.bill_number}
                </p>
              )}
              <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                {session && (
                  <button
                    type="button"
                    disabled={inFlight}
                    onClick={() => void handleManualRecheck()}
                    className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink hover:bg-paper-2 disabled:opacity-50"
                  >
                    {inFlight ? "Checking…" : "Recheck status"}
                  </button>
                )}
                <button
                  type="button"
                  disabled={inFlight}
                  onClick={() => void handleStartCheckout()}
                  data-testid="checkout-new-qr-btn"
                  className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2 disabled:opacity-50"
                >
                  {inFlight ? "Generating…" : "Generate new QR"}
                </button>
              </div>
            </div>
          )}

          {step === "error" && (
            <div className="p-6">
              <h2
                id="checkout-dialog-title"
                className="pr-8 font-serif text-xl font-bold text-ink"
              >
                Checkout unavailable
              </h2>
              <p className="mt-2 text-sm text-ink-2">
                {errorMsg ?? "Something went wrong starting checkout."}
              </p>
              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setErrorMsg(null);
                    setStep("review");
                  }}
                  className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2"
                >
                  Back
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
