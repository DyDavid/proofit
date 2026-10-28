# Proofit — Project Spec

> Final Year Project, AUPP, 2026. Team of 3. ~15 weeks.
> This document describes the system **as it is built**. When code and this spec
> disagree, fix one of them — do not let them drift.

---

## 1. One-Line Definition

Resume-to-job-description matching for Cambodian entry-level candidates applying
locally or abroad — reads job posts from local boards or any pasted URL/text, matches
at requirement level using non-work evidence, and adapts guidance to
destination-country conventions.

**Cambodia-based, not Cambodia-limited.** Users are Cambodian. Job targets are global.

---

## 2. Problem Statement

Existing tools (Teal, Jobscan, Rezi, Careerflow) fail Cambodian entry-level job seekers
in three ways:

1. **They assume work history exists.** Match engines look for employment bullet
   points. A fresh graduate has coursework, group projects, and part-time work. Every
   requirement returns "Missing."
2. **They can't reach the job posts.** Teal's supported boards include no Cambodian
   sources. Local posts live on CamHR, BongThom, JobNet, and Jobify.
3. **No cross-border guidance.** A Cambodian applying to Singapore or Japan gets no
   help on resume conventions or whether the role sponsors visas.

Mainstream tools also score by **keyword overlap**, which is shallow. "Coordinated 3
departments on launch" satisfies "cross-functional collaboration" with zero shared
keywords.

### Accuracy notes for the report

- Do **not** claim "Teal is USA-only." It is a web app anyone can use. Accurate claims:
  its supported boards include zero Cambodian sources, its resume conventions are
  US-default, its matching is keyword-based, and it assumes prior employment.
- Do **not** frame the project as "beat the ATS score." Most ATS platforms do not
  AI-score resumes. Use **"requirement coverage analysis"**.

---

## 3. Target User

Cambodian job seekers, entry-level focus:
- Fresh graduates with no formal employment
- Early-career applicants (0–2 years)
- Applying locally **and** abroad (Singapore, Japan, Australia, remote-US)

Evaluation population: AUPP final-year students.

The UI is **English only**. Khmer (`km`) localisation and `next-intl` were removed
(`docs/superpowers/plans/2026-09-21-remove-khmer-i18n.md`); copy lives in
`web/messages/en.json` and is read through `web/lib/copy.tsx`.

---

## 4. The Six Features — as built

| # | Feature | Status | Where |
|---|---|---|---|
| F1 | Multi-source JD ingestion | **Built** (paste + URL); no scheduled scraper | `engine/ingest/`, `api/routes/jobs.py` |
| F2 | LLM normalization | **Built** | `engine/normalize/` |
| F3 | Requirement-level match | **Built** | `engine/match/matcher.py`, `rules.py` |
| F4 | Non-work evidence mapping | **Built** — enforced in code twice | `engine/match/rules.py`, `schema.py` |
| F5 | Hidden strengths & rewrite | **Built** — 3-layer validator | `engine/rewrite/`, `POST /analyses/{id}/rewrites` |
| F6 | Cross-border adaptation | **Built in engine/API**; Results panel hidden for now | `engine/country/`, `api/routes/countries.py` |

### F1 — Multi-source JD ingestion
- User pastes raw text (≥ 40 chars) or a URL. `POST /api/jobs` stores it and dedupes
  by SHA-256 content hash, returning `{job_id, cached}`.
- URLs are fetched **during the live analysis** by `engine.ingest.fetch_jd`, which is
  cache-aware (`data/.cache/*.json`, keyed by URL hash).
- `scrape_job_url` routes by host: dedicated extractors for **CamHR**, **JobNet**,
  and **Jobify**; everything else (BongThom, Greenhouse, Lever, Workday, …) goes
  through a generic extractor that tries schema.org **JSON-LD `JobPosting`** first,
  then main-content HTML.
- **LinkedIn and Facebook are refused** (API blocklist + scraper check) with
  `JOB_URL_BLOCKED`; the user is told to paste the text instead.
- `POST /api/jobs/fetch-url` returns fetched text for preview.
- Present but **not wired** to any route: `engine/ingest/ocr.py` (pytesseract
  screenshot OCR) and `is_url_allowed_by_robots` in `scraper.py`.
