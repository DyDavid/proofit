# Resume–JD Requirement Matcher — Project Spec

> Final Year Project. Team of 3. ~15 weeks. Rubric weights working product/demo.
> Paste this into Claude Code as project context. Work through Phase 0 → Phase 7 in order.

---

## 1. One-Line Definition

Resume-to-job-description matching for Cambodian entry-level candidates applying locally or abroad — reads JDs from local boards or any pasted URL/text, matches at requirement level using non-work evidence, and adapts output to destination-country conventions.

**Cambodia-based, not Cambodia-limited.** Users are Cambodian. Job targets are global.

---

## 2. Problem Statement

Existing tools (Teal, Jobscan, Rezi, Careerflow) fail Cambodian entry-level job seekers in three ways:

1. **They assume work history exists.** Match engines look for employment bullet points. A fresh graduate has coursework, group projects, and part-time work. Every requirement returns "Missing." The tool is useless to them.
2. **They can't reach the JDs.** Teal's Chrome extension covers 40+ boards, none Cambodian. Local JDs live on CamHR and Bongthom — unreadable to every existing tool built for global boards.
3. **No cross-border guidance.** A Cambodian applying to Singapore or Japan gets no help on resume format conventions or whether the role sponsors visas.

Additionally, mainstream tools score by **keyword overlap**, which is shallow. "Coordinated 3 departments on launch" satisfies "cross-functional collaboration" despite zero shared keywords. Keyword matchers report a gap; a human recruiter sees a match.

### Important accuracy note for the report

Do **not** claim "Teal is USA-only." It is a web app; anyone worldwide can sign up. The accurate claims are:
- Teal's supported job boards include zero Cambodian sources.
- Teal's resume conventions are US-default.
- Teal's matching is keyword-based and shallow (acknowledged in its own user reviews).
- Teal assumes prior employment.

Also do **not** build the project on "beat the ATS score." Most real ATS platforms (Workday, Greenhouse, Taleo) do not AI-score resumes; recruiters run keyword searches. Use the framing **"requirement coverage analysis"** instead — it is defensible.

---

## 3. Target User

Cambodian job seekers, entry-level focus:
- Fresh graduates with no formal employment
- Early-career applicants (0–2 years)
- Applying to local roles **and** abroad (Singapore, Japan, Australia, remote-US)

Evaluation population: AUPP final-year students. Accessible, N≈30 achievable.

---

## 4. The Six Features

### F1 — Multi-Source JD Ingestion
Get any job description into the system regardless of format.
- Paste raw text or URL (any board, any country)
- Scheduled scraper for CamHR / Bongthom
- Content-hash caching so the same JD never re-processes

### F2 — LLM Normalization Engine
Turn messy input into one clean structured schema.
- JD → structured requirement list
- Resume → same schema plus evidence records
- Handles inconsistent formatting, mixed phrasing
- Tags each requirement `required` vs `preferred`

### F3 — Requirement-Level Match Engine
Not one score — a verdict per requirement.

| Verdict | Meaning |
|---|---|
| **Proven** | Explicit evidence; cite the exact resume line |
| **Partial** | Adjacent or transferable evidence exists |
| **Missing** | No evidence found |

Coverage % weighted by required vs preferred. Every verdict traceable to a source line.

### F4 — Non-Work Evidence Mapping
Make the system usable by people with no employment history.
- Evidence taxonomy: coursework, project, internship, part-time, volunteer, certification, competition
- Maps academic and personal evidence to professional requirements
- Example: `"2 yrs web development"` → 3 shipped projects, 4-month team build → **Partial**, framed honestly

### F5 — Hidden Strengths & Rewrite Assistant
- Surfaces requirements silently satisfied by badly-phrased resume lines
- Rewrites bullets into JD language using **existing facts only**
- Hard constraint: never invents experience, never upgrades a class project into employment
- Validation pass flags any generated claim not traceable to a source line

### F6 — Cross-Border Adaptation & Realism Check
- Destination-country resume conventions (US/CA, UK/AU, DE, JP, SG, remote-first)
- Visa/sponsorship signal extracted from the JD
- Realism verdict: flags roles the candidate realistically cannot win
- Prioritized action list — what to fix first for the biggest coverage gain

### Feature dependency chain

```
F1 ingest → F2 normalize → F3 match → F4 evidence expansion
                              ↓
                    F5 rewrite ← F6 country rules
```

