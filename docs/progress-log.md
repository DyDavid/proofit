# Proofit — Progress Log

**Owner:** Person B · **Compiled:** 15 Sep 2026 · **Updated:** 16 Sep 2026 · **Semester week:** 2 of 15

Sections 1–6 below were compiled 15 Sep, covering Phases 0–2. Section 7 was added 16 Sep,
covering Phase 4. **Phase 3 (URL ingestion, analysis history, the F5 rewrite engine) is not
yet retrospectively logged here** — it happened, extensively, between those two dates (see
`git log`), but no one has gone back and written it up in this document's style. That is a
gap in this log, not a gap in the work; it is not corrected by this update.

This log records what has actually shipped against `PERSON_B_PLAN_v2.md`, phase by phase,
including what was skipped or deferred. It is written to be checkable: every "done" claim
below corresponds to a file in the repo, a commit, or a command that can be re-run.

Where a planned deliverable is **not** done, it says so plainly rather than omitting it.

---

## 1. Schedule position

| | Planned | Actual |
|---|---|---|
| Phase 0 — Foundation | Weeks 1–2 (7–20 Sep) | Substantially complete |
| Phase 1 — Fixtures, types, shell screens | Weeks 3–4 (21 Sep–4 Oct) | Substantially complete |
| Phase 2 — Results experience | Weeks 5–7 (5–25 Oct) | Complete, except the two CP2-blocked tasks |

**The build is running roughly seven weeks ahead of the plan's calendar.** Today is Week 2,
which the plan schedules as mid-Phase-0; Phase 2's own deadline is 25 Oct.

That headroom is real, but it is not uniformly distributed. The work that ran ahead is the
code; the work that lagged is the **human-dependent, calendar-bound** work — collecting
consented resumes, drawing wireframes, showing them to classmates, standing up live hosting.
Those cannot be compressed the way code can, and several of them gate later phases
(§5). The honest summary is: **implementation is far ahead, field and logistics work is behind.**

A second caveat: git history does not corroborate the Phase 0/1 timeline. All Phase 0 and
Phase 1 work was committed in two commits on 14 Sep (`d42067a`, `63614ce`), so the repo
cannot evidence *when* it was built. Phase 2 (26 commits, 14–15 Sep) is fully traceable.

---

## 2. Phase 0 — Foundation

**Goal:** every decision written down, both machines run the stack locally, hosting exists,
data collected. No product code.

| # | Deliverable | Status | Evidence / gap |
|---|---|---|---|
| 1 | Brand, `BRAND.md` | **Done** | `BRAND.md` — positioning, voice rules (§6), colour tokens. Design system later pivoted from indigo to the paper/ink/lac palette now in use. |
| 2 | Monorepo scaffold | **Done** | `web/` (Next.js 15, App Router, TS strict, Tailwind), `api/` (FastAPI + pydantic-settings), `engine/` (installable package, `pyproject.toml`) |
| 3 | Local dev via Docker Compose | **Done** | `deploy/docker-compose.yml`, `api/Dockerfile`, `deploy/runbook.md`. Note: Colima must be started manually on the dev machine. |
| 4 | i18n skeleton | **Done** | `next-intl`, `app/[locale]/` routing, `messages/en.json` + `km.json`, locale switcher in header |
| 5 | Design system + primitives | **Done** | `Button`, `Card`, `Badge`, `Stamp`, `VerdictIcon`, `CoverageStat`. Verdict colours always paired with an icon, never colour alone. |
| 6 | Wireframes + classmate feedback | **Not done** | `docs/wireframes/` contains only a README, which states this plainly. No images, no feedback round. |
| 7 | Hosting accounts + first deploy | **Not done** | `deploy/render.yaml` and the runbook exist; no live URL is recorded anywhere in the repo. |
| 8 | Data collection (15 JDs, 5 resumes) | **Partial** | See below — JDs exceeded in volume but skewed; resumes well short. |
| 9 | `.env.example`, secrets discipline | **Done** | `.env.example` present, `.env` git-ignored, no keys committed |

