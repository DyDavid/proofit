# Person B — Full Semester Plan (v2)

> Product / Experience owner. Companion to `PROJECT_SPEC.md`.
> Semester start: Mon 7 Sep 2026. Week 15 ends: Sun 20 Dec 2026.
> Each phase below ends with a **Claude Code prompt** you can paste verbatim to start that phase's work.

---

## 0. Locked Decisions (do not revisit)

| Decision | Choice | Why |
|---|---|---|
| Frontend | **Next.js 15 (App Router) + TypeScript + Tailwind** | Demo polish; rubric weights demo quality |
| Backend | **FastAPI (Python 3.12)** | Person A's engine is Python; one language for the pipeline |
| Database | Supabase (PostgreSQL + pgvector), accessed only from FastAPI | Spec-mandated; frontend never touches DB directly |
| LLM | Anthropic API, called only from FastAPI | Keys never reach the browser |
| Deployment | **Vercel (Next.js, free) + Render free web service (FastAPI, Docker)** | $0. Trade-off: the API sleeps after ~15 min idle and takes 30–60 s to wake — mitigated by a keep-alive ping and a pre-demo warm-up (Section 8) |
| UI language | **Khmer + English from day one** (`next-intl`, `km` / `en`) | Target user is Cambodian; bilingual UI is a visible differentiator |
| Generated content language | English by default (resumes for global jobs are English); reasoning/explanations get a Khmer toggle | Keeps rewrite validator single-language and testable |
| Team split | **2 people.** Person A = data/intelligence. Person B (you) = product/experience + F5 + evaluation + deployment | Matches `TEAM_PLAN.md` |

**Language split rule** (write this on the wall): UI chrome, labels, empty states, errors, onboarding = bilingual. Requirement text, evidence lines, rewrites = English (they come from English JDs/resumes). Verdict reasoning = English with optional Khmer translation call (Phase 5, stretch).

---

## 1. Brand Name — pick one