### Build priority

| Priority | Features | Note |
|---|---|---|
| Must | F1 (paste + URL), F2, F3 | No product without these |
| Must | F4 | No differentiation without it |
| Should | F5 | Demo value, moderate effort |
| Could | F6 | Trim to 3 countries if week 12 arrives hot |

If the schedule slips, **cut the scheduled scraper first** — paste and URL fetch cover the same demo.

---

## 5. Explicitly Out of Scope

Do not build these. They are commodity features, Teal-dominated, and will eat the semester:

- Application tracker / kanban pipeline
- Networking CRM / contact manager
- Cover letter generator
- Chrome extension
- Template gallery
- Employer-side portal
- Mobile app
- Auto-apply
- Interview prep

---

## 6. Architecture

```
JD input (scraped | pasted URL/text)
        ↓
   LLM normalizer  →  structured JSON schema
        ↓
Resume input (PDF/DOCX) → same normalizer → same schema + evidence
        ↓
   Match engine — requirement-level, semantic
        ↓
Output: per-requirement verdict + evidence citation + rewrite
```

**Key design decision:** both JD and resume normalize to one schema. Matching is schema-vs-schema, not text-vs-text. This is the architecture story for the defense — do not deviate from it.

---

## 7. Stack

| Layer | Choice |
|---|---|
| Frontend + app | Streamlit (fast, one language, matches existing proposal) |
| Database | Supabase (PostgreSQL) + pgvector |
| DB client | `supabase-py` |
| Backend logic | Python |
| Resume parsing | `pdfminer.six` / `python-docx` |
| JD ingestion | Public ATS APIs + free aggregator APIs + JSON-LD; `requests` + `BeautifulSoup` last resort. See `INGESTION_STRATEGY.md` |
| LLM | Anthropic API |
| Charts | Plotly |

### Stack decision to make in Phase 0

Streamlit ships faster and matches the existing proposal, but limits UI polish — and the rubric weights demo quality. If anyone on the team knows React, consider Next.js + Tailwind for the frontend with a Python FastAPI backend. **Decide once in Phase 0 and do not revisit.**

### Supabase caveats
- Free tier pauses after ~1 week of inactivity — ping it weekly or the demo dies the morning of.
- PostgreSQL syntax, not MySQL. `SERIAL`/`IDENTITY`, `TEXT[]`, `JSONB`, `ILIKE`.
- Enable the `vector` extension before creating embedding columns.

### Team split (3 people)
1. Ingestion — scraper, caching
2. Match engine — normalizer, matching, backend
3. Frontend, UX, evaluation

---

## 8. Core Schema

Lock this in Phase 1. Everything downstream depends on it.

```json
{
  "job": {
    "source_url": "string | null",
    "source_type": "scraped | pasted",
    "content_hash": "string",
    "title": "string",
    "company": "string | null",
    "location": "string | null",
    "country": "string | null",
    "industry": "string",
    "seniority": "intern | entry | junior | mid | senior",
    "years_exp_required": "number | null",
    "education_required": "string | null",
    "sponsors_visa": "yes | no | unstated",
    "salary_range": "string | null",
    "requirements": [
      {
        "id": "r1",
        "text": "verbatim requirement from the JD",
        "category": "hard_skill | soft_skill | education | certification | experience | language | other",
        "priority": "required | preferred",
        "normalized_skill": "canonical name, e.g. 'React'"
      }
    ]
  },

  "resume": {
    "candidate_summary": "string",
    "total_years_work": "number",
    "education": [
      { "degree": "string", "institution": "string", "year": "number", "gpa": "string | null" }
    ],
    "evidence": [
      {
        "id": "e1",
        "source_line": "verbatim line from the resume",
        "evidence_type": "employment | internship | part_time | coursework | project | volunteer | certification | competition",
        "skills": ["React", "REST APIs"],
        "duration_months": "number | null",
        "team_size": "number | null",
        "outcome": "string | null"
      }
    ]
  },

  "match": {
    "coverage_score": "number 0-100",
    "coverage_required_only": "number 0-100",
    "realism_verdict": "strong_fit | stretch | unrealistic",
    "results": [
      {
        "requirement_id": "r1",
        "verdict": "proven | partial | missing",
        "evidence_ids": ["e3", "e7"],
        "reasoning": "one sentence",
        "confidence": "number 0-1"
      }
    ],
    "hidden_strengths": [
      {
        "requirement_id": "r4",
        "evidence_id": "e2",
        "current_phrasing": "verbatim from resume",
        "suggested_phrasing": "rewritten, no new facts",
        "facts_used": ["e2"]
      }
    ],
    "priority_actions": ["ordered list of highest-impact fixes"]
  }
}
```