### Data collection, in detail

**Job descriptions — 25 unique real listings collected** (44 CSV records across four files,
with overlap between them), past the 15 the plan asked for in raw volume:

| Source | Records | | Country | Records |
|---|---|---|---|---|
| CamHR | 24 | | KH | 38 |
| BongThom | 14 | | REMOTE | 3 |
| RemoteOK | 3 | | unlabelled | 3 |
| Arbeitnow | 3 | | | |

Two qualifications matter more than the headline count:

- **The geographic mix does not match the demo story.** The plan asked for 5 local,
  5 Singapore/Japan/Australia, 5 remote-US. Actual: 38 Cambodian, 3 remote, and
  **zero** Singapore, Japan, or Australia listings. F6 (country rules) and the
  cross-border differentiator both depend on JDs that have not been collected.
- **The three individual JD files are synthetic.** `data/jds/*.txt` are hand-written
  stand-ins — `source.json` flags each with `"synthetic": true` and the note
  *"Hand-written stand-in until real JDs are collected"*. The golden fixtures, and
  therefore every demo and screenshot to date, are built on these rather than on the
  25 real listings sitting in the CSVs.

**Resumes — 1 of 5.** `data/resumes/anonymized/candidate_a.txt` only; `raw/` is empty.
`eval/consent_form.md` exists as a bilingual template but is unsigned and unfilled.
The plan explicitly notes these consents are reused for the Phase 6 evaluation study.

---

## 3. Phase 1 — Fixtures, Types, Shell Screens

**Goal:** build every screen without Person A's engine existing, so the engine slots in
with zero UI changes when it lands.

| # | Deliverable | Status | Evidence / gap |
|---|---|---|---|
| 1 | CP1 — schema locked with Person A | **Provisional** | `engine/normalize/schema.py` exists and is the working contract, marked `0.1.0-provisional`. Not yet jointly locked in a CP1 session. |
| 2 | Generated TypeScript types | **Done** | `scripts/gen-types.sh` → `web/lib/schema.json` → `web/lib/types.ts` (generated, never hand-edited). CI workflow present (`.github/workflows/ci.yml`). |
| 3 | Three golden fixtures + validation test | **Done** | `data/fixtures/{fresh_grad_strong_fit,fresh_grad_stretch,unrealistic}.json`, validated by `tests/test_fixtures.py` (schema conformance, verdict-per-requirement, distinct realism verdicts) |
| 4 | FastAPI mock mode | **Done** | `ENGINE_MODE=mock\|live`; `POST /api/resumes`, `POST /api/jobs`, `POST /api/analyses`, `GET /api/analyses/{id}`; in-memory store, `BackgroundTasks`, artificial delay so loading states are honest |
| 5 | Screens v0 (Landing, Analyze, Results) | **Done** | Five screens built: Landing, Analyze, Progress, Results, About |
| 6 | i18n discipline | **Partial** | `scripts/i18n-check.mjs` enforces key parity and reports 0 errors. The planned ESLint rule failing CI on raw JSX string literals was **not** added. |
| 7 | First real deploy + keep-alive | **Partial** | `.github/workflows/keepalive.yml` exists; no live deployment. |

**Carried into Phase 2:** the mock store is explicitly non-durable (in-memory, resets on
process restart) and is scheduled for replacement by Supabase at CP2.

---

## 4. Phase 2 — The Results Experience

**Goal:** finish the screen the examiner will stare at, before the engine behind it exists.

Executed as a written 13-task plan (`docs/superpowers/plans/2026-09-14-phase-2-results-experience.md`),
one task at a time, each with an independent review before the next began, plus a final
whole-branch review. **26 commits**, merged to `main` at `efe489a`.

### What shipped

