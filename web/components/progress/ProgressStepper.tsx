"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { useRouter } from "next/navigation";
import { getAnalysis, retryAnalysis } from "@/lib/api";
import { cn } from "@/lib/utils";

const STAGES = [
  "reading_resume",
  "reading_job",
  "matching_requirements",
  "checking_realism",
] as const;

const POLL_INTERVAL_MS = 1000;
const STEP_ADVANCE_MS = 250;
const TIMEOUT_MS = 120_000;

export interface ProgressStepperProps {
  analysisId: string;
}

interface ServerErrorState {
  code: string;
  errorId: string;
}

/**
 * Polls `GET /api/analyses/{id}` every 1s and drives the stepper from the
 * real `stage` field, smoothly stepping through intermediate stages so every
 * checkmark is visibly completed in sequence before navigating to `/results`.
 */
export function ProgressStepper({ analysisId }: ProgressStepperProps) {
  const t = useTranslations("progress");
  const te = useTranslations("errors");
  const tc = useTranslations("common");
  const router = useRouter();
  const [currentId, setCurrentId] = React.useState(analysisId);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const [targetIndex, setTargetIndex] = React.useState(0);
  const [isFinished, setIsFinished] = React.useState(false);
  const [timedOut, setTimedOut] = React.useState(false);
  const [serverError, setServerError] = React.useState<ServerErrorState | null>(null);
  const [retrying, setRetrying] = React.useState(false);
  const [retryFailed, setRetryFailed] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const startedAtRef = React.useRef<number | null>(null);
  const pollRef = React.useRef<() => void>(() => {});

  // Smoothly advance `activeIndex` one step at a time up to `targetIndex`
  React.useEffect(() => {
    if (activeIndex < targetIndex) {
      const timer = setTimeout(() => {
        setActiveIndex((prev) => Math.min(prev + 1, targetIndex));
      }, STEP_ADVANCE_MS);
      return () => clearTimeout(timer);
    }
    if (isFinished && activeIndex >= STAGES.length) {
      const timer = setTimeout(() => {
        router.push(`/results?id=${currentId}`);
      }, 200);
      return () => clearTimeout(timer);
    }
  }, [activeIndex, targetIndex, isFinished, currentId, router]);

  React.useEffect(() => {
    let cancelled = false;
    startedAtRef.current = Date.now();
    setTimedOut(false);
    setServerError(null);
    setRetryFailed(false);
    setActiveIndex(0);
    setTargetIndex(0);
    setIsFinished(false);

    async function poll() {
      const elapsed = Date.now() - (startedAtRef.current ?? Date.now());
      try {
        const res = await getAnalysis(currentId);
        if (cancelled) return;

        if (res.status === "done") {
          setTargetIndex(STAGES.length);
          setIsFinished(true);
          return;
        }
        if (res.status === "failed") {
          setServerError({
            code: res.error?.code ?? "INTERNAL",
            errorId: res.error?.error_id ?? "",
          });
          return;
        }
        if (elapsed > TIMEOUT_MS) {
          setTimedOut(true);
          return;
        }

        const index = STAGES.indexOf(res.stage as (typeof STAGES)[number]);
        if (index >= 0) {
          setTargetIndex((prev) => Math.max(prev, index));
        }
        setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (cancelled) return;
        if (elapsed > TIMEOUT_MS) {
          setTimedOut(true);
          return;
        }
        setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    pollRef.current = poll;
    poll();
    return () => {
      cancelled = true;
    };
  }, [currentId, router]);

  function keepWaiting() {
    startedAtRef.current = Date.now();
    setTimedOut(false);
    pollRef.current();
  }

  async function retry() {
    setRetrying(true);
    setRetryFailed(false);
    try {
      const { analysis_id } = await retryAnalysis(currentId);
      setCurrentId(analysis_id);
      setServerError(null);
    } catch {
      // Retry itself failed (e.g. the original analysis is gone server-side
      // after a restart). Say so instead of silently reverting the spinner —
      // the card's "Back" link is then the way out.
      setRetryFailed(true);
    } finally {
      setRetrying(false);
    }
  }

  async function copyErrorId() {
    if (!serverError?.errorId) return;
    try {
      await navigator.clipboard.writeText(serverError.errorId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — nothing to do; the id is still visible as text.
    }
  }

  if (serverError) {
    const knownCodes = [
      "RESUME_UNREADABLE",
      "JOB_FETCH_FAILED",
      "ENGINE_FAILED",
      "RATE_LIMITED",
      "INTERNAL",
    ] as const;
    const message = (knownCodes as readonly string[]).includes(serverError.code)
      ? te(serverError.code as (typeof knownCodes)[number])
      : te("INTERNAL");

    return (
      <div className="grid gap-4">
        <p className="text-sm leading-[1.6] text-missing">{message}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={retry}
            loading={retrying}
          >
            {tc("action.retry")}
          </Button>
          <Button as="a" href="/analyze" variant="ghost" size="sm">
            {tc("action.back")}
          </Button>
          {serverError.errorId ? (
            <button
              type="button"
              onClick={copyErrorId}
              className="font-mono text-xs text-ink-3 underline decoration-rule underline-offset-2 hover:decoration-ink"
            >
              {copied ? tc("action.copy") + " ✓" : `${serverError.errorId} · ${tc("action.copy")}`}
            </button>
          ) : null}
        </div>
        {retryFailed ? (
          <p role="alert" className="text-sm leading-[1.6] text-ink-2">
            {tc("error.generic")}
          </p>
        ) : null}
      </div>
    );
  }

  if (timedOut) {
    return (
      <div className="grid gap-4">
        <p className="text-sm leading-[1.6] text-ink-2">{t("timeout")}</p>
        <div className="flex flex-wrap gap-3">
          <Button type="button" variant="secondary" size="sm" onClick={keepWaiting}>
            {t("timeoutAction")}
          </Button>
          <Button as="a" href="/analyze" variant="ghost" size="sm">
            {t("timeoutRetry")}
          </Button>
        </div>
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
                isActive && "border-accent border-t-transparent animate-spin",
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