---

## 9. Non-Negotiable Rules

These must be enforced in code, not just prompts. The examiner will test them.

1. **No invented facts.** The rewrite step receives only the candidate's own evidence records. Every generated claim must cite an `evidence_id`. A validation pass rejects any output containing a claim with no traceable source.
2. **No scope inflation.** A 4-month class project may not be described as "years of professional experience." Reframe wording; never upgrade magnitude, duration, or employment status.
3. **Every verdict is traceable.** No verdict without either an `evidence_id` or an explicit "missing" reason.
4. **Cache by content hash.** Never re-normalize the same JD. LLM cost scales with users otherwise.
5. **Respect robots.txt.** Read it before scraping any board. Rate-limit. Store structured extracts plus a link back, not full JD text copies. Have a written legality answer before the proposal defense.
6. **Never scrape Facebook or LinkedIn.** Login walls, anti-bot, ToS violation. Out of scope for automated ingestion — a user can still paste the text manually via F1's paste path.

---

## 10. Phased Build Plan

### Phase 0 — Foundation (Week 1–2)
**Goal: decisions locked, data collected, nothing built yet.**

1. Confirm the stack decision (Streamlit vs Next.js). Write it down. Do not revisit.
2. Set up the repo: `/ingest`, `/normalize`, `/match`, `/app`, `/tests`, `/data`.
3. Create the Supabase project. Enable the `vector` extension.
4. Store the Anthropic API key in `.env`. Add `.env` to `.gitignore`.
5. **Hand-collect 30 real job posts** as board HTML or pasted text. This is the test set — everything depends on it.
6. Collect 5 real anonymized student resumes as PDFs.
7. Read `robots.txt` for CamHR and Bongthom. Record what is permitted.

**Done when:** repo scaffolded, Supabase reachable from Python, 30 JDs and 5 resumes sitting in `/data`.

---

### Phase 1 — Schema + Normalizer (Week 3–4)
**Goal: messy text in, clean JSON out. No UI, no scraping.**

1. Write the schema as Pydantic models in `/normalize/schema.py`.
2. Write the JD normalizer prompt. It must:
   - Extract each requirement verbatim, one record per requirement
   - Tag `required` vs `preferred` from JD wording ("must have" vs "nice to have")
   - Normalize skill names to canonical forms
   - Return JSON only, no prose, no markdown fences
3. Write the resume normalizer prompt with the same output discipline, producing `evidence` records with `evidence_type`.
4. Parse the LLM response defensively: strip fences, `json.loads`, validate against Pydantic, retry once on failure.
5. Run all 30 collected JDs through the normalizer. Manually check 10. Fix prompts until output is consistent.
6. Design the DB tables and write the migration: `jobs`, `requirements`, `resumes`, `evidence`, `matches`, `match_results`.

**Done when:** any pasted JD or resume PDF produces valid schema-conformant JSON, verified on the full test set.

---

### Phase 2 — Match Engine (Week 5–7)
**Goal: F3 + F4. The core of the project.**

1. Build the matcher: for each requirement, find candidate evidence records.
   - First pass: embedding similarity to shortlist evidence
   - Second pass: LLM judges `proven` / `partial` / `missing` with reasoning and confidence
2. Implement the non-work evidence rules (F4):
   - A `project` or `coursework` record can satisfy a skill requirement → `partial`, never `proven`, when the JD asks for professional experience
   - Aggregate duration across projects when the JD specifies years
   - Never let non-employment evidence produce a `proven` verdict on an experience requirement
3. Compute `coverage_score` and `coverage_required_only`, weighting `required` higher than `preferred`.
4. Implement `realism_verdict` thresholds.
5. Build a TF-IDF keyword-overlap baseline matcher in `/match/baseline.py`. This is the comparison for the evaluation chapter — cheap to build, high report value.

**Done when:** a resume + JD pair produces a full per-requirement verdict list with citations, and the baseline runs on the same input for comparison.

---

### Phase 3 — Ingestion (Week 8–9)
**Goal: F1. Everything beyond paste.**

