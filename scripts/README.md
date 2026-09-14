# `scripts/`

Build-time tooling for the two contracts that break silently if nobody checks them:

1. the **schema contract** between Person A's Python engine and Person B's TypeScript UI
   (PERSON_B_PLAN_v2.md §2, point 1);
2. the **i18n contract** between `en` and `km` (PERSON_B_PLAN_v2.md §7).

Nothing here is imported at runtime. These scripts run on a developer's machine
and in CI, and they produce or verify files that the app then consumes.

---

## `export_schema.py`

Exports `SchemaBundle` from `engine/normalize/schema.py` to a single JSON Schema
document at `web/lib/schema.json`.

```bash
python scripts/export_schema.py          # venv active
.venv/bin/python scripts/export_schema.py  # venv not active
```

Runs from any working directory. It inserts the repo root on `sys.path`, so it
works whether or not the `engine` package is installed.

The output is deliberately normalised so that two runs of an unchanged schema are
byte-identical, which is the only reason the CI staleness check below is reliable:

| Choice | Reason |
|---|---|
| `sort_keys=True` | key order never depends on dict insertion order |
| trailing newline | POSIX text file; stops `git diff` reporting "no newline at end of file" forever |
| **no timestamps** | a generated file that embeds "now" is stale one second later, and CI would fail on every run |
| pinned root `title` | `json-schema-to-typescript` names the root interface from `title`; pinning it keeps `SchemaBundle` stable in `web/lib/types.ts` |
| property `title`s stripped | see below |

### Why property titles are stripped

Pydantic auto-titles every property (`"Id"`, `"Text"`, `"Score"`, `"Results"`, …).
`json-schema-to-typescript` hoists each one into its own exported alias, which turns
12 honest interfaces into 78 aliases — and because `Requirement.id` and `Evidence.id`
are both titled `"Id"`, it disambiguates them into `Id` and `Id1`. Those numbers are
assigned in traversal order, so adding a model upstream can silently renumber a type
the UI imports.

A `title` is an annotation with no validation meaning (JSON Schema 2020-12 §9.1), so
dropping the property-level ones changes nothing about what `schema.json` validates.
Model-level titles are kept — they are what names the interfaces.

The walker is schema-aware on purpose: `Job.title` is a real field living at
`$defs/Job/properties/title`, so a naive "delete every key named `title`" would
delete the field itself.

---

## `gen-types.sh`

The full pipeline. This is the command to run after **any** change to `schema.py`.

```bash
bash scripts/gen-types.sh
```

```
engine/normalize/schema.py          <- source of truth (Person A)
  -> scripts/export_schema.py
  -> web/lib/schema.json
  -> json-schema-to-typescript@16
  -> web/lib/types.ts               <- GENERATED, never hand-edited
```

- `set -euo pipefail`; every path resolved from the script, so cwd is irrelevant.
- Preflight-checks the repo venv and `npx`, and fails with a readable message rather
  than a broken half-run.
- Generates into a `mktemp -d` and `mv`s into place, so a failed run never leaves a
  truncated `types.ts` for the Next.js build to pick up.
- Prepends the `GENERATED — DO NOT EDIT BY HAND` banner naming `schema.py` as the
  source. `--bannerComment ""` suppresses the tool's own header so there is exactly
  one banner.
- **Idempotent**: running it twice leaves `schema.json` and `types.ts` byte-identical.
  The banner records the schema *version* (derived from the source), never the clock.
- The `json-schema-to-typescript` major version is pinned, because output formatting
  changes between majors would look like schema drift to CI.

### Current output

12 exported interfaces: `SchemaBundle`, `Job`, `Requirement`, `Resume`, `Education`,
`Evidence`, `Match`, `MatchResult`, `HiddenStrength`, `PriorityAction`,
`BaselineMatch`, `BaselineResult`. Every Pydantic docstring survives as JSDoc, so
the field documentation is visible on hover in the editor.

