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
