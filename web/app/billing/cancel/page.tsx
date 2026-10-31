import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Payment Canceled",
  description: "Your payment was canceled and you were not charged.",
  robots: {
    index: false,
    follow: false,
  },
};

export default function BillingCancelPage() {
  return (
    <div className="mx-auto w-full max-w-lg px-4 py-16 sm:px-8">
      <div className="rounded-2xl border border-rule bg-surface-raised p-8 text-center shadow-xs">
        <h1 className="font-serif text-2xl font-bold text-ink">
          Payment canceled, you were not charged
        </h1>
        <p className="mt-2 text-sm text-ink-2">
          Your checkout session was canceled before completion. You can try
          again whenever you are ready.
        </p>

        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link
            href="/pricing?plan=pass"
            className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-surface-raised hover:bg-accent-2"
          >
            Try again
          </Link>
          <Link
            href="/pricing"
            className="rounded-lg border border-rule px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-paper-2"
          >
            Back to pricing
          </Link>
        </div>
      </div>
    </div>
  );
}