- Real postings were collected offline into `data/jds/*.csv` (CamHR, BongThom,
  Khmer boards, RemoteOK/Arbeitnow). No scheduled scraper runs in production.

### F2 — LLM normalization
- `normalize_jd(text) -> Job` and `normalize_resume(bytes, filename) -> Resume` call
  Gemini with a Pydantic `response_schema` (structured JSON output, temperature 0).
- JD: extracts **at most 10** requirements, balanced across both "details" and
  "requirements" sections of the post, each tagged `required | preferred` and with a
  category and canonical `normalized_skill`. Also extracts seniority, years required,
  education, and the visa signal (`sponsors_visa` + verbatim source line).
- Resume: text extracted with pdfminer (PDF) / python-docx (DOCX, incl. tables) /
  UTF-8 fallback, then turned into typed `evidence` records with verbatim
  `source_line`s.
- Both normalizers keep an in-process cache keyed by content hash. In the live
  pipeline, the resume and JD are normalized **in parallel** threads.

### F3 — Requirement-level match engine
One verdict per requirement, not one score.

| Verdict | Meaning |
|---|---|
| **Proven** | Explicit evidence; cites the evidence record(s) |
| **Partial** | Adjacent or transferable evidence (incl. non-work evidence for experience) |
| **Missing** | No evidence; carries an explicit `missing_reason` |

- **One batched Gemini call** judges every requirement against every evidence record
  (`thinking_budget=0`, temperature 0), returning verdict, evidence ids, a reasoning
  sentence under 15 words, and confidence.
- Coverage (`engine/match/rules.py`): requirement weight **required = 1.0,
  preferred = 0.4**; verdict score **proven = 1.0, partial = 0.5, missing = 0.0**.
  `coverage_score` covers all requirements; `coverage_required_only` is the headline.
- Realism verdict:
  - `unrealistic` — JD asks ≥ 4 years and candidate has < 1 year paid work, **or**
    ≥ 3 required requirements missing, **or** > 40 % of required missing.
  - `strong_fit` — no required missing and ≥ 60 % of required proven.
  - `stretch` — otherwise.
- Priority actions: up to 5, ranked by percentage-point gain in coverage if the gap
  were closed, with category-specific advice text (e.g. `+8.3% Match Boost: …`).
- **Baseline**: `run_baseline` is a TF-IDF cosine keyword matcher over the same
  normalized pair. It exists to be beaten — it powers the "Compare with keyword
  baseline" toggle and the evaluation comparison column.
- Embeddings (`gemini-embedding-001`, 768-d) are computed **after** the match and
  persisted to pgvector for later analysis. They are **not** used to shortlist
  evidence for the judge.

### F4 — Non-work evidence mapping
- Evidence taxonomy: `employment`, `internship`, `part_time`, `coursework`, `project`,
  `volunteer`, `certification`, `competition`.
- Employment-grade: `employment`, `internship`, `part_time`. Non-employment:
  `coursework`, `project`, `volunteer`, `competition`.
- An `experience` requirement cited **only** by non-employment evidence is
  downgraded `proven → partial` by `enforce_no_scope_inflation` (with a
  `[Scope Rule F4]` reasoning note), and the `Match` model independently rejects any
  such `proven` verdict at validation time.
- The Results screen explains *why* a class project counts only partially.

### F5 — Hidden strengths & rewrite assistant
`POST /api/analyses/{id}/rewrites` (runs on demand from the Results screen):
1. **Detect** (`detect.py`) — LLM finds `partial`/`missing` requirements that an
   existing evidence record actually satisfies; candidates citing unknown ids are
   dropped.
2. **Generate** (`generate.py`) — input is **evidence records only** plus the
   requirement wording; output must list `facts_used`. Country `tone_notes` from F6
   are applied when the destination has rules. Temperature 0.4 so a retry differs.
3. **Validate** (`validate.py`), three layers in order:
   1. Deterministic scope-inflation gate — forbidden phrases
      (`engine/rewrite/forbidden.json`, e.g. "professional", "worked at") when every
      cited record is non-employment.
   2. Deterministic pre-check — every number, year, month count, and capitalised
      proper noun must appear in a cited evidence record.
   3. Separate LLM validator for quiet overstatement ("led" vs "participated").
