import { Suspense } from "react";
import type { Metadata } from "next";
import { PricingGrid } from "@/components/billing/PricingGrid";

export const metadata: Metadata = {
  title: "Pricing — Proofit",
  description:
    "Simple, transparent pricing for first-job seekers. Start free or unlock a 30-day Job Hunt Pass with no recurring subscription.",
};

export default function PricingPage() {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-8 sm:py-16">
      <div className="max-w-2xl">
        <p className="font-mono text-xs font-medium uppercase tracking-widest text-accent">
          Pricing
        </p>
        <h1 className="mt-2 font-serif text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
          Pay for your job hunt,{" "}
          <span className="font-accent font-normal italic text-accent">
            not a subscription.
          </span>
        </h1>
        <p className="mt-3 text-base leading-relaxed text-ink-2">
          Start free with full non-work evidence mapping. Need more applications
          and AI bullet rewrites? Grab a 30-day Job Hunt Pass — one-time
          purchase, never auto-renews.
        </p>
      </div>

      <div className="mt-10">
        <Suspense
          fallback={
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-[520px] animate-pulse rounded-2xl border border-rule bg-paper-2/60"
                />
              ))}
            </div>
          }
        >
          <PricingGrid />
        </Suspense>
      </div>

      <div className="mt-12 grid grid-cols-1 gap-6 border-t border-rule pt-8 text-sm text-ink-2 sm:grid-cols-3">
        <div>
          <h2 className="font-semibold text-ink">No auto-renewal</h2>
          <p className="mt-1 text-ink-3">
            The Job Hunt Pass is a one-time 30-day pass. Buying another pass
            while yours is active extends your end date by 30 days.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-ink">
            Non-work evidence is always free
          </h2>
          <p className="mt-1 text-ink-3">
            Every tier maps university coursework, capstones, and volunteer work
            to real job requirements.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-ink">University &amp; career centres</h2>
          <p className="mt-1 text-ink-3">
            Supporting a graduating cohort? Reach out via the Campus plan for
            annual campus access.
          </p>
        </div>
      </div>
    </div>
  );
}

