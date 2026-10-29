"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  getCheckoutSession,
  notifySubscriptionUpdated,
} from "@/lib/billing/api";

type PollState = "polling" | "paid" | "still_pending" | "missing_session";

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

function BillingSuccessContent() {
  const searchParams = useSearchParams();
  const sessionId =
    searchParams.get("session_id") || searchParams.get("id");
  const [state, setState] = useState<PollState>(
    sessionId ? "polling" : "missing_session",
  );
  const [activeUntil, setActiveUntil] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setState("missing_session");
      return;
    }

    let cancelled = false;
    const startedAt = Date.now();

    async function checkOnce(): Promise<boolean> {
      try {
        const res = await getCheckoutSession(sessionId!);
        if (cancelled) return true;
        if (res.status === "paid") {
          setActiveUntil(res.active_until);
          setState("paid");
          notifySubscriptionUpdated();
          return true;
        }
        if (res.status === "expired") {
          setState("still_pending");
          return true;
        }
      } catch {
        // Ignore transient errors while polling
      }
      if (Date.now() - startedAt >= 60_000) {
        if (!cancelled) setState("still_pending");
        return true;
      }
      return false;
    }

    void checkOnce();
    const timer = window.setInterval(async () => {
      const done = await checkOnce();
      if (done) {
        window.clearInterval(timer);
      }
    }, 3500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId]);

  return (
    <div className="mx-auto w-full max-w-lg px-4 py-16 sm:px-8">
      <div className="rounded-2xl border border-rule bg-surface-raised p-8 text-center shadow-xs">
        {state === "polling" && (
          <div>
            <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-rule border-t-accent" />
            <h1 className="mt-5 font-serif text-2xl font-bold text-ink">
              Verifying Bakong KHQR payment...
            </h1>
            <p className="mt-2 text-sm text-ink-2">
              Please wait while our server verifies your transaction with the
              official NBC Bakong API.
            </p>
          </div>
        )}

        {state === "paid" && (
          <div>
            <div className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-full bg-accent-tint text-lg font-bold text-accent">
              ✓
            </div>
            <h1 className="mt-4 font-serif text-2xl font-bold text-ink">
              Pass active until {formatDate(activeUntil)}
            </h1>
            <p className="mt-2 text-sm text-ink-2">
              Your 30-day Job Hunt Pass is unlocked with 50 analyses, 30 AI
              rewrites, and up to 10 saved resumes.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Link
                href="/dashboard"
                className="rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-ink-2"
              >
                Back to dashboard
              </Link>
              <Link
                href="/pricing"
                className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2"
              >
                View pricing
              </Link>
            </div>
          </div>
        )}

        {state === "still_pending" && (
          <div>
            <h1 className="font-serif text-2xl font-bold text-ink">
              Payment not yet confirmed
            </h1>
            <p className="mt-2 text-sm text-ink-2">
              Check your bank transaction history before paying again, or
              refresh in a moment to recheck status.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2"
              >
                Refresh status
              </button>
              <Link
                href="/dashboard"
                className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2"
              >
                Back to dashboard
              </Link>
            </div>
          </div>
        )}

        {state === "missing_session" && (
          <div>
            <h1 className="font-serif text-2xl font-bold text-ink">
              No checkout session found
            </h1>
            <p className="mt-2 text-sm text-ink-2">
              We could not find a checkout reference in the URL.
            </p>
            <div className="mt-6 flex justify-center">
              <Link
                href="/pricing"
                className="rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-ink-2"
              >
                Back to pricing
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function BillingSuccessPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-lg px-4 py-16 text-center text-sm text-ink-3">
          Verifying Bakong KHQR payment...
        </div>
      }
    >
      <BillingSuccessContent />
    </Suspense>
  );
}