Follow the tiered strategy in `INGESTION_STRATEGY.md`. Do **not** build a scraper first.

1. ATS API client — Greenhouse, Lever, Ashby. Public JSON, no auth. Curated company token list.
2. Aggregator client — Arbeitnow (free, no key, has visa-sponsorship flag).
3. URL path: fetch → try JSON-LD `JobPosting` first → fall back to main-content extraction → normalizer.
4. Local board module (CamHR/Bongthom) — sitemap/RSS/JSON-LD first, HTML extraction last. Not load-bearing.
5. Content-hash caching layer in front of every normalizer call.

**Done when:** all input paths reach the same normalizer, and the same JD submitted twice hits the cache.

---

### Phase 4 — Rewrite + Cross-Border (Week 10–11)
**Goal: F5 + F6.**

1. Hidden-strengths detector: scan `partial` and `missing` verdicts for evidence that satisfies the requirement but is poorly phrased.
2. Rewrite generator. Input: evidence records only. Output must cite `facts_used`.
3. **Validation pass** — a separate call that checks the rewrite introduces no claim absent from the source evidence. Reject and retry on failure. Log rejections; they become a report figure.
4. Country convention rules as a config file (JSON), not hardcoded. Start with 3 countries; add more only if time allows.
5. Visa/sponsorship extraction from JD text.
6. Priority action list — sort gaps by impact on `coverage_required_only`.

**Done when:** a rewrite is produced, the validator catches a deliberately hallucinated test case, and country rules change the output.

---

### Phase 5 — Frontend (Week 11–12)
**Goal: demoable in one screen.**

1. Upload resume → paste JD → results view.
2. Results view: coverage gauge, per-requirement list grouped by verdict, each expandable to show the cited resume line and reasoning.
3. Hidden strengths section with before/after phrasing.
4. Priority actions list.
5. Country selector affecting F6 output.
6. Loading states and error handling — a demo that hangs silently loses marks.

**Feature freeze at end of Week 12. No exceptions.**

---

### Phase 6 — Evaluation (Week 13)
**Goal: the number the examiner will ask for.**

1. Build 20 resume–JD pairs from the collected data.
2. Have 2–3 local recruiters or career-services staff independently rate each pair's fit.
3. Compare: your system's verdicts vs recruiter ratings vs the TF-IDF baseline.
4. Report agreement rate.
5. Report the hallucination-rejection count from the Phase 4 validator.

**Done when:** you have a table with three columns — human, your system, baseline.

---

### Phase 7 — Polish & Defense (Week 14–15)
1. README, architecture diagram, setup instructions.
2. Seed the database so the demo works without live scraping.
3. Rehearse the demo. Have offline fallback data — never depend on a live scrape or a live API during the presentation.
4. Prepare answers to the four questions you will definitely be asked (below).

---

## 11. Defense Preparation

**"Why not just use Teal?"**
> Teal counts keywords and assumes you already have a career. We check whether the candidate's actual evidence — including coursework and projects — satisfies each stated requirement, and we read the JDs Teal cannot reach.

**"How do you know the match score is correct?"**
> Recruiter agreement study, N=20 pairs, compared against a TF-IDF keyword baseline. Results in Chapter 5.

**"What stops the AI from making things up?"**
> The rewrite step receives only the candidate's own evidence records, every claim must cite an evidence ID, and a separate validation pass rejects untraceable claims. Rejection rate logged.

**"Is the scraping legal?"**
> robots.txt checked and obeyed, rate-limited, structured extracts with source attribution rather than full-text copies, no scraping of platforms that prohibit it. Facebook and LinkedIn are out of scope for automated ingestion; a user can still paste the text manually.

---

## 12. Risk Register

| Risk | Mitigation |
|---|---|
| LLM invents experience | Evidence-only input, citation requirement, validation pass, logged rejections |
| Weak differentiation at defense | Lead with non-work evidence mapping and local JD reach, never "Teal is USA-only" |
| Scraper breaks on layout change | Cache aggressively; paste path always works as fallback |
| Supabase free tier pauses | Weekly ping; seeded local backup before the demo |
| LLM cost | Content-hash cache, never re-normalize |
| Scope creep | Section 5 is binding; feature freeze Week 12 |

---

## 13. First Command to Run

Start Phase 0, step 5. Collect the 30 job posts and 5 resumes before writing a single line of pipeline code. Every prompt, threshold, and evaluation in this document depends on that data existing first.
