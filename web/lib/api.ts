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
