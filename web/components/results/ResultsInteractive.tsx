"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { BaselineToggle } from "@/components/results/BaselineToggle";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { VerdictIcon, type Verdict } from "@/components/ui/VerdictIcon";
import { cn } from "@/lib/utils";
import type {
  BaselineMatch,
  BaselineResult,
  Evidence,
  Match,
  MatchResult,
  Requirement,
} from "@/lib/types";

export interface ResultsInteractiveProps {
  match: Match;
  baseline?: BaselineMatch | null;
}

const GROUP_ORDER: Verdict[] = ["missing", "partial", "proven"];
const FILTER_KEYS = ["all", "proven", "partial", "missing"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];
const VERDICT_TONE: Record<Verdict, BadgeTone> = {
  proven: "proven",
  partial: "partial",
  missing: "missing",
};
const VERDICT_TEXT_CLASS: Record<Verdict, string> = {
  proven: "text-proven",
  partial: "text-partial-ink",
  missing: "text-missing",
};

function ConfidenceBar({ confidence, label }: { confidence: number; label: string }) {
  const pct = Math.round(Math.min(Math.max(confidence, 0), 1) * 100);
  return (
    <div
      className="h-1 w-16 shrink-0 overflow-hidden rounded-pill bg-paper-3"
      role="img"
      aria-label={label}
    >
      <div className="h-full rounded-pill bg-ink-2" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Sliding-pill All/Proven/Partial/Missing filter (the source design's
 * `.seg`), a toggle-button group rather than a tablist — the requirement
 * list stays a single page, this just narrows which groups render. */
function FilterPills({
  filter,
  onChange,
  counts,
  label,
}: {
  filter: FilterKey;
  onChange: (key: FilterKey) => void;
  counts: Record<FilterKey, number>;
  label: string;
}) {
  const t = useTranslations("results.filter");
  const activeIndex = FILTER_KEYS.indexOf(filter);

  return (
    <div
      role="group"
      aria-label={label}
      className="relative mb-6 grid max-w-md grid-cols-4 rounded-pill border border-rule p-1"
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-1 left-1 w-[calc(25%-4px)] rounded-pill bg-accent transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
        style={{ transform: `translateX(${activeIndex * 100}%)` }}
      />
      {FILTER_KEYS.map((key) => (
        <button
          key={key}
          type="button"
          aria-pressed={filter === key}
          onClick={() => onChange(key)}
          className={cn(
            "relative z-10 flex min-h-9 items-center justify-center gap-1.5 rounded-pill text-[13px] font-medium transition-colors",
            filter === key ? "text-paper" : "text-ink-2 hover:text-ink",
          )}
        >
          {t(key)}
          <span className="font-mono text-[11px] opacity-70">{counts[key]}</span>
        </button>
      ))}
    </div>
  );
}

function RequirementRow({
  result,
  requirement,
  evidenceById,
  isOpen,
  onToggle,
  baselineResult,
  showBaseline,
}: {
  result: MatchResult;
  requirement: Requirement | undefined;
  evidenceById: Map<string, Evidence>;
  isOpen: boolean;
  onToggle: (open: boolean) => void;
  baselineResult: BaselineResult | undefined;
  showBaseline: boolean;
}) {
  const t = useTranslations("results");
  const evidenceRecords = (result.evidence_ids ?? [])
    .map((id) => evidenceById.get(id))
    .filter((e): e is Evidence => Boolean(e));

  return (
    <details
      id={`req-${result.requirement_id}`}
      open={isOpen}
      onToggle={(e) => onToggle(e.currentTarget.open)}
      className="border-b border-rule first:border-t"
    >
      <summary
        className={cn(
          "grid cursor-pointer list-none grid-cols-[auto_1fr_auto] items-center gap-4 py-3.5",
          "[&::-webkit-details-marker]:hidden",
        )}
      >
        <Badge tone={VERDICT_TONE[result.verdict]}>
          <VerdictIcon verdict={result.verdict} />
          {t(`verdict.${result.verdict}`)}
        </Badge>
        <span className="text-[15.5px] leading-[1.5] text-ink">
          {requirement?.text ?? result.requirement_id}
        </span>
        <span className="flex items-center gap-3">
          {requirement?.priority === "required" ? (
            <span className="font-mono text-[11px] font-medium uppercase tracking-wide text-ink">
              {t("priority.required")}
            </span>
          ) : (
            <span className="font-mono text-[11px] uppercase tracking-wide text-ink-3">
              {t("priority.preferred")}
            </span>
          )}
          <ConfidenceBar
            confidence={result.confidence}
            label={t("confidence", { pct: Math.round(result.confidence * 100) })}
          />
          {showBaseline && baselineResult ? (
            <Badge tone="muted" className="opacity-70">
              {t(`verdict.${baselineResult.verdict}`)}
            </Badge>
          ) : null}
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className={cn(
              "shrink-0 text-ink-3 transition-transform duration-200",
              isOpen && "rotate-180",
            )}
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </summary>

      <div className="grid gap-3 py-1 pb-5 pl-0 sm:pl-[7.5rem]">
        {result.verdict === "missing" ? (
          <p className={cn("flex gap-2 text-[15px] leading-[1.6]", VERDICT_TEXT_CLASS.missing)}>
            <VerdictIcon verdict="missing" className="mt-0.5" />
            <span>{result.missing_reason}</span>
          </p>
        ) : (
          evidenceRecords.map((evidence) => (
            <div key={evidence.id} className="rounded-2xl border border-rule bg-surface-raised p-4">
              <div className="mb-2.5 flex items-center justify-between font-mono text-[11px] uppercase tracking-wide text-ink-3">
                <span>{t("evidence.from")}</span>
                <Badge tone="muted">{t(`evidenceType.${evidence.evidence_type}`)}</Badge>
              </div>
              <p className="text-[15.5px] leading-[1.65] text-ink">
                <mark className="proofit-mark">{evidence.source_line}</mark>
              </p>
              {evidence.duration_months || evidence.team_size ? (
                <p className="mt-2 font-mono text-[11px] text-ink-3">
                  {[
                    evidence.duration_months ? `${evidence.duration_months} mo` : null,
                    evidence.team_size ? `team of ${evidence.team_size}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              ) : null}
              {result.verdict === "partial" &&
              evidence.evidence_type !== "employment" &&
              evidence.evidence_type !== "internship" ? (
                <p className="mt-2 text-[13px] leading-[1.5] text-ink-3">
                  {evidence.duration_months || evidence.team_size
                    ? t("evidence.howThisCountsDetailed", {
                        evidenceType: t(`evidenceType.${evidence.evidence_type}`),
                        detail: [
                          evidence.duration_months ? `${evidence.duration_months} mo` : null,
                          evidence.team_size ? `team of ${evidence.team_size}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · "),
                      })
                    : t("evidence.howThisCounts", {
                        evidenceType: t(`evidenceType.${evidence.evidence_type}`),
                      })}
                </p>
              ) : null}
            </div>
          ))
        )}

        {result.reasoning ? (
          <p className="text-[15px] leading-[1.6] text-ink-2">
            <span className="font-medium text-ink">{t("evidence.why")}: </span>
            {result.reasoning}
          </p>
        ) : null}
      </div>
    </details>
  );
}

/**
 * Requirement list (grouped Missing → Partial → Proven, required before
 * preferred within each group), an All/Proven/Partial/Missing filter that
 * narrows which groups render, plus the sticky priority-actions rail.
 *
 * Client component because the rail's "jump to requirement" links must open
 * the target's `<details>` and scroll to it (clearing the filter first, so
 * the target row is guaranteed to be in the DOM). Carries the
 * keyword-baseline comparison toggle when a `baseline` is supplied (Phase 2);
 * the hidden-strengths section is still Phase 4 scope. Switching that toggle
 * on reveals the matcher's aggregate coverage score beside the real one, and
 * its per-requirement verdict as a muted badge on each row.
 */
export function ResultsInteractive({ match, baseline }: ResultsInteractiveProps) {
  const t = useTranslations("results");
  const [openIds, setOpenIds] = React.useState<Set<string>>(new Set());
  const [showBaseline, setShowBaseline] = React.useState(false);
  const [filter, setFilter] = React.useState<FilterKey>("all");

  const requirementById = React.useMemo(() => {
    const map = new Map<string, Requirement>();
    for (const r of match.job?.requirements ?? []) map.set(r.id, r);
    return map;
  }, [match.job?.requirements]);

  const evidenceById = React.useMemo(() => {
    const map = new Map<string, Evidence>();
    for (const e of match.resume?.evidence ?? []) map.set(e.id, e);
    return map;
  }, [match.resume?.evidence]);

  const baselineByRequirement = React.useMemo(() => {
    const map = new Map<string, BaselineResult>();
    for (const r of baseline?.results ?? []) map.set(r.requirement_id, r);
    return map;
  }, [baseline?.results]);

  const groups = React.useMemo(() => {
    const results = match.results ?? [];
    return GROUP_ORDER.map((verdict) => {
      const items = results
        .filter((r) => r.verdict === verdict)
        .sort((a, b) => {
          const ra = requirementById.get(a.requirement_id);
          const rb = requirementById.get(b.requirement_id);
          if (ra?.priority === rb?.priority) return 0;
          return ra?.priority === "required" ? -1 : 1;
        });
      const requiredCount = items.filter(
        (r) => requirementById.get(r.requirement_id)?.priority === "required",
      ).length;
      return { verdict, items, requiredCount };
    }).filter((g) => g.items.length > 0);
  }, [match.results, requirementById]);

  const filterCounts = React.useMemo(() => {
    const counts: Record<FilterKey, number> = { all: 0, proven: 0, partial: 0, missing: 0 };
    for (const r of match.results ?? []) {
      counts.all += 1;
      counts[r.verdict] += 1;
    }
    return counts;
  }, [match.results]);

  const visibleGroups = filter === "all" ? groups : groups.filter((g) => g.verdict === filter);

  function openRequirement(id: string) {
    setOpenIds((prev) => new Set(prev).add(id));
    // The target row may be hidden by an active filter — clear it first so
    // `req-${id}` is guaranteed to exist in the DOM before scrolling to it.
    setFilter("all");
    requestAnimationFrame(() => {
      document
        .getElementById(`req-${id}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  function toggle(id: string, open: boolean) {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_320px] lg:items-start">
      <div>
        {baseline ? (
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-serif text-2xl text-ink">{t("title")}</h2>
            <BaselineToggle
              shown={showBaseline}
              onToggle={() => setShowBaseline((s) => !s)}
            />
          </div>
        ) : (
          <h2 className="mb-2 font-serif text-2xl text-ink">{t("title")}</h2>
        )}
        {baseline && showBaseline ? (
          <div className="mb-6 grid gap-3 border-y border-dashed border-rule py-4 sm:grid-cols-[auto_1fr] sm:items-center sm:gap-8">
            <div className="flex items-baseline gap-8">
              <p className="grid gap-1">
                <span className="font-mono text-[11px] uppercase tracking-wide text-ink-3">
                  {t("coverage.all")}
                </span>
                <span className="font-serif text-3xl leading-none tracking-tight text-ink">
                  {Math.round(match.coverage_score)}
                  <span className="ml-0.5 font-mono text-xs uppercase tracking-wide text-ink-3">
                    %
                  </span>
                </span>
              </p>
              <p className="grid gap-1">
                <span className="font-mono text-[11px] uppercase tracking-wide text-ink-3">
                  {t("baseline.score")}
                </span>
                <span className="font-serif text-3xl leading-none tracking-tight text-ink-3">
                  {Math.round(baseline.coverage_score)}
                  <span className="ml-0.5 font-mono text-xs uppercase tracking-wide text-ink-3">
                    %
                  </span>
                </span>
              </p>
            </div>
            <p className="max-w-[52ch] text-sm leading-[1.6] text-ink-3">
              {t("baseline.caption")}
            </p>
          </div>
        ) : null}

        <FilterPills
          filter={filter}
          onChange={setFilter}
          counts={filterCounts}
          label={t("filter.label")}
        />

        {visibleGroups.length === 0 ? (
          <p className="py-8 text-sm text-ink-3">{t("filter.empty")}</p>
        ) : (
          visibleGroups.map((group) => (
            <div key={group.verdict} className="mb-8">
              {filter === "all" ? (
                <div className="mb-1 flex items-baseline justify-between border-b border-ink pb-2">
                  <h3
                    className={cn(
                      "font-mono text-xs font-semibold uppercase tracking-wider",
                      VERDICT_TEXT_CLASS[group.verdict],
                    )}
                  >
                    {t(`group.${group.verdict}`)}
                  </h3>
                  <span className="font-mono text-xs text-ink-3">
                    {t("group.count", {
                      count: group.items.length,
                      required: group.requiredCount,
                    })}
                  </span>
                </div>
              ) : null}
              {group.items.map((result) => (
                <RequirementRow
                  key={result.requirement_id}
                  result={result}
                  requirement={requirementById.get(result.requirement_id)}
                  evidenceById={evidenceById}
                  isOpen={openIds.has(result.requirement_id)}
                  onToggle={(open) => toggle(result.requirement_id, open)}
                  baselineResult={baselineByRequirement.get(result.requirement_id)}
                  showBaseline={showBaseline}
                />
              ))}
            </div>
          ))
        )}
      </div>

      {match.priority_actions?.length ? (
        <aside className="lg:sticky lg:top-24">
          <div className="rounded-card border border-rule bg-surface-raised p-5">
            <h3 className="mb-3 font-serif text-xl text-ink">{t("actions.title")}</h3>
            <ol className="grid gap-3">
              {match.priority_actions.map((action, i) => (
                <li
                  key={i}
                  className="flex gap-3 border-t border-dashed border-rule pt-3 first:border-t-0 first:pt-0"
                >
                  <span className="font-serif text-2xl font-light leading-none text-accent">
                    {i + 1}
                  </span>
                  <span className="text-sm leading-[1.6] text-ink">
                    {action.requirement_id ? (
                      <button
                        type="button"
                        onClick={() => openRequirement(action.requirement_id!)}
                        className="text-left underline decoration-rule underline-offset-2 hover:decoration-ink"
                      >
                        {action.text}
                      </button>
                    ) : (
                      action.text
                    )}
                    {typeof action.coverage_gain === "number" ? (
                      <span className="mt-1 block font-mono text-[11px] tracking-wide text-proven">
                        {t("actions.gain", { pct: action.coverage_gain })}
                      </span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </aside>
      ) : null}
    </div>
  );
}