**Error handling — a real contract, not ad-hoc messages.**
`docs/errors.md` had specified a ten-code error contract before any of it was built; Phase 2
implemented it. A typed `ApiError` (`api/errors.py`) now produces one envelope everywhere —
`{"error": {"code", "message", "error_id"}}` — and every route raises it (no bare
`HTTPException` remains anywhere in `api/routes/`). The frontend switches on `code`, never
on message text, and renders localized copy from a new ten-key `errors.*` catalogue.
Each code routes to the right place in the UI: file-type and size rejections appear
inline under the resume dropzone, empty-job-post errors under the JD tabs (with focus moved
to the field), a missing analysis gets a full-page state with a way back, and an engine
failure gets an error card carrying Retry and a copyable error id.

**Keyword-baseline comparison — the evaluation chapter's argument, made visible.**
Hand-authored TF-IDF baseline fixtures now pair with each golden fixture (separate sibling
files; the schema forbids extra keys, so they could not be merged in). A results-screen
toggle shows the naive matcher's verdict beside the real engine's for every requirement,
plus both aggregate scores side by side.

**Evidence-type storytelling — the product's core differentiator, stated on screen.**
When a requirement is only partly proven by a class project, coursework, or part-time work,
the UI now explains why it counts partially and not fully — in the register `BRAND.md` §6
prescribes: name the claim and its limit in the same breath.

**Progress stepper — three honest states instead of one dead end.**
A real 120-second client-side ceiling, distinct from a server-reported failure. Hitting the
ceiling offers "keep waiting" (the analysis may still finish) rather than discarding work; a
genuine failure offers Retry against a new `POST /api/analyses/{id}/retry` endpoint that
reuses the original resume, job, and country, so nothing is re-uploaded.

**Recovered work.** A "remember the last uploaded resume" feature had been built earlier but
never committed, and was stranded outside the working branch. It was recovered and re-merged.

### A finding worth carrying into the report

The baseline comparison was expected to show the engine beating naive keyword matching
everywhere. Derived honestly and consistently, it does not: on `fresh_grad_strong_fit` the
engine leads by 19.2 points, but on `fresh_grad_stretch` the gap narrows to 2.5, and on
`unrealistic` the naive matcher actually **outscores** the engine by 4.2.

This is not a defect. Those two postings demand depth — *years of professional production
experience*, CI/CD pipelines — while the candidate's resume happens to contain the words
"React", "API", and "pipeline" from unrelated class projects. A keyword matcher cannot tell
a class project from two years of paid work; the engine's F4 rules correctly refuse the
credit. The naive matcher does not merely lose — **on demanding postings it misleads the
candidate into believing they are a better fit than they are**, which is a stronger argument
for requirement-level matching than a uniform win would have been.

The test suite now asserts this pattern directly rather than a "baseline always loses"
invariant, and `web/lib/fixtures/sample-baseline.ts` documents the derivation rule so the
numbers can be defended under questioning.

### Deliberately out of scope

Two of the plan's seven Phase 2 tasks were **not** attempted:

- **Wire the live engine (CP2).** `engine/match/run_match` and `run_baseline` both still
  raise `NotImplementedError` — they are Person A's, and unfinished. There is nothing to
  wire. `engine/` was left completely untouched by this phase.
- **Deploy live mode.** Follows the above.

Both are picked up at CP2. Everything else in Phase 2 was built against mock mode, which is
exactly what the phase was designed to allow.

### Quality state at merge

| Check | Result |
|---|---|
| Backend tests | 27 passed, 0 failed |
| Frontend typecheck (`tsc --noEmit`) | Clean |
| Lint (`eslint .`) | 0 errors (1 pre-existing warning in generated `types.ts`) |
| i18n key parity | 128 keys, 0 errors |

Four genuine bugs were caught and fixed during review that automated checks would not have
found — two of them defects in the *plan's own prescribed code*: a fixture-pairing bug that
would have compared a resume against one job's baseline and another job's match, and a
"keep waiting" button that would have silently done nothing. The other two: a test that
passed without exercising the code it claimed to test, and developer-facing error strings
reaching users.

---

## 5. Outstanding items, in priority order

Ordered by how much they gate later work, not by effort.

