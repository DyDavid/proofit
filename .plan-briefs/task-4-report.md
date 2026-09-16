# Task 4 report — F6 country rules endpoint + selector effects

Branch: `phase-4-hardening-f5-f6`. Scope: `api/routes/countries.py` (new),
`api/main.py`, `engine/rewrite/prompts.py`, `engine/rewrite/generate.py`,
`api/routes/analyses.py`, `web/lib/api.ts`, `web/components/results/CountryFormat.tsx`
(new), `web/components/results/ResultsView.tsx`, `web/messages/{en,km}.json`,
`docs/errors.md`, plus tests.

## What was built

### (a) Format checklist

`GET /api/countries` — `{countries: [{code, display_name}]}`, all five markets
in `rules.json`'s own order. `GET /api/countries/{destination}` — the full
`CountryRules` object, resolved through `rules_for` (so the browser's
`"usRemote"`, the schema's `"REMOTE"`, and a long form like `"Cambodia"` all
work), or a 404 `ApiError` with code `COUNTRY_RULES_NOT_FOUND` when
`rules_for` returns `None`. Both routes live in the new `api/routes/countries.py`,
registered in `api/main.py`.

`web/components/results/CountryFormat.tsx` renders this: a destination
`<select>` (values `KH | SG | JP | AU | REMOTE | other` — the canonical codes
`rules_for` and `match.job.country` already use, so the selector's default can
read straight off `match.job.country` with no translation step) that
re-fetches `getCountryRules(destination)` on change and never touches the
analysis. Below it: page length, the photo line (`include_photo` badge +
`photo_note`), include/omit personal-detail lists, date format + example,
section order, and tone notes — all rendered verbatim from the fetched
`CountryRules`, same "engine content is English regardless of locale"
convention as `Requirement.text` / `Evidence.source_line`.

### (b) Visa line

`VisaLine` (inside `CountryFormat.tsx`) reads `match.job.sponsors_visa` and
`match.job.sponsors_visa_source_line` — independent of whichever destination
the selector currently shows, since the visa signal is about the actual job
post, not a hypothetical market. Two rules, enforced by one small piece of
logic:

```ts
const sourceLine = job?.sponsors_visa_source_line ?? null;
const verdict =
  sourceLine && (job?.sponsors_visa === "yes" || job?.sponsors_visa === "no")
    ? job.sponsors_visa
    : null;
```

`verdict` is `null` whenever `sponsors_visa` is `"unstated"`, absent, *or*
whenever `sourceLine` is falsy — so a verdict badge can never appear without
its quoted source, and `unstated` (or any state with no source line) always
falls through to the plain, non-badge "doesn't say either way ... silence
isn't a no" copy. The country's `visa_terms` render underneath as "what to
look for in a post from this market", sourced from the currently-selected
destination's `CountryRules` — the only place this vocabulary reaches a user,
per `engine/country/__init__.py`.

Manually traced against the three shipped fixtures (no dev server needed —
the branch logic is pure and the fixture data is static):

| Fixture | `sponsors_visa` | `sponsors_visa_source_line` | Renders |
|---|---|---|---|
| `fresh_grad_strong_fit` (KH) | `unstated` | `null` | unstated copy, no badge |
| `fresh_grad_stretch` (SG) | `yes` | real JD sentence | proven badge + quoted sentence |
| `unrealistic` (REMOTE) | `no` | real JD sentence | missing badge + quoted sentence |

All three of the app's real demo paths exercise a different branch, including
the one that matters most (`unstated`, never shown as a "no").

### (c) Country-toned rewrites

`build_generate_user_prompt` (`engine/rewrite/prompts.py`) gains an optional,
backward-compatible `tone_notes: list[str] | None = None` parameter. When
given, it appends a clearly-labelled block *after* the existing "Rewrite the
primary evidence line..." instruction:

> Style guidance for the target market — HOW to phrase this rewrite, never a
> source of facts. Nothing below is something the candidate did or has, and
> none of it may be cited in facts_used:
> - {tone note}
> - ...

`None` (the default) produces byte-identical output to before — every
existing call site and test is unaffected. `generate_rewrite`
(`engine/rewrite/generate.py`) gained the same optional parameter and passes
it straight through. `create_rewrites` (`api/routes/analyses.py`) resolves
`rules_for(record.country)` once per call and passes `rules.tone_notes if
rules else None` into every `generate_rewrite(...)` call in its retry loop —
`record.country` is `AnalysisRecord.country`, whatever spelling the browser
originally sent, so `rules_for` does the same reconciliation it does
everywhere else in this codebase.

