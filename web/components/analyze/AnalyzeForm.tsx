"use client";

import { useTranslations } from "@/lib/copy";
import * as React from "react";

import { hasJobPost, isBlockedJobUrl, JobPostPanel, type JobPostValue } from "@/components/analyze/JobPostPanel";
import { ResumeDropzone } from "@/components/analyze/ResumeDropzone";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useRouter } from "next/navigation";
import { ApiError, createAnalysis, submitJob, uploadResume } from "@/lib/api";
import {
  clearRememberedResume,
  loadRememberedResume,
  saveRememberedResume,
  type RememberedResume,
} from "@/lib/localResume";
import { cn } from "@/lib/utils";

const COUNTRY_KEYS = [
  "cambodia",
  "singapore",
  "japan",
  "usRemote",
  "australia",
  "other",
] as const;

/**
 * The only server error codes this form renders a code-specific message for.
 * Every other code — `RESUME_NOT_FOUND`, `JOB_NOT_FOUND`, anything added
 * later — falls back to `common.error.generic`. An `ApiError.message` is
 * developer-facing English for logs only and is never rendered to a user
 * (docs/errors.md §1, api/errors.py).
 */
const LOCALIZED_CODES = [
  "RESUME_BAD_TYPE",
  "RESUME_TOO_LARGE",
  "JOB_EMPTY",
  "JOB_URL_BLOCKED",
  "JOB_FETCH_FAILED",
] as const;
type LocalizedCode = (typeof LOCALIZED_CODES)[number];

function isLocalizedCode(code: string | undefined): code is LocalizedCode {
  return (LOCALIZED_CODES as readonly string[]).includes(code ?? "");
}

/**
 * Orchestrates the Analyze form (PERSON_B_PLAN_v2.md §5 Phase 1 task 5):
 * resume dropzone + JD tabs + country select, gated submit. Submitting
 * uploads the resume, submits the job post, and creates an analysis against
 * the mock API (Phase 1 task 4), then navigates to the Progress screen,
 * which polls that analysis to completion.
 */
