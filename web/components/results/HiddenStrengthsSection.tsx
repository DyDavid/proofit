"use client";

import * as React from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { Match } from "@/lib/types";
import { generateRewrites, type RewritesResponse } from "@/lib/api";

interface HiddenStrengthsSectionProps {
  analysisId: string;
  match: Match;
}

export function HiddenStrengthsSection({ analysisId, match }: HiddenStrengthsSectionProps) {
  const [loading, setLoading] = React.useState(false);
  const [data, setData] = React.useState<RewritesResponse | null>(null);
  const [copiedIndex, setCopiedIndex] = React.useState<number | null>(null);
  const [dismissed, setDismissed] = React.useState<Set<number>>(new Set());
  const [hasRequested, setHasRequested] = React.useState(false);

  const fetchRewrites = React.useCallback(async () => {
    setLoading(true);
    setHasRequested(true);
    try {
      const res = await generateRewrites(analysisId);
      setData(res);
    } catch (e) {
      console.error("Failed to generate rewrites:", e);
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  const strengths = data?.hidden_strengths || match.hidden_strengths || [];
  const rejectionsCount = data?.rejections_count ?? 0;

  if (!hasRequested && strengths.length === 0) {
    return (
      <Card padding="lg" className="mt-8 border border-rule bg-surface-raised">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl">✨</span>
              <h2 className="font-serif text-xl text-ink">Hidden Strengths & Resume Bullet Rewrites</h2>
            </div>
            <p className="mt-1 text-sm text-ink-2 max-w-xl leading-relaxed">
              Generate evidence-bound bullet suggestions for requirement gaps, strictly citing your existing resume facts.
            </p>
          </div>
          <Button
            type="button"
            onClick={fetchRewrites}
            loading={loading}
            className="shrink-0 bg-ink text-paper hover:bg-neutral-800"
          >
            ✨ Generate AI Suggestions
          </Button>
        </div>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card padding="lg" className="mt-8 border-rule bg-surface-raised">
        <div className="animate-pulse space-y-4">
          <div className="h-6 w-1/3 bg-neutral-200 dark:bg-neutral-800 rounded" />
          <div className="h-4 w-2/3 bg-neutral-200 dark:bg-neutral-800 rounded" />
          <div className="h-24 w-full bg-neutral-200 dark:bg-neutral-800 rounded" />
        </div>
      </Card>
    );
  }

  if (strengths.length === 0) {
    return (
      <Card padding="lg" className="mt-8 border-rule bg-surface-raised">
        <p className="text-sm text-ink-3">No additional hidden strengths found for this match.</p>
      </Card>
    );
  }

  const activeStrengths = strengths.filter((_, idx) => !dismissed.has(idx));

  function handleCopy(text: string, idx: number) {
    navigator.clipboard.writeText(text);
    setCopiedIndex(idx);
    setTimeout(() => setCopiedIndex(null), 2000);
  }

  function handleDismiss(idx: number) {
    setDismissed((prev) => new Set(prev).add(idx));
  }

  return (
    <Card padding="lg" className="mt-8 border border-emerald-200 bg-emerald-50/30 dark:border-emerald-900/50 dark:bg-emerald-950/10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-emerald-200/60 pb-4 dark:border-emerald-900/50">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">✨</span>
            <h2 className="font-serif text-2xl text-ink">Hidden Strengths & Evidence-Bound Rewrites</h2>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-ink-2">
            Highlights unphrased candidate experience. Every claim is strictly validated against cited evidence records.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-emerald-300 bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-900 dark:border-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">
          <span>🛡️ {strengths.length} suggestions passed validation</span>
          {rejectionsCount > 0 && <span className="opacity-75">· {rejectionsCount} rejected by safety rules</span>}
        </div>
      </div>

      {activeStrengths.length === 0 ? (
        <p className="text-sm text-ink-3">All suggested rewrites processed.</p>
      ) : (
        <div className="grid gap-6">
          {activeStrengths.map((hs, idx) => {
            const isCopied = copiedIndex === idx;
            return (
              <div
                key={`${hs.requirement_id}-${idx}`}
                className="rounded-lg border border-rule bg-paper p-5 shadow-sm transition-all hover:shadow-md"
              >
                <div className="mb-3 flex items-center justify-between text-xs font-mono text-ink-3">
                  <span className="rounded bg-neutral-100 px-2 py-0.5 font-semibold text-ink dark:bg-neutral-800">
                    Requirement {hs.requirement_id}
                  </span>
                  <span className="text-emerald-700 dark:text-emerald-400 font-medium">
                    Evidence Source: {hs.evidence_id}
                  </span>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-900/50">
                    <p className="mb-1 text-xs font-semibold text-ink-3 uppercase tracking-wider">Original Resume Line</p>
                    <p className="text-sm leading-relaxed text-ink-2 line-through opacity-80">{hs.current_phrasing}</p>
                  </div>

                  <div className="rounded border border-emerald-200 bg-emerald-50/50 p-3 dark:border-emerald-900/40 dark:bg-emerald-900/20">
                    <p className="mb-1 text-xs font-semibold text-emerald-800 dark:text-emerald-300 uppercase tracking-wider">
                      Suggested Phrasing (Evidence-Bound)
                    </p>
                    <p className="text-sm font-medium leading-relaxed text-ink">
                      {hs.suggested_phrasing}
                    </p>
                    {hs.changed_words && hs.changed_words.length > 0 && (
                      <div className="mt-2.5 flex flex-wrap items-center gap-1 text-[11px]">
                        <span className="text-ink-3">Highlighted Additions:</span>
                        {hs.changed_words.map((w) => (
                          <span
                            key={w}
                            className="rounded bg-emerald-100 px-1.5 py-0.5 font-mono text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100"
                          >
                            +{w}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-100 pt-3 dark:border-neutral-800">
                  <div className="flex items-center gap-1.5 text-xs text-ink-3">
                    <span>Facts Used:</span>
                    {hs.facts_used.map((fId) => (
                      <span key={fId} className="rounded border border-rule px-1.5 py-0.5 font-mono text-[11px]">
                        {fId}
                      </span>
                    ))}
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleCopy(hs.suggested_phrasing, idx)}
                    >
                      {isCopied ? "✓ Copied" : "Copy Phrasing"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDismiss(idx)}
                      className="text-ink-3 hover:text-ink"
                    >
                      Dismiss
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
