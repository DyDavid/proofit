"use client";

import * as React from "react";
import { Link } from "@/i18n/routing";
import { Card } from "@/components/ui/Card";
import { getAnalysesHistory, type AnalysisHistoryItem } from "@/lib/api";

export function AnalysisHistoryList() {
  const [history, setHistory] = React.useState<AnalysisHistoryItem[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    getAnalysesHistory()
      .then((data) => setHistory(Array.isArray(data) ? data : []))
      .catch(() => setHistory([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading || history.length === 0) return null;

  return (
    <Card padding="lg" className="mt-8 border border-rule bg-surface-raised">
      <div className="mb-4 border-b border-rule pb-3">
        <h2 className="font-serif text-xl text-ink">Analysis History</h2>
        <p className="text-xs text-ink-3">Past requirement coverage reports</p>
      </div>

      <div className="grid gap-3">
        {history.map((item) => (
          <Link
            key={item.id}
            href={`/results/${item.id}`}
            className="flex flex-wrap items-center justify-between gap-4 rounded-md border border-rule bg-paper p-3.5 transition-colors hover:bg-neutral-50 dark:hover:bg-neutral-900"
          >
            <div>
              <h3 className="font-medium text-ink text-sm">
                {item.job_title} {item.company ? `· ${item.company}` : ""}
              </h3>
              <p className="text-xs text-ink-3">Target Country: {item.country.toUpperCase()}</p>
            </div>

            <div className="flex items-center gap-3">
              <span className="font-mono text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                {item.coverage_score.toFixed(0)}% Coverage
              </span>
              <span className="rounded bg-neutral-100 px-2 py-0.5 font-mono text-xs capitalize text-ink dark:bg-neutral-800">
                {item.realism_verdict.replace("_", " ")}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </Card>
  );
}
