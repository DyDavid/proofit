# Phase 3 — URL Path, History, and Starting F5 Early — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Paste-URL tab (with a client+server LinkedIn/Facebook block and a content-hash-cache badge), add a per-resume analysis history list, and build the whole F5 rewrite engine — detector, generator, two-layer hallucination validator, rejection log, and the API endpoint that orchestrates them — entirely against `ENGINE_MODE=mock` fixtures and hand-built schema objects, with every LLM call point mockable so the test suite needs no `ANTHROPIC_API_KEY`.

**Architecture:** F5 (`engine/rewrite/`) is Person B's own package — unlike `engine.match`/`engine.ingest`, it is not one of the five ownership-boundary contract callables (`engine/README.md`), so `api/` may call its functions directly. Its three public functions (`detect_hidden_strengths`, `generate_rewrite`, `validate_rewrite`) are pure, LLM-backed, and independently unit-testable via one shared `call_structured` helper that every test monkeypatches. The API's new `POST /api/analyses/{id}/rewrites` endpoint is the only place that composes them, retries a failed validation once, logs every failure, and folds accepted output back into the stored `Match` by re-validating the whole object (never a raw `list.append`, which would bypass `Match`'s own integrity checks). The URL and History tasks are thin: a host-blocklist check that needs no fetching, and a read endpoint over data the mock engine already produces.

**Tech Stack:** FastAPI + Pydantic v2 (existing), Anthropic Python SDK (`anthropic`, already a declared dependency in `pyproject.toml`'s `api` extra, not yet used anywhere in this codebase), Next.js 15 / React / next-intl (existing), pytest + `unittest.mock` (existing).

**Spec:** `PERSON_B_PLAN_v2.md` lines 255–284 (Phase 3), `PROJECT_SPEC.md` §9 (non-negotiable rules) and §4 F5, `engine/README.md` (ownership + the five contract callables), `docs/errors.md` (the error envelope and the ten-code matrix this plan extends to eleven).

## Global Constraints

- **Rule 1 (no invented facts, PROJECT_SPEC.md §9).** Every generated claim must cite an `evidence_id`; a validation pass rejects any claim with no traceable source. This is F5's entire reason to exist — it is not a nice-to-have on top of the feature.
- **Rule 2 (no scope inflation, PROJECT_SPEC.md §9).** A class project may never be reframed as professional employment. Phase 3's deterministic pre-check does not enforce this directly (that is Phase 4's wordlist gate) — it is caught by the LLM validation layer in Phase 3, and this plan's test suite proves that layer actually catches it.
- **Rule 6 (never scrape Facebook or LinkedIn, PROJECT_SPEC.md §9).** Enforced as a pure host-string check, both client- and server-side. It needs no fetching and is therefore not blocked on `engine.ingest.fetch_jd`.
- **The internals rule (`engine/README.md`).** `api/` may only call the five ownership-boundary contract callables belonging to Person A's packages. `engine.rewrite` is Person B's own package and is not on that boundary — `api/` calling `detect_hidden_strengths`/`generate_rewrite`/`validate_rewrite` directly is correct, not a violation.
- **Nothing in `engine/` imports FastAPI, reads a request, or knows about a locale** (`engine/README.md`). The Anthropic client reads `ANTHROPIC_API_KEY` from the environment itself; `engine/rewrite/llm.py` never imports `api.config`.
- **`extra="forbid"` on every Pydantic model** (`engine/normalize/schema.py`'s own convention) — a typo fails loudly. New models in `engine/rewrite/models.py` follow the same rule with their own local `_Base`, decoupled from `schema.py`'s private `_Base` since that file is provisional until CP1.
- **Bilingual strings.** Every new user-facing string gets both an `en` and a `km` entry in `web/messages/*.json`, even though `km.json` currently holds English placeholders pending the Phase 5 Khmer QA session (`docs/errors.md` §4) — that is the established Phase 2 precedent, not a new decision.
- **Never raise a bare `HTTPException` from a route** (`api/errors.py`) — always `ApiError` with one of the established codes, or a new one added to `docs/errors.md` §2 with the same justification.
- **No new frontend test runner.** `web/package.json` has no `vitest`/`jest`; frontend verification is `tsc --noEmit`, `eslint`, `node scripts/i18n-check.mjs`, and manual QA — matching every prior phase.
- **Python environment:** `/Users/macbook/AUPP_FALL_2026/FYP/.venv/bin/python`, never bare `python3` (3.14 system Python is not this project's runtime).
- **Test commands:** `.venv/bin/python -m pytest tests/ -v` (all), or `-k <name>` for one file/test; `.venv/bin/python -m ruff check engine api tests`; `.venv/bin/python -m mypy` (strict, per `pyproject.toml`).
- **Frontend commands (from `web/`):** `npx tsc --noEmit`, `npm run lint`; **from repo root:** `node scripts/i18n-check.mjs`.

## Design decisions worth flagging in review

1. **`detect_hidden_strengths` returns `list[HiddenStrengthCandidate]`, not `list[HiddenStrength]`.** The plan's literal signature (`§5 Phase 3.3`) says `-> list[HiddenStrength]`, but `HiddenStrength` requires `suggested_phrasing`/`facts_used` (both non-empty, schema-enforced) — fields that don't exist until *after* `generate_rewrite` runs. `HiddenStrengthCandidate` (Task 5) is the lighter intermediate type; the full `HiddenStrength` is only constructed once a candidate has cleared `generate_rewrite` + `validate_rewrite` (Task 10). This is also why detect/generate/validate are three separate, independently callable functions rather than one nested call chain — `POST /api/analyses/{id}/rewrites` is where they compose, which is also the only place retry-on-failure can live.
2. **`rewrite_rejections` lives in the in-memory store (`api/store.py`), not a real DB table.** `engine/README.md` line 30 gives DB migrations to Person A, but nothing in this codebase has a real database yet — `Match`, `Job`, `JobRecord`, `AnalysisRecord` all live in `api/store.py`'s in-memory `Store` until Supabase is wired at CP2. Adding `rewrite_rejections` there follows the exact same, already-established pattern rather than blocking F5's rejection log on a migration nobody can write yet.
3. **History is keyed by the browser's remembered `resume_id` (`web/lib/localResume.ts`, built in Phase 2), not a new cookie mechanism.** The plan text says "identify the user by an anonymous cookie id," but the endpoint's own signature is `GET /api/analyses?resume_id=` — an anonymous, per-browser resume id is exactly what Phase 2 already built and remembers in `localStorage`. Introducing a second, parallel anonymous-identity mechanism for the same purpose would be pure duplication.
4. **A new, eleventh error code: `ANALYSIS_NOT_READY` (409).** None of the existing ten codes fit "the analysis exists but has not finished yet," which `POST /api/analyses/{id}/rewrites` can hit. `docs/errors.md`'s own stated policy for this exact situation: "either add a specific code or fix the cause" (§2, `INTERNAL`'s entry) — Task 10 adds it, with matching entries in `docs/errors.md` §2 and both `web/messages/*.json`.
5. **Server-side `JOB_URL_BLOCKED` needs no `engine.ingest.fetch_jd`.** It is a pure `urlparse(url).hostname` string check — Task 1 closes out the *server* half of the block without waiting on Person A's fetcher, which is only needed for the two codes this phase leaves unreachable: the URL actually being *fetched* is still CP2.

---

### Task 1: Server-side `JOB_URL_BLOCKED` for LinkedIn/Facebook

**Files:**
- Modify: `api/routes/jobs.py`
- Test: `tests/test_routes_errors.py`

**Interfaces:**
- Produces: `_is_blocked_job_host(url: str) -> bool` in `api/routes/jobs.py`, used by Task 2's client-side mirror only as a design reference (the frontend has its own copy — no shared module crosses the Python/TypeScript boundary).

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_routes_errors.py`:

```python
def test_job_url_blocked_for_linkedin() -> None:
    res = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/1234"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_URL_BLOCKED"


def test_job_url_blocked_for_facebook_subdomain() -> None:
    res = client.post("/api/jobs", json={"url": "https://m.facebook.com/jobs/1234"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_URL_BLOCKED"


def test_job_url_allowed_for_other_hosts() -> None:
    res = client.post("/api/jobs", json={"url": "https://www.camhr.com/job/1234"})
    assert res.status_code == 200
    assert res.json()["cached"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_routes_errors.py -v`
Expected: the two new `_blocked_` tests FAIL (no `JOB_URL_BLOCKED` is ever raised today); `test_job_url_allowed_for_other_hosts` passes already.

- [ ] **Step 3: Implement the blocklist check**

In `api/routes/jobs.py`, add the import and helper near the top (after the existing imports), and call it in `submit_job`:

```python
from urllib.parse import urlparse

from api.errors import ApiError
from api.store import store

router = APIRouter()

_BLOCKED_JOB_HOSTS: frozenset[str] = frozenset({"linkedin.com", "facebook.com"})


def _is_blocked_job_host(url: str) -> bool:
    """True if `url`'s host is linkedin.com/facebook.com or a subdomain of
    either (PROJECT_SPEC.md §9 rule 6). A pure string check on the URL as
    given — it never fetches anything, so it needs none of Person A's
    engine.ingest.fetch_jd (still NotImplementedError until CP2)."""
    host = (urlparse(url).hostname or "").lower()
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in _BLOCKED_JOB_HOSTS)
```

Then in `submit_job`, after the XOR check and before the two branches, add the block check on the url branch:

```python
    if text:
        if len(text) < 40:
            raise ApiError(
                status_code=422,
                code="JOB_EMPTY",
                message="Job text is present but too short to be a real job post.",
            )
        record, cached = store.add_job(text, source="text")
    else:
        if _is_blocked_job_host(url):
            raise ApiError(
                status_code=422,
                code="JOB_URL_BLOCKED",
                message="Host is on the LinkedIn/Facebook blocklist (PROJECT_SPEC.md §9 rule 6).",
            )
        record, cached = store.add_job(url, source="url")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_routes_errors.py -v`
Expected: all tests PASS, including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add api/routes/jobs.py tests/test_routes_errors.py
git commit -m "feat(api): block LinkedIn/Facebook job URLs server-side"
```

---

### Task 2: Client-side URL blocking + the content-hash cache badge

**Files:**
- Modify: `web/components/analyze/JobPostPanel.tsx`
- Modify: `web/components/analyze/AnalyzeForm.tsx`
- Modify: `web/app/[locale]/progress/page.tsx`
- Modify: `web/messages/en.json`, `web/messages/km.json`

**Interfaces:**
- Consumes: `ApiError`, `submitJob` (`web/lib/api.ts`, unchanged signature — `submitJob` already returns `{job_id, cached}`).
- Produces: `isBlockedJobUrl(url: string): boolean`, exported from `JobPostPanel.tsx`, alongside the existing `hasJobPost`.

- [ ] **Step 1: Add the client-side host check to `JobPostPanel.tsx`**

At the end of `web/components/analyze/JobPostPanel.tsx`, alongside `hasJobPost`:

```ts
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
```

- [ ] **Step 2: Wire it into `AnalyzeForm.tsx`, and handle the server codes too**

Update the imports and the localized-codes list:

```ts
import { hasJobPost, isBlockedJobUrl, JobPostPanel, type JobPostValue } from "@/components/analyze/JobPostPanel";
```

```ts
const LOCALIZED_CODES = [
  "RESUME_BAD_TYPE",
  "RESUME_TOO_LARGE",
  "JOB_EMPTY",
  "JOB_URL_BLOCKED",
  "JOB_FETCH_FAILED",
] as const;
```

In `handleSubmit`, right after the `if (!canSubmit || submitting) return;` guard and before `setSubmitting(true)`, add the pre-flight block:

```ts
    if (jobPost.mode === "url" && isBlockedJobUrl(jobPost.url)) {
      setJobPost({ ...jobPost, mode: "text" });
      setJobError(te("JOB_URL_BLOCKED"));
      requestAnimationFrame(() => document.getElementById("jd-text")?.focus());
      return;
    }
```

In the `catch` block, add a branch for the two URL codes before the existing `JOB_EMPTY` branch — both get the same "switch to Paste text" recovery (`docs/errors.md` JOB_URL_BLOCKED and JOB_FETCH_FAILED entries):

```ts
      if (code === "RESUME_BAD_TYPE" || code === "RESUME_TOO_LARGE") {
        setResumeError(message);
      } else if (code === "JOB_URL_BLOCKED" || code === "JOB_FETCH_FAILED") {
        setJobPost((v) => ({ ...v, mode: "text" }));
        setJobError(message);
        document.getElementById("jd-text")?.focus();
      } else if (code === "JOB_EMPTY") {
```

- [ ] **Step 3: Pass `cached` through to the Progress screen**

In `handleSubmit`, capture `cached` and add it to the navigation query string:

```ts
      const { job_id, cached } = await submitJob(
        jobPost.mode === "text" ? { text: jobPost.text } : { url: jobPost.url },
      );
      const { analysis_id } = await createAnalysis({ resume_id: resumeId, job_id, country });
      router.push(`/progress?id=${analysis_id}${cached ? "&cached=1" : ""}`);
```

- [ ] **Step 4: Render the badge on the Progress page**

In `web/app/[locale]/progress/page.tsx`:

```tsx
import { getLocale, getTranslations } from "next-intl/server";

import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { ProgressStepper } from "@/components/progress/ProgressStepper";
import { redirect } from "@/i18n/routing";

export interface ProgressPageProps {
  searchParams: Promise<{ id?: string; cached?: string }>;
}

export default async function ProgressPage({ searchParams }: ProgressPageProps) {
  const { id, cached } = await searchParams;
  if (!id) {
    redirect({ href: "/analyze", locale: await getLocale() });
  }

  const t = await getTranslations("progress");
  const tc = await getTranslations("common");

  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-md items-center px-4 py-16 sm:px-6">
      <Card padding="lg" className="w-full">
        <p className="mb-1 font-mono text-xs uppercase tracking-wide text-ink-3">
          {t("title")}
        </p>
        {cached === "1" ? (
          <Badge tone="lac" className="mb-3">
            {t("cachedBadge")}
          </Badge>
        ) : null}
        <h1 className="mb-6 font-serif text-2xl text-ink">{tc("loading")}</h1>
        <ProgressStepper analysisId={id as string} />
      </Card>
    </div>
  );
}
```

- [ ] **Step 5: Add the i18n key**

In `web/messages/en.json`, inside `"progress"`, add:

```json
    "cachedBadge": "Already analyzed — loaded instantly"
```

In `web/messages/km.json`, inside `"progress"`, add the same English string (Phase 5 Khmer QA session confirms real Khmer later — matching every other key in this file today):

```json
    "cachedBadge": "Already analyzed — loaded instantly"
```

- [ ] **Step 6: Verify**

Run: `cd web && npx tsc --noEmit && npm run lint`
Run: `node scripts/i18n-check.mjs` (from the repo root)
Expected: all clean.

Manual QA (no frontend test runner in this repo — `docs/errors.md`'s own established verification method): start the dev server, go to Analyze, paste `https://www.linkedin.com/jobs/view/1` into the URL tab, submit — confirm it switches to Paste Text with the inline error, without a network call. Then submit the exact same JD text twice in a row (two separate analyses) — confirm the second run's Progress screen shows the "Already analyzed — loaded instantly" badge.

- [ ] **Step 7: Commit**

```bash
git add web/components/analyze/JobPostPanel.tsx web/components/analyze/AnalyzeForm.tsx \
        "web/app/[locale]/progress/page.tsx" web/messages/en.json web/messages/km.json
git commit -m "feat(web): block LinkedIn/Facebook URLs client-side, show the cache badge"
```

---

### Task 3: History API — `GET /api/analyses?resume_id=`

**Files:**
- Modify: `api/store.py`
- Modify: `api/routes/analyses.py`
- Test: `tests/test_analyses_history.py` (new)

**Interfaces:**
- Consumes: `Match.job.title`, `Match.job.company`, `Match.coverage_required_only`, `Match.realism_verdict` (all existing `engine/normalize/schema.py` fields).
- Produces: `Store.analyses_for_resume(resume_id: str) -> list[AnalysisRecord]`; `AnalysisSummary` Pydantic model in `api/routes/analyses.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analyses_history.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _create_done_analysis(resume_id: str, job_text: str) -> str:
    job_id = client.post("/api/jobs", json={"text": job_text}).json()["job_id"]
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
    ).json()["analysis_id"]
    for _ in range(50):
        res = client.get(f"/api/analyses/{analysis_id}").json()
        if res["status"] == "done":
            return analysis_id
    raise AssertionError("mock analysis never finished")


def test_history_lists_only_this_resumes_done_analyses() -> None:
    resume_a = client.post(
        "/api/resumes", files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    resume_b = client.post(
        "/api/resumes", files={"file": ("b.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]

    id_a1 = _create_done_analysis(resume_a, "x" * 41)
    _create_done_analysis(resume_b, "y" * 41)

    res = client.get(f"/api/analyses?resume_id={resume_a}")
    assert res.status_code == 200
    body = res.json()
    assert [row["analysis_id"] for row in body] == [id_a1]
    assert body[0]["job_title"]
    assert 0.0 <= body[0]["coverage"] <= 100.0
    assert body[0]["realism_verdict"] in {"strong_fit", "stretch", "unrealistic"}


def test_history_newest_first() -> None:
    resume_id = client.post(
        "/api/resumes", files={"file": ("c.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    first = _create_done_analysis(resume_id, "p" * 41)
    second = _create_done_analysis(resume_id, "q" * 41)

    res = client.get(f"/api/analyses?resume_id={resume_id}")
    ids = [row["analysis_id"] for row in res.json()]
    assert ids.index(second) < ids.index(first)


def test_history_empty_for_unknown_resume() -> None:
    res = client.get("/api/analyses?resume_id=res_doesnotexist")
    assert res.status_code == 200
    assert res.json() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analyses_history.py -v`
Expected: FAIL — `GET /api/analyses` (no id) does not exist yet (404s against the `{analysis_id}` route or a 405/422).

- [ ] **Step 3: Add `created_at` and the lookup to `api/store.py`**

Update the import line and `AnalysisRecord`:

```python
from engine.normalize.schema import AnalysisStatus, BaselineMatch, Match, MatchStage, utcnow
```

```python
@dataclass
class AnalysisRecord:
    id: str
    resume_id: str
    job_id: str
    country: str
    status: AnalysisStatus = "queued"
    stage: MatchStage | None = None
    match: Match | None = None
    baseline: BaselineMatch | None = None
    error: dict | None = None
    created_at: datetime = field(default_factory=utcnow)
```

Add `from datetime import datetime` to the existing import block at the top of the file. Then add the lookup method on `Store`, next to `create_retry`:

```python
    def analyses_for_resume(self, resume_id: str) -> list[AnalysisRecord]:
        """Completed analyses for one resume, newest first — the History list
        (PERSON_B_PLAN_v2.md §5 Phase 3 task 2). Only `status == "done"`
        records carry a `match`, which is where job title/company/coverage/
        realism come from in mock mode — there is no separate normalized-job
        store to join against."""
        done = [
            a for a in self.analyses.values()
            if a.resume_id == resume_id and a.status == "done" and a.match is not None
        ]
        return sorted(done, key=lambda a: a.created_at, reverse=True)
```

- [ ] **Step 4: Add the endpoint to `api/routes/analyses.py`**

Add the import and the route:

```python
from fastapi import APIRouter, BackgroundTasks, Query
```

```python
class AnalysisSummary(BaseModel):
    analysis_id: str
    job_title: str
    company: str | None
    coverage: float
    realism_verdict: str
    created_at: str


@router.get("/analyses")
async def list_analyses(resume_id: str = Query(..., min_length=1)) -> list[AnalysisSummary]:
    summaries: list[AnalysisSummary] = []
    for record in store.analyses_for_resume(resume_id):
        assert record.match is not None  # guaranteed by analyses_for_resume's own filter
        job = record.match.job
        summaries.append(
            AnalysisSummary(
                analysis_id=record.id,
                job_title=job.title if job else "",
                company=job.company if job else None,
                coverage=record.match.coverage_required_only,
                realism_verdict=record.match.realism_verdict,
                created_at=record.created_at.isoformat(),
            )
        )
    return summaries
```

Place this route anywhere in the file — `/analyses` (no path segment) and `/analyses/{analysis_id}` never collide.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analyses_history.py tests/test_analyses_baseline_and_retry.py tests/test_routes_errors.py -v`
Expected: all PASS. (Running the other two files alongside confirms `created_at`'s addition to `AnalysisRecord` didn't break anything that constructs one.)

- [ ] **Step 6: Commit**

```bash
git add api/store.py api/routes/analyses.py tests/test_analyses_history.py
git commit -m "feat(api): add GET /api/analyses?resume_id= for analysis history"
```

---

### Task 4: History UI on the Analyze page

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/components/results/ResultsView.tsx`
- Create: `web/components/analyze/AnalysisHistory.tsx`
- Modify: `web/app/[locale]/analyze/page.tsx`
- Modify: `web/messages/en.json`, `web/messages/km.json`

**Interfaces:**
- Consumes: `AnalysisSummary` shape from Task 3's endpoint; `loadRememberedResume` (`web/lib/localResume.ts`, Phase 2, unchanged).
- Produces: `getAnalysisHistory(resumeId: string): Promise<AnalysisSummary[]>` in `web/lib/api.ts`; `REALISM_TONE` now exported from `ResultsView.tsx` instead of module-private.

- [ ] **Step 1: Add the API client function**

Append to `web/lib/api.ts`:

```ts
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
```

- [ ] **Step 2: Export the realism→tone mapping**

In `web/components/results/ResultsView.tsx`, change the existing module-private constant to an export (same three lines, only the `const` → `export const`):

```ts
export const REALISM_TONE: Record<string, StampTone> = {
  strong_fit: "proven",
  stretch: "partial",
  unrealistic: "missing",
};
```

- [ ] **Step 3: Build the History component**

Create `web/components/analyze/AnalysisHistory.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { REALISM_TONE } from "@/components/results/ResultsView";
import { Card } from "@/components/ui/Card";
import { Stamp } from "@/components/ui/Stamp";
import { getAnalysisHistory, type AnalysisSummary } from "@/lib/api";
import { loadRememberedResume } from "@/lib/localResume";

/**
 * Past analyses for the resume remembered in this browser (PERSON_B_PLAN_v2.md
 * §5 Phase 3 task 2). There are no accounts, so "the current user" is exactly
 * the resume_id `localResume.ts` already remembers per browser (Phase 2) —
 * reusing that identity rather than adding a second anonymous-id mechanism
 * for the same purpose. Renders nothing when there is no remembered resume or
 * no history yet, rather than an empty-state card — the Analyze form is
 * already the first thing on this page.
 */
export function AnalysisHistory() {
  const t = useTranslations("analyze.history");
  const tr = useTranslations("results");
  const [rows, setRows] = React.useState<AnalysisSummary[] | null>(null);

  React.useEffect(() => {
    const remembered = loadRememberedResume();
    if (!remembered) {
      setRows([]);
      return;
    }
    getAnalysisHistory(remembered.id)
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  if (!rows || rows.length === 0) return null;

  return (
    <Card padding="lg" className="mt-8">
      <h2 className="mb-4 font-serif text-xl text-ink">{t("title")}</h2>
      <ul className="grid gap-3">
        {rows.map((row) => (
          <li key={row.analysis_id}>
            <a
              href={`/results?id=${row.analysis_id}`}
              className="flex flex-wrap items-center justify-between gap-3 border border-rule bg-paper p-3.5 transition-colors hover:bg-paper-2"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-ink">
                  {row.job_title}
                  {row.company ? ` · ${row.company}` : ""}
                </p>
                <p className="font-mono text-xs text-ink-3">
                  {new Date(row.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="font-mono text-sm text-ink-2">{Math.round(row.coverage)}%</span>
                <Stamp tone={REALISM_TONE[row.realism_verdict] ?? "partial"}>
                  {tr(`realism.${row.realism_verdict}`)}
                </Stamp>
              </div>
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
```

- [ ] **Step 4: Wire it into the Analyze page**

In `web/app/[locale]/analyze/page.tsx`, add the import and render it below the form:

```tsx
import { AnalysisHistory } from "@/components/analyze/AnalysisHistory";
```

```tsx
      <AnalyzeForm />
      <AnalysisHistory />
```

- [ ] **Step 5: Add the i18n key**

In `web/messages/en.json`, inside `"analyze"`, add a new `"history"` object (as a sibling of `"jd"`, `"country"`, etc.):

```json
  "history": {
    "title": "Your past analyses"
  },
```

Same in `web/messages/km.json`:

```json
  "history": {
    "title": "Your past analyses"
  },
```

- [ ] **Step 6: Verify**

Run: `cd web && npx tsc --noEmit && npm run lint`
Run: `node scripts/i18n-check.mjs` (from the repo root)

Manual QA: upload a resume, run two analyses against two different pasted JDs, return to `/analyze` — confirm both appear under "Your past analyses," newest first, each with a coverage percentage and a realism stamp, and each links to its own results page.

- [ ] **Step 7: Commit**

```bash
git add web/lib/api.ts web/components/results/ResultsView.tsx \
        web/components/analyze/AnalysisHistory.tsx "web/app/[locale]/analyze/page.tsx" \
        web/messages/en.json web/messages/km.json
git commit -m "feat(web): show past analyses for the remembered resume"
```

---

### Task 5: `engine/rewrite/` foundation — models, LLM wrapper, prompts

**Files:**
- Create: `engine/rewrite/models.py`
- Create: `engine/rewrite/llm.py`
- Create: `engine/rewrite/prompts.py`
- Modify: `engine/rewrite/__init__.py`
- Test: `tests/test_rewrite_models.py` (new)

**Interfaces:**
- Produces: `HiddenStrengthCandidate`, `Rewrite`, `Violation`, `ValidationResult` (`engine/rewrite/models.py`); `call_structured(*, system, user, tool_name, tool_description, tool_schema, max_tokens=1024) -> dict[str, Any]` (`engine/rewrite/llm.py`); `format_evidence_line(evidence: Evidence) -> str`, `DETECT_*`, `GENERATE_*`, `VALIDATE_*` prompt constants and `build_*_user_prompt` functions (`engine/rewrite/prompts.py`).

- [ ] **Step 1: Write the models, and their tests first**

Create `tests/test_rewrite_models.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.rewrite.models import HiddenStrengthCandidate, Rewrite, ValidationResult


def test_rewrite_requires_at_least_one_fact_used() -> None:
    with pytest.raises(ValidationError):
        Rewrite(
            requirement_id="r1",
            evidence_id="e1",
            suggested_phrasing="Built a dashboard.",
            facts_used=[],
        )


def test_validation_result_defaults_to_no_violations() -> None:
    result = ValidationResult(ok=True)
    assert result.violations == []


def test_hidden_strength_candidate_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HiddenStrengthCandidate.model_validate(
            {"requirement_id": "r1", "evidence_id": "e1", "rationale": "fits", "extra": "nope"}
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_rewrite_models.py -v`
Expected: FAIL — `engine.rewrite.models` does not exist yet (`ModuleNotFoundError`).

- [ ] **Step 3: Create `engine/rewrite/models.py`**

```python
"""Internal data models for the F5 rewrite pipeline.

These never cross into `engine/normalize/schema.py` or `web/lib/types.ts` — the
only F5 output that reaches the UI is a fully-validated
`engine.normalize.schema.HiddenStrength`, appended to `Match.hidden_strengths`
by the orchestration in `api/routes/analyses.py` (Task 10). Everything here is
intermediate plumbing between `detect_hidden_strengths`, `generate_rewrite` and
`validate_rewrite`.

A local `_Base` rather than importing `engine.normalize.schema`'s private one:
that name is private, and `schema.py` is provisional until CP1
(PERSON_B_PLAN_v2.md §2) — decoupling from it means Person A's CP1 replacement
cannot break this package by renaming or removing a symbol it never needed to
share.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["HiddenStrengthCandidate", "Rewrite", "Violation", "ValidationResult"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HiddenStrengthCandidate(_Base):
    """One `detect_hidden_strengths` finding: a requirement + the evidence
    record an LLM judged satisfies it despite how the resume phrases it."""

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    evidence_id: str = Field(..., pattern=r"^e\d+$")
    rationale: str = Field(
        ..., min_length=1, description="One sentence: why this evidence satisfies the requirement."
    )


class Rewrite(_Base):
    """One `generate_rewrite` output, before validation."""

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    evidence_id: str = Field(
        ..., pattern=r"^e\d+$", description="The primary evidence this rewrite is anchored to."
    )
    suggested_phrasing: str = Field(..., min_length=1)
    facts_used: list[str] = Field(..., min_length=1, description="Evidence.id values cited.")
    changed_words: list[str] = Field(default_factory=list)


class Violation(_Base):
    claim: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class ValidationResult(_Base):
    """`validate_rewrite`'s verdict. `ok=False` should always carry at least
    one violation in practice — that is what the rejection log records — but
    this is not schema-enforced, since an `ok=True` result legitimately has
    none."""

    ok: bool
    violations: list[Violation] = Field(default_factory=list)

    @property
    def as_log_violations(self) -> list[dict[str, str]]:
        return [v.model_dump() for v in self.violations]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_rewrite_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Create `engine/rewrite/llm.py`**

```python
"""Thin Anthropic wrapper shared by detect/generate/validate.

One structured-output helper (`call_structured`) backs all three LLM call
sites: it forces the model to answer through a single tool call, so the
response is a validated JSON object, never prose to regex out of a message.
Every call site owns its own prompt and tool schema
(`engine/rewrite/prompts.py`); this module owns talking to the API and nothing
about F5's rules.

Never imports from `api/` (`engine/README.md`, "the internals rule": nothing
in `engine/` knows about FastAPI, a locale, or a request). The Anthropic SDK
reads `ANTHROPIC_API_KEY` from the environment on its own (see
`.env.example`), so this module needs no config object passed in.
"""

from __future__ import annotations

from typing import Any

import anthropic

MODEL = "claude-sonnet-5"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy singleton: importing this module — and running the deterministic
    half of the validator suite (`tests/test_rewrite_validator.py`) — must not
    require `ANTHROPIC_API_KEY` to be set."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def call_structured(
    *,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    tool_schema: dict[str, Any],
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Call the model and force its answer through one tool call.

    Returns the tool call's `input` dict, already shaped by `tool_schema` — the
    caller parses it with a Pydantic model and gets Pydantic's own error
    messages for anything the model got wrong, rather than a JSON parse error
    on free text.
    """
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[{"name": tool_name, "description": tool_description, "input_schema": tool_schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RuntimeError(f"Anthropic response had no {tool_name!r} tool_use block: {response.content!r}")
```

- [ ] **Step 6: Create `engine/rewrite/prompts.py`**

```python
"""Prompts and tool schemas for the three F5 LLM calls. Kept separate from
detect.py/generate.py/validate.py so the prompt text — the part most likely to
be iterated on for the report — never gets lost inside control flow.
"""

from __future__ import annotations

from typing import Any

from engine.normalize.schema import Evidence

__all__ = [
    "format_evidence_line",
    "DETECT_SYSTEM_PROMPT",
    "DETECT_TOOL_NAME",
    "DETECT_TOOL_SCHEMA",
    "build_detect_user_prompt",
    "GENERATE_SYSTEM_PROMPT",
    "GENERATE_TOOL_NAME",
    "GENERATE_TOOL_SCHEMA",
    "build_generate_user_prompt",
    "VALIDATE_SYSTEM_PROMPT",
    "VALIDATE_TOOL_NAME",
    "VALIDATE_TOOL_SCHEMA",
    "build_validate_user_prompt",
]


def format_evidence_line(evidence: Evidence) -> str:
    """One evidence record as `id: description [type] skills: ... — ...` — the
    only shape any of the three prompts below ever see an Evidence in."""
    parts = [f"{evidence.id}: {evidence.source_line}", f"[{evidence.evidence_type}]"]
    if evidence.skills:
        parts.append(f"skills: {', '.join(evidence.skills)}")
    if evidence.duration_months is not None:
        parts.append(f"duration_months: {evidence.duration_months}")
    if evidence.team_size is not None:
        parts.append(f"team_size: {evidence.team_size}")
    if evidence.outcome:
        parts.append(f"outcome: {evidence.outcome}")
    return " — ".join(parts)


# ── detect_hidden_strengths ─────────────────────────────────────────────────

DETECT_SYSTEM_PROMPT = (
    "You are checking whether a candidate's resume already satisfies a single job "
    "requirement, even if the resume's wording does not match the requirement directly.\n\n"
    "Rules:\n"
    "- You may only point to evidence already in the list given to you. Never invent evidence.\n"
    "- Judge substance, not keywords: an evidence record satisfies the requirement if what it "
    "describes would reasonably count, even in different words.\n"
    "- If no evidence record satisfies the requirement, say so — do not force a match.\n"
    "- Cite exactly one evidence id: the single strongest piece of evidence, if any."
)

DETECT_TOOL_NAME = "report_hidden_strength"
DETECT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {
            "type": "boolean",
            "description": "True if some evidence record satisfies the requirement.",
        },
        "evidence_id": {
            "type": "string",
            "description": "Id of the strongest satisfying evidence record. Required when found is true.",
        },
        "rationale": {
            "type": "string",
            "description": "One sentence: why this evidence satisfies the requirement. Required when found is true.",
        },
    },
    "required": ["found"],
}


def build_detect_user_prompt(requirement_text: str, evidence_lines: list[str]) -> str:
    numbered = "\n".join(evidence_lines)
    return (
        f"Requirement: {requirement_text}\n\n"
        f"Evidence records (id: description):\n{numbered}\n\n"
        "Does any evidence record satisfy this requirement, even if phrased differently?"
    )


# ── generate_rewrite ─────────────────────────────────────────────────────────

GENERATE_SYSTEM_PROMPT = (
    "You rewrite one resume line so it speaks to a requirement's language, without "
    "inventing anything.\n\n"
    "Rules, and they are absolute:\n"
    "- No new numbers. No new durations. No new employers. No new tools or technologies.\n"
    "- You may reorder words, and you may borrow the job post's vocabulary for a skill or "
    "concept already present in the evidence.\n"
    "- You may not change what kind of evidence this is: a class project stays a project, a "
    "volunteer role stays volunteer work. Never imply paid professional employment where the "
    "evidence is coursework, a project, a competition, or volunteering.\n"
    "- Every fact in your rewrite must already be present in the evidence given to you. If you "
    "are not sure a word is grounded in the evidence, leave it out.\n"
    "- Cite every evidence id you actually used in facts_used."
)

GENERATE_TOOL_NAME = "propose_rewrite"
GENERATE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggested_phrasing": {"type": "string"},
        "facts_used": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence ids (e.g. 'e3') every claim in suggested_phrasing traces to.",
        },
    },
    "required": ["suggested_phrasing", "facts_used"],
}


def build_generate_user_prompt(requirement_text: str, evidence_lines: list[str]) -> str:
    numbered = "\n".join(evidence_lines)
    return (
        f"Job requirement (for vocabulary only — never a source of facts): {requirement_text}\n\n"
        f"Evidence records, the ONLY source of facts (id: description):\n{numbered}\n\n"
        "Rewrite the primary evidence line so it speaks to the requirement, using only facts "
        "already present above."
    )


# ── validate_rewrite (LLM layer) ────────────────────────────────────────────

VALIDATE_SYSTEM_PROMPT = (
    "You are a strict fact-checker for a resume rewrite. You already know the rewrite "
    "contains no invented numbers, dates or proper nouns — a separate deterministic check "
    "covers that. Your job is the subtler failure: a rewrite that invents no new literal "
    "token but still claims more than the evidence supports.\n\n"
    "Look specifically for:\n"
    "- Status upgrades: unpaid, academic or informal work described as if it were paid "
    'professional employment (e.g. "worked as a software engineer" for a class project).\n'
    "- Scope inflation: a claim of responsibility, outcome or independence broader than the "
    'evidence states (e.g. "led the team" when the evidence says "participated").\n'
    "- Causal or outcome claims the evidence does not support.\n\n"
    "If the rewrite is a faithful restatement of the evidence, say so. Do not invent a "
    "violation to have something to report."
)

VALIDATE_TOOL_NAME = "report_validation"
VALIDATE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["claim", "reason"],
            },
        },
    },
    "required": ["ok", "violations"],
}


def build_validate_user_prompt(suggested_phrasing: str, evidence_lines: list[str]) -> str:
    numbered = "\n".join(evidence_lines)
    return (
        f"Rewrite to check: {suggested_phrasing}\n\n"
        f"Evidence it must be grounded in (id: description):\n{numbered}"
    )
```

- [ ] **Step 7: Update `engine/rewrite/__init__.py`'s docstring**

The file currently says the package is "intentionally empty right now" and "Nothing public yet." Replace the closing comment and `__all__` to reflect that Phase 3 has started:

Change:
```python
#: Nothing public yet. Populated in Phase 3 (F5). Deliberately empty rather than
#: stubbed: no name here should promise behaviour that does not exist.
__all__: list[str] = []
```
to:
```python
#: Phase 3 (F5) is underway. Nothing is re-exported at the package root —
#: import from the submodule that owns it (`engine.rewrite.detect`,
#: `.generate`, `.validate`) rather than `engine.rewrite` directly.
__all__: list[str] = []
```

- [ ] **Step 8: Run the full suite, ruff, and mypy**

Run: `.venv/bin/python -m pytest tests/ -v`
Run: `.venv/bin/python -m ruff check engine api tests`
Run: `.venv/bin/python -m mypy`
Expected: all clean. (`mypy`'s `[[tool.mypy.overrides]]` already ignores missing stubs for `anthropic.*`.)

- [ ] **Step 9: Commit**

```bash
git add engine/rewrite/models.py engine/rewrite/llm.py engine/rewrite/prompts.py \
        engine/rewrite/__init__.py tests/test_rewrite_models.py
git commit -m "feat(engine): add the F5 rewrite pipeline's models, LLM wrapper, and prompts"
```

---

### Task 6: `detect_hidden_strengths`

**Files:**
- Create: `engine/rewrite/detect.py`
- Test: `tests/test_rewrite_detect.py` (new)

**Interfaces:**
- Consumes: `engine.rewrite.llm.call_structured`, `engine.rewrite.prompts.{DETECT_SYSTEM_PROMPT, DETECT_TOOL_NAME, DETECT_TOOL_SCHEMA, build_detect_user_prompt, format_evidence_line}`, `engine.rewrite.models.HiddenStrengthCandidate`.
- Produces: `detect_hidden_strengths(match: Match, resume: Resume) -> list[HiddenStrengthCandidate]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rewrite_detect.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from engine.normalize.schema import Evidence, Job, Match, MatchResult, Requirement, Resume
from engine.rewrite.detect import detect_hidden_strengths


def _job() -> Job:
    return Job(
        source_type="pasted",
        content_hash="abcd1234",
        title="Junior Developer",
        industry="Tech",
        seniority="entry",
        requirements=[
            Requirement(id="r1", text="Experience with Python", category="hard_skill", priority="required"),
            Requirement(id="r2", text="Team leadership", category="soft_skill", priority="preferred"),
        ],
    )


def _resume() -> Resume:
    return Resume(
        evidence=[
            Evidence(
                id="e1",
                source_line="Built a Python scraper for a class project.",
                evidence_type="project",
                skills=["Python"],
            ),
            Evidence(id="e2", source_line="Volunteered at a coding club.", evidence_type="volunteer"),
        ],
    )


def _match(job: Job) -> Match:
    return Match(
        coverage_score=50.0,
        coverage_required_only=50.0,
        realism_verdict="stretch",
        results=[
            MatchResult(
                requirement_id="r1", verdict="partial", evidence_ids=["e1"],
                reasoning="close", confidence=0.5,
            ),
            MatchResult(
                requirement_id="r2", verdict="missing",
                missing_reason="no leadership evidence", reasoning="none found", confidence=0.9,
            ),
        ],
        job=job,
    )


def test_detect_returns_a_candidate_when_the_llm_finds_one() -> None:
    match = _match(_job())
    resume = _resume()

    with patch(
        "engine.rewrite.detect.llm.call_structured",
        side_effect=[
            {"found": True, "evidence_id": "e1", "rationale": "Python scraper demonstrates the skill."},
            {"found": False},
        ],
    ):
        candidates = detect_hidden_strengths(match, resume)

    assert len(candidates) == 1
    assert candidates[0].requirement_id == "r1"
    assert candidates[0].evidence_id == "e1"


def test_detect_drops_a_candidate_citing_an_unknown_evidence_id() -> None:
    match = _match(_job())
    resume = _resume()

    with patch(
        "engine.rewrite.detect.llm.call_structured",
        side_effect=[
            {"found": True, "evidence_id": "e99", "rationale": "hallucinated id"},
            {"found": False},
        ],
    ):
        candidates = detect_hidden_strengths(match, resume)

    assert candidates == []


def test_detect_returns_nothing_for_a_match_with_no_job() -> None:
    resume = _resume()
    bare_match = Match(coverage_score=0, coverage_required_only=0, realism_verdict="stretch", results=[])
    assert detect_hidden_strengths(bare_match, resume) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_rewrite_detect.py -v`
Expected: FAIL — `engine.rewrite.detect` does not exist.

- [ ] **Step 3: Create `engine/rewrite/detect.py`**

```python
"""F5 — hidden-strengths detector (PERSON_B_PLAN_v2.md §5 Phase 3 task 3).

For every requirement the match engine scored `partial` or `missing`, asks one
LLM call whether any evidence record satisfies it despite how the resume
phrases it. One call per requirement, not one call for the whole resume, so
each judgement is auditable on its own and a single bad call cannot silently
swallow every candidate.
"""

from __future__ import annotations

from pydantic import ValidationError

from engine.normalize.schema import Match, Resume
from engine.rewrite import llm, prompts
from engine.rewrite.models import HiddenStrengthCandidate

__all__ = ["detect_hidden_strengths"]

_CANDIDATE_VERDICTS = ("partial", "missing")


def detect_hidden_strengths(match: Match, resume: Resume) -> list[HiddenStrengthCandidate]:
    """Find resume evidence that already satisfies a poorly-worded requirement.

    Args:
        match: A `Match` with `job` embedded — `match.job.requirements`
            supplies the requirement text for every `partial`/`missing` result.
            Returns `[]` immediately if `job` is absent.
        resume: The `Resume` whose `evidence` list is offered to the LLM as the
            only source of facts it may point to.

    Returns:
        One `HiddenStrengthCandidate` per requirement where the LLM found a
        satisfying evidence record. A candidate whose `evidence_id` is not a
        real id in `resume.evidence`, or that otherwise fails
        `HiddenStrengthCandidate`'s own validation, is dropped rather than
        trusted — the model inventing an id is a real failure mode, not a
        hypothetical one.
    """
    if match.job is None:
        return []

    known_evidence_ids = {e.id for e in resume.evidence}
    evidence_lines = [prompts.format_evidence_line(e) for e in resume.evidence]

    candidates: list[HiddenStrengthCandidate] = []
    for result in match.results:
        if result.verdict not in _CANDIDATE_VERDICTS:
            continue
        requirement = next((r for r in match.job.requirements if r.id == result.requirement_id), None)
        if requirement is None:
            continue

        response = llm.call_structured(
            system=prompts.DETECT_SYSTEM_PROMPT,
            user=prompts.build_detect_user_prompt(requirement.text, evidence_lines),
            tool_name=prompts.DETECT_TOOL_NAME,
            tool_description="Report whether any evidence record satisfies the requirement.",
            tool_schema=prompts.DETECT_TOOL_SCHEMA,
        )
        if not response.get("found"):
            continue
        evidence_id = response.get("evidence_id")
        if evidence_id not in known_evidence_ids:
            continue

        try:
            candidates.append(
                HiddenStrengthCandidate(
                    requirement_id=requirement.id,
                    evidence_id=evidence_id,
                    rationale=response.get("rationale") or "",
                )
            )
        except ValidationError:
            continue
    return candidates
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_rewrite_detect.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/rewrite/detect.py tests/test_rewrite_detect.py
git commit -m "feat(engine): add detect_hidden_strengths"
```

---

### Task 7: `generate_rewrite`

**Files:**
- Create: `engine/rewrite/generate.py`
- Test: `tests/test_rewrite_generate.py` (new)

**Interfaces:**
- Consumes: `engine.rewrite.llm.call_structured`, `engine.rewrite.prompts.{GENERATE_SYSTEM_PROMPT, GENERATE_TOOL_NAME, GENERATE_TOOL_SCHEMA, build_generate_user_prompt, format_evidence_line}`, `engine.rewrite.models.Rewrite`.
- Produces: `generate_rewrite(requirement: Requirement, evidence_records: list[Evidence]) -> Rewrite`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rewrite_generate.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.normalize.schema import Evidence, Requirement
from engine.rewrite.generate import generate_rewrite


def test_generate_rewrite_computes_changed_words_deterministically() -> None:
    requirement = Requirement(id="r1", text="Experience with React", category="hard_skill", priority="required")
    evidence = Evidence(
        id="e1",
        source_line="Built a dashboard for a university course project.",
        evidence_type="project",
        skills=["React"],
    )

    with patch(
        "engine.rewrite.generate.llm.call_structured",
        return_value={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    ):
        rewrite = generate_rewrite(requirement, [evidence])

    assert rewrite.requirement_id == "r1"
    assert rewrite.evidence_id == "e1"
    assert rewrite.facts_used == ["e1"]
    assert rewrite.changed_words == ["React"]


def test_generate_rewrite_requires_at_least_one_evidence_record() -> None:
    requirement = Requirement(id="r1", text="Experience with React", category="hard_skill", priority="required")
    with pytest.raises(ValueError):
        generate_rewrite(requirement, [])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_rewrite_generate.py -v`
Expected: FAIL — `engine.rewrite.generate` does not exist.

- [ ] **Step 3: Create `engine/rewrite/generate.py`**

```python
"""F5 — evidence-bound rewrite generator (PERSON_B_PLAN_v2.md §5 Phase 3 task 3).

`generate_rewrite`'s input is evidence records ONLY — never the raw resume
text, never the JD beyond the requirement's own wording used for vocabulary.
Rewriting toward the JD's wording from the JD itself, rather than from what the
evidence actually says, is how this feature would become a lying machine
(engine/rewrite/__init__.py).
"""

from __future__ import annotations

import re

from engine.normalize.schema import Evidence, Requirement
from engine.rewrite import llm, prompts
from engine.rewrite.models import Rewrite

__all__ = ["generate_rewrite"]

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _changed_words(current_phrasing: str, suggested_phrasing: str) -> list[str]:
    """Words in `suggested_phrasing` absent from `current_phrasing`,
    case-insensitively, in order, without duplicates — powers the word-level
    diff highlight (`HiddenStrength.changed_words`, Phase 4.3's before/after
    UI). Computed here, deterministically, rather than asked of the model —
    `HiddenStrength.changed_words`'s own docstring: "keeps the UI dumb and the
    diff reproducible.\""""
    current_words = {w.lower() for w in _WORD_RE.findall(current_phrasing)}
    seen: set[str] = set()
    changed: list[str] = []
    for word in _WORD_RE.findall(suggested_phrasing):
        lowered = word.lower()
        if lowered not in current_words and lowered not in seen:
            seen.add(lowered)
            changed.append(word)
    return changed


def generate_rewrite(requirement: Requirement, evidence_records: list[Evidence]) -> Rewrite:
    """Rewrite the primary evidence record's line toward one requirement.

    Args:
        requirement: Supplies vocabulary only — its own words are never a
            source of facts the rewrite may add.
        evidence_records: The only source of facts. `evidence_records[0]` is
            the anchor: its `source_line` is `current_phrasing` for the
            `changed_words` diff, and its `id` becomes `Rewrite.evidence_id`.
            Any further records are extra context the model may also cite in
            `facts_used`.

    Raises:
        ValueError: if `evidence_records` is empty — there is nothing to
            anchor the rewrite to.
    """
    if not evidence_records:
        raise ValueError("generate_rewrite requires at least one evidence record")

    anchor = evidence_records[0]
    evidence_lines = [prompts.format_evidence_line(e) for e in evidence_records]

    response = llm.call_structured(
        system=prompts.GENERATE_SYSTEM_PROMPT,
        user=prompts.build_generate_user_prompt(requirement.text, evidence_lines),
        tool_name=prompts.GENERATE_TOOL_NAME,
        tool_description="Propose a rewrite grounded only in the given evidence.",
        tool_schema=prompts.GENERATE_TOOL_SCHEMA,
    )

    suggested_phrasing = response["suggested_phrasing"]
    return Rewrite(
        requirement_id=requirement.id,
        evidence_id=anchor.id,
        suggested_phrasing=suggested_phrasing,
        facts_used=list(response["facts_used"]),
        changed_words=_changed_words(anchor.source_line, suggested_phrasing),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_rewrite_generate.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/rewrite/generate.py tests/test_rewrite_generate.py
git commit -m "feat(engine): add generate_rewrite with a deterministic word-diff"
```

---

### Task 8: `validate_rewrite` — the two-layer hallucination validator

This is the phase's centerpiece and the file the plan's own Phase 3 prompt explicitly asks for: `tests/test_rewrite_validator.py`, with ≥5 hand-crafted hallucinated rewrites that must be rejected and 3 legitimate rephrasings that must pass, and the validator design explained in a docstring.

**Files:**
- Create: `engine/rewrite/validate.py`
- Test: `tests/test_rewrite_validator.py` (new — the required file)

**Interfaces:**
- Consumes: `engine.rewrite.llm.call_structured`, `engine.rewrite.prompts.{VALIDATE_SYSTEM_PROMPT, VALIDATE_TOOL_NAME, VALIDATE_TOOL_SCHEMA, build_validate_user_prompt, format_evidence_line}`, `engine.rewrite.models.{Rewrite, ValidationResult, Violation}`.
- Produces: `validate_rewrite(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult`; `precheck_rewrite(rewrite, evidence_records) -> ValidationResult | None` (exported so it is directly testable on its own); `_call_llm_validator` (private — this exact name is what Task 10's tests and this task's own tests monkeypatch).

- [ ] **Step 1: Write `engine/rewrite/validate.py`**

```python
"""F5 — hallucination validator (PERSON_B_PLAN_v2.md §5 Phase 3 task 4).

Two layers, in order, and the order is load-bearing:

1. **Deterministic pre-check** (`precheck_rewrite`), which costs nothing: every
   number, year, month-count and capitalized proper noun in the rewrite must
   already appear in the text of at least one cited (`facts_used`) evidence
   record, or the rewrite fails immediately, before any LLM is called. This
   catches the loud failures — an invented year, employer, tool or headcount —
   deterministically and for free.

2. **A separate LLM call** (`_call_llm_validator`), reached only if the
   pre-check passes, that receives only the rewrite and the cited evidence and
   looks for the quiet failure the regex cannot see: a claim that invents no
   new literal token but still overstates the evidence — a status upgrade
   ("worked as a software engineer" for a class project), a scope inflation
   ("led the team" for "participated"), or an unsupported outcome claim
   (PROJECT_SPEC.md §9 rule 2).

Two layers = defensible: a reviewer can point at the pre-check's exact
non-matching token for the loud failures, and at the LLM's own stated
reasoning for the quiet ones — neither layer is asked to do the other's job.

Every rejection, from either layer, is meant to be logged by the caller via
`api.store.store.log_rewrite_rejection` (PERSON_B_PLAN_v2.md §5 Phase 3 task
5, Task 10 of this plan) — this module only judges, it does not log, keeping
it importable and testable with no store dependency.
"""

from __future__ import annotations

import re

from engine.normalize.schema import Evidence
from engine.rewrite import llm, prompts
from engine.rewrite.models import Rewrite, ValidationResult, Violation

__all__ = ["validate_rewrite", "precheck_rewrite"]

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")
_WORD_RE = re.compile(r"[A-Za-z][a-zA-Z']*")


def _facts_text(rewrite: Rewrite, evidence_records: list[Evidence]) -> str:
    """Every field of every evidence record `rewrite.facts_used` actually
    cites, joined into one lowercase haystack to substring-check claims
    against."""
    cited = [e for e in evidence_records if e.id in rewrite.facts_used]
    parts: list[str] = []
    for e in cited:
        parts.append(e.source_line)
        parts.extend(e.skills)
        if e.outcome:
            parts.append(e.outcome)
        if e.duration_months is not None:
            parts.append(str(e.duration_months))
        if e.team_size is not None:
            parts.append(str(e.team_size))
    return " ".join(parts).lower()


def _extract_checkable_tokens(text: str) -> list[str]:
    """Numbers (checked regardless of position — a number is a claim wherever
    it sits) and proper-noun-shaped words. Each sentence's first word is
    skipped for the Title-case check, to avoid flagging ordinary
    sentence-initial capitalization ("Coordinated with...") as an invented
    proper noun; an ALL-CAPS acronym is checked at any position, since
    something like "AWS" is exactly as much a claim at a sentence's start as
    in its middle."""
    tokens = list(_NUMBER_RE.findall(text))
    for sentence in _SENTENCE_RE.split(text):
        words = _WORD_RE.findall(sentence)
        for i, word in enumerate(words):
            if _ACRONYM_RE.fullmatch(word):
                tokens.append(word)
            elif i > 0 and word[0].isupper():
                tokens.append(word)
    return tokens


def precheck_rewrite(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult | None:
    """The deterministic layer. Returns `None` when the rewrite passes — the
    caller then proceeds to the LLM layer — or a `ValidationResult(ok=False,
    ...)` naming every unsupported token when it does not."""
    haystack = _facts_text(rewrite, evidence_records)
    violations = [
        Violation(claim=token, reason="Not present in any cited evidence record.")
        for token in _extract_checkable_tokens(rewrite.suggested_phrasing)
        if token.lower() not in haystack
    ]
    if not violations:
        return None
    return ValidationResult(ok=False, violations=violations)


def _call_llm_validator(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult:
    cited = [e for e in evidence_records if e.id in rewrite.facts_used]
    evidence_lines = [prompts.format_evidence_line(e) for e in cited]
    response = llm.call_structured(
        system=prompts.VALIDATE_SYSTEM_PROMPT,
        user=prompts.build_validate_user_prompt(rewrite.suggested_phrasing, evidence_lines),
        tool_name=prompts.VALIDATE_TOOL_NAME,
        tool_description="Report whether the rewrite is a faithful restatement of the evidence.",
        tool_schema=prompts.VALIDATE_TOOL_SCHEMA,
    )
    return ValidationResult(
        ok=bool(response.get("ok")),
        violations=[Violation(**v) for v in response.get("violations", [])],
    )


def validate_rewrite(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult:
    """Run both layers in order. The LLM layer never runs if the pre-check
    already failed — "costs nothing" only holds if the free check runs first."""
    precheck_failure = precheck_rewrite(rewrite, evidence_records)
    if precheck_failure is not None:
        return precheck_failure
    return _call_llm_validator(rewrite, evidence_records)
```

- [ ] **Step 2: Write `tests/test_rewrite_validator.py`**

```python
"""Adversarial + legitimate cases for `engine.rewrite.validate.validate_rewrite`
(PERSON_B_PLAN_v2.md §5 Phase 3 — "Claude Code prompt — Phase 3", item 5).

Validator design, in one paragraph for the report: `validate_rewrite` runs two
independent layers in order. The first, `precheck_rewrite`, is a
deterministic, zero-cost regex pass — it extracts every number, year,
month-count and capitalized proper noun from the candidate rewrite and
rejects immediately if any of them is absent from the text of every evidence
record the rewrite cites in `facts_used`. This catches invented facts: a
fabricated year, employer, tool name or headcount. It runs first, and if it
fails, the second layer never runs at all — that is what "costs nothing"
means in practice: the loud, common failure mode is caught for free. The
second layer, `_call_llm_validator`, exists for the failure the regex
structurally cannot see: a rewrite that invents no new literal token but
still overstates the evidence semantically — a class project described as
paid employment, "participated" upgraded to "led" (PROJECT_SPEC.md §9 rule
2). Two layers, because a reviewer can point at the pre-check's exact
non-matching token for the loud failures, and at the LLM's own stated
reasoning for the quiet ones; neither layer is asked to do the other's job.

The five hallucinated cases below split 4-and-1 for exactly that reason: four
are caught by the deterministic layer alone (asserted by mocking
`_call_llm_validator` and checking it is never called), and one — the status
upgrade, which introduces no new number or proper noun — reaches and is
caught by the mocked LLM layer, demonstrating the second layer is
load-bearing rather than decorative. The LLM call itself is mocked
throughout: this suite must stay fast, free and deterministic in CI, which is
also why `engine/rewrite/llm.py`'s `_get_client()` is lazy — importing this
module and running every case below requires no `ANTHROPIC_API_KEY` at all.
"""

from __future__ import annotations

from unittest.mock import patch

from engine.normalize.schema import Evidence
from engine.rewrite.models import Rewrite, ValidationResult
from engine.rewrite.validate import validate_rewrite


def _evidence(**overrides: object) -> Evidence:
    base: dict[str, object] = dict(
        id="e1",
        source_line=(
            "Built a Python-based encryption tool for a university course project, "
            "coordinating with 2 teammates over 3 months."
        ),
        evidence_type="project",
        skills=["Python"],
        duration_months=3,
        team_size=2,
    )
    base.update(overrides)
    return Evidence(**base)


def _rewrite(suggested_phrasing: str) -> Rewrite:
    return Rewrite(
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing=suggested_phrasing,
        facts_used=["e1"],
    )


# ── Hallucinated: caught by the deterministic pre-check, no LLM call ────────


def test_rejects_an_invented_year() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite("In 2019, built a Python-based encryption tool for a course project.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("2019" in v.claim for v in result.violations)


def test_rejects_an_invented_employer() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite("Built the encryption tool while working at TechNova Solutions.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("TechNova" in v.claim for v in result.violations)


def test_rejects_an_inflated_team_size() -> None:
    evidence = [_evidence(team_size=2)]
    rewrite = _rewrite("Led a team of 12 engineers building the encryption tool.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("12" in v.claim for v in result.violations)


def test_rejects_an_invented_tool() -> None:
    evidence = [_evidence(skills=["Python"])]
    rewrite = _rewrite("Built the encryption tool using Python and Kubernetes.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("Kubernetes" in v.claim for v in result.violations)


# ── Hallucinated: no new number or proper noun — only the LLM layer catches it ─


def test_rejects_a_status_upgrade_from_project_to_employment() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite(
        "Worked professionally as a software engineer, delivering production "
        "features independently."
    )
    llm_result = ValidationResult(
        ok=False,
        violations=[
            {
                "claim": "worked professionally as a software engineer",
                "reason": "Evidence is an academic course project, not paid employment.",
            }
        ],
    )

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=llm_result
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is False
    assert result.violations


# ── Legitimate rephrasings: must pass both layers ───────────────────────────


def _passing() -> ValidationResult:
    return ValidationResult(ok=True, violations=[])


def test_accepts_a_reordered_rephrasing() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite(
        "Coordinated with 2 teammates over 3 months to build a Python-based "
        "encryption tool for a university course project."
    )

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=_passing()
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is True
    assert result.violations == []


def test_accepts_a_jd_vocabulary_substitution() -> None:
    evidence = [_evidence(skills=["Python", "cryptography"])]
    rewrite = _rewrite("Implemented a Python cryptography tool for a university course project.")

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=_passing()
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is True


def test_accepts_a_condensed_rephrasing() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite("Built a Python encryption tool as a university course project.")

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=_passing()
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is True
```

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_rewrite_validator.py -v`
Expected: all 8 tests PASS on the first run (this file is TDD'd against the implementation from Step 1, written together deliberately — the design is exacting enough, in exactly which tokens get flagged, that writing the regex against a vague spec first and fixing it against real test failures is the practical order here). If any test fails, the likely cause is `_extract_checkable_tokens`' sentence-initial skip rule — check which sentence index a flagged/missed word falls at before changing the regex.

Then run the full suite once more to confirm nothing upstream broke:

Run: `.venv/bin/python -m pytest tests/ -v`
Run: `.venv/bin/python -m ruff check engine api tests`
Run: `.venv/bin/python -m mypy`

- [ ] **Step 4: Commit**

```bash
git add engine/rewrite/validate.py tests/test_rewrite_validator.py
git commit -m "feat(engine): add the two-layer hallucination validator"
```

---

### Task 9: Rejection log storage

**Files:**
- Modify: `api/store.py`
- Test: `tests/test_rewrite_rejection_log.py` (new)

**Interfaces:**
- Produces: `RewriteRejection` dataclass; `Store.log_rewrite_rejection(*, analysis_id, requirement_id, evidence_id, suggested_phrasing, violations, retry_succeeded) -> RewriteRejection`; `Store.rewrite_rejections: list[RewriteRejection]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rewrite_rejection_log.py`:

```python
from __future__ import annotations

from api.store import Store


def test_log_rewrite_rejection_records_every_field() -> None:
    store = Store()
    record = store.log_rewrite_rejection(
        analysis_id="an_1",
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing="Worked as a software engineer.",
        violations=[{"claim": "software engineer", "reason": "evidence is a project"}],
        retry_succeeded=False,
    )

    assert record in store.rewrite_rejections
    assert record.analysis_id == "an_1"
    assert record.retry_succeeded is False
    assert record.created_at is not None


def test_log_rewrite_rejection_accumulates_across_calls() -> None:
    store = Store()
    store.log_rewrite_rejection(
        analysis_id="an_1", requirement_id="r1", evidence_id="e1",
        suggested_phrasing="a", violations=[], retry_succeeded=True,
    )
    store.log_rewrite_rejection(
        analysis_id="an_1", requirement_id="r2", evidence_id="e2",
        suggested_phrasing="b", violations=[], retry_succeeded=False,
    )
    assert len(store.rewrite_rejections) == 2
```

Note this test uses a fresh `Store()` instance, not the module-level `store` singleton — isolating it from every other test file that shares that singleton via `TestClient(app)`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_rewrite_rejection_log.py -v`
Expected: FAIL — `Store` has no `log_rewrite_rejection`.

- [ ] **Step 3: Add to `api/store.py`**

Add `RewriteRejection`, right after `AnalysisRecord`:

```python
@dataclass
class RewriteRejection:
    """One F5 validator failure (PERSON_B_PLAN_v2.md §5 Phase 3 task 5) — a
    report figure for the evaluation chapter, not an error to hide. Lives here
    rather than in a real DB table for the same reason `AnalysisRecord` does:
    nothing in this codebase has a real database yet (`engine/README.md` line
    30 gives DB migrations to Person A, but Supabase isn't wired until CP2)."""

    id: str
    analysis_id: str
    requirement_id: str
    evidence_id: str
    suggested_phrasing: str
    violations: list[dict[str, str]]
    retry_succeeded: bool
    created_at: datetime = field(default_factory=utcnow)
```

Add the field and method to `Store`:

```python
@dataclass
class Store:
    resumes: dict[str, ResumeRecord] = field(default_factory=dict)
    jobs: dict[str, JobRecord] = field(default_factory=dict)
    jobs_by_hash: dict[str, str] = field(default_factory=dict)
    analyses: dict[str, AnalysisRecord] = field(default_factory=dict)
    rewrite_rejections: list[RewriteRejection] = field(default_factory=list)
    _rotation_index: int = 0
    _picked_fixture_names: dict[str, str] = field(default_factory=dict)
```

```python
    def log_rewrite_rejection(
        self,
        *,
        analysis_id: str,
        requirement_id: str,
        evidence_id: str,
        suggested_phrasing: str,
        violations: list[dict[str, str]],
        retry_succeeded: bool,
    ) -> RewriteRejection:
        record = RewriteRejection(
            id=_new_id("rej"),
            analysis_id=analysis_id,
            requirement_id=requirement_id,
            evidence_id=evidence_id,
            suggested_phrasing=suggested_phrasing,
            violations=violations,
            retry_succeeded=retry_succeeded,
        )
        self.rewrite_rejections.append(record)
        return record
```

(`utcnow` and `datetime` are already imported from Task 3's changes to this same file; no new imports needed here.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_rewrite_rejection_log.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add api/store.py tests/test_rewrite_rejection_log.py
git commit -m "feat(api): add the rewrite_rejections log to the in-memory store"
```

---

### Task 10: `POST /api/analyses/{id}/rewrites` — the orchestration endpoint

**Files:**
- Modify: `api/routes/analyses.py`
- Modify: `docs/errors.md`
- Modify: `api/errors.py` (comment only — "ten" → "eleven")
- Modify: `web/messages/en.json`, `web/messages/km.json`
- Test: `tests/test_rewrite_endpoint.py` (new)

**Interfaces:**
- Consumes: `detect_hidden_strengths`, `generate_rewrite`, `validate_rewrite` (Tasks 6–8), `store.log_rewrite_rejection` (Task 9), `HiddenStrength` (`engine.normalize.schema`, unchanged).
- Produces: `POST /api/analyses/{analysis_id}/rewrites -> {"hidden_strengths": [...], "rejected_count": int}`; a new error code `ANALYSIS_NOT_READY`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rewrite_endpoint.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.store import AnalysisRecord, store
from engine.normalize.schema import Evidence, Job, Match, MatchResult, Requirement, Resume
from engine.rewrite.models import ValidationResult

client = TestClient(app)


def _seed_done_analysis(analysis_id: str) -> str:
    job = Job(
        source_type="pasted",
        content_hash="deadbeef",
        title="Junior Developer",
        industry="Tech",
        seniority="entry",
        requirements=[
            Requirement(id="r1", text="Experience with React", category="hard_skill", priority="required"),
        ],
    )
    resume = Resume(
        evidence=[
            Evidence(
                id="e1",
                source_line="Built a dashboard for a university course project.",
                evidence_type="project",
                skills=["React"],
            ),
        ],
    )
    match = Match(
        coverage_score=50.0,
        coverage_required_only=50.0,
        realism_verdict="stretch",
        results=[
            MatchResult(
                requirement_id="r1", verdict="partial", evidence_ids=["e1"],
                reasoning="close", confidence=0.6,
            ),
        ],
        job=job,
        resume=resume,
    )
    record = AnalysisRecord(id=analysis_id, resume_id="res_test", job_id="job_test", country="cambodia")
    record.status = "done"
    record.match = match
    store.analyses[record.id] = record
    return record.id


def test_rewrites_endpoint_accepts_a_valid_candidate() -> None:
    analysis_id = _seed_done_analysis("an_test_rewrites_ok")

    with (
        patch(
            "engine.rewrite.detect.llm.call_structured",
            return_value={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        ),
        patch(
            "engine.rewrite.generate.llm.call_structured",
            return_value={
                "suggested_phrasing": "Built a React dashboard for a university course project.",
                "facts_used": ["e1"],
            },
        ),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    body = res.json()
    assert body["rejected_count"] == 0
    assert len(body["hidden_strengths"]) == 1
    assert body["hidden_strengths"][0]["evidence_id"] == "e1"

    get_res = client.get(f"/api/analyses/{analysis_id}").json()
    assert len(get_res["match"]["hidden_strengths"]) == 1


def test_rewrites_endpoint_logs_a_rejection_after_two_failed_attempts() -> None:
    analysis_id = _seed_done_analysis("an_test_rewrites_reject")

    with (
        patch(
            "engine.rewrite.detect.llm.call_structured",
            return_value={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        ),
        patch(
            "engine.rewrite.generate.llm.call_structured",
            return_value={
                "suggested_phrasing": "Worked professionally as a software engineer.",
                "facts_used": ["e1"],
            },
        ),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(
                ok=False,
                violations=[{"claim": "software engineer", "reason": "evidence is a project"}],
            ),
        ),
    ):
        before = len(store.rewrite_rejections)
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    body = res.json()
    assert body["rejected_count"] == 1
    assert body["hidden_strengths"] == []
    logged = store.rewrite_rejections[before:]
    assert len(logged) == 2
    assert all(r.retry_succeeded is False for r in logged)


def test_rewrites_endpoint_requires_a_done_analysis() -> None:
    record = AnalysisRecord(id="an_test_not_ready", resume_id="res_x", job_id="job_x", country="cambodia")
    store.analyses[record.id] = record  # status defaults to "queued"

    res = client.post(f"/api/analyses/{record.id}/rewrites")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_READY"


def test_rewrites_endpoint_404s_for_an_unknown_analysis() -> None:
    res = client.post("/api/analyses/an_doesnotexist/rewrites")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_rewrite_endpoint.py -v`
Expected: FAIL — the route does not exist (404s on all four).

- [ ] **Step 3: Implement the endpoint in `api/routes/analyses.py`**

Add the imports:

```python
from engine.normalize.schema import HiddenStrength, Match
from engine.rewrite.detect import detect_hidden_strengths
from engine.rewrite.generate import generate_rewrite
from engine.rewrite.validate import validate_rewrite
```

Add the helper and the route, anywhere after `retry_analysis`:

```python
def _append_hidden_strength(match: Match, hidden_strength: HiddenStrength) -> Match:
    """Re-validates the whole `Match` with the new `HiddenStrength` appended,
    rather than mutating `match.hidden_strengths` in place — a plain
    `list.append` would bypass `Match._references_resolve`, the exact
    integrity check that would catch a generated `HiddenStrength` citing an id
    that does not exist. schema.py's own stated philosophy: validation at
    parse time, so a violation cannot reach the API response."""
    updated = match.model_dump(mode="json")
    updated["hidden_strengths"] = [
        *updated["hidden_strengths"],
        hidden_strength.model_dump(mode="json"),
    ]
    return Match.model_validate(updated)


@router.post("/analyses/{analysis_id}/rewrites")
async def create_rewrites(analysis_id: str) -> dict:
    """Runs the F5 pipeline for one completed analysis (PERSON_B_PLAN_v2.md §5
    Phase 3 task 6): detect candidates, generate a rewrite for each, validate
    it, retry generation+validation once on failure, log every failure, and
    append every accepted HiddenStrength to the stored match."""
    record = store.analyses.get(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")
    if record.status != "done" or record.match is None:
        raise ApiError(
            status_code=409,
            code="ANALYSIS_NOT_READY",
            message="Analysis has not finished; there is no match to run rewrites against.",
        )

    match = record.match
    resume = match.resume
    if resume is None or match.job is None:
        return {
            "hidden_strengths": [h.model_dump(mode="json") for h in match.hidden_strengths],
            "rejected_count": 0,
        }

    requirements_by_id = {r.id: r for r in match.job.requirements}
    evidence_by_id = {e.id: e for e in resume.evidence}
    candidates = detect_hidden_strengths(match, resume)

    rejected_count = 0
    for candidate in candidates:
        requirement = requirements_by_id.get(candidate.requirement_id)
        anchor = evidence_by_id.get(candidate.evidence_id)
        if requirement is None or anchor is None:
            continue

        accepted = None
        first_failure = None
        for attempt in range(2):
            rewrite = generate_rewrite(requirement, [anchor])
            result = validate_rewrite(rewrite, resume.evidence)
            if result.ok:
                if first_failure is not None:
                    first_failure.retry_succeeded = True
                accepted = rewrite
                break
            failure = store.log_rewrite_rejection(
                analysis_id=analysis_id,
                requirement_id=candidate.requirement_id,
                evidence_id=candidate.evidence_id,
                suggested_phrasing=rewrite.suggested_phrasing,
                violations=result.as_log_violations,
                retry_succeeded=False,
            )
            if attempt == 0:
                first_failure = failure

        if accepted is None:
            rejected_count += 1
            continue

        hidden_strength = HiddenStrength(
            requirement_id=candidate.requirement_id,
            evidence_id=candidate.evidence_id,
            current_phrasing=anchor.source_line,
            suggested_phrasing=accepted.suggested_phrasing,
            facts_used=accepted.facts_used,
            changed_words=accepted.changed_words,
        )
        match = _append_hidden_strength(match, hidden_strength)

    record.match = match
    return {
        "hidden_strengths": [h.model_dump(mode="json") for h in match.hidden_strengths],
        "rejected_count": rejected_count,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_rewrite_endpoint.py -v`
Expected: all PASS.

- [ ] **Step 5: Document the new error code**

In `docs/errors.md`, add a new subsection right after `### \`ANALYSIS_NOT_FOUND\` — 404 Not Found` and before `### \`ENGINE_FAILED\``:

```markdown
### `ANALYSIS_NOT_READY` — 409 Conflict

| | |
|---|---|
| **Trigger** | `POST /api/analyses/{id}/rewrites` called before the analysis has `status: "done"` — there is no `match` yet to run F5 against. Added in Phase 3 alongside the endpoint itself (`PERSON_B_PLAN_v2.md` §5 Phase 3 task 6); not one of the original ten because the endpoint that can raise it did not exist before this phase. |
| **English** | This analysis isn't finished yet. Wait for it to complete before asking for rewrite suggestions. |
| **Khmer** | ការវិភាគនេះមិនទាន់បញ្ចប់ទេ។ សូមរង់ចាំវាបញ្ចប់សិន មុននឹងសុំសំណើសរសេរឡើងវិញ។ |
| **Recovery** | Not user-facing in Phase 3 — the endpoint is called from Phase 4's Hidden Strengths UI, which only appears once `status: "done"`, so a real user should not be able to trigger this. Kept in the envelope rather than a bare exception anyway, per this file's own rule (§1). |
| **i18n key** | `errors.ANALYSIS_NOT_READY` *(Phase 3)* |
```

Update the file's opening banner (the blockquote at the top) and §1's "one of the ten values" line, and `api/errors.py`'s matching docstring comment, from "ten" to "eleven" wherever the code count is stated. Search for every occurrence first:

Run: `grep -rn "ten error\|ten values\|ten codes" docs/errors.md api/errors.py`

Update each match found. (At minimum: the top banner's "The ten error **codes**...", and `api/errors.py`'s `ApiError` docstring, "`code` must be one of docs/errors.md §2's ten values".)

- [ ] **Step 6: Add the i18n catalogue entries**

In `web/messages/en.json`, inside `"errors"`, add (after `"ANALYSIS_NOT_FOUND"`):

```json
  "ANALYSIS_NOT_READY": "This analysis isn't finished yet. Wait for it to complete before asking for rewrite suggestions.",
```

Same key and English text in `web/messages/km.json` (placeholder, per this file's established convention — see Step 5's Khmer column for what a future QA session moves in).

- [ ] **Step 7: Full verification**

Run: `.venv/bin/python -m pytest tests/ -v`
Run: `.venv/bin/python -m ruff check engine api tests`
Run: `.venv/bin/python -m mypy`
Run: `node scripts/i18n-check.mjs` (from the repo root — confirms the new `ANALYSIS_NOT_READY` key stayed in sync between `en.json` and `km.json`)

Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add api/routes/analyses.py api/errors.py docs/errors.md \
        web/messages/en.json web/messages/km.json tests/test_rewrite_endpoint.py
git commit -m "feat(api): add POST /api/analyses/{id}/rewrites, orchestrating F5 end to end"
```

---

## Manual verification (once all ten tasks are merged)

These are the phase's own "Done when" criteria (`PERSON_B_PLAN_v2.md` §5 Phase 3) plus the deliberately-deferred live-LLM check:

- [ ] **Force `JOB_URL_BLOCKED` and screenshot both locales**, updating `docs/errors.md` §4's Phase 2 checklist note that currently reads "Still blocked: ... `JOB_URL_BLOCKED`/`JOB_FETCH_FAILED` (URL fetching is Phase 3 scope)" — `JOB_URL_BLOCKED` is reachable now; `JOB_FETCH_FAILED` still is not (that needs the real `fetch_jd`, CP2).
- [ ] **Run the full pipeline against one real fixture pair with a real `ANTHROPIC_API_KEY`** (not mocked): pick the `fresh_grad_strong_fit` fixture (has 7 evidence records and multiple `partial` results), seed it as a done analysis the same way `tests/test_rewrite_endpoint.py` does, and call `POST /api/analyses/{id}/rewrites` for real. Confirm: at least one hidden strength is detected, its `facts_used` is non-empty and traces to real evidence ids, and — as a manual sanity check — hand-edit one `generate_rewrite` response to insert a fake number, and confirm `precheck_rewrite` catches it before any LLM validation call fires. This is the phase's literal "Done when" bar; it is deliberately not an automated test (no real API key in CI, no non-deterministic model output in the test suite), so it is a one-time developer check, not something automated verification can stand in for.
- [ ] **Confirm `docs/errors.md`'s own error count language matches reality** after Step 5 of Task 10 — reread the top banner once all edits land, since the sentence structure inherited from Phase 2's version may need small rewording beyond a find-and-replace of "ten" → "eleven".
