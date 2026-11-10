"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { type PlanDefinition } from "@/lib/billing/api";
import {
  formatCardNumber,
  formatExpiry,
  isValidCvc,
  isValidFutureExpiry,
  mockCheckout,
  sanitizeDigits,
} from "@/lib/billing/mockCheckout";
import { saveDemoEntitlement } from "@/lib/billing/entitlement";

type DialogStep = "review" | "payment" | "success" | "error";

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

export function CheckoutDialog({
  open,
  plan,
  isExtending = false,
  onClose,
  onCompleted,
}: CheckoutDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cardNumberInputRef = useRef<HTMLInputElement | null>(null);

  const [step, setStep] = useState<DialogStep>("review");
  const [inFlight, setInFlight] = useState<boolean>(false);
  const [activeUntil, setActiveUntil] = useState<string | null>(null);
  const [receiptLast4, setReceiptLast4] = useState<string>("4242");

  // Payment form state
  const [cardholderName, setCardholderName] = useState("");
  const [cardNumber, setCardNumber] = useState("");
  const [expiry, setExpiry] = useState("");
  const [cvc, setCvc] = useState("");

  // Field validation and touched states
  const [touched, setTouched] = useState({
    cardNumber: false,
    expiry: false,
    cvc: false,
  });
  const [paymentError, setPaymentError] = useState<string | null>(null);

  // Reset state whenever the dialog opens
  useEffect(() => {
    if (open) {
      setStep("review");
      setInFlight(false);
      setActiveUntil(null);
      setReceiptLast4("4242");
      setCardholderName("");
      setCardNumber("");
      setExpiry("");
      setCvc("");
      setTouched({ cardNumber: false, expiry: false, cvc: false });
      setPaymentError(null);
    }
  }, [open]);

  // Focus trap + Escape handling
  useEffect(() => {
    if (!open) return;
    const container = dialogRef.current;
    if (!container) return;

    // Focus the first appropriate element
    if (step === "payment") {
      cardNumberInputRef.current?.focus();
    } else {
      const focusables = container.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      focusables?.[0]?.focus();
    }

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
            'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
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

  if (!open) return null;

  // Validation calculations
  const rawDigits = sanitizeDigits(cardNumber);
  const isCardNumberValid = rawDigits.length === 16;
  const isExpiryValid = isValidFutureExpiry(expiry);
  const isCvcValid = isValidCvc(cvc);
  const isFormValid = isCardNumberValid && isExpiryValid && isCvcValid;

  // Input change handlers with automatic formatting
  function handleCardNumberChange(e: React.ChangeEvent<HTMLInputElement>) {
    const formatted = formatCardNumber(e.target.value);
    setCardNumber(formatted);
    setPaymentError(null);
  }

  function handleExpiryChange(e: React.ChangeEvent<HTMLInputElement>) {
    const formatted = formatExpiry(e.target.value);
    setExpiry(formatted);
    setPaymentError(null);
  }

  function handleCvcChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = sanitizeDigits(e.target.value).slice(0, 4);
    setCvc(val);
    setPaymentError(null);
  }

  async function handlePaymentSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ cardNumber: true, expiry: true, cvc: true });

    if (!isFormValid || inFlight) return;

    setInFlight(true);
    setPaymentError(null);

    try {
      const result = await mockCheckout({
        cardNumber,
        expiry,
        cvc,
        cardholderName: cardholderName.trim() || undefined,
      });

      if (result.success) {
        const entitlement = saveDemoEntitlement({
          last4: result.last4,
          amountCents: result.amountCents,
          currency: result.currency,
        });
        setActiveUntil(entitlement.expiresAt);
        setReceiptLast4(result.last4);
        setStep("success");
        onCompleted();
      } else {
        setPaymentError(result.error);
      }
    } catch {
      setPaymentError("An unexpected error occurred. Please try again.");
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
        {/* Demo mode safety banner — kept across all active interaction steps */}
        <div className="mb-4 rounded-lg border border-accent/30 bg-accent-tint/60 px-3.5 py-2.5 text-xs font-medium text-ink">
          <p className="font-semibold text-accent">
            Demo mode: no real money is charged
          </p>
          <p className="mt-0.5 text-ink-2">
            Use test card{" "}
            <span className="font-mono font-semibold text-ink">
              4242 4242 4242 4242
            </span>
            , any future date, any CVC.
          </p>
        </div>

        {/* STEP 1: Order Summary Review */}
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
                onClick={() => setStep("payment")}
                data-testid="checkout-continue-btn"
                className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2 disabled:opacity-50"
              >
                Continue to payment
              </button>
            </div>
          </div>
        )}

        {/* STEP 2: Mock Payment Form */}
        {step === "payment" && (
          <form onSubmit={handlePaymentSubmit}>
            <div className="flex items-baseline justify-between">
              <h2
                id="checkout-dialog-title"
                className="font-serif text-xl font-bold text-ink"
              >
                Payment details
              </h2>
              <span className="font-mono text-xs font-semibold text-accent">
                $5.00 USD
              </span>
            </div>
            <p className="mt-1 text-sm text-ink-2">
              Enter test card credentials to activate your 30-day pass.
            </p>

            {/* Error banner if payment declined / failed */}
            {paymentError && (
              <div
                role="alert"
                className="mt-3 rounded-lg border border-missing/40 bg-missing/10 p-3 text-xs font-medium text-missing"
              >
                {paymentError}
              </div>
            )}

            <div className="mt-4 space-y-3.5">
              {/* Cardholder name (optional) */}
              <div>
                <label
                  htmlFor="cc-name"
                  className="block text-xs font-medium text-ink-2"
                >
                  Cardholder name <span className="text-ink-3">(optional)</span>
                </label>
                <input
                  id="cc-name"
                  type="text"
                  autoComplete="cc-name"
                  value={cardholderName}
                  onChange={(e) => setCardholderName(e.target.value)}
                  placeholder="e.g. Alex Morgan"
                  disabled={inFlight}
                  className="mt-1 block w-full rounded-lg border border-rule bg-paper/60 px-3.5 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:bg-surface-raised focus:outline-hidden focus:ring-1 focus:ring-accent disabled:opacity-50"
                />
              </div>

              {/* Card number */}
              <div>
                <label
                  htmlFor="cc-number"
                  className="block text-xs font-medium text-ink-2"
                >
                  Card number
                </label>
                <div className="relative mt-1">
                  <input
                    ref={cardNumberInputRef}
                    id="cc-number"
                    type="text"
                    inputMode="numeric"
                    autoComplete="cc-number"
                    value={cardNumber}
                    onChange={handleCardNumberChange}
                    onBlur={() => setTouched((t) => ({ ...t, cardNumber: true }))}
                    placeholder="4242 4242 4242 4242"
                    maxLength={19}
                    disabled={inFlight}
                    aria-invalid={touched.cardNumber && !isCardNumberValid}
                    aria-describedby={
                      touched.cardNumber && !isCardNumberValid
                        ? "cc-number-error"
                        : undefined
                    }
                    className={`block w-full rounded-lg border bg-paper/60 px-3.5 py-2 font-mono text-sm tracking-wider text-ink placeholder:font-sans placeholder:tracking-normal placeholder:text-ink-3 focus:bg-surface-raised focus:outline-hidden focus:ring-1 disabled:opacity-50 ${
                      touched.cardNumber && !isCardNumberValid
                        ? "border-missing focus:border-missing focus:ring-missing"
                        : "border-rule focus:border-accent focus:ring-accent"
                    }`}
                  />
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
                    <span className="font-mono text-xs text-ink-3">TEST</span>
                  </div>
                </div>
                {touched.cardNumber && !isCardNumberValid && (
                  <p
                    id="cc-number-error"
                    role="alert"
                    className="mt-1 text-xs text-missing"
                  >
                    Enter a 16-digit card number (4242 4242 4242 4242).
                  </p>
                )}
              </div>

              {/* Expiry and CVC grid */}
              <div className="grid grid-cols-2 gap-3">
                {/* Expiry */}
                <div>
                  <label
                    htmlFor="cc-exp"
                    className="block text-xs font-medium text-ink-2"
                  >
                    Expires (MM/YY)
                  </label>
                  <input
                    id="cc-exp"
                    type="text"
                    inputMode="numeric"
                    autoComplete="cc-exp"
                    value={expiry}
                    onChange={handleExpiryChange}
                    onBlur={() => setTouched((t) => ({ ...t, expiry: true }))}
                    placeholder="MM/YY"
                    maxLength={5}
                    disabled={inFlight}
                    aria-invalid={touched.expiry && !isExpiryValid}
                    aria-describedby={
                      touched.expiry && !isExpiryValid ? "cc-exp-error" : undefined
                    }
                    className={`mt-1 block w-full rounded-lg border bg-paper/60 px-3.5 py-2 font-mono text-sm text-ink placeholder:font-sans placeholder:text-ink-3 focus:bg-surface-raised focus:outline-hidden focus:ring-1 disabled:opacity-50 ${
                      touched.expiry && !isExpiryValid
                        ? "border-missing focus:border-missing focus:ring-missing"
                        : "border-rule focus:border-accent focus:ring-accent"
                    }`}
                  />
                  {touched.expiry && !isExpiryValid && (
                    <p
                      id="cc-exp-error"
                      role="alert"
                      className="mt-1 text-xs text-missing"
                    >
                      Enter a future MM/YY date.
                    </p>
                  )}
                </div>

                {/* CVC */}
                <div>
                  <label
                    htmlFor="cc-csc"
                    className="block text-xs font-medium text-ink-2"
                  >
                    CVC
                  </label>
                  <input
                    id="cc-csc"
                    type="text"
                    inputMode="numeric"
                    autoComplete="cc-csc"
                    value={cvc}
                    onChange={handleCvcChange}
                    onBlur={() => setTouched((t) => ({ ...t, cvc: true }))}
                    placeholder="123"
                    maxLength={4}
                    disabled={inFlight}
                    aria-invalid={touched.cvc && !isCvcValid}
                    aria-describedby={
                      touched.cvc && !isCvcValid ? "cc-csc-error" : undefined
                    }
                    className={`mt-1 block w-full rounded-lg border bg-paper/60 px-3.5 py-2 font-mono text-sm text-ink placeholder:font-sans placeholder:text-ink-3 focus:bg-surface-raised focus:outline-hidden focus:ring-1 disabled:opacity-50 ${
                      touched.cvc && !isCvcValid
                        ? "border-missing focus:border-missing focus:ring-missing"
                        : "border-rule focus:border-accent focus:ring-accent"
                    }`}
                  />
                  {touched.cvc && !isCvcValid && (
                    <p
                      id="cc-csc-error"
                      role="alert"
                      className="mt-1 text-xs text-missing"
                    >
                      3 or 4 digits.
                    </p>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-6 flex items-center justify-between gap-3">
              <button
                type="button"
                disabled={inFlight}
                onClick={() => setStep("review")}
                className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2 disabled:opacity-50"
              >
                Back
              </button>
              <button
                type="submit"
                disabled={!isFormValid || inFlight}
                data-testid="checkout-pay-btn"
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {inFlight ? (
                  <>
                    <svg
                      className="h-4 w-4 animate-spin text-surface-raised"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                      />
                    </svg>
                    <span>Processing…</span>
                  </>
                ) : (
                  <span>Pay $5.00</span>
                )}
              </button>
            </div>
          </form>
        )}

        {/* STEP 4: Success State & Receipt */}
        {step === "success" && (
          <div data-testid="checkout-success-view">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-accent-tint text-base font-bold text-accent">
              ✓
            </div>
            <h2
              id="checkout-dialog-title"
              className="mt-3 font-serif text-xl font-bold text-ink"
            >
              Job Hunt Pass activated
            </h2>
            <p className="mt-1 text-sm text-ink-2">
              Your 30-day Job Hunt Pass is now active. All 50 analyses and 30 AI bullet rewrites have been unlocked.
            </p>

            {/* Receipt Summary Card */}
            <div className="mt-4 divide-y divide-rule rounded-xl border border-rule bg-paper/60 px-4 text-xs">
              <div className="flex items-center justify-between py-2.5">
                <span className="text-ink-3">Plan</span>
                <span className="font-medium text-ink">Job Hunt Pass</span>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-ink-3">Amount</span>
                <span className="font-semibold text-ink">$5.00 USD</span>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-ink-3">Payment method</span>
                <span className="font-mono text-ink">Demo Card (•••• {receiptLast4})</span>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-ink-3">Activated on</span>
                <span className="text-ink">{formatDate(new Date().toISOString())}</span>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-ink-3">Valid until</span>
                <span className="font-semibold text-accent">{formatDate(activeUntil)}</span>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-ink-3">Included credits</span>
                <span className="font-medium text-ink">50 analyses · 30 rewrites</span>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2"
              >
                Close
              </button>
              <Link
                href="/analyze"
                onClick={onClose}
                className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2"
              >
                Start using your pass
              </Link>
            </div>
          </div>
        )}

        {/* STEP: Unexpected Error State (Fallback) */}
        {step === "error" && (
          <div>
            <h2
              id="checkout-dialog-title"
              className="font-serif text-xl font-bold text-ink"
            >
              Checkout issue
            </h2>
            <p className="mt-2 text-sm text-ink-2">
              Something went wrong starting checkout. Please try again.
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
                onClick={() => setStep("payment")}
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
