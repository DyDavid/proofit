# Task 5 report — Priority Actions verification, sample fixture, dead endpoint, CP3 blockers

**Branch:** `phase-4-hardening-f5-f6` · **Date:** 2026-09-16

This task had four items: the two in the written brief (verify the Priority Actions rail;
record CP3's blockers) plus two surfaced by earlier tasks in this plan (populate the sample
fixture's hidden strengths; resolve the unused `/api/countries` endpoint).

---

## Item 1 — Priority Actions rail: verified, no gap found

Read `web/components/results/ResultsInteractive.tsx:242–256` (the `openRequirement`/`toggle`
helpers) and `:337–373` (the rail itself). Checked all three things the brief asked for
against the actual code, not against memory of Phase 2:

1. **The anchor genuinely opens the target row and scrolls to it.**
   `openRequirement(id)` (line 242) adds `id` to the `openIds` React state set, then calls
   `document.getElementById(\`req-${id}\`)?.scrollIntoView({ behavior: "smooth", block: "center" })`.
   Each `RequirementRow`'s `<details id={`req-${result.requirement_id}`} open={isOpen} ...>`
   (line 72–74) has its `open` prop driven by that same `openIds` set via
   `isOpen={openIds.has(result.requirement_id)}` (line 327) — so the state update genuinely
   re-renders the target `<details>` open, and the scroll call runs against that same DOM id.
   Not a fake anchor.

2. **`coverage_gain` renders as "+8% required coverage".** Line 362–366:
   `{typeof action.coverage_gain === "number" ? <span>{t("actions.gain", { pct: action.coverage_gain })}</span> : null}`.
   `web/messages/en.json:166` and `km.json:166`: `"gain": "+{pct}% required coverage"`. Matches
   the plan's wording exactly.

3. **A null `requirement_id` degrades to plain text.** Line 351–361:
   `action.requirement_id ? <button onClick={() => openRequirement(action.requirement_id!)}>{action.text}</button> : action.text`.
   No button renders when `requirement_id` is null — just the text — so there is no dead/inert
   control.

All three hold. **No code was changed for this item**, per the brief's instruction not to
rewrite working code to look different.

---

## Item 2 — Sample fixture's hidden strengths: gap closed

`web/lib/fixtures/sample-match.ts` had no `hidden_strengths` entries, so `HiddenStrengths.tsx`
rendered its empty state (`t("empty")`) on the no-`?id=` sample path — the first thing a
landing-page visitor and any report screenshot would see for Proofit's most distinctive
feature.

Added two entries to `sampleMatch.hidden_strengths`:

1. `requirement_id: "r5"` ("Experience supporting production systems", verdict `partial`),
   `evidence_id: "e14"`. `current_phrasing` copied verbatim from `e14.source_line`.
   `suggested_phrasing` restates it in flowing prose without adding any fact e14 doesn't
   already carry.
2. `requirement_id: "r4"` ("2+ years of experience building REST APIs", verdict `partial`),
   `evidence_id: "e22"`, `facts_used: ["e21", "e22"]` (both requirement's own `evidence_ids`).
   `current_phrasing` verbatim from `e22.source_line`; `suggested_phrasing` adds nothing
   beyond what e21/e22 together state (deliberately does **not** add "years of experience" —
   that phrase is on `engine/rewrite/forbidden.json`'s wordlist and is also exactly the fact
   this requirement is missing).

**Did not touch** `coverage_score` (55.6) or `coverage_required_only` (50.0), per the brief.

### Verified against the real validator, not just by eye

Wrote a throwaway script (`/private/tmp/.../scratchpad/check_hidden_strengths.py`, not
committed) that constructs the real `engine.normalize.schema.Evidence` /
`engine.normalize.schema.HiddenStrength` / `engine.rewrite.models.Rewrite` objects for both
entries and runs the actual `engine.rewrite.validate.precheck_scope_inflation` and
`precheck_rewrite` against them. Output for both entries:

```
HiddenStrength model: OK                     (evidence_id ∈ facts_used, schema-enforced)
precheck_scope_inflation: PASS (None)
precheck_rewrite: PASS (None)
current_phrasing verbatim match: True
changed_word checks: all present_in_suggested=True, absent_from_current=True
```

Both `Evidence.type` for e21/e22 is `project`, which *is* on
`forbidden.json`'s `applies_to_evidence_types` list, so the scope-inflation gate ran its real
substantive check (not a trivial no-op) and still passed — the suggested phrasings contain
none of `professional` / `employed` / `worked at` / `years of experience` / `engineer at`.

---

## Item 3 — Unused `/api/countries` endpoint: wired up (option a)

**Chose (a): wire `CountryFormat.tsx` to `GET /api/countries`**, not (b) removal.

**Why (a) over (b):** The defect was a genuine duplicated source of truth, not a
speculative one. `CountryFormat.tsx`'s old `DESTINATION_KEYS = ["KH", "SG", "JP", "AU",
"REMOTE", "other"]` was byte-for-byte the same five real codes `engine/country/rules.json`
defines (verified via `tests/test_countries_route.py`'s own `EXPECTED_COUNTRY_CODES` import
and a direct read of `rules.json`) plus the one sentinel ("other") that legitimately can't
come from the API. If Person A ever adds a sixth market to `rules.json`, the old hardcoded
array would silently drift out of sync with no test catching it (the Python test only checks
the API response, not this TS file). Wiring the fetch removes that drift risk entirely, and
the added complexity was bounded to one component:

- `web/lib/api.ts` gained `CountryListEntry` + `getCountries()` (mirrors the existing
  `getCountryRules()` pattern exactly).
- `CountryFormat.tsx`: `countries` state (`CountryListEntry[] | null`, null = loading) is
  fetched once on mount. Once it resolves, `destination` is picked (job's own destination if
  it's a market this app has rules for, else `"KH"` — same default as before) and the
  existing per-destination rules-fetch effect proceeds unchanged. The `<select>` renders a
  disabled placeholder (`tc("loading")`) for the brief window before the country list
  arrives, then its options from `countries.map(c => c.code)` plus the `OTHER_KEY` sentinel.
  Labels still come from `results.country.destinations.*` (i18n), not the API's English-only
  `display_name` — locale switching is unaffected.
- A failed `getCountries()` call degrades to `setCountries([])` (select shows only "Other"),
  matching this file's own existing "must degrade, not error" convention for the per-country
  rules fetch, rather than throwing.

I considered (b) — dropping `GET /api/countries` and keeping only `/api/countries/{destination}` —
but rejected it: the list route is real, tested (`tests/test_countries_route.py::
test_list_countries_returns_all_five`), and cheap to serve (`rules_for` is already loaded);
removing it would not remove the actual duplication (`CountryFormat.tsx` would still need
*some* list), it would just delete a working, tested piece of surface area for no gain. I did
not touch `AnalyzeForm.tsx`'s separate, differently-spelled `COUNTRY_KEYS` array (a browser
submission list, not a rules-display list, and outside this item's named scope) — that is a
second, smaller instance of the same pattern but the brief named only `CountryFormat.tsx`.

No test files reference `CountryFormat.tsx`, `DESTINATION_KEYS`, or `isDestinationKey`
(no frontend test suite exists in this repo), so there was nothing to update there.

---

## Item 4 — CP3's blockers recorded honestly

Verified both claims directly before writing anything, rather than trusting the brief's own
wording:

- `engine/match/__init__.py:27` (`run_match`) and `:89` (`run_baseline`) both still end in an
  unconditional `raise NotImplementedError(...)`. Read the full file; confirmed no gating
  logic makes this conditional.
- `grep -rniE 'vercel\.app|onrender\.com|...'` across every tracked file (excluding
  `node_modules`/`.git`) turns up only template/placeholder occurrences — `deploy/runbook.md`
  and `.env.example`'s fill-in-this-value tables, `PERSON_B_PLAN_v2.md`'s instructions to
  create such a URL — never a URL that reads as an actually-deployed instance.

Appended a new dated section to `docs/progress-log.md`:

- **§7 "Phase 4 — Hardening F5, Building F6"**: a status table for all seven of
  `PERSON_B_PLAN_v2.md`'s Phase 4 tasks (1–6 done, including task 4 exceeding the plan — 5
  countries shipped against the planned 3 — and task 6 reported as "verified, already done"
  per Item 1 above), plus task 7 (CP3) marked Blocked with a pointer to the detail below.
- **"CP3 is blocked — 16 Sep 2026"**: the two verified blockers above, cited to exact file and
  line, plus what unblocks each (CP2 landing unblocks the real-pairs half independently of
  hosting; hosting going live unblocks the live-URL half independently of the engine; both are
  needed together before CP3's literal wording is true).
- Updated the document's header/title: dropped the now-stale "Phases 0–2" range from the H1,
  added an "Updated: 16 Sep 2026" date, and added one explicit sentence noting that Phase 3
  is *not* retrospectively logged in this document yet (it happened, per `git log`, but
  writing it up was not part of this task's scope) — so the jump from §2 (Phase 2) to §7
  (Phase 4) doesn't read as Phase 3 having been skipped in reality.

---

## Verification

```
.venv/bin/python -m pytest -q
  → 205 passed, 2 warnings in 12.75s      (unchanged from the 205 baseline; no Python files touched)

cd web && npx tsc --noEmit
  → clean, no output

cd web && npx eslint components/results lib/api.ts lib/fixtures
  → clean, no output

node scripts/i18n-check.mjs
  → 167 keys checked, 0 error(s), 167 warning(s)   (warnings are the pre-existing,
    tracked km.json-mirrors-en.json state — docs/errors.md §4 — not introduced here)

cd web && npx eslint .   (extra full-project sanity check, not in the required gate list)
  → 0 errors, 1 pre-existing warning in generated web/lib/types.ts (unrelated to this task)
```

No Python files were touched (`git status --porcelain` confirms only three TS files
modified under `web/`), so no `ruff check` was run, per the brief.

## Files changed

- `web/components/results/CountryFormat.tsx` — Item 3
- `web/lib/api.ts` — Item 3 (`getCountries`, `CountryListEntry`)
- `web/lib/fixtures/sample-match.ts` — Item 2 (`hidden_strengths` entries)
- `docs/progress-log.md` — Item 4
- `.plan-briefs/task-5-report.md` — this file

`web/components/results/ResultsInteractive.tsx` was read but **not modified** (Item 1: no gap
found).