## RED → GREEN evidence

**Step 1 (RED):** `tests/test_countries_route.py` written first, run against
the codebase before `api/routes/countries.py` existed:

```
FAILED tests/test_countries_route.py::test_list_countries_returns_all_five
FAILED tests/test_countries_route.py::test_get_country_returns_full_rules_for_a_known_destination
FAILED tests/test_countries_route.py::test_get_country_404s_for_other_with_country_rules_not_found
FAILED tests/test_countries_route.py::test_get_country_404s_for_an_unrecognised_string
FAILED tests/test_countries_route.py::test_get_country_resolves_the_browser_spelling_end_to_end
FAILED tests/test_countries_route.py::test_get_country_resolves_a_long_form_name
```

**GREEN** after `api/routes/countries.py` + `api/main.py` registration: all 6
pass.

**Step 3 (RED):** two new tests added to `tests/test_rewrite_generate.py`
before `generate_rewrite` accepted `tone_notes`:

```
FAILED tests/test_rewrite_generate.py::test_generate_rewrite_tone_notes_are_labelled_style_guidance_not_facts
FAILED tests/test_rewrite_generate.py::test_generate_rewrite_works_when_destination_has_no_country_rules
TypeError: generate_rewrite() got an unexpected keyword argument 'tone_notes'
```

**GREEN** after extending `build_generate_user_prompt` / `generate_rewrite`:
all 4 tests in that file pass.

Beyond the two named tests, I added two more at the `POST
/api/analyses/{id}/rewrites` endpoint level (`tests/test_rewrite_endpoint.py`)
to prove the *wiring* in `create_rewrites` is actually live, not just
plumbed:

- `test_rewrites_endpoint_passes_the_destination_tone_notes_into_the_prompt` —
  seeds an analysis with `country="singapore"`, captures the prompt text the
  (mocked) model receives, and asserts one of Singapore's real `tone_notes`
  (from `rules.json`) is actually in it.
- `test_rewrites_endpoint_works_when_destination_has_no_country_rules` —
  seeds `country="other"` and asserts the endpoint still returns 200 with a
  valid hidden strength, exercising the exact `rules_for(record.country) is
  None` path end to end.

Both pass.

## Verification output

**Full pytest suite:**

```
205 passed, 2 warnings in 12.67s
```

(was 195 before this task; +10 new: 6 in `test_countries_route.py`, 2 in
`test_rewrite_generate.py`, 2 in `test_rewrite_endpoint.py`)

**Scoped ruff:**

```
$ .venv/bin/python -m ruff check api tests/test_countries_route.py engine/rewrite
All checks passed!
```

(also re-checked with `tests/test_rewrite_generate.py tests/test_rewrite_endpoint.py
api/routes/analyses.py` explicitly included — clean.)

**Frontend:**

```
$ npx tsc --noEmit
(no output — clean)

$ npx eslint components/results lib/api.ts
(no output — clean)

$ node scripts/i18n-check.mjs
i18n-check: 167 keys checked, 0 error(s), 167 warning(s).
OK  (warnings do not fail the build)
```

All warnings are the pre-existing, accepted "km mirrors en" state
(global-constraints.md); zero errors, including for every new
`results.country.*` and `errors.COUNTRY_RULES_NOT_FOUND` key.

## Files changed

