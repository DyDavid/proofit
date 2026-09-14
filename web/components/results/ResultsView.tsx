import { useTranslations } from "next-intl";

import { ResultsInteractive } from "@/components/results/ResultsInteractive";
import { CoverageStat, type CoverageTile } from "@/components/results/CoverageStat";
import type { StampTone } from "@/components/ui/Stamp";
import { Stamp } from "@/components/ui/Stamp";
import type { Match } from "@/lib/types";

const REALISM_TONE: Record<string, StampTone> = {
  strong_fit: "proven",
  stretch: "partial",
  unrealistic: "missing",
};

/** Display names for the ISO 3166-1 alpha-2 codes the fixtures use, plus the
 * schema's 'REMOTE' sentinel. Full country-rules config is Phase 4 scope. */
const COUNTRY_NAME: Record<string, string> = {
  KH: "Cambodia",
  SG: "Singapore",
  JP: "Japan",
  AU: "Australia",
  US: "United States",
  REMOTE: "Remote",
};

/** Dates are metadata, not translated prose (BRAND.md §4) — one fixed format
 * in both locales, same as the untranslated evidence/reasoning text. */
function formatDate(iso: string): string {
  const d = new Date(iso);
  const day = new Intl.DateTimeFormat("en-US", { day: "2-digit" }).format(d);
  const month = new Intl.DateTimeFormat("en-US", { month: "short" }).format(d);
  const year = new Intl.DateTimeFormat("en-US", { year: "numeric" }).format(d);
  return `${day} ${month} ${year}`;
}

export interface ResultsViewProps {
  match: Match;
}

/**
 * The full Results screen body, as a pure function of one `Match` — shared by
 * the static "try a sample" path (`app/[locale]/results/page.tsx`, no `?id=`)
 * and the real-analysis path (`ResultsById.tsx`, fetched by `?id=`). Uses
 * `next-intl`'s isomorphic `useTranslations` (not the `/server` variant) so
 * the exact same component works from a Server or a Client Component.
 */
export function ResultsView({ match }: ResultsViewProps) {
  const t = useTranslations("results");
  const job = match.job;

  const requirementById = new Map((job?.requirements ?? []).map((r) => [r.id, r]));
  const orderedResults = [...(match.results ?? [])].sort((a, b) => {
    const oa = requirementById.get(a.requirement_id)?.display_order ?? 0;
    const ob = requirementById.get(b.requirement_id)?.display_order ?? 0;
    return oa - ob;
  });
  const tiles: CoverageTile[] = orderedResults.map((r) => ({
    verdict: r.verdict,
    required: requirementById.get(r.requirement_id)?.priority === "required",
  }));

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
      <div className="mb-10 grid gap-6 border-b border-ink pb-8 sm:grid-cols-[1fr_auto] sm:items-start">
        <div>
          <p className="mb-2 flex flex-wrap items-center gap-2 font-mono text-xs text-ink-3">
            <span className="uppercase tracking-wide">{t("eyebrow")}</span>
            {job?.company ? (
              <>
                <span aria-hidden="true">·</span>
                <span>{job.company}</span>
              </>
            ) : null}
            {job?.country ? (
              <>
                <span aria-hidden="true">·</span>
                <span className="rounded-pill border border-rule px-2.5 py-0.5 text-ink-2">
                  {job.country} · {COUNTRY_NAME[job.country] ?? job.country}
                </span>
              </>
            ) : null}
            {match.generated_at ? (
              <>
                <span aria-hidden="true">·</span>
                <span>{formatDate(match.generated_at)}</span>
              </>
            ) : null}
          </p>
          <h1 className="font-serif text-4xl text-ink sm:text-5xl">{job?.title}</h1>
          {match.realism_explanation ? (
            <p className="mt-3 max-w-2xl text-base leading-[1.7] text-ink-2">
              {match.realism_explanation}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col items-start gap-2 pt-1 sm:items-end">
          <Stamp tone={REALISM_TONE[match.realism_verdict] ?? "partial"}>
            {t(`realism.${match.realism_verdict}`)}
          </Stamp>
          <span className="font-mono text-xs text-ink-3">{t("realismLabel")}</span>
        </div>
      </div>

      <div className="mb-12 grid gap-10 border-b border-rule pb-10 sm:grid-cols-2">
        <CoverageStat
          label={t("coverage.all")}
          helpLabel={t("coverage.tooltip")}
          value={match.coverage_score}
          tiles={tiles}
          underlineLabel={t("coverage.underline")}
        />
        <CoverageStat
          label={t("coverage.required")}
          helpLabel={t("coverage.tooltip")}
          value={match.coverage_required_only}
          note={t("coverage.weighting")}
        />
      </div>

      <ResultsInteractive match={match} />
    </div>
  );
}