1. **Collect consented resumes (4 more).** Phase 6's evaluation study depends on these, and
   the plan says to book raters in Week 11 — but the resumes must exist first. The consent
   template is ready; this is purely a matter of asking classmates. **Longest lead time of
   anything on this list.**
2. **Collect Singapore / Japan / Australia JDs.** Currently zero. F6 country rules and the
   cross-border differentiator — a headline claim on the landing page — have no data behind
   them.
3. **CP1 — lock the schema with Person A.** Currently provisional. Everything downstream
   depends on it, and the longer it stays unlocked the more expensive a change becomes.
4. **Stand up the live deployment.** Vercel + Render, per `deploy/runbook.md`. The plan
   wanted a live URL in the proposal document; the keep-alive workflow is already written
   and waiting for something to keep alive.
5. **Rebuild the fixtures on real JDs.** The demo currently runs on synthetic stand-ins.
   Twenty-five real listings are already collected and unused.
6. **Draw the wireframes and run the classmate feedback round.** Five screens are already
   built, so this is now partly retrospective — but the feedback round still has value, and
   the plan counts it as a deliverable.
7. **Add the raw-JSX-string ESLint rule** so i18n discipline is enforced by CI rather than
   by habit.

### Known minor items, deliberately deferred

Roughly two dozen minor findings were raised during Phase 2 reviews and consciously parked
as non-blocking — a duplicated coverage label, a doc clause broader than the behaviour it
describes, a missing regression test for one recently fixed edge case. They are recorded in
the commit history and the plan document. None affect correctness.

One larger deferred item worth naming: **`web/messages/km.json` contains no actual Khmer.**
All 128 keys are byte-identical to the English. This is intentional and tracked — `docs/errors.md`
§4 and the plan both schedule a Khmer QA session with Khmer-first speakers for Phase 5 — but
it does mean the bilingual claim is currently structural, not substantive.

---

## 6. Next checkpoint

**CP2 — wire the live engine.** Blocked on Person A delivering `run_match` / `run_baseline`.
When it lands, the work is: flip `ENGINE_MODE=live`, call the contract functions from the
background task, replace the in-memory store with Supabase, and reconcile any place the live
output differs from the fixtures — fixing the fixture, never the UI.

The whole point of Phase 2's mock-mode design is that this is a single integration step
rather than a rebuild. Until then, Phase 3 work (URL ingestion, analysis history, and the
F5 rewrite engine — which is Person B's to build, not Person A's) can proceed independently.

---

## 7. Phase 4 — Hardening F5, Building F6

**Updated:** 16 Sep 2026, at the close of a 5-task hardening plan run on branch
`phase-4-hardening-f5-f6` (`docs/superpowers/plans/` — the plan's brief set is in
`.plan-briefs/`). This section reports against `PERSON_B_PLAN_v2.md`'s seven Phase 4 tasks.

