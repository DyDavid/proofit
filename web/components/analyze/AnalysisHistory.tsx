"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { REALISM_TONE } from "@/components/results/ResultsView";
import { Card } from "@/components/ui/Card";
import { Stamp } from "@/components/ui/Stamp";
import { getAnalysisHistory, type AnalysisSummary } from "@/lib/api";
import { loadRememberedResume } from "@/lib/localResume";

/**
 * Past analyses for the resume remembered in this browser (PERSON_B_PLAN_v2.md
 * §5 Phase 3 task 2). There are no accounts, so "the current user" is exactly
 * the resume_id `localResume.ts` already remembers per browser (Phase 2) —
 * reusing that identity rather than adding a second anonymous-id mechanism
 * for the same purpose. Renders nothing when there is no remembered resume or
 * no history yet, rather than an empty-state card — the Analyze form is
 * already the first thing on this page.
 */
export function AnalysisHistory() {
  const t = useTranslations("analyze.history");
  const tr = useTranslations("results");
  const [rows, setRows] = React.useState<AnalysisSummary[] | null>(null);

  React.useEffect(() => {
    const remembered = loadRememberedResume();
    if (!remembered) {
      setRows([]);
      return;
    }
    getAnalysisHistory(remembered.id)
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  if (!rows || rows.length === 0) return null;

  return (
    <Card padding="lg" className="mt-8">
      <h2 className="mb-4 font-serif text-xl text-ink">{t("title")}</h2>
      <ul className="grid gap-3">
        {rows.map((row) => (
          <li key={row.analysis_id}>
            <a
              href={`/results?id=${row.analysis_id}`}
              className="flex flex-wrap items-center justify-between gap-3 border border-rule bg-paper p-3.5 transition-colors hover:bg-paper-2"
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
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
