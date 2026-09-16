# Task 3 report — Hidden Strengths UI

## What was built

A new client component `web/components/results/HiddenStrengths.tsx` renders the F5
("hidden strengths") section below the requirement list on the Results screen, plus the
supporting API client function and i18n keys.

### `web/lib/api.ts`
Added `createRewrites(id: string): Promise<{ hidden_strengths: HiddenStrength[]; rejected_count:
number }>`, following `retryAnalysis`'s exact shape: `POST /api/analyses/{id}/rewrites`, no
body, `toApiError(res)` on non-ok, typed JSON return. Imports `HiddenStrength` from
`@/lib/types`.

### `web/components/results/HiddenStrengths.tsx` (new)
- **State machine:** `strengths` (seeded from `match.hidden_strengths ?? []`), `rejectedCount`
  (starts at 0 — unknown until a run completes), `loading`, `errorCode`, a local `dismissed`
  Set keyed by `` `${requirement_id}:${evidence_id}` `` (the schema has no `id` field on
  `HiddenStrength`, but that pair is unique per detected candidate), and an `aria-live` region
  for reject announcements.
- **Opt-in run:** the button only renders when `analysisId` is defined. Pressing it calls
  `createRewrites`, replaces `strengths`/`rejectedCount` with the response on success, or sets
  `errorCode` on failure. Nothing fires on mount.
- **Error state:** allowlist-with-fallback exactly like `ProgressStepper.tsx` and
  `ResultsById.tsx` — `KNOWN_ERROR_CODES = ["ANALYSIS_NOT_FOUND", "ANALYSIS_NOT_READY",
  "RATE_LIMITED", "ENGINE_FAILED", "INTERNAL"]` (the five codes `docs/errors.md` §2 says this
  endpoint can raise, synchronously or as a network failure), falling back to `errors.INTERNAL`
  for anything else rather than casting an arbitrary code into `te()`.
- **Counter:** `t("counter", { passed: strengths.length, rejected: rejectedCount })` — deliberately
  reads off the raw state, never off the locally-`dismissed`-filtered `visible` list, so a
  user's local "Reject" clicks (a display preference) can never distort the number that is the
  report's proof the F5 validator rejects overreaching claims. Always rendered once there is a
  result to report — including `0 passed`.
- **Word-level diff:** `HighlightedPhrasing` splits `suggested_phrasing` on whitespace (kept as
  its own tokens, so rejoining is byte-exact), and wraps a token in
  `<mark className="proofit-mark">` when its stripped-and-lowercased form
  (`token.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "").toLowerCase()`) is in the
  similarly-normalized `changed_words` set. Verified standalone: `"shipped,"` and
  `"published."` both match `"shipped"`/`"published"` in `changed_words`.
- **Evidence chips:** `FactsChips` resolves each `facts_used` id against an `evidenceById` map
  built from `match.resume?.evidence ?? []`. A resolvable id renders a toggleable chip that
  expands to `<mark className="proofit-mark">{evidence.source_line}</mark>`; an id that cannot
  be resolved (missing `resume.evidence`) renders as a plain, non-interactive chip instead of
  crashing or offering a dead toggle.
- **Copy / Reject:** Copy writes `suggested_phrasing` via `navigator.clipboard.writeText`
  wrapped in the same silent `try/catch` as `ProgressStepper.tsx`'s `copyErrorId`. Reject adds
  the item's key to the local `dismissed` Set — no reject endpoint exists or was added.
- Reuses `common.action.copy` / `common.action.reject` (no duplicate keys), `Badge`-adjacent
  chip styling, `border-rule`/`text-ink`/`text-ink-3` tokens, and the `proofit-mark` class
  exactly as `ResultsInteractive.tsx` uses it for evidence excerpts.

### `web/components/results/ResultsView.tsx`
Added an optional `analysisId?: string` prop and mounted `<HiddenStrengths match={match}
analysisId={analysisId} />` directly below `<ResultsInteractive />`.

### `web/components/results/ResultsById.tsx` (not in the brief's file list — see Concerns)
Changed `return <ResultsView match={match} baseline={baseline} />;` to pass `analysisId={id}`
through. This was the minimal necessary change to satisfy the brief's own "Produces" line
(`<HiddenStrengths match={match} analysisId={id} />`) — `id` only exists inside `ResultsById`,
so `ResultsView` needed a new prop and its one real-analysis caller needed to supply it. The
sample-path caller (`app/[locale]/results/page.tsx`) is unchanged and passes no `analysisId`.

### `web/messages/en.json` / `web/messages/km.json`
Added `results.hiddenStrengths.{title, intro, run, running, empty, counter, current, suggested,
factsUsed, rejected}` to both files, identically in English, per the project's stated
"km mirrors en pending Phase 5 QA" convention. Exact strings:

| key | value |
|---|---|
| `title` | Hidden strengths |
| `intro` | These are things you already prove, phrased weakly in your resume. Every suggestion below is built only from lines already there — nothing is invented. |
| `run` | Suggest rewrites |
| `running` | Checking your evidence… |
| `empty` | No suggestions to show right now. |
| `counter` | {passed} suggestions passed validation · {rejected} rejected |
| `current` | Currently in your resume |
| `suggested` | Suggested rewrite |
| `factsUsed` | Built from your resume |
| `rejected` | Suggestion rejected. |

