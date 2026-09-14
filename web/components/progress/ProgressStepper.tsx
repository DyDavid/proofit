"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { useRouter } from "@/i18n/routing";
import { getAnalysis } from "@/lib/api";
import { cn } from "@/lib/utils";

const STAGES = [
  "reading_resume",
  "reading_job",
  "matching_requirements",
  "checking_realism",
] as const;

const POLL_INTERVAL_MS = 2000;

export interface ProgressStepperProps {
  analysisId: string;
}

/**
 * Polls `GET /api/analyses/{id}` every 2s (PERSON_B_PLAN_v2.md §5 Phase 1
 * task 4) and drives the stepper from the real `stage` field. `null`/unknown
 * stage (e.g. still `queued`) falls back to showing the first step active,
 * per Phase 2 task 3's "fall back to timed fake stages when stage is null."
 */
export function ProgressStepper({ analysisId }: ProgressStepperProps) {
  const t = useTranslations("progress");
  const router = useRouter();
  const [activeIndex, setActiveIndex] = React.useState(0);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await getAnalysis(analysisId);
        if (cancelled) return;

        if (res.status === "done") {
          setActiveIndex(STAGES.length);
          router.push(`/results?id=${analysisId}`);
          return;
        }
        if (res.status === "failed") {
          setFailed(true);
          return;
        }

        const index = STAGES.indexOf(res.stage as (typeof STAGES)[number]);
        setActiveIndex(index >= 0 ? index : 0);
        setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [analysisId, router]);

  if (failed) {
    return (
      <div className="grid gap-4">
        <p className="text-sm leading-[1.6] text-missing">{t("timeout")}</p>
        <Button as="a" href="/analyze" variant="secondary" size="sm" className="justify-self-start">
          {t("timeoutAction")}
        </Button>
      </div>
    );
  }

  return (
    <ol className="grid gap-1">
      {STAGES.map((stage, i) => {
        const isDone = i < activeIndex;
        const isActive = i === activeIndex;
        return (
          <li key={stage} className="flex items-center gap-3 py-2">
            <span
              className={cn(
                "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-pill border-[1.5px]",
                isDone && "border-ink bg-ink text-paper",
                isActive && "border-lac border-t-transparent animate-spin",
                !isDone && !isActive && "border-rule",
              )}
            >
              {isDone ? (
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="m5 12 4 4 10-10" />
                </svg>
              ) : null}
            </span>
            <span
              className={cn(
                "text-[15px] leading-[1.6]",
                isDone || isActive ? "font-medium text-ink" : "text-ink-3",
              )}
            >
              {t(`stage.${stage}`)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