- `api/routes/countries.py` — new. `GET /api/countries`, `GET /api/countries/{destination}`.
- `api/main.py` — registers the new router.
- `api/routes/analyses.py` — `create_rewrites` resolves `rules_for(record.country)` and threads `tone_notes` through the generate/retry loop.
- `engine/rewrite/prompts.py` — `build_generate_user_prompt` gains optional `tone_notes`.
- `engine/rewrite/generate.py` — `generate_rewrite` gains optional `tone_notes`, passed through.
- `web/lib/api.ts` — `CountryRules` type + `getCountryRules(destination)`.
- `web/components/results/CountryFormat.tsx` — new. Destination selector, format checklist, visa line.
- `web/components/results/ResultsView.tsx` — mounts `<CountryFormat match={match} />` after `<HiddenStrengths />`.
- `web/messages/en.json`, `web/messages/km.json` — `results.country.*` (title, intro, selectLabel, destinations, noRules, length, photo, include, omit, dateFormat, sectionOrder, toneNotes, visa.*) and `errors.COUNTRY_RULES_NOT_FOUND`, identical in both per the repo's accepted pending-Phase-5-QA state.
- `docs/errors.md` — added `COUNTRY_RULES_NOT_FOUND` as a twelfth code (§2 entry + banner note), mirroring how `ANALYSIS_NOT_READY` was added as an eleventh in Phase 3. Not in the brief's file list; added for consistency with `api/errors.py`'s own rule that every `ApiError` code be one of this table's values — flagged below as a judgment call, not hidden.
- Tests: `tests/test_countries_route.py` (new, 6 cases), `tests/test_rewrite_generate.py` (+2), `tests/test_rewrite_endpoint.py` (+2, plus a `country` parameter added to the existing `_seed_done_analysis` helper, default `"cambodia"` — every pre-existing call site unaffected).

## Self-review

- **Does an `unstated` visa signal ever render as a negative?** No. `verdict`
  is computed as `sourceLine && (sponsors_visa === "yes" || sponsors_visa ===
  "no") ? sponsors_visa : null` — `"unstated"` (and any other/absent value)
  always yields `null`, which renders only the plain "doesn't say either
  way... silence isn't a no" copy, no badge, no tone. Traced against all
  three fixtures above; the primary demo fixture (`fresh_grad_strong_fit`) is
  the `unstated` case.
- **Does a verdict ever render without its source sentence?** No — `verdict`
  is gated on `sourceLine` being truthy *first*, before the sponsors_visa
  check runs, so a badge is structurally impossible without a source line,
  even under a malformed/defensive input.
- **Is a tone note reachable by the model as a fact?** Re-read the built
  prompt as the model would see it: the evidence section is delimited and
  labelled "the ONLY source of facts" *before* the tone-notes block appears;
  the tone-notes block itself opens with "HOW to phrase this rewrite, never a
  source of facts" and closes with "none of it may be cited in facts_used".
  `test_generate_rewrite_tone_notes_are_labelled_style_guidance_not_facts`
  asserts structurally that a fabricated-fact-bearing tone note never lands
  in the prompt's evidence section and that the label text is present.
- **Does the selector work for `"other"` (no rules)?** Yes. Selecting it
  calls the real `GET /api/countries/other`, which 404s with
  `COUNTRY_RULES_NOT_FOUND`; `CountryFormat` catches that specific code and
  renders `results.country.noRules` instead of the generic error banner —
  `KNOWN_ERROR_CODES` deliberately excludes it so it never reaches
  `errors.INTERNAL`-style messaging. The visa line still renders normally
  underneath (it depends on `match.job`, not on the selected destination's
  rules), so nothing about (b) breaks when (a) has nothing to show.

## Concerns

- `docs/errors.md` was edited to add `COUNTRY_RULES_NOT_FOUND` as a twelfth
  error code, even though it isn't in the brief's file list. `api/errors.py`
  states every `ApiError` code should be one of this document's values, and
  Phase 3 set the precedent (`ANALYSIS_NOT_READY` as an eleventh) — I judged
  leaving the doc silently out of date would be worse than a small, additive
  edit. I left the "Phase 2 checklist" force-exercise section untouched
  (that checklist is specifically about the original Phase 1–3 codes' manual
  screenshot pass, and this code is graceful-degrade-only, never shown as an
  error banner, so it has nothing to force). Flagging this as a scope
  decision made on my own judgment, not something the brief asked for
  explicitly.
- `GET /api/countries` (the list endpoint) is built and tested per the
  brief's interface spec, but `CountryFormat.tsx` does not call it — the
  destination `<select>` uses a small hardcoded set of canonical codes plus
  i18n labels instead, matching the brief's explicit frontend interface list
  (`getCountryRules` only). The list endpoint is exercised solely by
  `tests/test_countries_route.py`. If a future task wants the selector's
  labels sourced live from the API rather than the i18n catalogue, that
  endpoint is already there.
- No live browser check was run (no dev server started) — verification for
  the UI is tsc/eslint/i18n-check plus the manual fixture trace above, per
  the task's own "no JS test runner" framing.
