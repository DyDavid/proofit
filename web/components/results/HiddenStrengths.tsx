"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { UpgradePrompt } from "@/components/billing/UpgradePrompt";
import { Button } from "@/components/ui/Button";
import { ApiError, createRewrites } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Evidence, HiddenStrength, Match } from "@/lib/types";

export interface HiddenStrengthsProps {
  match: Match;
  /** Undefined on the static "try a sample" path (`/results` with no `?id=`)
   * — there is no analysis to POST against, so the run button is hidden and
   * the section renders `match.hidden_strengths` as-is (PERSON_B_PLAN_v2.md
   * §5 Phase 4 task 3, requirement 6). */
  analysisId?: string;
}

/**
 * `errors.*` codes `POST /api/analyses/{id}/rewrites` can raise
 * (docs/errors.md §2): a stale/bookmarked id, an analysis still running, the
 * Anthropic rate limit, or the F5 pipeline failing outright. Same
 * allowlist-with-fallback pattern as `ProgressStepper.tsx` and
 * `ResultsById.tsx` — never hand an arbitrary server code straight to `te()`.
 */
const KNOWN_ERROR_CODES = [
  "ANALYSIS_NOT_FOUND",
  "ANALYSIS_NOT_READY",
  "RATE_LIMITED",
  "ENGINE_FAILED",
  "INTERNAL",
] as const;

/** Stable key for one HiddenStrength — the schema has no `id` field, but a
 * requirement/evidence pair is unique per detected candidate. */
function itemKey(h: HiddenStrength): string {
  return `${h.requirement_id}:${h.evidence_id}`;
}

/** Strips leading/trailing punctuation and lowercases, so a trailing comma
 * or period never defeats the `changed_words` match ("shipped," still
 * matches "shipped"). */
function normalizeToken(token: string): string {
  return token.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "").toLowerCase();
}

/**
 * Renders `suggested_phrasing` with every word in `changed_words` wrapped in
 * `<mark className="proofit-mark">` — the same highlight class
 * `ResultsInteractive.tsx` uses for evidence excerpts. Splits on whitespace
 * (kept as its own tokens) so the rendered text is byte-identical to the
 * source string, not just visually close.
 */
function HighlightedPhrasing({
  text,
  changedWords,
}: {
  text: string;
  changedWords: string[];
}) {
  const changedSet = React.useMemo(
    () => new Set(changedWords.map(normalizeToken).filter(Boolean)),
    [changedWords],
  );

  const tokens = text.split(/(\s+)/);
  return (
    <>
      {tokens.map((token, i) => {
        if (token === "" || /^\s+$/.test(token)) return token;
        return changedSet.has(normalizeToken(token)) ? (
          <mark key={i} className="proofit-mark">
            {token}
          </mark>
        ) : (
          <React.Fragment key={i}>{token}</React.Fragment>
        );
      })}
    </>
  );
}

/**
 * `facts_used` chips that expand to the cited `Evidence.source_line` — the
 * traceability guarantee made visible: every suggestion shows exactly which
 * resume lines it was built from. Degrades to a plain, non-interactive chip
 * when `match.resume?.evidence` doesn't carry a matching record (an id it
 * cannot resolve is not a crash, just nothing to expand).
 */
