# Phase 4 — Hardening F5, Building F6 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish every Phase 4 task that is not blocked on Person A — the validator's adversarial suite and its deterministic scope-inflation gate, the Hidden Strengths UI, the F6 country selector effects, and the Priority Actions rail — so that Phase 4's "done when" holds: *an examiner-style hallucinated rewrite is rejected and the rejection counter increments; switching country changes the checklist and the visa line.*

**Architecture:** Additive throughout. The F5 engine (`engine/rewrite/`), the rewrites endpoint (`POST /api/analyses/{id}/rewrites`), and the F6 config (`engine/country/rules.json`) all already exist and are tested. This plan adds one new deterministic validator layer, a labelled adversarial dataset shared by the test suite and the report's metrics script, two new frontend sections, and one new read-only API route. Nothing here touches `engine/match/` or `engine/normalize/` — both are Person A's and both still raise `NotImplementedError`.

**Tech Stack:** FastAPI + Pydantic v2 (`api/`, `engine/`), Next.js 15 + next-intl + Tailwind (`web/`), pytest.

**Spec:** `PERSON_B_PLAN_v2.md` §5 Phase 4 (tasks 1–6; task 7 is blocked, see below), `PROJECT_SPEC.md` §9 (non-negotiable rules), `BRAND.md` §6 (voice rules), `docs/errors.md` (error contract).

## Global Constraints

- **PROJECT_SPEC.md §9 rule 1 — no invented facts.** The rewrite path receives evidence records only. Nothing added here may pass the JD, the raw resume, or a country's tone notes into a position where the model could mistake them for facts about the candidate.
- **PROJECT_SPEC.md §9 rule 2 — no scope inflation.** A `coursework` / `project` / `competition` / `volunteer` record may never be restated as employment. Task 1 makes this deterministic rather than prompt-dependent.
- **BRAND.md §6** binds every user-facing string added here: no ATS framing in any form, never imply invented experience, never promise an outcome, name the gap plainly, second person.
- **The LLM is never called from the test suite.** `engine/rewrite/llm.py`'s `_get_client()` is lazy precisely so the suite runs with no `ANTHROPIC_API_KEY`. Every test added here mocks it, exactly as `tests/test_rewrite_validator.py` already does.
- **Existing gates, unchanged:** `pytest` (currently 138 passing), `ruff check` on changed files, `tsc --noEmit`, `node scripts/i18n-check.mjs` → 0 errors. CI runs `ruff check .` and `pytest` only — it does **not** run `ruff format` or `mypy`, and 14 pre-existing files would fail `ruff format`, so do not reformat.
- **Known pre-existing failure, not this plan's to fix:** `ruff check .` reports one UP017 error in `engine/normalize/schema.py:92` (`datetime.timezone.utc` → `datetime.UTC`). That file is Person A's, marked for wholesale replacement at CP1. Leave it. Verify your own changed files with a scoped `ruff check <paths>`.
- **km.json mirrors en.json in English.** That is this project's accepted state, with a Khmer QA session scheduled for Phase 5 (`docs/errors.md` §4). Add both keys; do not invent Khmer.
- **Out of scope — Phase 4 task 7 (CP3).** It requires "the 3 fixture pairs **plus 5 real pairs** end-to-end on the live URL". Real pairs need `engine.match.run_match`, which still raises `NotImplementedError`; the live URL does not exist (no Vercel/Render deployment was ever stood up — see `docs/progress-log.md` §5). Both blockers are outside Person B's control. Task 5 of this plan records the blockers rather than faking the checkpoint.

---

## File Structure

**Engine / backend — new:**
- `engine/rewrite/forbidden.json` — the scope-inflation wordlist, with per-phrase reasons.
- `tests/rewrite_cases.py` — the labelled adversarial dataset, imported by both the test suite and the metrics script so the report's table measures exactly what CI asserts.
- `scripts/validator_metrics.py` — prints the precision/recall table for Chapter 5.
- `api/routes/countries.py` — read-only F6 rules endpoint.

