"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  createCheckoutSession,
  getCheckoutSession,
  notifySubscriptionUpdated,
  simulateCheckoutPayment,
  type CheckoutCreatedResponse,
  type PlanDefinition,
} from "@/lib/billing/api";

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

function formatRemaining(expiresAtIso: string | null | undefined): string {
  if (!expiresAtIso) return "30:00";
  const diffMs = new Date(expiresAtIso).getTime() - Date.now();
  if (diffMs <= 0) return "00:00";
  const totalSec = Math.floor(diffMs / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function CheckoutDialog({
  open,
  plan,
  isExtending = false,
  onClose,
  onCompleted,
}: CheckoutDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const [step, setStep] = useState<DialogStep>("review");
  const [inFlight, setInFlight] = useState<boolean>(false);
  const [session, setSession] = useState<CheckoutCreatedResponse | null>(null);
  const [activeUntil, setActiveUntil] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [countdown, setCountdown] = useState<string>("30:00");

  useEffect(() => {
    if (open) {
      setStep("review");
      setInFlight(false);
      setSession(null);
      setActiveUntil(null);
      setErrorMsg(null);
    }
  }, [open]);

  // Focus trap + Escape handling
  useEffect(() => {
    if (!open) return;
    const container = dialogRef.current;
    const focusables = container?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    );
    focusables?.[0]?.focus();

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
          container.querySelectorAll<HTMLElement>(
            'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
          ),
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

  // Poll mock checkout status & update countdown while waiting
  useEffect(() => {
    if (!open || step !== "waiting" || !session) return;
    const activeSessionId = session.session_id;
    const activeExpiresAt = session.expires_at;

    setCountdown(formatRemaining(activeExpiresAt));
    const timer = window.setInterval(() => {
      const rem = formatRemaining(activeExpiresAt);
      setCountdown(rem);
      if (rem === "00:00") {
        setStep("expired");
      }
    }, 1000);

    const poller = window.setInterval(async () => {
      try {
        const st = await getCheckoutSession(activeSessionId);
        if (st.status === "paid") {
          setActiveUntil(st.active_until);
          setStep("success");
          notifySubscriptionUpdated();
          onCompleted();
        } else if (st.status === "expired") {
          setStep("expired");
        }
      } catch {
        // Ignore transient network errors during poll
      }
    }, 2000);

    return () => {
      window.clearInterval(timer);
      window.clearInterval(poller);
    };
  }, [open, step, session, onCompleted]);

  if (!open) return null;

  async function handleStartCheckout() {
    setInFlight(true);
    setErrorMsg(null);
    try {
      const created = await createCheckoutSession("pass");
      if (created.provider === "stripe_sandbox" && created.checkout_url) {
        window.location.assign(created.checkout_url);
        return;
      }
      setSession(created);
      setStep("waiting");
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Could not start checkout. Please try again.",
      );
      setStep("error");
    } finally {
      setInFlight(false);
    }
  }

  async function handleSimulatePayment() {
    if (!session) return;
    setInFlight(true);
    setErrorMsg(null);
    try {
      const updated = await simulateCheckoutPayment(session.session_id);
      if (updated.status === "paid") {
        setActiveUntil(updated.active_until);
        setStep("success");
        notifySubscriptionUpdated();
        onCompleted();
      } else if (updated.status === "expired") {
        setStep("expired");
      }
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Could not simulate payment. Please try again.",
      );
      setStep("error");
    } finally {
      setInFlight(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4 backdrop-blur-xs"
      onClick={(e) => {
        if (e.target === e.currentTarget && !inFlight) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="checkout-dialog-title"
        className="w-full max-w-md rounded-2xl border border-rule bg-surface-raised p-6 shadow-xl"
      >
        {/* Payment method info banner */}
        <div className="mb-4 rounded-lg border border-accent/30 bg-accent-tint/60 px-3.5 py-2.5 text-xs font-medium text-ink">
          <p className="font-semibold text-accent">
            Bakong KHQR · ABA Mobile ($5.00 USD)
          </p>
          <p className="mt-0.5 text-ink-2">
            Scan with ABA Mobile or any Bakong-supported banking app in Cambodia.
          </p>
        </div>

        {step === "review" && (
          <div>
            <h2
              id="checkout-dialog-title"
              className="font-serif text-xl font-bold text-ink"
            >
              {isExtending ? "Extend Job Hunt Pass" : "Get Job Hunt Pass"}
            </h2>
            <p className="mt-1 text-sm text-ink-2">
              One-time 30-day pass. Does not auto-renew.
            </p>

            <dl className="mt-5 divide-y divide-rule rounded-xl border border-rule bg-paper/60 px-4 text-sm">
              <div className="flex items-center justify-between py-3">
                <dt className="text-ink-3">Plan</dt>
                <dd className="font-medium text-ink">{plan.name}</dd>
              </div>
              <div className="flex items-center justify-between py-3">
                <dt className="text-ink-3">Duration</dt>
                <dd className="font-medium text-ink">
                  {plan.period_days} days {isExtending ? "(extends current pass)" : ""}
                </dd>
              </div>
              <div className="flex items-center justify-between py-3">
                <dt className="text-ink-3">Included</dt>
                <dd className="font-medium text-ink">
                  50 analyses · 30 AI rewrites
                </dd>
              </div>
              <div className="flex items-center justify-between py-3">
                <dt className="font-medium text-ink">Total due</dt>
                <dd className="font-serif text-lg font-bold text-ink">
                  {plan.price_display}.00 USD
                </dd>
              </div>
            </dl>

            <div className="mt-6 flex items-center justify-end gap-3">
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
                {inFlight ? "Starting checkout…" : "Continue to payment ↗"}
              </button>
            </div>
          </div>
        )}

        {step === "waiting" && session && (
          <div>
            <div className="flex items-center justify-between gap-2">
              <h2
                id="checkout-dialog-title"
                className="font-serif text-xl font-bold text-ink"
              >
                Scan ABA KHQR to pay
              </h2>
              <span className="rounded-md bg-paper-2 px-2.5 py-1 font-mono text-xs font-medium text-ink-2">
                Expires in {countdown}
              </span>
            </div>
            <p className="mt-1 text-sm text-ink-2">
              Order total:{" "}
              <span className="font-semibold text-ink">
                ${(session.amount_cents / 100).toFixed(2)} {session.currency}
              </span>{" "}
              for 30-day Job Hunt Pass.
            </p>

            {/* Official ABA Bakong KHQR Card */}
            <div className="mt-4 flex flex-col items-center justify-center rounded-xl border border-rule bg-paper/70 p-4 text-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/aba-khqr.jpg"
                alt="ABA KHQR — DY DAVID (5 USD)"
                className="h-auto w-56 rounded-xl border border-rule shadow-sm"
              />
              <p className="mt-3 font-mono text-xs font-semibold text-ink">
                USD account: 012 929 221 · DY DAVID
              </p>
              <p className="mt-1 text-xs text-ink-3">
                Scan with ABA Mobile or any Bakong KHQR banking app, then click
                below to confirm and activate your pass.
              </p>
            </div>

            <div className="mt-6 flex items-center justify-between gap-3">
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
                onClick={() => void handleSimulatePayment()}
                data-testid="checkout-simulate-btn"
                className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2 disabled:opacity-50"
              >
                {inFlight ? "Confirming…" : "I've completed payment"}
              </button>
            </div>
          </div>
        )}

        {step === "success" && (
          <div data-testid="checkout-success-view">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-accent-tint text-accent">
              ✓
            </div>
            <h2
              id="checkout-dialog-title"
              className="mt-3 font-serif text-xl font-bold text-ink"
            >
              Job Hunt Pass activated
            </h2>
            <p className="mt-1 text-sm text-ink-2">
              Pass active until{" "}
              <span className="font-semibold text-ink">
                {formatDate(activeUntil)}
              </span>
              . Your 50 analyses and 30 AI rewrites are ready to use.
            </p>

            <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
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
                Back to dashboard ↗
              </Link>
            </div>
          </div>
        )}

        {(step === "expired" || step === "error") && (
          <div>
            <h2
              id="checkout-dialog-title"
              className="font-serif text-xl font-bold text-ink"
            >
              {step === "expired" ? "Checkout session expired" : "Checkout issue"}
            </h2>
            <p className="mt-2 text-sm text-ink-2">
              {step === "expired"
                ? "This checkout session timed out before payment was completed. You were not charged."
                : (errorMsg ?? "Something went wrong starting checkout.")}
            </p>

            <div className="mt-6 flex items-center justify-end gap-3">
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
                Try again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