4. One retry on failure. Every rejection is logged
   (`store.rewrite_rejections`, in-memory) as an evaluation figure.
5. Accepted rewrites become `HiddenStrength` records (with `changed_words` for the
   word-level diff) and the whole `Match` is re-validated before saving.

Rewrites always call Gemini, **even in `ENGINE_MODE=mock`**, so they need
`GEMINI_API_KEY`. Rate limits surface as `RATE_LIMITED` (429).

### F6 — Cross-border adaptation & realism
- Country conventions are config, not code: `engine/country/rules.json` covers
  **KH, SG, JP, AU, REMOTE (US remote)** — page length, photo, personal details,
  date format, section order, tone notes, visa terms.
- `rules_for()` reconciles the three spellings in the codebase (browser keys like
  `usRemote`, ISO codes like `SG`, long names like "United States"). The UI's
  "other" destination has no rules by design.
- Served by `GET /api/countries` and `GET /api/countries/{destination}`; used by F5
  rewrites for tone.
- Visa/sponsorship signal is extracted by the JD normalizer into `Job.sponsors_visa`
  (`yes | no | unstated`) with the verbatim source sentence.
- The `CountryFormat` Results panel exists but is **hidden for now**.

### Dependency chain

```
F1 ingest → F2 normalize → F3 match ⇄ F4 rules
                              ↓
                    F5 rewrite ← F6 country rules (tone)
```

---

## 5. Explicitly Out of Scope

Commodity, Teal-dominated features that would eat the semester:

- Application tracker / kanban pipeline
- Networking CRM / contact manager
- Cover letter generator
- Chrome extension
- Template gallery
- Employer-side portal
- Mobile app
- Auto-apply
- Interview prep
- User accounts / authentication (resumes are remembered per browser via
  `localStorage` only)
- Khmer UI localisation (removed)

---

## 6. Architecture

```
Browser (Next.js, same origin)
   │  /api/*  ──rewrite──▶  FastAPI (api/)
   │                          │
   │   POST /resumes ─────────┤ parse text (pdfminer / python-docx) → store
   │   POST /jobs ────────────┤ content-hash dedupe → store
   │   POST /analyses ────────┤ BackgroundTask:
   │                          │   ├─ normalize_resume ┐ (parallel threads)
   │                          │   ├─ fetch_jd → normalize_jd ┘
   │                          │   ├─ run_match  (Gemini judge + F4 rules)
   │                          │   ├─ run_baseline (TF-IDF)
   │                          │   └─ embeddings → pgvector (best-effort)
   │   GET /analyses/{id} ◀───┤ poll: status, stage, match, baseline
   │   POST …/rewrites ───────┘ F5 detect → generate → validate
```

**Key design decision:** both the JD and the resume normalize to **one schema**
(`engine/normalize/schema.py`). Matching is schema-vs-schema, not text-vs-text. This
is the architecture story for the defense.

### Boundaries
- `api/` calls exactly five engine callables: `normalize_jd`, `normalize_resume`,
  `fetch_jd`, `run_match`, `run_baseline` — plus the F5/F6 modules owned by the API
  side (`engine.rewrite.*`, `engine.country.rules`).
- Nothing in `engine/` imports FastAPI or knows about HTTP.
- `engine/gemini_client.py` is the single Gemini wrapper (structured JSON, text,
  embeddings, model aliasing, fallback model list). `engine/rewrite/llm.py` is a thin
  separate wrapper so rewrites can run in mock mode.

### Engine modes
- **`mock`** — analyses return a golden fixture from `data/fixtures/` after
  `MOCK_DELAY_SECONDS`, stepping through the progress stages. No normalizer/matcher
  LLM calls; Supabase is disabled.
- **`live`** — the full pipeline above. If the live pipeline throws, the API logs the
  real error and stores a fallback result with a generic `error_message`
  ("The live engine could not complete this analysis.") — raw provider errors are
  never returned to the browser.

