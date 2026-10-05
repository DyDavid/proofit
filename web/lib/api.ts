import type { BaselineMatch, HiddenStrength, Match } from "@/lib/types";

/**
 * Thin client for the FastAPI mock/live service (PERSON_B_PLAN_v2.md §5
 * Phase 1 task 4). Every call is a relative `/api/*` path — the browser only
 * ever talks to its own origin; `next.config.ts` rewrites server-side to the
 * actual service, so there is no CORS configuration anywhere.
 */
export class ApiError extends Error {
  code?: string;
  errorId?: string;

  constructor(message: string, code?: string, errorId?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.errorId = errorId;
  }
}

type ErrorFields = { code?: string; message?: string; error_id?: string };

/**
 * Pulls `{code, message, error_id}` out of an error body. The API's own envelope
 * is `{"error": {...}}` (api/errors.py). A backend that has not been redeployed
 * yet, or FastAPI's stock HTTPException, answers `{"detail": {...}}` or
 * `{"detail": "text"}` instead; reading those too keeps error codes working
 * (e.g. RESUME_NOT_FOUND clearing a stale remembered resume) while the two
 * halves are on different versions.
 */
function readErrorFields(body: unknown): ErrorFields | undefined {
  if (typeof body !== "object" || body === null) return undefined;
  const { error, detail } = body as { error?: unknown; detail?: unknown };
  if (typeof error === "object" && error !== null) return error as ErrorFields;
  if (typeof detail === "object" && detail !== null) return detail as ErrorFields;
  if (typeof detail === "string") return { message: detail };
  return undefined;
}

async function toApiError(res: Response): Promise<ApiError> {
  let error: ErrorFields | undefined;
  try {
    error = readErrorFields(await res.json());
  } catch {
    // Non-JSON error body — fall through to the generic message below.
  }
  return new ApiError(
    error?.message ?? `Request failed (${res.status})`,
    error?.code,
    error?.error_id,
  );
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

export async function retryAnalysis(
  id: string,
): Promise<{ analysis_id: string; status: string }> {
  const res = await fetch(`/api/analyses/${id}/retry`, { method: "POST" });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface CreateRewritesResponse {
  hidden_strengths: HiddenStrength[];
  rejected_count: number;
}

/**
 * Runs the F5 rewrite pipeline for one completed analysis (Phase 4 task 3:
 * the Hidden Strengths section). Opt-in and costs real LLM calls server-side,
 * so this is only ever invoked from a direct button press, never on mount.
 * `POST /api/analyses/{id}/rewrites` takes no body — `analysis_id` in the
 * path is the whole request, same shape as `retryAnalysis` above.
 */
export async function createRewrites(id: string): Promise<CreateRewritesResponse> {
  const res = await fetch(`/api/analyses/${id}/rewrites`, { method: "POST" });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface AnalysisStatusResponse {
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  match: Match | null;
  baseline: BaselineMatch | null;
  error: { code: string; message: string; error_id: string } | null;
}

export async function getAnalysis(id: string): Promise<AnalysisStatusResponse> {
  const res = await fetch(`/api/analyses/${id}`);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export interface AnalysisSummary {
  analysis_id: string;
  job_title: string;
  company: string | null;
  coverage: number;
  realism_verdict: string;
  created_at: string;
}

export async function getAnalysisHistory(resumeId: string): Promise<AnalysisSummary[]> {
  const res = await fetch(`/api/analyses?resume_id=${encodeURIComponent(resumeId)}`);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

/**
 * F6 — one destination market's resume conventions (`engine.country.rules.
 * CountryRules`). Not part of `web/lib/types.ts`: that file is generated
 * from `engine/normalize/schema.py`'s `SchemaBundle`
 * (PERSON_B_PLAN_v2.md §2), and F6's config model lives in
 * `engine/country/rules.py`, a separate module never bundled into it.
 */

export interface CountryRules {
  code: string;
  display_name: string;
  aliases: string[];
  max_pages: number;
  page_length_note: string;
  include_photo: boolean;
  photo_note: string;
  include_personal_details: string[];
  omit_personal_details: string[];
  date_format: string;
  date_format_example: string;
  section_order: string[];
  tone_notes: string[];
  visa_terms: string[];
}

/**
 * Fetches one destination's full rule set (Phase 4 task 4: the Results
 * screen's country checklist, `CountryFormat.tsx`). `destination` may be any
 * of this codebase's three spellings — `rules_for`
 * (engine/country/rules.py) resolves them all. Throws `ApiError` with code
 * `COUNTRY_RULES_NOT_FOUND` (404) for the UI's "other" destination and for
 * anything unrecognised — a normal, expected outcome the caller should
 * degrade for, not an unexpected failure.
 */
export async function getCountryRules(destination: string): Promise<CountryRules> {
  const res = await fetch(`/api/countries/${encodeURIComponent(destination)}`);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

/** One entry from `GET /api/countries` — just enough to populate a
 * destination selector. `display_name` is English only (same convention as
 * `CountryRules`); the UI's own labels still come from `results.country.
 * destinations.*` so locale switching keeps working. */
export interface CountryListEntry {
  code: string;
  display_name: string;
}

/**
 * Every market this app has rules for, in `rules.json`'s own order
 * (Phase 4 hardening task 5). `CountryFormat.tsx`'s destination selector
 * fetches this instead of hardcoding the code list a second time, so a
 * country added to `engine/country/rules.json` needs no matching UI change.
 * The UI's sixth option, "other", is deliberately absent from this response
 * — see `api/routes/countries.py` — and is still added by the caller.
 */
export async function getCountries(): Promise<CountryListEntry[]> {
  const res = await fetch("/api/countries");
  if (!res.ok) throw await toApiError(res);
  const body = (await res.json()) as { countries: CountryListEntry[] };
  return body.countries;
}
