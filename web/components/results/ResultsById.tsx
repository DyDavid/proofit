"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { ResultsView } from "@/components/results/ResultsView";
import { useRouter } from "next/navigation";
import { ApiError, getAnalysis } from "@/lib/api";
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
  const [notFound, setNotFound] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await getAnalysis(id);
        if (cancelled) return;
        if (res.status === "done" && res.match) {
          setMatch(res.match);
          setBaseline(res.baseline);
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
        } else {
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

  if (error) {
    return <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-2">{error}</div>;
  }

  if (!match) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-3">{t("loading")}</div>
    );
  }

  return <ResultsView match={match} baseline={baseline} analysisId={id} />;
}
