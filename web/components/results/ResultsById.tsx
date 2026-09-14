"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { ResultsView } from "@/components/results/ResultsView";
import { useRouter } from "@/i18n/routing";
import { getAnalysis } from "@/lib/api";
import type { Match } from "@/lib/types";

export interface ResultsByIdProps {
  id: string;
}

/**
 * Fetches one analysis by id and renders it through the shared `ResultsView`.
 * By the time `ProgressStepper` navigates here the analysis is already
 * `done`, so this is normally a single fast fetch — the redirect-back-to-
 * progress branch only covers a stale or bookmarked `/results?id=` link.
 */
export function ResultsById({ id }: ResultsByIdProps) {
  const t = useTranslations("common");
  const router = useRouter();
  const [match, setMatch] = React.useState<Match | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await getAnalysis(id);
        if (cancelled) return;
        if (res.status === "done" && res.match) {
          setMatch(res.match);
        } else if (res.status === "failed") {
          setError(t("error.generic"));
        } else {
          router.replace(`/progress?id=${id}`);
        }
      } catch {
        if (!cancelled) setError(t("error.generic"));
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [id, router, t]);

  if (error) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-2">{error}</div>
    );
  }

  if (!match) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-3">
        {t("loading")}
      </div>
    );
  }

  return <ResultsView match={match} />;
}