| # | Task | Status | Evidence / gap |
|---|---|---|---|
| 1 | 30-case adversarial suite + precision/recall table | **Done** | `tests/rewrite_cases.py` — 20 adversarial cases across six categories, 10 legitimate rephrasings (three deliberately citing real employment/internship/part-time evidence, to prove the Task 2 gate doesn't over-fire). `scripts/validator_metrics.py` prints the precision/recall table. |
| 2 | Scope-inflation rule as code (not prompt) | **Done** | `engine/rewrite/forbidden.json` (5 phrases, bilingual reason strings) + `engine/rewrite/validate.py::precheck_scope_inflation`, run before any LLM call, before the pre-check, before anything that costs money. |
| 3 | Hidden strengths UI | **Done** | `web/components/results/HiddenStrengths.tsx` — before/after with word-level diff, `facts_used` chips expanding to the cited evidence, Copy/Reject, a passed/rejected counter fed by `POST /api/analyses/{id}/rewrites`. This plan's own task 5 fixed a gap surfaced by an earlier task in the same plan: `web/lib/fixtures/sample-match.ts` had zero `hidden_strengths` entries, so the section rendered its empty state on the no-`?id=` sample path — the first thing a landing-page visitor and any report screenshot would see. Two entries were added, each checked against the real `precheck_scope_inflation` / `precheck_rewrite` functions directly (not just by eye) before being committed. |
| 4 | F6 country rules config | **Done, exceeds plan** | `engine/country/rules.json` covers **five** markets (KH, SG, JP, AU, REMOTE) against the plan's three (SG, JP, US-remote) — Cambodia and Australia were added. Pydantic loader + completeness test in `tests/test_country_rules.py`. |
| 5 | Country selector effects | **Done** | `web/components/results/CountryFormat.tsx` — (a) format checklist and (b) visa line both re-render on destination change; (c) `api/routes/analyses.py`'s `create_rewrites` resolves `rules_for(record.country)` independently and appends `tone_notes` to the evidence-only rewrite prompt. |
| 6 | Priority actions UI finished | **Verified, already done** | This plan's task 5 re-checked `ResultsInteractive.tsx` against the plan's exact wording rather than assuming Phase 2's work still matched it. All three held: `openRequirement` genuinely opens the target `<details>` and scrolls to it; `coverage_gain` renders through `results.actions.gain` → "+8% required coverage"; an action with a null `requirement_id` degrades to plain text, never a dead button. No code changed for this item — the report says so precisely because nothing needed fixing. |
| 7 | **CP3** — merge to `main`, deploy, run 3 fixture + 5 real pairs on the live URL, screenshot every screen in both locales | **Blocked** | See below. |

Tasks 1–6 are the seven-task list's actual scope; task 7 is a checkpoint gated on
infrastructure outside this list's own tasks, which is exactly why it is reported
separately rather than marked "not done" alongside a real task.

### CP3 is blocked — 16 Sep 2026

CP3 could not be executed, for two independent reasons, verified directly rather than
assumed from an earlier note:

1. **No live engine.** `engine/match/run_match` and `engine/match/run_baseline`
   (`engine/match/__init__.py`, lines 27 and 89) both still unconditionally
   `raise NotImplementedError` — confirmed by reading the current file, not carried over
   from the Phase 2 entry above. CP2 ("wire the live engine," §6) has not happened. Without
   it there is no way to run any *real* resume/JD pair — fixture pairs are the only pairs
   this build can produce a `Match` for at all.
2. **No live deployment.** No Vercel or Render URL is recorded anywhere in the repository.
   `grep` across every tracked file for a `*.vercel.app` or `*.onrender.com` host turns up
   only template placeholders in `deploy/runbook.md`, `PERSON_B_PLAN_v2.md`, and
   `.env.example` (e.g. `https://proofit-api.onrender.com` as an example value in a
   how-to-fill-this-in table) — none of them a URL anyone has actually deployed to. Item 7
   of the outstanding-items list in §5 above ("stand up the live deployment") is still open.

CP3's own wording needs both at once: "the 3 fixture pairs **plus 5 real pairs**
end-to-end **on the live URL**." Fixture pairs alone could, in principle, be run against a
local dev server today — but that is not what CP3 asks for, and faking the checkpoint by
quietly substituting a weaker version of it would misreport where the project actually
stands. So this plan records the blockers instead.

**What unblocks it, in sequence:**

- The moment Person A delivers `run_match` / `run_baseline` (CP2), real pairs become
  possible for the first time, and the 5-real-pairs half of CP3 stops being blocked on
  anything but running them.
- The moment Vercel + Render hosting is stood up (`deploy/runbook.md`, outstanding item 4
  in §5), the live-URL half of CP3 stops being blocked, independently of the first item —
  the 3 fixture pairs could be screenshotted on a live URL today if hosting existed, engine
  or no engine.
- CP3 itself needs both to have landed before "run 3 fixture pairs plus 5 real pairs
  end-to-end on the live URL" is a true statement rather than an aspirational one.

Both blockers are outside Person B's control: the engine is Person A's contract
(`PERSON_B_PLAN_v2.md` §2), and hosting is the calendar-bound, human-dependent kind of work
§1 above already flagged as the project's actual lag, not the code.