**Engine / backend — modified:**
- `engine/rewrite/validate.py` — add `precheck_scope_inflation`, run it first in `validate_rewrite`.
- `engine/rewrite/prompts.py` — `build_generate_user_prompt` gains optional country tone notes.
- `api/routes/analyses.py` — pass the analysis's country tone notes into generation.
- `api/main.py` — register the countries router.
- `tests/test_rewrite_validator.py` — grow to 30 labelled cases driven by the shared dataset.

**Frontend — new:**
- `web/components/results/HiddenStrengths.tsx` — the F5 section.
- `web/components/results/CountryFormat.tsx` — the F6 checklist + visa line.

**Frontend — modified:**
- `web/lib/api.ts` — `createRewrites`, `getCountryRules`.
- `web/components/results/ResultsView.tsx` — mount both new sections.
- `web/messages/en.json`, `web/messages/km.json` — new keys.

---

### Task 1: Deterministic scope-inflation gate

Built **before** the adversarial suite: it adds a third rejection layer, and Task 2's cases must be written against the finished behaviour rather than retro-fitted.

**Files:**
- Create: `engine/rewrite/forbidden.json`
- Modify: `engine/rewrite/validate.py`
- Test: `tests/test_rewrite_scope_gate.py`

**Interfaces:**
- Produces: `precheck_scope_inflation(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult | None` — `None` when the rewrite passes, a populated failure otherwise. `validate_rewrite` calls it **first**, before `precheck_rewrite` and therefore long before any LLM call.
- Produces: `load_forbidden() -> ForbiddenConfig` (cached), and `ForbiddenConfig` / `ForbiddenPhrase` Pydantic models.

**The rule, stated precisely.** The gate fires only when **every** evidence record the rewrite cites in `facts_used` has an `evidence_type` in the forbidden set (`coursework`, `project`, `competition`, `volunteer`). If even one cited record is `employment`, `internship`, or `part_time`, professional language may be legitimately supported by that record and the gate must not fire — that decision belongs to the LLM layer, which can weigh it. Matching is case-insensitive on a leading word boundary, so "professionally" matches "professional" but "professor" does not.

- [ ] **Step 1: Write the failing tests** — `tests/test_rewrite_scope_gate.py` covering: fires on a project-only rewrite containing "professional"; fires for each phrase in the wordlist; does **not** fire when a cited record is `employment`; does **not** fire on a substring ("professor"); does not fire when the rewrite is clean; returns `None` (not a passing `ValidationResult`) on success; and — critically — that `validate_rewrite` never reaches the LLM when the gate fires (assert a patched `_call_llm_validator` was not called).

- [ ] **Step 2: Run to confirm RED** — `.venv/bin/python -m pytest tests/test_rewrite_scope_gate.py -q`. Expect `ImportError` on `precheck_scope_inflation`.

- [ ] **Step 3: Write `engine/rewrite/forbidden.json`**

```json
{
  "version": "1.0.0",
  "applies_to_evidence_types": ["coursework", "project", "competition", "volunteer"],
  "forbidden_phrases": [
    {
      "phrase": "professional",
      "reason_en": "Describes unpaid coursework or a personal project as professional work.",
      "reason_km": "Describes unpaid coursework or a personal project as professional work."
    },
    {
      "phrase": "employed",
      "reason_en": "Claims an employment relationship the cited evidence does not record.",
      "reason_km": "Claims an employment relationship the cited evidence does not record."
    },
    {
      "phrase": "worked at",
      "reason_en": "Names an employer for evidence that is not employment.",
      "reason_km": "Names an employer for evidence that is not employment."
    },
    {
      "phrase": "years of experience",
      "reason_en": "Converts project or coursework duration into professional experience.",
      "reason_km": "Converts project or coursework duration into professional experience."
    },
    {
      "phrase": "engineer at",
      "reason_en": "Assigns a job title at an organisation on non-employment evidence.",
      "reason_km": "Assigns a job title at an organisation on non-employment evidence."
    }
  ]
}
```