### Analysis lifecycle
`status`: `queued → running → done | failed`
`stage`: `reading_resume → reading_job → matching_requirements → checking_realism`
The Progress screen polls `GET /api/analyses/{id}` with a 120 s client-side ceiling
that offers "keep waiting" rather than discarding work; a failure offers Retry.

### Storage
`api/store.py` writes through to Supabase when `SUPABASE_URL` is set (and not in
mock mode), otherwise keeps everything in memory (lost on restart).
Tables (`data/supabase_schema.sql`): `resumes`, `jobs`, `analyses`,
`jd_requirements`, `resume_evidence` (the last two hold 768-d pgvector embeddings).

---

## 7. Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15 (App Router, standalone output) · React 19 · TypeScript strict · Tailwind CSS 4 |
| Backend | Python 3.12 · FastAPI · uvicorn · pydantic v2 / pydantic-settings |
| LLM | Google Gemini via `google-genai` (legacy `google-generativeai` as fallback SDK) |
| Default model | `gemini-3.1-flash-lite` (`GEMINI_MODEL`, overridable per stage via `GEMINI_EXTRACT_MODEL`, `GEMINI_ANALYSIS_MODEL`) |
| Embeddings | `gemini-embedding-001`, 768 dims |
| Database | Supabase (PostgreSQL + pgvector), `supabase-py`; optional |
| Resume parsing | `pdfminer.six`, `python-docx` |
| JD fetch | `httpx` + regex/JSON-LD extraction |
| Baseline | Custom TF-IDF cosine (`engine/match/baseline.py`) |
| Types | `scripts/export_schema.py` → JSON Schema → `json-schema-to-typescript` → `web/lib/types.ts` |
| Quality | pytest, ruff, mypy (strict), `tsc --noEmit`, GitHub Actions |
| Hosting | Vercel (web) · Render free tier, Singapore, Docker (API) |

The engine stays thin on purpose: the API runs on a 512 MB Render instance, so no
local embedding models or torch.

### Ownership (see `PERSON_B_PLAN_v2.md` §2)
- **Person A (Dy David)** — `engine.normalize`, `engine.match`, `engine.ingest`, DB migrations.
- **Person B** — `web/`, `api/`, `engine.rewrite` (F5), `engine.country` (F6),
  `data/fixtures/`, `deploy/`, `eval/`.

---

## 8. Core Schema

Single source of truth: [`engine/normalize/schema.py`](engine/normalize/schema.py)
(`SCHEMA_VERSION = "0.1.0-provisional"`). Every model sets `extra="forbid"`.
TypeScript types are generated, never hand-written; CI fails if they are stale.

```text
Job
  source_url?, source_type: scraped|pasted, content_hash, title, company?, location?,
  country? (ISO-2 or REMOTE), industry, seniority: intern|entry|junior|mid|senior,
  years_exp_required?, education_required?, sponsors_visa: yes|no|unstated,
  sponsors_visa_source_line?, salary_range?,
  requirements[]: { id "r\d+", text (verbatim), category, priority: required|preferred,
                    normalized_skill?, display_order? }

Resume
  candidate_summary, total_years_work (paid only), education[]: {degree, institution, year?, gpa?},
  evidence[]: { id "e\d+", source_line (verbatim), evidence_type, skills[],
                duration_months?, team_size?, outcome? }

Match
  coverage_score, coverage_required_only, realism_verdict: strong_fit|stretch|unrealistic,
  realism_explanation?, results[]: { requirement_id, verdict, evidence_ids[], reasoning,
                                     confidence, missing_reason? },
  hidden_strengths[]: { requirement_id, evidence_id, current_phrasing, suggested_phrasing,
                        facts_used[], changed_words[] },
  priority_actions[]: { text, requirement_id?, coverage_gain? }  (bare strings accepted),
  engine_version, generated_at, job?, resume?

BaselineMatch
  method: "tfidf", coverage_score, results[]: { requirement_id, verdict, score, matched_terms[] }
```

