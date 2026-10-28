"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  fetchSubscription,
  type SubscriptionSummary,
} from "@/lib/billing/api";

function formatEndDate(iso: string | null): string {
  if (!iso) return "Rolling 30-day window";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Rolling 30-day window";
  return `Pass active until ${d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })}`;
}

export function UsageMeter() {
  const [sub, setSub] = useState<SubscriptionSummary | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function load() {
      const data = await fetchSubscription();
      if (!mounted) return;
      setSub(data);
      setLoaded(true);
    }
    void load();

    const onUpdated = () => void load();
    window.addEventListener("proofit:subscription-updated", onUpdated);
    return () => {
      mounted = false;
      window.removeEventListener("proofit:subscription-updated", onUpdated);
    };
  }, []);

  if (!loaded || !sub) return null;

  const analysisUsed = sub.usage.analysis.used;
  const analysisLimit = sub.usage.analysis.limit;
  const rewriteUsed = sub.usage.rewrite.used;
  const rewriteLimit = sub.usage.rewrite.limit;
  const isPass = sub.plan_id === "pass" || sub.plan_id === "campus";

  return (
    <div
      data-testid="usage-meter"
      className="rounded-2xl border border-rule bg-surface-raised p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span
            className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
              isPass
                ? "bg-accent-tint text-accent"
                : "bg-paper-2 text-ink-2"
            }`}
          >
            {sub.plan_id === "pass"
              ? "Job Hunt Pass"
              : sub.plan_id === "campus"
                ? "Campus"
                : "Free Plan"}
          </span>
          <span className="text-xs text-ink-3">
            {formatEndDate(sub.active_until)}
          </span>
        </div>

        <Link
          href="/pricing"
          className="text-xs font-semibold text-accent hover:underline"
        >
          {isPass ? "Extend pass ↗" : "Upgrade to Job Hunt Pass ↗"}
        </Link>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-rule bg-paper/60 p-3.5">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-ink-2">Analyses</span>
            <span className="font-mono font-semibold text-ink">
              {analysisLimit !== null
                ? `${analysisUsed} of ${analysisLimit} analyses used`
                : `${analysisUsed} used (Unlimited)`}
            </span>
          </div>
          {analysisLimit !== null && (
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-track">
              <div
                className="h-full rounded-full bg-accent transition-all"
                style={{
                  width: `${Math.min(
                    100,
                    Math.round((analysisUsed / Math.max(1, analysisLimit)) * 100),
                  )}%`,
                }}
              />
            </div>
          )}
        </div>

        <div className="rounded-xl border border-rule bg-paper/60 p-3.5">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-ink-2">AI rewrites</span>
            <span className="font-mono font-semibold text-ink">
              {rewriteLimit !== null
                ? `${rewriteUsed} of ${rewriteLimit} rewrites used`
                : `${rewriteUsed} used (Unlimited)`}
            </span>
          </div>
          {rewriteLimit !== null && (
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-track">
              <div
                className="h-full rounded-full bg-accent transition-all"
                style={{
                  width: `${Math.min(
                    100,
                    Math.round((rewriteUsed / Math.max(1, rewriteLimit)) * 100),
                  )}%`,
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