export function AnalyzeForm() {
  const t = useTranslations("analyze");
  const tc = useTranslations("common");
  const te = useTranslations("errors");
  const router = useRouter();
  const [file, setFile] = React.useState<File | null>(null);
  const [jobPost, setJobPost] = React.useState<JobPostValue>({
    mode: "text",
    text: "",
    url: "",
  });
  const [country, setCountry] = React.useState<(typeof COUNTRY_KEYS)[number]>(
    COUNTRY_KEYS[0],
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [resumeError, setResumeError] = React.useState<string | null>(null);
  const [jobError, setJobError] = React.useState<string | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [rememberedResume, setRememberedResume] = React.useState<RememberedResume | null>(
    null,
  );

  React.useEffect(() => {
    setRememberedResume(loadRememberedResume());
  }, []);

  const canSubmit = Boolean(file || rememberedResume) && hasJobPost(jobPost);

  function handleReplaceRememberedResume() {
    clearRememberedResume();
    setRememberedResume(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || submitting) return;

    if (jobPost.mode === "url" && isBlockedJobUrl(jobPost.url)) {
      setJobPost({ ...jobPost, mode: "text" });
      setJobError(te("JOB_URL_BLOCKED"));
      requestAnimationFrame(() => document.getElementById("jd-text")?.focus());
      return;
    }

    setSubmitting(true);
    setResumeError(null);
    setJobError(null);
    setFormError(null);
    try {
      let resumeId: string;
      if (file) {
        const uploaded = await uploadResume(file);
        resumeId = uploaded.resume_id;
        const remembered = { id: resumeId, filename: file.name, size: file.size };
        saveRememberedResume(remembered);
        setRememberedResume(remembered);
      } else {
        // canSubmit guarantees rememberedResume is set when file is not.
        resumeId = rememberedResume!.id;
      }
      const { job_id, cached } = await submitJob(
        jobPost.mode === "text" ? { text: jobPost.text } : { url: jobPost.url },
      );
      const { analysis_id } = await createAnalysis({ resume_id: resumeId, job_id, country });
      router.push(`/progress?id=${analysis_id}${cached ? "&cached=1" : ""}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "RESUME_NOT_FOUND") {
        // The remembered id came from a server session that no longer
        // exists (e.g. the backend restarted) — drop it and ask again.
        clearRememberedResume();
        setRememberedResume(null);
      }
      const code = err instanceof ApiError ? err.code : undefined;
      const message = isLocalizedCode(code) ? te(code) : tc("error.generic");
      if (code === "RESUME_BAD_TYPE" || code === "RESUME_TOO_LARGE") {
        setResumeError(message);
      } else if (code === "JOB_URL_BLOCKED" || code === "JOB_FETCH_FAILED") {
        setJobPost((v) => ({ ...v, mode: "text" }));
        setJobError(message);
        requestAnimationFrame(() => document.getElementById("jd-text")?.focus());
      } else if (code === "JOB_EMPTY") {
        setJobError(message);
        document.getElementById(jobPost.mode === "text" ? "jd-text" : "jd-url")?.focus();
      } else {
        setFormError(message);
      }
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-8">
      <div className="grid gap-8 md:grid-cols-2">
        <Card padding="lg">
          <h2 className="mb-1 font-serif text-xl text-ink">{t("resume.label")}</h2>
          <p className="mb-4 text-sm text-ink-3">{t("resume.dropzoneHint")}</p>
          {!file && rememberedResume ? (
            <div className="flex items-center gap-3.5 border border-rule bg-paper p-3.5">
              <div className="relative flex h-12 w-10 shrink-0 items-center justify-center border border-ink bg-surface-raised">
                <span className="absolute bottom-1 left-0 right-0 text-center font-mono text-[9px] tracking-wide text-ink">
                  {rememberedResume.filename.split(".").pop()?.toUpperCase()}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink">{rememberedResume.filename}</p>
                <p className="font-mono text-xs text-ink-3">{t("resume.remembered")}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                type="button"
                onClick={handleReplaceRememberedResume}
              >
                {t("resume.replace")}
              </Button>
            </div>
          ) : (
            <ResumeDropzone
              file={file}
              onChange={(f) => {
                setFile(f);
                setResumeError(null);
                // Any edit also clears a stale whole-form message — e.g. the
                // one left behind when a remembered resume_id was dropped.
                setFormError(null);
              }}
              serverError={resumeError}
            />
          )}
        </Card>

        <Card padding="lg">
          <h2 className="mb-4 font-serif text-xl text-ink">{t("jd.label")}</h2>
          <JobPostPanel
            value={jobPost}
            onChange={(v) => {
              setJobPost(v);
              setJobError(null);
              setFormError(null);
            }}
            error={jobError}
          />
        </Card>
      </div>

      <div className={cn("grid gap-6 sm:grid-cols-[1fr_auto] sm:items-end")}>
        <div className="grid max-w-sm gap-1.5">
          <label htmlFor="country" className="text-sm font-medium text-ink">
            {t("country.label")}
          </label>
          <select
            id="country"
            value={country}
            onChange={(e) => setCountry(e.target.value as (typeof COUNTRY_KEYS)[number])}
            className="min-h-11 w-full border border-rule bg-paper px-3.5 text-[15px] text-ink"
          >
            {COUNTRY_KEYS.map((key) => (
              <option key={key} value={key}>
                {t(`country.options.${key}`)}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" size="lg" disabled={!canSubmit} loading={submitting}>
          {t("submit")}
        </Button>
      </div>
      {!canSubmit && !submitting ? (
        <p className="-mt-4 font-mono text-sm text-ink-3">{t("submitHint")}</p>
      ) : null}
      {formError ? (
        <p role="alert" className="-mt-4 text-sm text-missing">
          {formError}
        </p>
      ) : null}
    </form>
  );
}