Validators enforced at parse time:
- One result per requirement; every requirement has a verdict.
- Every cited requirement/evidence id resolves to the embedded job/resume.
- `missing` ⇒ no evidence ids and a non-empty `missing_reason`; `proven`/`partial` ⇒ ≥ 1 evidence id.
- No `proven` experience requirement backed only by non-employment evidence.
- A `HiddenStrength` must include its own `evidence_id` in `facts_used`.

---

## 9. Non-Negotiable Rules — and where they are enforced

| # | Rule | Enforcement |
|---|---|---|
| 1 | **No invented facts.** Rewrites use only the candidate's evidence and cite `facts_used`. | `generate.py` input contract; 3-layer `validate.py`; `HiddenStrength._cites_its_own_evidence`; rejection log |
| 2 | **No scope inflation.** A class project is never "professional experience." | `rules.enforce_no_scope_inflation`; `Match._enforce_no_scope_inflation`; F5 forbidden-phrase gate |
| 3 | **Every verdict is traceable.** | `MatchResult._traceable`; `Match._references_resolve` |
| 4 | **Cache by content hash.** Never re-normalize the same JD. | `store.add_job` dedupe; normalizer in-process cache; `ingest/cache.py` URL cache |
| 5 | **Respect robots.txt; rate-limit; store extracts with a link back.** | ⚠️ `is_url_allowed_by_robots` exists but is **not called** yet (see §12) |
| 6 | **Never scrape Facebook or LinkedIn.** | `api/routes/jobs.py` blocklist + `scrape_job_url` refusal → `JOB_URL_BLOCKED` |

Also: raw provider/LLM errors are never returned to the browser — only a stable
error `code`, a generic message, and an `error_id` (see `docs/errors.md`).

---

## 10. API Contract