`reason_km` deliberately mirrors `reason_en` in English for now: this repo's `km.json` does the same, and `docs/errors.md` §4 schedules one Khmer QA pass for Phase 5 rather than accumulating unreviewed machine translation. The key exists so that pass has somewhere to land.

- [ ] **Step 4: Implement the gate in `engine/rewrite/validate.py`**

Add near the top (after existing imports):

```python
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

FORBIDDEN_PATH = Path(__file__).resolve().parent / "forbidden.json"


class _ForbiddenBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class ForbiddenPhrase(_ForbiddenBase):
    phrase: str = Field(..., min_length=1)
    reason_en: str = Field(..., min_length=1)
    reason_km: str = Field(..., min_length=1)


class ForbiddenConfig(_ForbiddenBase):
    version: str = Field(..., min_length=1)
    applies_to_evidence_types: list[str] = Field(..., min_length=1)
    forbidden_phrases: list[ForbiddenPhrase] = Field(..., min_length=1)


@lru_cache(maxsize=1)
def load_forbidden() -> ForbiddenConfig:
    return ForbiddenConfig.model_validate(json.loads(FORBIDDEN_PATH.read_text(encoding="utf-8")))
```

Then the gate itself:

```python
def precheck_scope_inflation(
    rewrite: Rewrite, evidence_records: list[Evidence]
) -> ValidationResult | None:
    """PROJECT_SPEC.md §9 rule 2, as code rather than as a prompt instruction.

    Fires only when *every* cited evidence record is non-employment. One cited
    `employment` / `internship` / `part_time` record can legitimately support
    professional language, and deciding that is the LLM layer's job, not this
    one's — a deterministic gate should only reject what is unambiguous.
    """
    config = load_forbidden()
    cited = [e for e in evidence_records if e.id in rewrite.facts_used]
    if not cited:
        return None
    if not all(e.evidence_type in config.applies_to_evidence_types for e in cited):
        return None

    haystack = rewrite.suggested_phrasing.lower()
    violations = [
        Violation(claim=entry.phrase, reason=entry.reason_en)
        for entry in config.forbidden_phrases
        if re.search(rf"\b{re.escape(entry.phrase.lower())}", haystack)
    ]
    if not violations:
        return None
    return ValidationResult(ok=False, violations=violations)
```

Note the deliberately one-sided `\b` — leading boundary only, so "professionally" is caught while "professor" is not.

Finally, run it first in `validate_rewrite`:

```python
def validate_rewrite(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult:
    scope_failure = precheck_scope_inflation(rewrite, evidence_records)
    if scope_failure is not None:
        return scope_failure
    precheck_failure = precheck_rewrite(rewrite, evidence_records)
    if precheck_failure is not None:
        return precheck_failure
    return _call_llm_validator(rewrite, evidence_records)
```

Update `__all__` to include `precheck_scope_inflation` and `load_forbidden`, and extend the module docstring to describe three layers rather than two.

- [ ] **Step 5: Run to confirm GREEN** — the new file, then the full suite.

- [ ] **Step 6: Commit** — `feat(engine): add the deterministic scope-inflation gate ahead of the LLM validator`

---

### Task 2: 30-case adversarial suite + precision/recall table

**Files:**
- Create: `tests/rewrite_cases.py`
- Create: `scripts/validator_metrics.py`
- Modify: `tests/test_rewrite_validator.py`

