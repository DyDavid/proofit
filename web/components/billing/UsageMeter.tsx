"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  fetchSubscription,
  type SubscriptionSummary,
} from "@/lib/billing/api";

function formatEndDate(iso: string | null, planId?: string): string {
  if (planId === "campus") return "Unlimited lifetime access";
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

  const analysisPct =
    analysisLimit !== null
      ? Math.min(100, Math.round((analysisUsed / Math.max(1, analysisLimit)) * 100))
      : 0;

  const rewritePct =
    rewriteLimit !== null
      ? Math.min(100, Math.round((rewriteUsed / Math.max(1, rewriteLimit)) * 100))
      : 0;

  return (
    <div
      data-testid="usage-meter"
      className="rounded-2xl border border-rule bg-surface-raised p-6 shadow-xs"
    >
      <div className="flex flex-col gap-3 border-b border-rule pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2.5">
          <span
            className={`inline-flex items-center rounded-pill px-3 py-1 font-mono text-xs font-semibold uppercase tracking-wider ${
              isPass
                ? "bg-accent-tint text-accent"
                : "bg-paper-2 text-ink"
            }`}
          >
            {sub.plan_id === "pass"
              ? "Job Hunt Pass"
              : sub.plan_id === "campus"
                ? "Campus (Unlimited)"
                : "Free Plan"}
          </span>
          <span className="text-xs font-medium text-ink-3">
            {formatEndDate(sub.active_until, sub.plan_id)}
          </span>
        </div>

        <Link
          href="/pricing"
          className="inline-flex items-center text-xs font-semibold text-accent transition-colors hover:text-accent-2 hover:underline"
        >
          {isPass ? "Extend pass ↗" : "Upgrade to Job Hunt Pass ↗"}
        </Link>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Analyses Usage Card */}
        <div className="rounded-xl border border-rule bg-paper/60 p-4">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-ink-2">Analyses</span>
            <span className="font-mono text-sm font-bold text-ink">
              {analysisLimit !== null
                ? `${analysisUsed} / ${analysisLimit} used`
                : `${analysisUsed} used`}
            </span>
          </div>

          {analysisLimit !== null ? (
            <div className="mt-3">
              <div className="h-2 w-full overflow-hidden rounded-full bg-track">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-300"
                  style={{ width: `${analysisPct}%` }}
                />
              </div>
              <div className="mt-1.5 flex justify-between text-[11px] font-mono text-ink-3">
                <span>{analysisPct}% utilized</span>
                <span>{Math.max(0, analysisLimit - analysisUsed)} remaining</span>
              </div>
            </div>
          ) : (
            <p className="mt-2 font-mono text-xs text-accent">Unlimited quota</p>
          )}
        </div>

        {/* AI Rewrites Usage Card */}
        <div className="rounded-xl border border-rule bg-paper/60 p-4">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-ink-2">AI bullet rewrites</span>
            <span className="font-mono text-sm font-bold text-ink">
              {rewriteLimit !== null
                ? `${rewriteUsed} / ${rewriteLimit} used`
                : `${rewriteUsed} used`}
            </span>
          </div>

          {rewriteLimit !== null ? (
            <div className="mt-3">
              <div className="h-2 w-full overflow-hidden rounded-full bg-track">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-300"
                  style={{ width: `${rewritePct}%` }}
                />
              </div>
              <div className="mt-1.5 flex justify-between text-[11px] font-mono text-ink-3">
                <span>{rewritePct}% utilized</span>
                <span>{Math.max(0, rewriteLimit - rewriteUsed)} remaining</span>
              </div>
            </div>
          ) : (
            <p className="mt-2 font-mono text-xs text-accent">Unlimited quota</p>
          )}
        </div>
      </div>
    </div>
  );
}