Error envelope everywhere: `{"error": {"code", "message", "error_id"}}`. The UI
switches on `code`, never on `message`. Codes: `RESUME_BAD_TYPE` (415),
`RESUME_TOO_LARGE` (413), `RESUME_UNREADABLE` (422, documented), `RESUME_NOT_FOUND`
(404), `JOB_EMPTY` (422), `JOB_URL_BLOCKED` (422), `JOB_FETCH_FAILED` (502),
`JOB_NOT_FOUND` (404), `ANALYSIS_NOT_FOUND` (404), `ANALYSIS_NOT_READY` (409),
`ENGINE_FAILED` (500), `RATE_LIMITED` (429), `COUNTRY_RULES_NOT_FOUND` (404),
`INTERNAL` (500).

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /api/health` | — | `status`, `engine_mode`, `app_version`, `has_key` |
| `POST /api/resumes` | multipart `file` (PDF/DOCX, ≤ `MAX_UPLOAD_BYTES`) | `{resume_id}` |
| `POST /api/jobs` | exactly one of `{text}` / `{url}` | `{job_id, cached}` |
| `POST /api/jobs/fetch-url` | `{url}` | `{url, text, word_count}` |
| `POST /api/analyses` | `{resume_id, job_id, country}` | 202 `{analysis_id, status}` |
| `GET /api/analyses/{id}` | — | `{status, stage, match, baseline, error, error_message}` |
| `GET /api/analyses` | `?resume_id=` | `[{analysis_id, job_title, company, coverage, realism_verdict, created_at}]` |
| `POST /api/analyses/{id}/retry` | — | 202 `{analysis_id, status}` |
| `POST /api/analyses/{id}/rewrites` | — | `{hidden_strengths[], rejected_count}` |
| `GET /api/countries` | — | `{countries: [{code, display_name}]}` |
| `GET /api/countries/{destination}` | — | full `CountryRules` |

---

## 11. Frontend

Routes (`web/app/`): `/` Landing · `/analyze` · `/progress?id=` · `/results?id=` · `/about`.

- **Analyze** — resume dropzone (remembers the last `resume_id` in `localStorage`),
  job post tabs (paste text / paste URL), destination selector (Cambodia, Singapore,
  Japan, US remote, Australia, Other), and analysis history for the remembered resume.
- **Progress** — stage stepper driven by polling, 120 s ceiling, retry on failure.
- **Results** — coverage ring + required-only stat, realism stamp, verdict filter
  pills, requirement rows grouped gaps-first (missing → partial → proven) with cited
  evidence line, reasoning and confidence, keyword-baseline toggle, priority actions,
  and the on-demand Hidden Strengths (before/after with changed words highlighted).
  `/results` with no id renders a built-in sample.
- Verdict colours are always paired with an icon. Brand and voice: `BRAND.md`.

---

## 12. Current Status & Known Gaps

Status as of the latest commits on `main`: all six features exist; the test suite
(244 tests) passes in mock mode.

Known gaps — honest list for the report and for the next work items:

| Area | Gap |
|---|---|
| Ingestion | `is_url_allowed_by_robots` is never called, so rule 5 is not enforced in code. No rate limiting on outbound fetches. OCR module unused. |
| Matcher | If Gemini cites evidence ids that do not exist, the matcher substitutes the resume's first evidence record rather than downgrading the verdict. |
| Live fallback | On a live-pipeline exception, the stored result is a golden fixture's verdicts with the real job/resume attached, marked `done` (with a generic `error_message`). |
| Concurrency | `_run_live_analysis` is `async` but performs blocking LLM calls, which can stall other requests (including progress polling) on a single worker. |
| Persistence | Rewrite rejections are in-memory only. Without Supabase, all data is lost on restart. |
| F6 UI | `CountryFormat` panel hidden on Results. |
| Health | `GET /api/health` also returns the first characters of the API key (`key_prefix`); consider removing. |
| Data | Few real non-Cambodian JDs; most golden fixtures were built from synthetic JDs (`data/jds/source.json`). One anonymized resume. |
| Schema | Still marked `0.1.0-provisional`. |

---

## 13. Evaluation

- `eval/run_pairs.py` runs resume–JD pairs from `eval/pairs.json` through
  `run_match` and `run_baseline`, writing `eval/system_outputs.json` (stamped with
  `SCHEMA_VERSION`).
- `eval/analysis.py` computes percent agreement and 3-class **Cohen's kappa**
  between human raters, the system, and the TF-IDF baseline.
- Target: 20 pairs, 2–3 local recruiters or career-services staff rating independently.
- Report also: rewrite validator rejection count/rate (from the rejection log).
- Consent form: `eval/consent_form.md`.

Deliverable: a table with three columns — human, Proofit, baseline.

---

## 14. Defense Preparation

**"Why not just use Teal?"**
> Teal counts keywords and assumes you already have a career. We check whether the
> candidate's actual evidence — including coursework and projects — satisfies each
> stated requirement, and we read the job boards Teal cannot reach.

**"How do you know the match score is correct?"**
> Recruiter agreement study compared against a TF-IDF keyword baseline, reported as
> percent agreement and Cohen's kappa. The baseline is visible in the product itself
> via the comparison toggle.

**"What stops the AI from making things up?"**
> Rewrites receive only the candidate's own evidence records, every rewrite must cite
> its evidence ids, and a three-layer validator (forbidden-phrase gate, literal-token
> pre-check, separate LLM check) rejects untraceable claims. Rejections are logged.
> The schema itself refuses untraceable verdicts and scope-inflated `proven` verdicts.

**"Is the scraping legal?"**
> URLs are fetched one at a time on a user's request, not crawled. Facebook and
> LinkedIn are refused outright; the user can paste the text instead. Structured
> extracts are stored with the source URL. (Wire in the existing robots.txt check
> before the defense — see §12.)

---

## 15. Risk Register

| Risk | Mitigation |
|---|---|
| LLM invents experience | Evidence-only input, `facts_used` citation, 3-layer validator, schema validators, logged rejections |
| Weak differentiation at defense | Lead with non-work evidence mapping and local board reach |
| Scraper breaks on layout change | URL cache; paste path always works |
| Gemini rate limits / quota | Model alias map + fallback list in `gemini_client.py`; `RATE_LIMITED` surfaced cleanly; mock mode for demos |
| Render free tier sleeps / Supabase pauses | `keepalive.yml` health ping; in-memory fallback; `ENGINE_MODE=mock` offline demo via Docker Compose |
| LLM cost | Content-hash dedupe and normalizer cache; one batched judge call per analysis |
| Schema drift between Python and TypeScript | Generated types + CI staleness check |
| Scope creep | §5 is binding |
