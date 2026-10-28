"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { REALISM_TONE } from "@/components/results/ResultsView";
import { Card } from "@/components/ui/Card";
import { Stamp } from "@/components/ui/Stamp";
import Link from "next/link";
import { getAnalysisHistory, type AnalysisSummary } from "@/lib/api";
import { loadRememberedResume } from "@/lib/localResume";
import { createClient } from "@/lib/supabase/client";

export interface AnalysisHistoryProps {
  className?: string;
  showEmpty?: boolean;
}

/**
 * Past analyses for the signed-in user or the resume remembered in this browser.
 */
export function AnalysisHistory({
  className,
  showEmpty = false,
}: AnalysisHistoryProps) {
  const t = useTranslations("analyze.history");
  const tr = useTranslations("results");
  const [rows, setRows] = React.useState<AnalysisSummary[] | null>(null);

  React.useEffect(() => {
    let active = true;
    async function load() {
      const remembered = loadRememberedResume();
      const supabase = createClient();
      const userRes = supabase ? await supabase.auth.getUser() : null;
      const isSignedIn = Boolean(userRes?.data?.user);

      if (!remembered && !isSignedIn) {
        if (active) setRows([]);
        return;
      }

      try {
        const data = await getAnalysisHistory(remembered?.id);
        if (active) setRows(data);
      } catch {
        if (active) setRows([]);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  if (rows === null) return null;

  if (rows.length === 0) {
    if (!showEmpty) return null;
    return (
      <Card padding="lg" className={className ?? "mt-8"}>
        <div className="flex items-center justify-between gap-2 border-b border-rule pb-4">
          <h2 className="font-serif text-xl font-bold text-ink">{t("title")}</h2>
          <span className="rounded-pill bg-paper-2 px-2.5 py-0.5 font-mono text-xs text-ink-3">
            0 total
          </span>
        </div>
        <p className="mt-4 text-sm text-ink-3">
          No analyses saved yet. Head to the{" "}
          <Link href="/analyze" className="font-medium text-accent underline">
            Analyzer
          </Link>{" "}
          to run your first match.
        </p>
      </Card>
    );
  }

  return (
    <Card padding="lg" className={className ?? "mt-8"}>
      <div className="mb-4 flex items-center justify-between gap-3 border-b border-rule pb-4">
        <h2 className="font-serif text-xl font-bold text-ink">{t("title")}</h2>
        <span className="rounded-pill bg-paper-2 px-2.5 py-0.5 font-mono text-xs font-semibold text-ink-2">
          {rows.length} {rows.length === 1 ? "analysis" : "analyses"}
        </span>
      </div>

      <ul className="grid gap-3">
        {rows.map((row) => (
          <li key={row.analysis_id}>
            <Link
              href={`/results?id=${row.analysis_id}`}
              className="flex flex-col gap-3 rounded-xl border border-rule bg-paper/60 p-4 transition-all hover:border-ink/30 hover:bg-paper hover:shadow-xs sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink">
                  {row.job_title}
                  {row.company ? (
                    <span className="text-ink-2"> · {row.company}</span>
                  ) : (
                    ""
                  )}
                </p>
                <p className="mt-0.5 font-mono text-xs text-ink-3">
                  {new Date(row.created_at).toLocaleDateString("en-US", {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })}
                </p>
              </div>

              <div className="flex shrink-0 items-center justify-between gap-4 sm:justify-end">
                <div className="text-right">
                  <span className="font-mono text-sm font-semibold text-ink">
                    {Math.round(row.coverage)}%
                  </span>
                  <span className="ml-1 text-xs text-ink-3">match</span>
                </div>
                <Stamp tone={REALISM_TONE[row.realism_verdict] ?? "partial"}>
                  {tr(`realism.${row.realism_verdict}`)}
                </Stamp>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
