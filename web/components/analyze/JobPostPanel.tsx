"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { cn } from "@/lib/utils";

export type JobPostMode = "text" | "url";

export interface JobPostValue {
  mode: JobPostMode;
  text: string;
  url: string;
}

export interface JobPostPanelProps {
  value: JobPostValue;
  onChange: (value: JobPostValue) => void;
  error?: string | null;
}

const FIELD_CLASS = cn(
  "min-h-11 w-full rounded-control border border-rule bg-paper px-3.5 py-2.5 text-[15px] leading-[1.6] text-ink",
  "placeholder:text-ink-3",
);

const MODES = ["text", "url"] as const;

/** Paste-text / paste-URL tabs for the job post input — a sliding-pill
 * segmented control (the source design's `.seg`), `role="tablist"`/`"tab"`
 * semantics unchanged underneath. */
export function JobPostPanel({ value, onChange, error }: JobPostPanelProps) {
  const t = useTranslations("analyze.jd");
  const activeIndex = MODES.indexOf(value.mode);

  return (
    <div>
      <div
        role="tablist"
        aria-label={t("label")}
        className="relative mb-4 grid grid-cols-2 rounded-pill border border-rule p-1"
      >
        <span
          aria-hidden="true"
          className="absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-pill bg-accent transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
          style={{ transform: `translateX(${activeIndex * 100}%)` }}
        />
        {MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={value.mode === mode}
            onClick={() => onChange({ ...value, mode })}
            className={cn(
              "relative z-10 min-h-9 rounded-pill text-sm font-medium transition-colors",
              value.mode === mode ? "text-paper" : "text-ink-2 hover:text-ink",
            )}
          >
            {t(`tab.${mode}`)}
          </button>
        ))}
      </div>

      {value.mode === "text" ? (
        <>
          <label htmlFor="jd-text" className="sr-only">
            {t("label")}
          </label>
          <textarea
            id="jd-text"
            className={cn(FIELD_CLASS, "min-h-[236px] resize-y")}
            placeholder={t("placeholderText")}
            value={value.text}
            onChange={(e) => onChange({ ...value, text: e.target.value })}
          />
        </>
      ) : (
        <>
          <label htmlFor="jd-url" className="sr-only">
            {t("label")}
          </label>
          <input
            id="jd-url"
            type="url"
            inputMode="url"
            className={FIELD_CLASS}
            placeholder={t("placeholderUrl")}
            value={value.url}
            onChange={(e) => onChange({ ...value, url: e.target.value })}
          />
        </>
      )}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** True once the current tab's field has enough content to submit. */
export function hasJobPost(value: JobPostValue): boolean {
  if (value.mode === "text") return value.text.trim().length > 40;
  return /^https?:\/\/\S+\.\S+/.test(value.url.trim());
}

const BLOCKED_JOB_HOSTS = ["linkedin.com", "facebook.com"];

/** True if the URL's host is linkedin.com/facebook.com or a subdomain of
 * either — mirrors api/routes/jobs.py's `_is_blocked_job_host` so the same
 * rule fires before the request is even sent (docs/errors.md JOB_URL_BLOCKED
 * recovery: show inline and switch to Paste text before the round trip). */
export function isBlockedJobUrl(url: string): boolean {
  let host: string;
  try {
    host = new URL(url.trim()).hostname.toLowerCase();
  } catch {
    return false;
  }
  return BLOCKED_JOB_HOSTS.some((blocked) => host === blocked || host.endsWith(`.${blocked}`));
}
