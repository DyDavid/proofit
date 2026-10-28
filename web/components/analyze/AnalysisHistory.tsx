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
        <h2 className="mb-2 font-serif text-xl text-ink">{t("title")}</h2>
        <p className="text-sm text-ink-3">
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
      <h2 className="mb-4 font-serif text-xl text-ink">{t("title")}</h2>
      <ul className="grid gap-3">
        {rows.map((row) => (
          <li key={row.analysis_id}>
            <Link
              href={`/results?id=${row.analysis_id}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-rule bg-paper p-3.5 transition-colors hover:bg-paper-2"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-ink">
                  {row.job_title}
                  {row.company ? ` · ${row.company}` : ""}
                </p>
                <p className="font-mono text-xs text-ink-3">
                  {new Date(row.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="font-mono text-sm text-ink-2">{Math.round(row.coverage)}%</span>
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
