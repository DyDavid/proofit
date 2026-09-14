"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { JobPostPanel, hasJobPost, type JobPostValue } from "@/components/analyze/JobPostPanel";
import { ResumeDropzone } from "@/components/analyze/ResumeDropzone";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useRouter } from "@/i18n/routing";
import { ApiError, createAnalysis, submitJob, uploadResume } from "@/lib/api";
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

  const canSubmit = Boolean(file) && hasJobPost(jobPost);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || submitting || !file) return;

    setSubmitting(true);
    setResumeError(null);
    setJobError(null);
    setFormError(null);
    try {
      const { resume_id } = await uploadResume(file);
      const { job_id } = await submitJob(
        jobPost.mode === "text" ? { text: jobPost.text } : { url: jobPost.url },
      );
      const { analysis_id } = await createAnalysis({ resume_id, job_id, country });
      router.push(`/progress?id=${analysis_id}`);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : undefined;
      const message =
        code &&
        (["RESUME_BAD_TYPE", "RESUME_TOO_LARGE", "JOB_EMPTY"] as const).includes(
          code as "RESUME_BAD_TYPE" | "RESUME_TOO_LARGE" | "JOB_EMPTY",
        )
          ? te(code as "RESUME_BAD_TYPE" | "RESUME_TOO_LARGE" | "JOB_EMPTY")
          : err instanceof ApiError
            ? err.message
            : tc("error.generic");
      if (code === "RESUME_BAD_TYPE" || code === "RESUME_TOO_LARGE") {
        setResumeError(message);
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
          <ResumeDropzone file={file} onChange={setFile} serverError={resumeError} />
        </Card>

        <Card padding="lg">
          <h2 className="mb-4 font-serif text-xl text-ink">{t("jd.label")}</h2>
          <JobPostPanel value={jobPost} onChange={setJobPost} error={jobError} />
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
