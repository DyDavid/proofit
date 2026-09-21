"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { fetchJobFromUrl, ApiError } from "@/lib/api";
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
}

const FIELD_CLASS = cn(
  "min-h-11 w-full border border-rule bg-paper px-3.5 py-2.5 text-[15px] leading-[1.6] text-ink",
  "placeholder:text-ink-3",
);

/** Paste-text / paste-URL tabs for the job post input. */
export function JobPostPanel({ value, onChange }: JobPostPanelProps) {
  const t = useTranslations("analyze.jd");
  const [fetching, setFetching] = React.useState(false);
  const [fetchError, setFetchError] = React.useState<string | null>(null);
  const [fetchSuccess, setFetchSuccess] = React.useState<string | null>(null);

  const blocked = isBlockedUrl(value.url);

  async function handleFetchUrl() {
    if (!value.url.trim() || blocked || fetching) return;
    setFetching(true);
    setFetchError(null);
    setFetchSuccess(null);

    try {
      const res = await fetchJobFromUrl(value.url.trim());
      setFetchSuccess(`Successfully fetched ${res.word_count} words! Switched to text editor so you can review.`);
      onChange({
        ...value,
        mode: "text",
        text: res.text,
      });
    } catch (err) {
      setFetchError(
        err instanceof ApiError
          ? err.message
          : "Could not fetch job from this URL. Please copy and paste the text directly.",
      );
    } finally {
      setFetching(false);
    }
  }

  return (
    <div>
      <div role="tablist" aria-label={t("label")} className="mb-4 flex gap-1 border-b border-rule">
        {(["text", "url"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={value.mode === mode}
            onClick={() => {
              setFetchError(null);
              onChange({ ...value, mode });
            }}
            className={cn(
              "-mb-px min-h-11 border-b-2 px-3 text-sm font-medium transition-colors",
              value.mode === mode
                ? "border-ink text-ink"
                : "border-transparent text-ink-3 hover:text-ink",
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
          {fetchSuccess && (
            <p className="mt-2 text-xs font-medium text-emerald-700">
              ✓ {fetchSuccess}
            </p>
          )}
        </>
      ) : (
        <div className="grid gap-3">
          <label htmlFor="jd-url" className="sr-only">
            {t("label")}
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="jd-url"
              type="url"
              inputMode="url"
              className={FIELD_CLASS}
              placeholder={t("placeholderUrl")}
              value={value.url}
              onChange={(e) => {
                setFetchError(null);
                onChange({ ...value, url: e.target.value });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleFetchUrl();
                }
              }}
            />
            <button
              type="button"
              onClick={handleFetchUrl}
              disabled={fetching || !value.url.trim() || blocked}
              className={cn(
                "inline-flex shrink-0 items-center justify-center border border-rule px-4 py-2.5 text-sm font-medium transition-colors",
                fetching || !value.url.trim() || blocked
                  ? "cursor-not-allowed bg-paper-2 text-ink-3 opacity-60"
                  : "bg-surface-raised text-ink hover:bg-ink hover:text-paper",
              )}
            >
              {fetching ? "Fetching..." : "Fetch & Review"}
            </button>
          </div>

          <p className="text-xs text-ink-3">
            Supports <strong>BongThom</strong>, <strong>CamHR</strong>, company career pages, and public job boards.
          </p>

          {blocked && (
            <div className="rounded border border-amber-300 bg-amber-50 p-3.5 text-xs leading-[1.6] text-amber-900">
              <p className="font-semibold">⚠️ LinkedIn & Facebook cannot be scraped directly</p>
              <p className="mt-1">
                These platforms require user login sessions to view job details.
              </p>
              <button
                type="button"
                onClick={() => onChange({ ...value, mode: "text" })}
                className="mt-2.5 inline-block font-medium underline underline-offset-2 hover:text-amber-950"
              >
                Switch to Paste Text tab →
              </button>
            </div>
          )}

          {fetchError && !blocked && (
            <div className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              {fetchError}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function isBlockedUrl(url: string): boolean {
  const lower = url.trim().toLowerCase();
  return lower.includes("linkedin.com") || lower.includes("facebook.com");
}

export function hasJobPost(value: JobPostValue): boolean {
  if (value.mode === "text") return value.text.trim().length > 40;
  if (isBlockedUrl(value.url)) return false;
  return /^https?:\/\/\S+\.\S+/.test(value.url.trim());
}