function FactsChips({
  factsUsed,
  evidenceById,
}: {
  factsUsed: readonly string[];
  evidenceById: Map<string, Evidence>;
}) {
  const [openId, setOpenId] = React.useState<string | null>(null);

  return (
    <div className="flex flex-wrap gap-2">
      {factsUsed.map((id) => {
        const evidence = evidenceById.get(id);
        const isOpen = openId === id;

        if (!evidence) {
          return (
            <span
              key={id}
              className="inline-flex items-center rounded-tag border border-rule px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-ink-3"
            >
              {id}
            </span>
          );
        }

        return (
          <div key={id} className="grid gap-1.5">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpenId(isOpen ? null : id)}
              className={cn(
                "inline-flex w-fit items-center rounded-tag border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide transition-colors",
                isOpen
                  ? "border-ink bg-paper-3 text-ink"
                  : "border-rule text-ink-2 hover:border-ink hover:text-ink",
              )}
            >
              {id}
            </button>
            {isOpen ? (
              <p className="max-w-md border border-rule bg-surface-raised p-2.5 text-[13px] leading-[1.55] text-ink-2">
                <mark className="proofit-mark">{evidence.source_line}</mark>
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function HiddenStrengthCard({
  item,
  evidenceById,
  onReject,
}: {
  item: HiddenStrength;
  evidenceById: Map<string, Evidence>;
  onReject: () => void;
}) {
  const t = useTranslations("results.hiddenStrengths");
  const tc = useTranslations("common");
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(item.suggested_phrasing);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — nothing to do; the text is still visible
      // on screen for the user to select manually.
    }
  }

  return (
    <div className="rounded-card border border-rule bg-surface-raised p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
            {t("current")}
          </p>
          <p className="text-[15px] leading-[1.6] text-ink-2">{item.current_phrasing}</p>
        </div>
        <div>
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
            {t("suggested")}
          </p>
          <p className="text-[15px] leading-[1.6] text-ink">
            <HighlightedPhrasing
              text={item.suggested_phrasing}
              changedWords={item.changed_words ?? []}
            />
          </p>
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
          {t("factsUsed")}
        </p>
        <FactsChips factsUsed={item.facts_used} evidenceById={evidenceById} />
      </div>

      <div className="mt-4 flex gap-3 border-t border-dashed border-rule pt-3">
        <Button type="button" variant="secondary" size="sm" onClick={copy}>
          {copied ? `${tc("action.copy")} ✓` : tc("action.copy")}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onReject}>
          {tc("action.reject")}
        </Button>
      </div>
    </div>
  );
}

/**
 * F5's UI: rewrite suggestions for requirements the resume already satisfies
 * but phrases badly. Opt-in — nothing fires until the button is pressed, since
 * every run costs a real LLM call server-side. The counter reads straight off
 * `hidden_strengths.length` and `rejected_count`, never off what the user has
 * locally rejected, because it is the on-screen proof that the F5 validator
 * (engine/rewrite/validate.py) is actually rejecting overreaching claims —
 * a number this component's own UI state must never be able to distort.
 */
export function HiddenStrengths({ match, analysisId }: HiddenStrengthsProps) {
  const t = useTranslations("results.hiddenStrengths");
  const te = useTranslations("errors");

  const [strengths, setStrengths] = React.useState<HiddenStrength[]>(
    match.hidden_strengths ?? [],
  );
  const [rejectedCount, setRejectedCount] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [errorCode, setErrorCode] = React.useState<string | null>(null);
  const [dismissed, setDismissed] = React.useState<Set<string>>(new Set());
  const [liveMessage, setLiveMessage] = React.useState("");

  const evidenceById = React.useMemo(() => {
    const map = new Map<string, Evidence>();
    for (const e of match.resume?.evidence ?? []) map.set(e.id, e);
    return map;
  }, [match.resume?.evidence]);

  const visible = strengths.filter((h) => !dismissed.has(itemKey(h)));

  async function run() {
    if (!analysisId) return;
    setLoading(true);
    setErrorCode(null);
    try {
      const res = await createRewrites(analysisId);
      setStrengths(res.hidden_strengths);
      setRejectedCount(res.rejected_count);
    } catch (err) {
      setErrorCode(err instanceof ApiError && err.code ? err.code : "INTERNAL");
    } finally {
      setLoading(false);
    }
  }

  function reject(key: string) {
    setDismissed((prev) => new Set(prev).add(key));
    setLiveMessage(t("rejected"));
  }

  const errorMessage =
    errorCode && errorCode !== "quota_exceeded"
      ? (KNOWN_ERROR_CODES as readonly string[]).includes(errorCode)
        ? te(errorCode as (typeof KNOWN_ERROR_CODES)[number])
        : te("INTERNAL")
      : null;

  return (
    <section className="mt-12 border-t border-ink pt-10">
      <h2 className="mb-2 font-serif text-2xl text-ink">{t("title")}</h2>
      <p className="mb-5 max-w-2xl text-[15px] leading-[1.6] text-ink-2">{t("intro")}</p>

      {analysisId ? (
        <div className="mb-6">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={run}
            loading={loading}
          >
            {loading ? t("running") : t("run")}
          </Button>
        </div>
      ) : null}

      {errorCode === "quota_exceeded" ? (
        <div className="mb-6">
          <UpgradePrompt
            message="You have used all AI rewrite credits in your current plan. Upgrade to the Job Hunt Pass for 30 AI rewrites."
            onDismiss={() => setErrorCode(null)}
          />
        </div>
      ) : null}

      {errorMessage ? (
        <p role="alert" className="mb-6 text-sm leading-[1.6] text-danger">
          {errorMessage}
        </p>
      ) : null}

      {/* The point of the section: this line is the proof, on screen, that
          the F5 validator actually rejects overreaching suggestions. Always
          visible once there is any result to report, including 0 passed. */}
      <p className="mb-6 font-mono text-xs uppercase tracking-wide text-ink-3">
        {t("counter", { passed: strengths.length, rejected: rejectedCount })}
      </p>

      <div aria-live="polite" className="sr-only">
        {liveMessage}
      </div>

      {visible.length === 0 ? (
        <p className="text-sm leading-[1.6] text-ink-3">{t("empty")}</p>
      ) : (
        <div className="grid gap-4">
          {visible.map((item) => (
            <HiddenStrengthCard
              key={itemKey(item)}
              item={item}
              evidenceById={evidenceById}
              onReject={() => reject(itemKey(item))}
            />
          ))}
        </div>
      )}
    </section>
  );
}
