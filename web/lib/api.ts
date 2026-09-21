import type { Match } from "@/lib/types";

/**
 * Thin client for the FastAPI mock/live service (PERSON_B_PLAN_v2.md §5
 * Phase 1 task 4). Every call is a relative `/api/*` path — the browser only
 * ever talks to its own origin; `next.config.ts` rewrites server-side to the
 * actual service, so there is no CORS configuration anywhere.
 */
export class ApiError extends Error {
  code?: string;

  constructor(message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail: { code?: string; message?: string } | undefined;
  try {
    const body = await res.json();
    detail = body?.detail;
  } catch {
    // Non-JSON error body — fall through to the generic message below.
  }
  return new ApiError(detail?.message ?? `Request failed (${res.status})`, detail?.code);
}

export async function uploadResume(file: File): Promise<{ resume_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/resumes", { method: "POST", body: form });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export type JobInput = { text: string } | { url: string };

export async function submitJob(
  input: JobInput,
): Promise<{ job_id: string; cached: boolean }> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export async function fetchJobFromUrl(
  url: string,
): Promise<{ text: string; url: string; word_count: number }> {
  const res = await fetch("/api/jobs/fetch-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface CreateAnalysisInput {
  resume_id: string;
  job_id: string;
  country: string;
}

export async function createAnalysis(
  input: CreateAnalysisInput,
): Promise<{ analysis_id: string; status: string }> {
  const res = await fetch("/api/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface AnalysisStatusResponse {
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  match: Match | null;
}

export async function getAnalysis(id: string): Promise<AnalysisStatusResponse> {
  const res = await fetch(`/api/analyses/${id}`);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface RewritesResponse {
  hidden_strengths: Array<{
    requirement_id: string;
    evidence_id: string;
    current_phrasing: string;
    suggested_phrasing: string;
    facts_used: string[];
    changed_words: string[];
  }>;
  rejections_count: number;
}

export async function generateRewrites(analysisId: string): Promise<RewritesResponse> {
  const res = await fetch(`/api/analyses/${analysisId}/rewrites`, { method: "POST" });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface AnalysisHistoryItem {
  id: string;
  resume_id: string;
  job_id: string;
  country: string;
  status: string;
  job_title: string;
  company?: string;
  coverage_score: number;
  realism_verdict: string;
  created_at?: string;
}

export async function getAnalysesHistory(resumeId?: string): Promise<AnalysisHistoryItem[]> {
  const url = resumeId ? `/api/analyses?resume_id=${encodeURIComponent(resumeId)}` : "/api/analyses";
  const res = await fetch(url);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface CountryRulesResponse {
  country_code: string;
  name: string;
  max_pages: number;
  photo_recommended: boolean;
  include_personal_details: boolean;
  date_format: string;
  section_order: string[];
  tone_notes: string;
  visa_terms: string[];
}

export async function getCountryRules(code: string): Promise<CountryRulesResponse> {
  const res = await fetch(`/api/country/rules/${code}`);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}