I cannot verify domain or trademark availability; check `.com` / `.app` / `.kh` and Instagram/Facebook handles before committing. Confirm Khmer romanizations with a Khmer speaker on your team (you'll know better than I do).

| # | Name | Meaning / angle | Tagline draft | Notes |
|---|---|---|---|---|
| 1 | **Spean** (ស្ពាន) | "bridge" — bridges your evidence to their requirements; bridges Cambodia to global jobs | *Bridge the gap between what you've done and what they need* | Short, pronounceable abroad, strong story. **My pick.** |
| 2 | **Phlov** (ផ្លូវ) | "path / road" — the path from graduate to hire | *Your path to the job, requirement by requirement* | Warm; slight risk foreigners mispronounce |
| 3 | **Chhlong** (ឆ្លង) | "to cross" — cross-border angle | *Cross the border with a resume that fits* | Best for the F6 story; harder to spell for non-Khmer examiners |
| 4 | **Proofit** | proof + fit — every verdict is proven with evidence | *Prove your fit* | English, memorable; check trademark, "Proofit" may exist |
| 5 | **Evidently** | evidence-based matching, hidden strengths | *Evidently qualified* | Clean, professional; likely taken as `.com` |
| 6 | **GapMap** | maps requirement gaps, priority actions | *See the gap. Close it.* | Very literal; good for defense slides, less brand warmth |
| 7 | **Coverly** | "requirement coverage" is your core framing | *Know your coverage before you apply* | Generic-startup feel |
| 8 | **Kompas** | direction for job seekers; "kompas" sounds Khmer-adjacent (Kompong…) | *Find your direction* | Overused word globally |

Recommendation: **Spean**. It's two syllables, sounds like a real product, encodes the architecture story (evidence ↔ requirements bridge) and the market story (Cambodia ↔ world). Use `spean.app` or `spean.kh` style, and name the repo `spean`.

The rest of this document uses **Spean** as a placeholder. Find-and-replace once you decide.

---

## 2. Ownership Boundary

### You own
- `web/` — the entire Next.js app (screens, i18n, design system, state, API client)
- `api/` — the FastAPI application shell: routes, request/response models, job orchestration, error handling, auth-lite, CORS, health checks
- `engine/rewrite/` — F5: hidden-strengths detector, rewrite generator, **hallucination validator**, rejection log
- `engine/country/` — F6 country-rules config loader + visa-signal extraction (shared with A; you own the config, A owns extraction prompt if they have time — decide at Checkpoint 2)
- `data/fixtures/` — golden JSON fixtures that let you build screens before A's engine exists
- `deploy/` — API Dockerfile, `render.yaml`, keep-alive workflow, deployment runbook
- `eval/` — evaluation study protocol, rater sheets, agreement analysis notebook
- README, demo script, defense slides for product/UX/evaluation sections

### Person A owns
- `engine/normalize/` (schema Pydantic models, JD + resume normalizers)
- `engine/match/` (embedding shortlist, LLM judge, F4 rules, coverage, realism, TF-IDF baseline)
- `engine/ingest/` (ATS clients, aggregator, URL path, local board module, content-hash cache)
- DB migrations

### The contract between you
1. **Schema contract** — `engine/normalize/schema.py` Pydantic models are law. A publishes them by end of Week 3; you generate TypeScript types from them (`pydantic → JSON Schema → json-schema-to-typescript`). Never hand-write types that already exist in the schema.
2. **Function contract** — A exposes exactly these callables; you call them from FastAPI routes and never reach into their internals:
   ```python
   engine.normalize.normalize_jd(text: str) -> Job
   engine.normalize.normalize_resume(file_bytes: bytes, filename: str) -> Resume
   engine.ingest.fetch_jd(url: str) -> str            # raw text, cache-aware
   engine.match.run_match(job: Job, resume: Resume) -> Match
   engine.match.run_baseline(job: Job, resume: Resume) -> BaselineMatch
   ```
3. **Fixture contract** — every function above has a golden fixture in `data/fixtures/` that A keeps up to date when the schema changes. Your screens are built against fixtures first, live engine second.

---

## 3. Repo Layout (monorepo)

```
spean/
├── web/                     # Next.js 15, TypeScript, Tailwind, next-intl
│   ├── app/[locale]/        # routes: /, /analyze, /results/[id], /about
│   ├── components/
│   ├── lib/api.ts           # typed client for FastAPI
│   ├── lib/types.ts         # GENERATED from schema.py — do not edit by hand
│   ├── messages/en.json
│   ├── messages/km.json
│   └── Dockerfile
├── api/                     # FastAPI
│   ├── main.py
│   ├── routes/{analyze,jobs,resumes,rewrite,health}.py
│   ├── deps.py              # supabase client, anthropic client, settings
│   ├── models.py            # request/response wrappers around engine schema
│   └── Dockerfile
├── engine/                  # importable Python package, no web code
│   ├── normalize/           # A
│   ├── match/               # A
│   ├── ingest/              # A
│   ├── rewrite/             # B  ← F5
│   └── country/             # B  ← F6 config
├── data/
│   ├── jds/                 # 30 hand-collected job posts
│   ├── resumes/             # 5 anonymized PDFs
│   └── fixtures/            # golden JSON per contract function
├── eval/                    # rater sheets, notebook, results table
├── tests/
├── deploy/
│   ├── render.yaml            # FastAPI service definition
│   ├── docker-compose.yml     # local dev only (web + api)
│   ├── runbook.md             # Vercel + Render setup, env vars, warm-up
│   └── keepalive.yml          # → copied to .github/workflows/
├── .env.example
└── README.md
```

---
## 4. Week Calendar

| Week | Dates | Phase | Your headline |
|---|---|---|---|
| 1 | 7–13 Sep | 0 | Brand, scaffold, Vercel + Render accounts, data collection |
| 2 | 14–20 Sep | 0 | Design system, wireframes, i18n skeleton, local Docker working |
| 3 | 21–27 Sep | 1 | Fixtures + generated TS types, FastAPI mock mode |
| 4 | 28 Sep–4 Oct | 1 | Landing + Analyze screens, first live deploy |
| 5 | 5–11 Oct | 2 | Results screen on fixtures |
| 6 | 12–18 Oct | 2 | Async job flow, loading/error states |
| 7 | 19–25 Oct | 2 | Wire live engine (Checkpoint 2), baseline comparison toggle |
| 8 | 26 Oct–1 Nov | 3 | URL input + history; **start F5 engine** |
| 9 | 2–8 Nov | 3 | Rewrite generator + validator v1 |
| 10 | 9–15 Nov | 4 | Validator adversarial suite, rejection log, hidden-strengths UI |
| 11 | 16–22 Nov | 4→5 | F6 country config + selector, priority actions UI |
| 12 | 23–29 Nov | 5 | Polish, Khmer QA, demo mode. **Feature freeze Sun 29 Nov** |
| 13 | 30 Nov–6 Dec | 6 | Evaluation study |
| 14 | 7–13 Dec | 7 | README, offline fallback, slides |
| 15 | 14–20 Dec | 7 | Rehearsals, defense |

Joint checkpoints with A: **CP1** end of Wk3 (schema locked), **CP2** end of Wk7 (live engine wired), **CP3** end of Wk11 (F5/F6 merged), **CP4** end of Wk12 (freeze).

---

## 5. Phase-by-Phase

### Phase 0 — Foundation (Weeks 1–2, 7–20 Sep)

**Goal:** every decision written down, both machines can run the stack locally, hosting accounts exist, data collected. No product code yet.

**Tasks**

1. **Brand.** Pick the name (Section 1). Register domain. Create the GitHub org/repo `spean`. Create a 1-page `BRAND.md`: name, tagline, one-paragraph positioning ("requirement coverage analysis for Cambodian entry-level candidates"), color tokens, logo placeholder (wordmark in Kantumruy Pro is enough).
2. **Scaffold the monorepo** exactly as Section 3. `web/` via `create-next-app` (TypeScript, Tailwind, App Router, ESLint, `src/` off). `api/` with FastAPI + `uvicorn` + `pydantic-settings`. `engine/` as an installable package (`pyproject.toml`) so both `api/` and A's scripts import it the same way.
3. **Local dev.** `docker compose up` (services `web`, `api`) must serve `http://localhost:3000` → Next.js and `http://localhost:8000/api/health` → FastAPI `{"status":"ok"}`. Next.js proxies `/api/*` to the FastAPI URL via `NEXT_PUBLIC_API_URL` so the same code works locally and on Vercel. This is your first "done" artifact.
4. **i18n skeleton.** Install `next-intl`. Routes under `app/[locale]/`. `messages/en.json` + `messages/km.json` with 5 strings. Locale switcher in the header. Load **Kantumruy Pro** (Khmer + Latin, Google Fonts) as the single UI font; set `line-height ≥ 1.7` on Khmer body text (Khmer script has tall stacked consonants and clips at normal line heights).
5. **Design system** in `tailwind.config.ts`: 1 brand color, 3 verdict colors (proven = green, partial = amber, missing = red — plus icons, never color alone), neutral scale, radius, spacing. Build 6 primitives: `Button`, `Card`, `Badge`, `Tabs`, `Gauge` (SVG ring), `Expandable`. Write them once, reuse everywhere.
6. **Wireframes** (Figma, or paper photographed into `docs/wireframes/`): Landing, Analyze, Results, Rewrite panel, Country selector. Show them to 3 classmates; note what confused them.
7. **Hosting accounts.** Create Vercel and Render accounts with the team GitHub org. Import `web/` to Vercel (root directory `web`) and confirm the placeholder landing page deploys on a `*.vercel.app` URL. Create a Render **free web service** from `api/Dockerfile` and confirm `/api/health` responds. Point your domain at Vercel; add `api.yourdomain` as a custom domain on Render if the free tier allows it, otherwise use the `*.onrender.com` URL. Check both platforms' current free-tier terms the day you sign up — they change.
8. **Data collection (shared with A).** You collect 15 of the 30 JDs — bias toward the demo story: 5 CamHR/Bongthom, 5 Singapore/Japan/Australia, 5 remote-US. Save as `data/jds/{slug}.txt` with a `source.json` (URL, board, country, date). Collect the 5 anonymized student resumes (ask AUPP classmates, strip names/phones/emails, get written consent — you'll reuse these consents for Phase 6).
9. **`.env.example`** with every variable both services need. `.env` in `.gitignore`. Never commit a key. Secrets live only in Vercel/Render environment settings.

**Deliverables:** `BRAND.md`, scaffolded repo, `docker compose up` works, placeholder site live on Vercel + `/api/health` live on Render, wireframes, 15 JDs + 5 resumes in `/data`.

**Done when:** A can clone the repo, run `docker compose up`, and see the bilingual landing shell with a locale switcher.

**Claude Code prompt — Phase 0**
```
You are working in the `spean` monorepo (read PROJECT_SPEC.md and PERSON_B_PLAN_v2.md first).
I am Person B. Scaffold Phase 0:
1. `web/`: Next.js 15 App Router, TypeScript strict, Tailwind, next-intl with `app/[locale]/` routing for `en` and `km`, Kantumruy Pro font, a header with locale switcher, and one landing page with placeholder copy from messages/en.json and messages/km.json.
2. `api/`: FastAPI app with `/api/health`, CORS for the web origin, pydantic-settings reading `.env`, and a `deps.py` that lazily constructs Supabase and Anthropic clients.
3. `engine/`: installable package (pyproject.toml) with empty `normalize`, `match`, `ingest`, `rewrite`, `country` subpackages.
4. `deploy/docker-compose.yml` for local dev (web on 3000, api on 8000), `api/Dockerfile` (python:3.12-slim, uvicorn, reads PORT env for Render), `deploy/render.yaml`, and `next.config.ts` rewrites proxying `/api/*` to `NEXT_PUBLIC_API_URL`.
5. `.env.example`, `.gitignore`, root README with run instructions.
Constraints: no business logic yet; every file must run; use Tailwind design tokens (brand, proven, partial, missing) defined in tailwind.config.ts; Khmer text must render with line-height 1.7. Show me the file tree and the exact commands to verify.
```

---

### Phase 1 — Fixtures, Types, Shell Screens (Weeks 3–4, 21 Sep–4 Oct)

**Goal:** you can build every screen without A's engine existing, and the moment A's engine exists it slots in with zero UI changes.

**Tasks**

1. **CP1 (end Wk3):** A publishes `engine/normalize/schema.py`. Sit together for 2 hours and challenge every field: what does the UI need that isn't there? Typical additions you'll want: `job.requirements[].display_order`, `match.results[].evidence_ids` already exists — good; ask for `match.generated_at` and `match.engine_version` for the evaluation chapter.
2. **Generate TypeScript types.** Script `scripts/gen-types.sh`: `python -c "print(Job.model_json_schema())"` → `json-schema-to-typescript` → `web/lib/types.ts`. Add a CI check that fails if `types.ts` is stale relative to `schema.py`.
3. **Golden fixtures.** Hand-write (with Claude's help) 3 complete `Match` JSON objects in `data/fixtures/`: `fresh_grad_strong_fit.json`, `fresh_grad_stretch.json`, `unrealistic.json`. Each must validate against the Pydantic models (add a pytest for this). These are your demo data too — make them realistic: a real AUPP-style resume vs a real collected JD.
4. **FastAPI mock mode.** `ENGINE_MODE=mock|live`. In mock, routes return fixtures with a 1.5 s artificial delay so loading states are honest. Routes to build now:
   - `POST /api/resumes` (multipart PDF/DOCX) → `{resume_id}`
   - `POST /api/jobs` (`{text}` or `{url}`) → `{job_id, cached: bool}`
   - `POST /api/analyses` (`{resume_id, job_id, country}`) → `{analysis_id, status: "queued"}`
   - `GET /api/analyses/{id}` → `{status, match?}` — analyses are async from day one (LLM calls take 10–40 s; a synchronous request will time out behind Caddy and look like a hang)
   - Use FastAPI `BackgroundTasks` now; upgrade to a proper worker only if needed.
5. **Screens v0** against mock mode:
   - **Landing** — headline, 3 differentiator cards (non-work evidence, local JD reach, cross-border), CTA. Bilingual.
   - **Analyze** — two-column: left resume dropzone (PDF/DOCX, 5 MB, client-side validation), right JD tabs `Paste text | Paste URL`, destination-country select, "Analyze" button. Disabled until both inputs present.
   - **Results** — skeleton only: gauge + three verdict columns rendered from fixture.
6. **i18n discipline.** Every user-visible string goes through `t()`. Add an ESLint rule or a grep script that fails CI on raw string literals inside JSX. Keep `km.json` in sync by having a script list keys missing in one file.
7. **First real deploy.** Vercel and Render both auto-deploy on push to `main`; add preview deploys on PRs (Vercel does this by default). Add `.github/workflows/keepalive.yml` that hits `GET /api/health` every 10 minutes so the Render service rarely sleeps. Landing page + mock-mode analysis live on your domain by end of Wk4. Put the URL in your proposal document.

**Deliverables:** `types.ts` generated, 3 validated fixtures, mock-mode API, Landing + Analyze + Results-skeleton, live URL, keep-alive workflow.

**Done when:** you can upload a PDF and paste a JD on the live site and see a fixture result render after a loading state.

**Claude Code prompt — Phase 1**
```
Read PROJECT_SPEC.md, PERSON_B_PLAN_v2.md, and engine/normalize/schema.py (Person A's locked schema).
Phase 1 tasks for Person B:
1. Write scripts/gen-types.sh that exports JSON Schema from the Pydantic models and generates web/lib/types.ts. Add a GitHub Actions job that fails if types.ts is out of date.
2. Create data/fixtures/fresh_grad_strong_fit.json, fresh_grad_stretch.json, unrealistic.json as complete Match objects (with embedded Job and Resume) using the real JD in data/jds/<pick one> and resume in data/resumes/<pick one>. Add tests/test_fixtures.py validating them with Pydantic.
3. In api/, add ENGINE_MODE=mock|live. Implement POST /api/resumes, POST /api/jobs, POST /api/analyses, GET /api/analyses/{id} with an in-memory store, BackgroundTasks, and a 1.5 s delay in mock mode.
4. In web/, build the Analyze page (dropzone + JD tabs + country select + submit) and a Results page skeleton (Gauge + three verdict columns) reading from the API via lib/api.ts with typed responses. Poll GET /api/analyses/{id} every 2 s until status is done or failed.
5. All strings via next-intl; add scripts/i18n-check.ts that lists keys missing from km.json or en.json.
Show me a checklist of what to verify manually in the browser in both locales.
```

---

### Phase 2 — The Results Experience (Weeks 5–7, 5–25 Oct)

**Goal:** the screen the examiner will stare at is finished and beautiful before the engine behind it is finished.

**Tasks**

1. **Results view, full.** Layout top-to-bottom:
   - Header: job title · company · country flag · realism badge (`strong_fit / stretch / unrealistic`) with a one-line plain-language explanation in the user's locale.
   - Two gauges side by side: `coverage_score` and `coverage_required_only`. Label them in Khmer/English; add a tooltip explaining the weighting.
   - Requirement list grouped **Missing → Partial → Proven** (gaps first — that's what the user needs to act on). Within each group, `required` before `preferred`. Each row: requirement text, category chip, priority chip, confidence bar. Expand → the cited `source_line`(s) highlighted, reasoning, evidence type icon (coursework/project/part-time…). If `missing`, show the explicit missing reason.
   - Sticky right rail (desktop) / bottom sheet (mobile): **Priority actions** (from `match.priority_actions`) as a numbered list with estimated coverage gain if A provides it; otherwise ordered only.
   - "Compare with keyword baseline" toggle: shows the TF-IDF verdicts next to yours in a muted column. This single toggle *is* your evaluation-chapter argument made visible — keep it.
2. **Evidence-type storytelling.** Anywhere non-work evidence produced a `partial`, show a small "how this counts" note: e.g. *Class project (4 months, team of 4) — counts as partial evidence for a 2-year experience requirement.* This is F4 made legible; it's your strongest differentiator on screen.
3. **Async job UX.** Progress stepper while polling: `Reading your resume → Reading the job → Matching requirements → Checking realism`. Drive it from a `stage` field you ask A to emit from `run_match` progress hooks; if they can't, fake stages on a timer and switch to real when the result arrives. Timeout at 120 s with a retry button and a copyable error id.
4. **Error handling matrix.** Write `docs/errors.md`: unreadable PDF, scanned-image PDF, empty JD, URL blocked/needs login (LinkedIn, Facebook → message says "paste the text instead"), LLM rate limit, engine exception. Each has a bilingual message and a recovery action. Test every one with a forced failure.
5. **CP2 (end Wk7): wire live engine.** Flip `ENGINE_MODE=live` on your machine. Call A's contract functions from the routes. Persist `Job`, `Resume`, `Match` to Supabase via `supabase-py` in the API layer (tables per A's migration). Fix every place the live shape differs from the fixture — then update the fixture, not the UI.
6. **Performance guardrail.** Log per-stage timings in the API. If end-to-end > 60 s on a typical pair, tell A now; it's their prompt count, not your UI.
7. **Deploy live mode.** Set `ENGINE_MODE=live`, Anthropic and Supabase keys in Render's environment settings only (never in Git). Note: Render free tier has limited RAM (~512 MB) — if A's embedding model is heavy, use the Anthropic/Voyage embeddings API instead of a local model, or the service will OOM. Raise this with A at CP2.

**Deliverables:** finished Results view, stepper, error matrix, live engine wired locally and on Render.

**Done when:** a real AUPP resume + a real CamHR JD run end-to-end on the live URL in under 60 s, and every error case shows a bilingual recovery message.

**Claude Code prompt — Phase 2**
```
Read PROJECT_SPEC.md and PERSON_B_PLAN_v2.md. Person A's engine now exposes engine.normalize.normalize_jd/normalize_resume, engine.ingest.fetch_jd, engine.match.run_match/run_baseline (see engine/*/__init__.py).
Phase 2 for Person B:
1. Build the full Results page per Section 5 Phase 2 of the plan: header with realism badge, two Gauge components, requirement list grouped Missing→Partial→Proven with required-before-preferred ordering, expandable rows showing highlighted source_line + reasoning + evidence-type icon, sticky Priority Actions rail, and a "Compare with keyword baseline" toggle that renders BaselineMatch verdicts in a muted column.
2. Add a "how this counts" note on partial verdicts whose evidence_type is coursework/project/part_time/volunteer/competition.
3. Implement the progress stepper driven by a `stage` field on GET /api/analyses/{id}; fall back to timed fake stages if stage is null. 120 s timeout with retry.
4. Implement the error matrix in docs/errors.md as typed API error codes and bilingual UI messages.
5. Switch api/ to ENGINE_MODE=live: call the engine contract functions in BackgroundTasks, persist Job/Resume/Match to Supabase with supabase-py, and return the stored Match.
Keep all UI strings in messages/en.json and messages/km.json. After each step, list what I should test manually.
```

---
### Phase 3 — URL Path, History, and Starting F5 Early (Weeks 8–9, 26 Oct–8 Nov)

**Goal:** A is busy with ingestion. You expose their URL path in the UI, add analysis history, and start the rewrite engine now so Phase 4 is validation-hardening, not building.

**Tasks**

1. **URL input path.** Wire the `Paste URL` tab to `POST /api/jobs {url}`. Show the `cached: true` state as a small "Already analyzed — loaded instantly" badge; this demonstrates content-hash caching without a slide. Show a friendly block for LinkedIn/Facebook URLs before sending the request (client-side domain check) with the paste-instead message.
2. **History.** `GET /api/analyses?resume_id=` → list past analyses for the current resume: job title, company, coverage, realism badge, date. Lets the demo show "one resume, five jobs, five different verdicts." Identify the user by an anonymous cookie id (no accounts — out of scope).
3. **Start F5: `engine/rewrite/`.**
   - `detect_hidden_strengths(match, resume) -> list[HiddenStrength]`: for each `partial`/`missing` result, ask the LLM whether any evidence record satisfies the requirement despite phrasing; input is the requirement + the full evidence list; output cites `evidence_id`.
   - `generate_rewrite(requirement, evidence_records) -> Rewrite`: **input is evidence records only** — never the raw resume, never the JD summary. Output: `suggested_phrasing`, `facts_used: [evidence_id]`, `changed_words` diff.
   - Prompt rules embedded in the system prompt: no new numbers, no new durations, no new employers, no new tools; may reorder, may use JD vocabulary, may not change evidence_type semantics (project stays project).
4. **Validator v1: `validate_rewrite(rewrite, evidence_records) -> ValidationResult`.** A **separate** LLM call with a separate prompt that receives only the rewrite + the evidence records and returns `{"ok": bool, "violations": [{"claim": str, "reason": str}]}`. Plus a **deterministic pre-check** that runs first and costs nothing: extract every number, year, month-count, and capitalized proper noun from the rewrite; each must appear in at least one `facts_used` evidence record, or fail immediately. Two layers = defensible.
5. **Rejection log.** Every validator failure is written to a `rewrite_rejections` table (rewrite, violations, evidence_ids, timestamp, retry_succeeded). This is a report figure — start counting now.
6. **API:** `POST /api/analyses/{id}/rewrites` → runs detector + generator + validator, retries once on failure, stores accepted rewrites in `match.hidden_strengths`.

**Deliverables:** URL tab live, history list, `engine/rewrite/` with detector, generator, validator v1, rejection log table.

**Done when:** for a fixture pair, at least one hidden strength is detected, a rewrite is produced with `facts_used`, and a hand-crafted rewrite containing an invented number is rejected by the pre-check.

**Claude Code prompt — Phase 3**
```
Read PROJECT_SPEC.md (Section 9 non-negotiable rules) and PERSON_B_PLAN_v2.md Phase 3.
1. Wire the Paste URL tab to POST /api/jobs {url}; client-side block linkedin.com and facebook.com with a bilingual "paste the text instead" message; show a "cached" badge when the API returns cached: true.
2. Add GET /api/analyses?resume_id= and a History section on the Analyze page keyed by an anonymous cookie id.
3. Implement engine/rewrite/ with: detect_hidden_strengths, generate_rewrite (input = evidence records only, output cites facts_used), and validate_rewrite (deterministic pre-check for numbers/dates/proper nouns not present in facts_used evidence, then a separate LLM validation call). Log every rejection to a rewrite_rejections table. Retry once.
4. Add POST /api/analyses/{id}/rewrites.
5. Write tests/test_rewrite_validator.py with at least 5 hand-crafted hallucinated rewrites (invented years, invented employer, upgraded "project" to "employment", inflated team size, invented tool) that MUST be rejected, and 3 legitimate rephrasings that MUST pass.
Explain the validator design in a docstring I can paste into the report.
```

---

### Phase 4 — Hardening F5, Building F6 (Weeks 10–11, 9–22 Nov)

**Goal:** the validator survives an examiner trying to break it; country rules visibly change the output.

**Tasks**

1. **Adversarial suite for the validator.** Grow `test_rewrite_validator.py` to 30 cases across categories: magnitude inflation (3 → 30 users), duration inflation (4 months → 2 years), status upgrade (intern → engineer, project → job), tool insertion, outcome invention, subtle paraphrase that adds a claim ("led" when evidence says "participated"). Record precision/recall of the validator on this suite — that's a table in Chapter 5.
2. **Scope-inflation rule as code, not prompt.** If `evidence_type ∈ {coursework, project, competition, volunteer}` and the rewrite contains any of a wordlist (`professional`, `employed`, `worked at`, `years of experience`, `engineer at`), reject before any LLM call. Wordlist in `engine/rewrite/forbidden.json`, bilingual comments.
3. **Hidden strengths UI.** Section under the requirement list: for each item, left = `current_phrasing` (resume line), right = `suggested_phrasing`, diff-highlighted words, `facts_used` chips that expand to the evidence record. Buttons: `Copy`, `Reject`. A small counter: "3 suggestions passed validation · 1 rejected" — live proof of rule #1.
4. **F6 country rules config.** `engine/country/rules.json` — start with **SG, JP, US-remote** (your demo triad; matches the JDs you collected). Per country: page length, photo yes/no, personal details to include/omit, date format, section order, tone notes, common visa terminology to look for. Loader + Pydantic model + test that every country has every key.
5. **Country selector effects.** Changing the destination country on Results re-renders: (a) a "Format for {country}" checklist derived from the rules, (b) the visa line — `sponsors_visa: yes/no/unstated` from A's normalizer with the JD sentence that triggered it, (c) any rewrites regenerated with country tone notes in the prompt (still evidence-only).
6. **Priority actions UI** finished: each action links to the requirement row it addresses; if A supplies `coverage_gain`, show it as "+8% required coverage."
7. **CP3 (end Wk11):** merge F5/F6 into `main`. Deploy. Run the 3 fixture pairs plus 5 real pairs end-to-end on the live URL and screenshot every screen in both locales for the report.

**Deliverables:** 30-case adversarial suite with results table, forbidden-wordlist gate, hidden strengths UI, `rules.json` for 3 countries, country selector effects, priority actions UI.

**Done when:** an examiner-style hallucinated rewrite is rejected on the live site and the rejection counter increments; switching country changes the checklist and the visa line.

**Claude Code prompt — Phase 4**
```
Read PERSON_B_PLAN_v2.md Phase 4 and engine/rewrite/.
1. Expand tests/test_rewrite_validator.py to 30 adversarial cases in the categories listed; produce a small script that prints validator precision/recall as a markdown table.
2. Add engine/rewrite/forbidden.json and a deterministic scope-inflation gate that runs before any LLM call for non-employment evidence types.
3. Build the Hidden Strengths section on the Results page: before/after with word-level diff, facts_used chips expanding to evidence records, Copy/Reject buttons, and a passed/rejected counter fed by GET /api/analyses/{id}/rewrites.
4. Create engine/country/rules.json for SG, JP, US-remote with the fields in the plan, a Pydantic loader, and a completeness test.
5. Make the country selector on Results re-render the format checklist and visa line, and regenerate rewrites with the country's tone notes appended to the evidence-only prompt.
6. Finish the Priority Actions rail with anchor links to requirement rows.
Keep every string bilingual. List manual test steps at the end.
```

---

### Phase 5 — Polish and Freeze (Weeks 11–12, 16–29 Nov)

**Goal:** it looks like a product, works on a phone, reads correctly in Khmer, and never hangs. **Feature freeze Sunday 29 Nov.**

**Tasks**

1. **Khmer QA session.** Sit with two Khmer-first classmates (not your team) for 45 minutes. They use the app in `km` only. Fix: clipped glyphs, awkward machine-translated labels, verdict words (agree on the Khmer for proven/partial/missing and use it everywhere — write it in `BRAND.md`), number/date formats.
2. **Mobile pass.** Every screen at 375 px. Results list becomes accordion; priority actions become a bottom sheet; gauges stack.
3. **Empty, loading, error states** reviewed screen by screen against `docs/errors.md`. Skeleton loaders, not spinners, on Results.
4. **Accessibility basics:** verdicts carry icon + text, focus rings visible, dropzone keyboard-operable, contrast checked on the three verdict colors.
5. **Demo mode.** `?demo=1` (or a "Try a sample" button on Landing) preloads a fixture resume + JD so the demo needs zero uploads and zero LLM calls if the network dies. Seed Supabase with the 3 fixture analyses.
6. **Onboarding strip** on Analyze: three lines explaining what the tool does and does not do (doesn't invent experience; doesn't "beat ATS"; gives requirement coverage). This is your Section 2 "accuracy note" made user-facing.
7. **Reasoning in Khmer (stretch, only if Wk12 is calm).** `GET /api/analyses/{id}?lang=km` translates `reasoning` and `priority_actions` via one batched LLM call, cached in the DB. Rewrites stay English.
8. **Pre-demo warm-up runbook** (Section 8): the exact commands to wake Render, verify Supabase is unpaused, and run one real analysis 15 minutes before any presentation.
9. **CP4 (end Wk12):** tag `v1.0-freeze`. Anything after this is a bug fix with a linked issue.

**Deliverables:** Khmer QA fixes, mobile layouts, demo mode + seeded DB, onboarding strip, `v1.0-freeze` tag.

**Done when:** you can run the full demo from a phone on mobile data, in Khmer, with the sample data, without touching the keyboard.

**Claude Code prompt — Phase 5**
```
Read PERSON_B_PLAN_v2.md Phase 5. Do a polish pass on web/:
1. Audit every page at 375 px and fix layout; Results requirement list → accordion, Priority Actions → bottom sheet on mobile.
2. Replace spinners with skeleton loaders on Results; verify every state in docs/errors.md renders in both locales.
3. Add a "Try a sample" button on Landing and ?demo=1 support that loads data/fixtures/fresh_grad_stretch.json without calling the API's live engine; add scripts/seed_demo.py that inserts the three fixture analyses into Supabase.
4. Add the onboarding strip on Analyze with the three "what this is / isn't" lines.
5. Accessibility: icon+text on verdict badges, focus-visible styles, keyboard-operable dropzone, run an automated contrast check on the verdict tokens.
6. Write deploy/runbook.md sections "Pre-demo warm-up" and "If Render is asleep".
Then produce a bug-only issue template for post-freeze work.
```

---

### Phase 6 — Evaluation Study (Week 13, 30 Nov–6 Dec)

**Goal:** the numbers the examiner will ask for, with a method you can defend.

**Design**

- **Pairs:** 20 resume–JD pairs from your 5 resumes × collected JDs. Stratify: 7 local (CamHR/Bongthom), 7 SG/JP/AU, 6 remote-US; mix of realistic and stretch fits.
- **Raters:** 2–3 people who screen candidates for a living — AUPP career services staff, an HR contact, a recruiter. Book them in **Week 11**, not Week 13. Offer a summary of results as thanks.
- **Rating protocol** (`eval/rater_sheet.xlsx`, one tab per rater): for each pair, the rater sees the resume and the JD only (no system output). Per requirement, they mark `proven / partial / missing`; per pair, an overall `strong_fit / stretch / unrealistic`. 25–40 minutes per rater.
- **Metrics (`eval/analysis.ipynb`):**
  1. Requirement-level agreement: system vs each rater, TF-IDF baseline vs each rater — percent agreement and Cohen's κ (three-class).
  2. Inter-rater agreement (rater vs rater) — this is your ceiling; if humans agree 70%, a system at 65% is strong.
  3. Realism-verdict agreement per pair.
  4. Non-work evidence subset: agreement restricted to requirements where the system cited coursework/project/part-time evidence — the direct test of F4.
  5. Validator: total rewrites generated, rejected by pre-check, rejected by LLM validator, accepted after retry; plus precision/recall on the Phase 4 adversarial suite.
- **Output:** one table — `Human | Spean | TF-IDF baseline` — plus κ values, and one figure: agreement by evidence type. Freeze the system version used (`v1.0-freeze`) and record the engine version in every stored match.

**Tasks**

1. Mon–Tue: run all 20 pairs through the frozen system and the baseline; export `eval/system_outputs.json`.
2. Tue–Thu: rater sessions (in person; sit with them the first two pairs to calibrate the three verdicts).
3. Fri: analysis notebook, tables, figure; write Chapter 5 draft with A.
4. Log every disagreement where a rater said `proven` and the system said `missing` — read those 10; they're your "limitations" paragraph and your best future-work slide.

**Done when:** the three-column table and κ values exist, and you can explain in one sentence why the system disagrees with humans where it does.

**Claude Code prompt — Phase 6**
```
Read PERSON_B_PLAN_v2.md Phase 6.
1. Write eval/run_pairs.py that loads the 20 pairs from eval/pairs.json, runs engine.match.run_match and run_baseline at the frozen version, and writes eval/system_outputs.json with engine_version.
2. Generate eval/rater_sheet.xlsx: one tab per pair showing the resume text, the JD text, and a per-requirement dropdown proven/partial/missing plus one overall realism dropdown; no system output visible.
3. Write eval/analysis.ipynb that ingests the filled sheets, computes percent agreement and three-class Cohen's kappa for system-vs-rater, baseline-vs-rater, and rater-vs-rater, the non-work-evidence subset agreement, realism agreement, and the validator counts from the rewrite_rejections table; output a markdown table and one matplotlib figure.
Explain each metric in one sentence I can reuse in the report.
```

---

### Phase 7 — Polish, Defense (Weeks 14–15, 7–20 Dec)

**Tasks**

1. **README** with the architecture diagram (draw the "one schema, schema-vs-schema matching" story — it's the defense centerpiece), setup in under 10 commands, `.env` documentation, demo-mode instructions.
2. **Offline fallback.** The live site may be down on the day. Have: (a) demo mode on the deployed site, (b) the same app running on your laptop via `docker compose up` with `ENGINE_MODE=mock` and a local copy of the seeded data, (c) a screen-recorded 3-minute run-through as the last resort. Test all three the day before.
3. **Demo script** (6 minutes): sample resume → CamHR JD → results (point at a `partial` from a class project) → hidden strength rewrite → show the rejected-rewrite counter → switch country SG → JP → priority actions. Then the baseline toggle: "here's what a keyword matcher says about the same pair." Rehearse 5 times; A drives the engine slide, you drive the screen.
4. **Slides you own:** Problem & target user, product walkthrough (screenshots in km and en), F5 safety design (two-layer validator diagram), evaluation results, limitations, future work.
5. **Answers you own** from Section 11 of the spec: "What stops the AI from making things up?" and "How do you know the match score is correct?" — write them out, memorize the numbers.
6. **Supabase + Render warm-up** 30 minutes before the defense; run one real analysis; keep the tab open.

**Done when:** the demo has run cleanly 5 times, offline fallback tested, slides exported to PDF, both defense answers rehearsed aloud with A.

---

## 6. Screen Spec (reference)

| Screen | Route | Components | Data source |
|---|---|---|---|
| Landing | `/[locale]` | Hero, 3 differentiator cards, "Try a sample", locale switcher | static |
| Analyze | `/[locale]/analyze` | Resume dropzone, JD tabs (text/URL), country select, onboarding strip, History list | `POST /resumes`, `POST /jobs`, `GET /analyses` |
| Progress | `/[locale]/results/[id]` (status ≠ done) | Stepper, timeout/retry | `GET /analyses/{id}` polling |
| Results | `/[locale]/results/[id]` | Header + realism badge, 2 gauges, grouped requirement list, evidence expanders, Priority Actions rail, baseline toggle, Hidden Strengths, country format checklist, visa line | `GET /analyses/{id}`, `GET/POST /analyses/{id}/rewrites` |
| About | `/[locale]/about` | Method, what it doesn't do, team, legality statement (robots.txt, no LinkedIn/Facebook) | static |

---

## 7. i18n Rules

1. Every string through `t()`. CI fails on raw JSX literals.
2. Keys are semantic (`results.verdict.partial`), never English sentences.
3. Khmer verdict vocabulary is fixed in `BRAND.md` and used identically in UI, exports, and slides.
4. Font: Kantumruy Pro for both scripts; body line-height 1.7; never `text-xs` for Khmer.
5. Numbers stay Arabic numerals in both locales (Khmer users read them; Khmer numerals hurt scanability).
6. Generated content (requirements, evidence lines, rewrites) is displayed as-is in English regardless of locale, with a subtle "from your resume / from the job post" label so users know why it isn't translated.
7. Reasoning/priority-action translation is a cached, optional stretch (Phase 5.7). If it isn't built, don't fake it.

---

## 8. Deployment Runbook (Vercel + Render free tier)

**Setup (Phase 0)**
1. Vercel: import repo → root directory `web` → framework Next.js → env `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`. Add custom domain.
2. Render: New → Web Service → repo → root `api` → Docker → free plan → env: `ENGINE_MODE`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `CORS_ORIGINS=https://yourdomain,https://*.vercel.app`. Health check path `/api/health`. Bind uvicorn to `0.0.0.0:$PORT`.
3. `next.config.ts` rewrites `/api/:path*` → `${NEXT_PUBLIC_API_URL}/api/:path*` so the browser never deals with CORS or a second origin.
4. Keep-alive: `.github/workflows/keepalive.yml` on a `*/10 * * * *` schedule curling `/api/health`. GitHub may throttle scheduled jobs on quiet repos; add a second pinger on cron-job.org as backup.
5. Supabase: a second scheduled job (weekly) runs a trivial `select 1` through the API so the free project doesn't pause.

**Known free-tier limits to design around**
- Render free: sleeps after ~15 min idle (keep-alive mitigates, doesn't guarantee), ~512 MB RAM, slow cold builds. Keep the API image small; no local embedding models.
- Vercel free: serverless function timeout is short, which is fine because all heavy work is on Render; the Next.js app only renders and proxies.
- Long LLM runs: the async job pattern (Phase 1.4) exists precisely so nothing waits on a single HTTP request.

**Pre-demo warm-up (Phase 5.8, Phase 7.6)**
1. 30 min before: open the site, run "Try a sample," then run one real analysis. Confirm Render logs show the request.
2. Confirm Supabase dashboard shows the project active.
3. Keep the results tab open; if the network dies, switch to the laptop `docker compose up` mock-mode instance.

**If the budget ever allows $7/mo:** upgrade Render to the starter plan and delete the keep-alive job. Nothing else changes.

---

## 9. Person B Risk Register

| Risk | Mitigation |
|---|---|
| Blocked waiting on A's engine | Fixtures + mock mode from Week 3; UI never depends on live engine until CP2 |
| Schema drift breaks the UI | Generated types + CI staleness check; fix fixtures, not UI |
| Render asleep during demo | Keep-alive, warm-up runbook, demo mode, laptop fallback, screen recording |
| Render OOM on embeddings | Embeddings via API, not local model — raise at CP2 |
| Khmer UI reads as machine-translated | Week 12 QA with non-team Khmer-first users; fixed verdict vocabulary |
| Validator too strict (rejects good rewrites) or too loose | 30-case adversarial suite with precision/recall reported honestly |
| Raters unavailable in Week 13 | Book in Week 11; have a third backup rater |
| Scope creep into Section 5 "out of scope" | Feature freeze tag; bug-only issue template |

---

## 10. First Three Things to Do This Week

1. Pick the brand name and register the domain today.
2. Scaffold the repo with the Phase 0 Claude Code prompt and get `docker compose up` working.
3. Message 5 classmates for anonymized resumes with a one-line consent form — this unblocks fixtures, demo data, and the evaluation study at once.