### Getting a named union out of the generated types

String-union fields are inlined (`verdict: "proven" | "partial" | "missing"`) rather
than emitted as standalone aliases. Do **not** hand-write the alias into `types.ts` —
it is overwritten on the next run. Derive it in your own module instead:

```ts
import type { MatchResult, Match, Requirement } from "@/lib/types";

export type Verdict = MatchResult["verdict"];              // "proven" | "partial" | "missing"
export type RealismVerdict = Match["realism_verdict"];     // "strong_fit" | "stretch" | "unrealistic"
export type RequirementPriority = Requirement["priority"]; // "required" | "preferred"
```

These stay correct automatically: if Person A adds a verdict value, the derived type
changes with the regenerated schema and every `switch` that no longer covers all
cases fails the build.

---

## `i18n-check.mjs`

Compares `web/messages/en.json` and `web/messages/km.json` after flattening both to
dotted key paths (`common.appName`, `results.verdict.proven`, …).

```bash
node scripts/i18n-check.mjs
```

Output is one finding per line behind a fixed, greppable token:

| Token | Severity | Meaning |
|---|---|---|
| `NOFILE` | error | a message file does not exist |
| `BADJSON` | error | file is empty, not an object, or not valid JSON |
| `MISSING` | error | key present in one locale, absent from the other |
| `EMPTY` | error | value is an empty or whitespace-only string |
| `WARN untranslated` | warning | `km` value is byte-identical to `en` |

Ends with a summary line and a literal `OK` or `FAIL`.

**Exit codes:** `1` if any error was reported, `0` otherwise. Warnings never fail
the build.

Why the severities are split that way:

- A **missing** key is not cosmetic. `next-intl` throws at render time, so a Khmer
  user hits an error boundary where a label should be.
- An **empty** value is worse than a missing one — it renders as a blank button and
  nothing fails loudly.
- **Untranslated** is only a warning because plenty of values are legitimately
  identical across locales: the brand name `Proofit`, and any value that is just a
  number (§7.5 keeps Arabic numerals in both locales, so numeric-looking values are
  not flagged at all).

Missing or malformed files are reported as a clear one-line finding and a `FAIL`,
never as a Node stack trace, so the CI log stays readable.

---

## When CI runs these

Add to `.github/workflows/ci.yml`. Both jobs are cheap and should run on every push
and pull request.

### Job: types are not stale

PERSON_B_PLAN_v2.md §5 Phase 1.2 ("a CI check that fails if `types.ts` is stale
relative to `schema.py`") and §9 risk *"schema drift breaks the UI"*.

```yaml
- name: Regenerate types from the locked schema
  run: bash scripts/gen-types.sh

- name: Fail if the committed types are stale
  run: git diff --exit-code -- web/lib/schema.json web/lib/types.ts
```

The second step is the whole check: `gen-types.sh` is idempotent, so a clean `git
diff` proves the committed `types.ts` matches the current `schema.py`. If it fails,
the fix is always to run `bash scripts/gen-types.sh` locally and commit the result —
never to edit `types.ts`.

This is what catches Person A's CP1 schema replacement immediately instead of at
demo time.

### Job: locales are in parity

PERSON_B_PLAN_v2.md §5 Phase 1.6 and §7 rule 1.

```yaml
- name: i18n parity
  run: node scripts/i18n-check.mjs
```

Runs on every push and pull request that touches `web/`. It has no dependencies
beyond Node, so it needs no `npm ci` step.

---

## Rules

- `web/lib/types.ts` and `web/lib/schema.json` are **generated**. Never hand-edit
  either; both are rewritten on the next run and CI will reject the difference.
- If a type is wrong, the schema is wrong. Fix `engine/normalize/schema.py`,
  regenerate, and update the fixtures — not the UI.
- Do not unpin `json-schema-to-typescript@16` without regenerating and reviewing the
  resulting diff; a formatting change across majors is indistinguishable from schema
  drift in CI.
