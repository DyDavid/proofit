"use client";

import { useTranslations } from "next-intl";
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
}

const FIELD_CLASS = cn(
  "min-h-11 w-full border border-rule bg-paper px-3.5 py-2.5 text-[15px] leading-[1.6] text-ink",
  "placeholder:text-ink-3",
);

/** Paste-text / paste-URL tabs for the job post input. */
export function JobPostPanel({ value, onChange }: JobPostPanelProps) {
  const t = useTranslations("analyze.jd");

  return (
    <div>
      <div role="tablist" aria-label={t("label")} className="mb-4 flex gap-1 border-b border-rule">
        {(["text", "url"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={value.mode === mode}
            onClick={() => onChange({ ...value, mode })}
            className={cn(
              "-mb-px min-h-11 border-b-2 px-3 text-sm font-medium",
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
    </div>
  );
}

/** True once the current tab's field has enough content to submit. */
export function hasJobPost(value: JobPostValue): boolean {
  if (value.mode === "text") return value.text.trim().length > 40;
  return /^https?:\/\/\S+\.\S+/.test(value.url.trim());
}
