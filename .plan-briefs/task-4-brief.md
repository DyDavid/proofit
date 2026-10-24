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