`rejected` is used as the text announced to an `aria-live="polite"` region when the user
presses Reject (screen-reader feedback for an action that otherwise only removes DOM content
silently) — distinct from the `counter` string's inline literal word "rejected" and from
`common.action.reject` (the button label).

## Verification

```
cd web && npx tsc --noEmit
```
Output: none (clean).

```
cd web && npx eslint components/results lib/api.ts
```
Output: none (clean).

```
node scripts/i18n-check.mjs
```
Output: `i18n-check: 141 keys checked, 0 error(s), 141 warning(s).` / `OK (warnings do not fail
the build)`. The 10 new `UNTRANSLATED` warnings (km byte-identical to en) are expected and
match the project's existing convention — the check already reported 131 such warnings before
this change, all pre-existing.

Additionally ran `npx next build` (production build): compiled successfully, and both
`/en/results` and `/km/results` — the no-`?id=` sample path — were statically pre-rendered
(SSG) without error, which only succeeds if `HiddenStrengths` renders cleanly against
`sampleMatch` (whose `hidden_strengths` is undefined/absent). Also started the built app and
curled `/en/results` directly:
- Confirmed rendered text includes "Hidden strengths", "0 suggestions passed validation · 0
  rejected", and "No suggestions to show right now" (the empty state).
- Confirmed **no** `<button>` element renders "Suggest rewrites" on that page — the only
  occurrence of that string in the HTML is inside the serialized `next-intl` messages payload
  used for client hydration, not a rendered button. The run button is correctly absent when
  `analysisId` is undefined.

One pre-existing, unrelated build warning: `./lib/types.ts: Unused eslint-disable directive` —
confirmed via `git diff --stat web/lib/types.ts` that this generated file was not touched by
this task.

`ruff check .` was not run, per the brief (frontend-only task, no Python changed).

## Self-review findings

- **Counter at passed=0, rejected=3:** Traced the logic explicitly — `strengths.length` and
  `rejectedCount` are set directly from the API response (`res.hidden_strengths`,
  `res.rejected_count`) on every successful run, independent of the `dismissed` filtering used
  only for the rendered list. `0 suggestions passed validation · 3 rejected` renders correctly.
- **Punctuation survives the diff highlight:** verified with a standalone Node snippet —
  `"shipped,"` and `"published."` both normalize to match `"shipped"`/`"published"` in
  `changed_words` and get wrapped in `<mark>`.
- **Missing `match.resume?.evidence`:** `evidenceById` defaults to an empty `Map` via `?? []`;
  `FactsChips` renders any unresolvable `facts_used` id as a plain `<span>` chip (no button, no
  expand, no crash).
- **BRAND.md §6 voice check:** No ATS framing anywhere. `intro` explicitly states "nothing is
  invented" and frames rewrites as built only from existing resume lines (mirrors the
  onboarding-strip tone reference verbatim in spirit). No outcome is promised. Column labels
  ("Currently in your resume" / "Suggested rewrite" / "Built from your resume") describe
  mechanism, not benefit — avoided words like "stronger" or "improve" that BRAND.md explicitly
  flags as implying invented improvement.

## Concerns

- **`ResultsById.tsx` was modified even though the brief's file list only named
  `web/lib/api.ts`, `web/components/results/ResultsView.tsx`, and the two message files** (plus
  creating `HiddenStrengths.tsx`). This was unavoidable: the brief's own "Produces" line
  requires `<HiddenStrengths match={match} analysisId={id} />`, and `id` is only in scope
  inside `ResultsById`. The change is a single line (`analysisId={id}` added to an existing
  `<ResultsView>` call) with no other behavior change. Flagging in case this falls outside
  intended review scope.
- **`sample-match.ts` was left untouched.** The task-3 brief states "the fixtures already
  populate it," but `web/lib/fixtures/sample-match.ts` (the actual data source for the
  no-`?id=` path) has no `hidden_strengths` field — only the Python fixtures under
  `data/fixtures/*.json` (used by the real, id-bearing mock-API path) do. Since `sample-match.ts`
  was not in the brief's file list and editing generated/fixture data was not requested, I left
  it alone; the component handles the absence correctly (renders the empty state, counter at
  `0 · 0`, no crash — confirmed above), but the sample page does not currently demo a populated
  Hidden Strengths card the way the brief's phrasing implies. Worth a follow-up if a
  fixture-populated demo is wanted.
- Did not add automated tests for this component — the brief's Step 5 verification list was
  `tsc` + `eslint` + `i18n-check` only, with no test-runner step, and no existing `*.test.tsx`
  convention was found under `web/components/results/`.

## Files changed

- `web/components/results/HiddenStrengths.tsx` (new)
- `web/lib/api.ts`
- `web/components/results/ResultsView.tsx`
- `web/components/results/ResultsById.tsx`
- `web/messages/en.json`
- `web/messages/km.json`
