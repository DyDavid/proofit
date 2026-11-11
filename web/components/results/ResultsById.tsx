"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { ResultsView } from "@/components/results/ResultsView";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, getAnalysis } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import type { BaselineMatch, Match } from "@/lib/types";

export interface ResultsByIdProps {
  id: string;
}

/**
 * Error codes a `status: "failed"` analysis can carry (docs/errors.md §2).
 * An unrecognised code falls back to `errors.INTERNAL` rather than being
 * looked up unchecked — same allowlist-then-fallback rule as
 * `ProgressStepper`, which polls the same field.
 */
const FAILED_CODES = [
  "RESUME_UNREADABLE",
  "JOB_FETCH_FAILED",
  "ENGINE_FAILED",
  "RATE_LIMITED",
  "INTERNAL",
] as const;

/**
 * The `/results?id=…` path: fetches one analysis by id and renders
 * `ResultsView` from it. Four states — not-found (a stale or bookmarked link
 * against the in-memory store), error (the analysis finished `failed`, or the
 * fetch itself broke), loading, and success. An analysis still queued or
 * running is redirected back to `/progress?id=…` rather than shown here.
 */
export function ResultsById({ id }: ResultsByIdProps) {
  const t = useTranslations("common");
  const te = useTranslations("errors");
  const router = useRouter();
  const [match, setMatch] = React.useState<Match | null>(null);
  const [baseline, setBaseline] = React.useState<BaselineMatch | null>(null);
  const [isGuestResult, setIsGuestResult] = React.useState(false);
  const [notFound, setNotFound] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const hasMatchRef = React.useRef(false);
  hasMatchRef.current = Boolean(match);

  React.useEffect(() => {
    let cancelled = false;
    const cacheKey = `proofit:analysis:${id}`;

    try {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        const parsed = JSON.parse(cached) as {
          match: Match;
          baseline: BaselineMatch | null;
          isGuest: boolean;
        };
        if (parsed?.match) {
          setMatch(parsed.match);
          setBaseline(parsed.baseline);
          setIsGuestResult(Boolean(parsed.isGuest));
        }
      }
    } catch {
      // Ignore storage read error
    }

    async function load() {
      try {
        const supabase = createClient();
        const sessionRes = supabase ? await supabase.auth.getSession() : null;
        const isLoggedOut = !sessionRes?.data?.session?.user;

        let res = await getAnalysis(id);
        let retries = 0;
        while (!cancelled && res.status !== "done" && res.status !== "failed" && retries < 3) {
          await new Promise((resolve) => setTimeout(resolve, 800));
          if (cancelled) return;
          res = await getAnalysis(id);
          retries++;
        }
        if (cancelled) return;
        if (res.status === "done" && res.match) {
          const isGuest = Boolean(res.is_guest || isLoggedOut);
          setMatch(res.match);
          setBaseline(res.baseline);
          setIsGuestResult(isGuest);
          try {
            sessionStorage.setItem(
              cacheKey,
              JSON.stringify({
                match: res.match,
                baseline: res.baseline,
                isGuest,
              }),
            );
          } catch {
            // Ignore storage write error
          }
        } else if (res.status === "failed") {
          const code = res.error?.code;
          if (!code) {
            setError(t("error.generic"));
          } else {
            setError(
              (FAILED_CODES as readonly string[]).includes(code)
                ? te(code as (typeof FAILED_CODES)[number])
                : te("INTERNAL"),
            );
          }
        } else {
          router.replace(`/progress?id=${id}`);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "ANALYSIS_NOT_FOUND") {
          setNotFound(true);
        } else if (!hasMatchRef.current) {
          setError(t("error.generic"));
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [id, router, t, te]);

  if (notFound) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center">
        <p className="mb-6 text-ink-2">{te("ANALYSIS_NOT_FOUND")}</p>
        <Button as="a" href="/analyze" variant="primary">
          {t("action.back")}
        </Button>
      </div>
    );
  }

  if (error && !match) {
    return <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-2">{error}</div>;
  }

  if (!match) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-3">{t("loading")}</div>
    );
  }

  return (
    <div>
      {isGuestResult ? (
        <div className="mx-auto mt-6 max-w-6xl px-4 sm:px-8">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-accent/30 bg-accent-tint px-4 py-3 text-sm text-ink">
            <p className="font-medium">
              Sign in to save this result and get more analyses.
            </p>
            <Link
              href={`/login?next=${encodeURIComponent(`/results?id=${id}`)}`}
              className="inline-flex items-center rounded-pill bg-accent px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-surface-raised transition-colors hover:bg-accent-2"
            >
              Sign in
            </Link>
          </div>
        </div>
      ) : null}
      <ResultsView match={match} baseline={baseline} analysisId={id} />
    </div>
  );
}