**Interfaces:**
- Produces: `CASES: list[ValidatorCase]` in `tests/rewrite_cases.py`, where `ValidatorCase` is a frozen dataclass of `id: str`, `category: str`, `suggested_phrasing: str`, `evidence_overrides: dict`, `should_reject: bool`, `caught_by: Literal["scope", "precheck", "llm", "none"]`.
- Consumed by: `tests/test_rewrite_validator.py` (asserts each case's expected outcome) and `scripts/validator_metrics.py` (prints the table).

**Composition — 30 cases.** 20 adversarial across the plan's six categories, 10 legitimate:

| Category | Adversarial | Expected layer |
|---|---|---|
| magnitude inflation (3 → 30) | 4 | `precheck` |
| duration inflation (4 months → 2 years) | 3 | `precheck` |
| status upgrade (project → job) | 4 | `scope` |
| tool insertion | 3 | `precheck` |
| outcome invention | 3 | `llm` |
| subtle paraphrase ("participated" → "led") | 3 | `llm` |
| **legitimate — must pass** | 10 | `none` |

Ten legitimate cases is not padding: precision is meaningless without negatives, and the gate added in Task 1 is exactly the kind of blunt instrument that generates false positives. At least three legitimate cases must cite an `employment` record while using professional language, proving the gate's all-cited-are-non-employment condition actually holds.

- [ ] **Step 1: Write `tests/rewrite_cases.py`** — the frozen dataclass and the 30 labelled cases, each with a one-line comment naming what it tests. Reuse the existing test module's `_evidence()` shape (a 3-month, 2-person Python course project) so overrides stay small.

- [ ] **Step 2: Rewrite `tests/test_rewrite_validator.py` to drive off the dataset** — keep the existing module docstring (it is the report's validator-design paragraph) and extend it to describe three layers. Replace the eight hand-written tests with:
  - `@pytest.mark.parametrize` over `CASES`, asserting `validate_rewrite(...).ok is not case.should_reject`, with the LLM layer patched to return a rejection for `caught_by == "llm"` cases and a pass otherwise.
  - A separate test asserting that for every `caught_by in {"scope", "precheck"}` case, a patched `_call_llm_validator` was **never called** — the "costs nothing" claim, verified rather than asserted in prose.
  - A test asserting the dataset itself is well-formed: 30 cases, all six categories present, at least 10 legitimate.

- [ ] **Step 3: Write `scripts/validator_metrics.py`** — imports `CASES`, runs the two deterministic layers only (no network, no key required), and prints a Markdown table: TP / FP / FN / TN, precision, recall, F1, plus a count of cases that require the semantic layer. It must state in its own output that only the deterministic layers are being measured — a table that silently folded in a mocked LLM's verdicts would misreport the system. Accept `--live` to additionally run the real LLM layer, guarded on `ANTHROPIC_API_KEY` being present. Import path: the script must add the repo root to `sys.path` before `from tests.rewrite_cases import CASES` (namespace package; the script's own directory is `sys.path[0]` when run directly).

- [ ] **Step 4: Verify** — full suite green; `.venv/bin/python scripts/validator_metrics.py` prints the table and exits 0.

- [ ] **Step 5: Commit** — `test(engine): grow the validator suite to 30 labelled cases with a metrics table`

---

### Task 3: Hidden Strengths UI

**Files:**
- Create: `web/components/results/HiddenStrengths.tsx`
- Modify: `web/lib/api.ts`, `web/components/results/ResultsView.tsx`, `web/messages/en.json`, `web/messages/km.json`

**Interfaces:**
- Consumes: `POST /api/analyses/{id}/rewrites` → `{hidden_strengths: HiddenStrength[], rejected_count: number}` (already built; shape confirmed at `api/routes/analyses.py:283-286`).
- Produces: `createRewrites(id: string): Promise<{hidden_strengths: HiddenStrength[]; rejected_count: number}>` in `web/lib/api.ts`; `<HiddenStrengths match={match} analysisId={id} />`.

**Behaviour.** The section sits below the requirement list. It is **opt-in**: rewrites cost LLM calls, so nothing fires until the user presses a button. States: idle (button) → loading → results, or an error card reusing the existing `errors.*` catalogue. Each accepted suggestion renders `current_phrasing` on the left and `suggested_phrasing` on the right with every word in `changed_words` highlighted; `facts_used` renders as chips that expand to the cited `Evidence.source_line`. Copy writes `suggested_phrasing` to the clipboard (same `try/catch` graceful-failure shape as `ProgressStepper.tsx`); Reject hides that suggestion locally — there is no reject endpoint and this plan does not add one. The counter reads "{passed} suggestions passed validation · {rejected} rejected", driven by `hidden_strengths.length` and `rejected_count`.

- [ ] **Step 1: Add `createRewrites` to `web/lib/api.ts`**, following the exact shape of the existing `retryAnalysis` (POST, `toApiError` on non-ok, typed return). Import `HiddenStrength` from `@/lib/types`.

- [ ] **Step 2: Add i18n keys** under `results.hiddenStrengths` in **both** locale files: `title`, `intro`, `run`, `running`, `empty`, `counter` (`"{passed} suggestions passed validation · {rejected} rejected"`), `current`, `suggested`, `factsUsed`, `rejected`. Reuse `common.action.copy` / `common.action.reject`; do not add duplicates. Copy must obey BRAND.md §6 — `intro` must say the suggestions are built only from lines already in the resume.

- [ ] **Step 3: Build `HiddenStrengths.tsx`** — a `"use client"` component. Word-level highlight: split `suggested_phrasing` on whitespace and mark any token whose stripped, lowercased form is in a `Set` built from `changed_words`; render matches in `<mark className="proofit-mark">` (the class already exists, used by `ResultsInteractive.tsx`). Evidence chips resolve `facts_used` ids against `match.resume?.evidence`.

- [ ] **Step 4: Mount it** in `ResultsView.tsx` below `<ResultsInteractive />`, passing the analysis id. The sample path (`/results` with no `?id=`) has no analysis to POST against — render the section's static content from `match.hidden_strengths` (the fixtures already populate it) and hide the run button when no id is present.

- [ ] **Step 5: Verify** — `cd web && npx tsc --noEmit && npx eslint components/results`; `node scripts/i18n-check.mjs` → 0 errors.

- [ ] **Step 6: Commit** — `feat(web): add the Hidden Strengths section with validation counter`

---

### Task 4: F6 country rules endpoint + selector effects

**Files:**
- Create: `api/routes/countries.py`, `web/components/results/CountryFormat.tsx`
- Modify: `api/main.py`, `engine/rewrite/prompts.py`, `api/routes/analyses.py`, `web/lib/api.ts`, `web/components/results/ResultsView.tsx`, both locale files
- Test: `tests/test_countries_route.py`

**Interfaces:**
- Produces: `GET /api/countries` → `{countries: [{code, display_name}]}`; `GET /api/countries/{destination}` → the full `CountryRules` object, or a 404 `ApiError` with code `COUNTRY_RULES_NOT_FOUND` when `rules_for` returns `None`.
- Produces: `getCountryRules(destination: string)` in `web/lib/api.ts`; `<CountryFormat />`.
- Modifies: `build_generate_user_prompt(requirement_text, evidence_lines, tone_notes: list[str] | None = None)` — backward compatible default.

**The three effects, per the plan's task 5.**

*(a) Format checklist.* `CountryFormat.tsx` renders, from the fetched rules: page length, the photo line (`include_photo` + `photo_note`), include/omit personal-detail lists, date format with its example, section order, and tone notes. A destination `<select>` at the top of the section lets the user switch country without re-running the analysis; it defaults to the analysis's own country and re-fetches on change.

*(b) Visa line.* Rendered from `match.job.sponsors_visa` and `match.job.sponsors_visa_source_line`. Two rules from `engine/country/__init__.py`, both load-bearing: `unstated` is the honest default and must not be shown as a "no"; and a verdict is **never** displayed without the verbatim JD sentence that produced it. When `sponsors_visa_source_line` is null, show the unstated copy and no verdict badge. Also surface the country's `visa_terms` as "what to look for in the post" — the vocabulary side of F6, and the only place it currently reaches a user.

*(c) Country-toned rewrites.* `build_generate_user_prompt` gains an optional tone-notes block. `create_rewrites` resolves the analysis's country via `rules_for(record.country)` and passes `rules.tone_notes` through. **The evidence-only rule is unchanged and must be visibly preserved:** tone notes are style guidance about *how to phrase*, never facts about the candidate, and the prompt must label them as such. Add a test asserting that a tone note containing a fabricated fact does not appear in the generated `facts_used`, and that generation still works when `rules_for` returns `None`.

- [ ] **Step 1: Write `tests/test_countries_route.py`** (RED) — list returns all five; a known destination returns full rules; `"other"` 404s with `COUNTRY_RULES_NOT_FOUND` in the envelope; `"usRemote"` resolves end-to-end through the route.

- [ ] **Step 2: Build `api/routes/countries.py`** using `ApiError` for the 404 (never a bare `HTTPException` — `docs/errors.md` §1), register it in `api/main.py` alongside the existing routers.

- [ ] **Step 3: Extend `build_generate_user_prompt`** with the optional tone-notes block, clearly labelled as phrasing guidance and explicitly not a source of facts. Wire it through `create_rewrites`. Add the two tests named above.

- [ ] **Step 4: Add `getCountryRules` to `web/lib/api.ts`** and the `results.country.*` i18n keys to both locale files.

- [ ] **Step 5: Build `CountryFormat.tsx`** and mount it in `ResultsView.tsx`.

- [ ] **Step 6: Verify** — full pytest suite; `tsc --noEmit`; scoped `ruff check`; `i18n-check` → 0 errors.

- [ ] **Step 7: Commit** — `feat(api,web): expose F6 country rules and wire the destination selector`

---

### Task 5: Priority Actions rail — verify, and record CP3's blockers

Most of this landed in Phase 2. This task confirms what exists against the plan's wording and closes only genuine gaps.

**Files:** Modify `web/components/results/ResultsInteractive.tsx` (only if a gap is found); modify `docs/progress-log.md`

- [ ] **Step 1: Verify against the spec.** `PERSON_B_PLAN_v2.md` Phase 4 task 6 asks for two things: each action links to the requirement row it addresses, and `coverage_gain` renders as "+8% required coverage". Read `ResultsInteractive.tsx:337-370` and confirm both. Confirm the anchor actually opens the target row's `<details>` and scrolls to it (the `openRequirement` helper), and that an action with a null `requirement_id` degrades to plain text rather than a dead button.

- [ ] **Step 2: Close any gap found, or record that there is none.** Do not rewrite working code to look different. If both requirements already hold, say so in the report file and make no code commit for this task.

- [ ] **Step 3: Record CP3's blockers.** Append a short, dated section to `docs/progress-log.md` stating precisely why Phase 4 task 7 could not be executed: `engine.match.run_match` and `run_baseline` still raise `NotImplementedError` (CP2 never happened), and no live deployment exists, so "5 real pairs end-to-end on the live URL" has neither an engine nor a URL. List what becomes unblocked the moment each arrives.

- [ ] **Step 4: Commit** — `docs: record Phase 4 completion state and CP3's blockers`

---

## Self-Review

**Spec coverage** — `PERSON_B_PLAN_v2.md` §5 Phase 4:
- Task 1 (adversarial suite + precision/recall) → plan Task 2.
- Task 2 (scope-inflation rule as code, `forbidden.json`) → plan Task 1.
- Task 3 (Hidden strengths UI) → plan Task 3.
- Task 4 (F6 `rules.json` + loader + model + test) → **already complete**, shipped earlier on this branch with 79 tests.
- Task 5 (country selector effects a/b/c) → plan Task 4.
- Task 6 (priority actions UI) → plan Task 5 steps 1–2.
- Task 7 (CP3) → blocked; plan Task 5 step 3 records why rather than faking it.

**Ordering note:** the plan's tasks 1 and 2 are executed in reverse (gate before suite), because the suite's status-upgrade cases assert against the gate's behaviour and would otherwise be written twice.

**Type/name consistency:** `precheck_scope_inflation` (Task 1) is asserted by name in Task 2's layer test. `createRewrites`' return shape (Task 3) matches `api/routes/analyses.py:283-286` exactly. `rules_for` (Task 4) is the function shipped in `engine/country/rules.py`, already tested. `ValidatorCase.caught_by` values (`scope` / `precheck` / `llm` / `none`) map one-to-one onto the three layers in `validate_rewrite`.

## Execution Handoff

Plan complete. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, reviewed between tasks.

**2. Inline Execution** — executed in this session with checkpoints.
