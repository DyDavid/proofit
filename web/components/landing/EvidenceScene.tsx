"use client";

import { VerdictIcon, type Verdict } from "@/components/ui/VerdictIcon";
import { useCountUp, useInView } from "@/lib/useInView";

interface EvidenceRow {
  source: string;
  evidence: string;
  requirement: string;
  verdict: Verdict;
}

const ROWS: EvidenceRow[] = [
  {
    source: "Coursework · Database Systems",
    evidence: "Wrote multi-table joins for a course inventory database.",
    requirement: "SQL for joining and aggregating data",
    verdict: "proven",
  },
  {
    source: "Project · Final year project",
    evidence: "Built a pipeline that summarised results for the team.",
    requirement: "Explaining findings to non-technical teams",
    verdict: "proven",
  },
  {
    source: "Part-time · Tech support",
    evidence: "Used spreadsheets daily, no cleaning pipeline described.",
    requirement: "Python for cleaning messy datasets",
    verdict: "partial",
  },
  {
    source: "Coursework · Intro to Statistics",
    evidence: "Completed an intro statistics course.",
    requirement: "Statistics fundamentals",
    verdict: "partial",
  },
  {
    source: "No evidence yet",
    evidence: "",
    requirement: "1+ year in an analytics role",
    verdict: "missing",
  },
];

const VERDICT_LINE: Record<Verdict, string> = {
  proven: "bg-accent",
  partial: "bg-ink",
  missing: "border-t border-dashed border-missing",
};

const VERDICT_TEXT: Record<Verdict, string> = {
  proven: "text-accent",
  partial: "text-partial-ink",
  missing: "text-missing",
};

export interface EvidenceSceneStrings {
  resumeLabel: string;
  jobLabel: string;
  countLabel: string;
  coverageLabel: string;
  proven: string;
  partial: string;
  missing: string;
  weightingNote: string;
}

/**
 * The Landing page's "evidence in / verdict out" proof, matching the source
 * design's scene: resume evidence on the left, job requirements on the
 * right, joined by an animated line whose style (solid accent / solid ink /
 * dashed) carries the verdict, plus a count-up coverage stat once the scene
 * scrolls into view. Simplified from the source's crossing bezier-curve
 * diagram to straight per-row connectors — the pairing and reveal survive,
 * pixel-exact curve geometry does not, for a layout that stays responsive.
 */
export function EvidenceScene({ strings }: { strings: EvidenceSceneStrings }) {
  const { ref, inView } = useInView<HTMLDivElement>(0.25);
  const pct = useCountUp(60, inView, { delay: 300, duration: 1400 });
  const provenCount = ROWS.filter((r) => r.verdict === "proven").length;
  const partialCount = ROWS.filter((r) => r.verdict === "partial").length;
  const missingCount = ROWS.filter((r) => r.verdict === "missing").length;

  return (
    <div ref={ref}>
      <div className="grid grid-cols-[1fr_auto] gap-x-2 text-[11px] uppercase tracking-[0.14em] text-ink-3 sm:grid-cols-[1fr_2.5rem_1fr_auto] sm:gap-x-4">
        <span className="font-mono">{strings.resumeLabel}</span>
        <span className="hidden font-mono sm:block" />
        <span className="hidden font-mono sm:block">{strings.jobLabel}</span>
        <span className="col-span-2 mt-2 font-mono sm:col-span-1 sm:mt-0">
          {strings.countLabel}
        </span>
      </div>

      <ul className="mt-6 flex flex-col gap-3">
        {ROWS.map((row, i) => (
          <li
            key={row.requirement}
            className={
              "motion-safe:animate-rise grid grid-cols-1 items-center gap-3 rounded-pill border border-rule bg-surface-raised px-5 py-3 sm:grid-cols-[1fr_2.5rem_1fr_auto] sm:rounded-none sm:border-0 sm:bg-transparent sm:px-0 sm:py-0" +
              (inView ? "" : " opacity-0")
            }
            style={inView ? { animationDelay: `${i * 0.08}s` } : undefined}
          >
            <div className="min-w-0">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-3">
                {row.source}
              </p>
              {row.evidence ? (
                <p className="mt-0.5 truncate text-sm text-ink-2">{row.evidence}</p>
              ) : null}
            </div>

            <div className="relative hidden h-2.5 sm:block" aria-hidden="true">
              <span
                className={
                  "motion-safe:animate-grow-x absolute inset-x-0 top-1/2 h-[1.5px] origin-left -translate-y-1/2 " +
                  VERDICT_LINE[row.verdict]
                }
                style={inView ? { animationDelay: `${0.2 + i * 0.1}s` } : { transform: "scaleX(0)" }}
              />
            </div>

            <p className="text-base font-medium text-ink sm:text-lg">{row.requirement}</p>

            <span
              className={
                "motion-safe:animate-pop inline-flex w-fit items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.1em] " +
                VERDICT_TEXT[row.verdict]
              }
              style={inView ? { animationDelay: `${0.5 + i * 0.1}s` } : undefined}
            >
              <VerdictIcon verdict={row.verdict} size="0.9rem" />
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-16 grid grid-cols-1 items-end gap-8 border-t border-rule pt-10 sm:grid-cols-[auto_1fr_auto]">
        <div className="motion-safe:animate-rise" style={{ animationDelay: "0.2s" }}>
          <div className="font-serif text-[5.5rem] font-extrabold leading-[0.8] tabular-nums sm:text-[8rem]">
            {pct}
            <span className="text-accent text-[0.5em]">%</span>
          </div>
          <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-ink-3">
            {strings.coverageLabel}
          </p>
        </div>

        <div>
          <div className="flex h-2.5 gap-1">
            <div
              className="motion-safe:animate-grow-x h-full w-[40%] origin-left rounded-pill bg-accent"
              style={inView ? { animationDelay: "0.3s" } : { transform: "scaleX(0)" }}
            />
            <div
              className="motion-safe:animate-grow-x h-full w-[40%] origin-left rounded-pill bg-partial"
              style={inView ? { animationDelay: "0.45s" } : { transform: "scaleX(0)" }}
            />
            <div
              className="motion-safe:animate-grow-x h-full w-[20%] origin-left rounded-pill border border-dashed border-partial"
              style={inView ? { animationDelay: "0.6s" } : { transform: "scaleX(0)" }}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-6 text-sm text-ink">
            <span className="flex items-center gap-2">
              <VerdictIcon verdict="proven" size="0.85em" />
              {strings.proven.replace("{count}", String(provenCount))}
            </span>
            <span className="flex items-center gap-2">
              <VerdictIcon verdict="partial" size="0.85em" />
              {strings.partial.replace("{count}", String(partialCount))}
            </span>
            <span className="flex items-center gap-2">
              <VerdictIcon verdict="missing" size="0.85em" />
              {strings.missing.replace("{count}", String(missingCount))}
            </span>
          </div>
          <p className="mt-3 font-mono text-xs text-ink-3">{strings.weightingNote}</p>
        </div>
      </div>
    </div>
  );
}
