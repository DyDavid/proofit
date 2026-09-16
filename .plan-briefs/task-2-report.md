# Task 2 report: 30-case adversarial suite + precision/recall table

## What was implemented

Per `.plan-briefs/task-2-brief.md`, grew the F5 rewrite validator's test
suite from 8 hand-written tests to a 30-case labelled dataset, drove
`tests/test_rewrite_validator.py` off it, and added a metrics script that
prints an honest precision/recall table for the report.

- **`tests/rewrite_cases.py`** (new) — a frozen `ValidatorCase` dataclass
  (`id`, `category`, `suggested_phrasing`, `evidence_overrides`,
  `should_reject`, `caught_by: Literal["scope","precheck","llm","none"]`) and
  `CASES: list[ValidatorCase]` — 30 entries, 20 adversarial across the six
  categories the brief's composition table names, plus 10 legitimate.

- **`tests/test_rewrite_validator.py`** (rewritten) — module docstring kept
  and extended to describe all three layers (it is the report's
  validator-design paragraph). Replaced the eight hand-written tests with:
  - `test_validator_dataset` — parametrized over all 30 `CASES`, asserting
    `validate_rewrite(...).ok is not case.should_reject`, LLM patched to
    reject for `caught_by == "llm"` cases and pass otherwise.
  - `test_deterministic_layers_never_call_the_llm` — parametrized over the 14
    `scope`/`precheck` cases, asserting `_call_llm_validator` is never
    called (the "costs nothing" claim, verified, not just asserted in prose).
  - `test_llm_layer_cases_reach_the_llm` — parametrized over the 6 `llm`
    cases, the direct replacement for the old single
    `test_rejects_a_status_upgrade_from_project_to_employment`: asserts the
    (mocked) LLM *is* called and does reject, proving that layer is
    load-bearing rather than decorative — now over 6 cases instead of 1, and
    using fixtures the two free layers genuinely cannot catch (verified, see
    below) rather than one that collided with Task 1's new wordlist.
  - `test_dataset_is_well_formed` — 30 cases, all six categories present, at
    least 10 legitimate, and at least 3 legitimate cases cite an
    `employment`/`internship`/`part_time` record.

- **`scripts/validator_metrics.py`** (new) — imports `CASES` (repo root
  pushed onto `sys.path` before the `tests.rewrite_cases` namespace-package
  import, per the brief), runs only `precheck_scope_inflation` +
  `precheck_rewrite` (no network, no key) over all 30 cases, and prints a
  Markdown TP/FP/FN/TN/precision/recall/F1 table plus the count of cases
  needing the semantic layer. States in its own printed output, explicitly,
  that it measures the deterministic layers only. `--live` additionally runs
  the real three-layer `validate_rewrite`, gated on `ANTHROPIC_API_KEY` being
  set — skips with a message (still exit 0) if it isn't.

## Dataset composition actually built

| Category | Adversarial cases | `caught_by` | Verified by |
|---|---|---|---|
| magnitude inflation | 4 (`mag-1..4`) | `precheck` | direct call to `precheck_rewrite`/`precheck_scope_inflation` |
| duration inflation | 3 (`dur-1..3`) | `precheck` | same |
| status upgrade | 4 (`status-1..4`) | `scope` | same |
| tool insertion | 3 (`tool-1..3`) | `precheck` | same |
| outcome invention | 3 (`outcome-1..3`) | `llm` | both deterministic layers return `None` |
| subtle paraphrase | 3 (`paraphrase-1..3`) | `llm` | both deterministic layers return `None` |
| legitimate | 10 (`legit-1..7`, `legit-emp-1..3`) | `none` | both deterministic layers return `None`, mocked LLM accepts |

20 adversarial + 10 legitimate = 30. `legit-emp-1..3` each cite a genuine
`employment`/`internship`/`part_time` record while using a forbidden-list
word ("professionally", "professional engineer", "formally employed
part-time") — all three run through `precheck_scope_inflation` cleanly with
zero violations, confirmed by the same direct-call verification, proving the
Task 1 gate's all-cited-are-non-employment condition holds rather than
over-firing on the mere word "professional".

**A real mislabelling bug was caught during verification, not assumed
away.** The first draft of `rewrite_cases.py` left `caught_by` at its
dataclass default (`"none"`) on all 10 `magnitude_inflation`/
`duration_inflation`/`tool_insertion` cases — I'd written explicit
`caught_by="scope"`/`"llm"` for the other categories but forgot the
`"precheck"` cases. Running `test_deterministic_layers_never_call_the_llm`
against the dataset surfaced it immediately: only 4 cases (the `scope` ones)
were being parametrized into that test instead of the intended 14, silently
passing without testing what it claimed to. Fixed by adding
`caught_by="precheck"` to all 10; re-verified against the deterministic
layers directly afterward. This is exactly the failure mode the brief warned
about ("a case you label precheck that the scope gate actually catches is a
mislabelled dataset") — in this instance the case was mislabelled the other
way (as "none" instead of "precheck"), caught by the same discipline of
running rather than assuming.

A second, earlier bug (also caught by running, not assuming): the first
draft of the duration-inflation cases only overrode `duration_months` and
`team_size`, leaving the shared fixture's default `source_line` ("...2
teammates over 3 months") untouched. `dur-1`'s inflated claim ("2 years")
happened to reuse the digit "2" still sitting in that unedited sentence
(from "2 teammates," unrelated to years), so the pre-check's substring check
silently passed it — a false pass. Fixed by giving all three duration cases
a matching custom `source_line`, confirmed the inflated numbers (2, 24, 18)
appear nowhere in the new haystack, and reran.

## Metrics table as printed

```
$ .venv/bin/python scripts/validator_metrics.py
==============================================================================
F5 rewrite validator — precision/recall
==============================================================================

IMPORTANT: the table below measures the two DETERMINISTIC layers only —
precheck_scope_inflation and precheck_rewrite. No LLM is called to produce
it, no ANTHROPIC_API_KEY is read, and no network request is made. A case
labelled caught_by="llm" in tests/rewrite_cases.py is *expected* to show up
as a false negative here — the whole reason engine/rewrite/validate.py has a
third layer is that these two cannot see that class of failure. This table
reports what the free layers alone catch, honestly, not what the full system
catches with a mocked or live LLM standing in behind them.

#### Deterministic layers only (precheck_scope_inflation + precheck_rewrite)

| Metric | Value |
|---|---|
| True Positives (TP) | 14 |
| False Positives (FP) | 0 |
| False Negatives (FN) | 6 |
| True Negatives (TN) | 10 |
| Precision | 1.000 |
| Recall | 0.700 |
| F1 | 0.824 |

Cases that require the semantic (LLM) layer: 6 / 30 total — these are exactly this run's false negatives:
  - outcome-1 (outcome_invention)
  - outcome-2 (outcome_invention)
  - outcome-3 (outcome_invention)
  - paraphrase-1 (subtle_paraphrase)
  - paraphrase-2 (subtle_paraphrase)
  - paraphrase-3 (subtle_paraphrase)
```

Exit code: `0`.

**Read honestly:** the deterministic layers alone have perfect precision
(1.000 — zero false positives across all 20 adversarial cases and, just as
important, zero false positives against any of the 10 legitimate cases,
including the 3 employment-citing ones) but only 0.700 recall. The 6 false
negatives are exactly the `outcome_invention` and `subtle_paraphrase`
categories — cases constructed to introduce no invented number, no invented
proper noun, and no forbidden phrase, so both free layers are structurally
blind to them by design. This is the number the report should state: **20%
of the adversarial dataset (6/30 of all cases) requires the semantic layer**,
and the free layers alone would let those 6 fabrications through. The
dataset was not tuned to hide this — the composition table in the brief
specifies exactly these two `caught_by: "llm"` categories, and the numbers
above are what running the actual code against them produces.

Also ran with `--live` (no `ANTHROPIC_API_KEY` set in this environment): it
printed the same deterministic table, then correctly reported "`--live` was
passed but `ANTHROPIC_API_KEY` is not set... skipping the live LLM run. No
network call was made." and exited 0 — the guard works as specified.

## RED evidence (pre-existing state, before this task's changes)

```
$ .venv/bin/python -m pytest -q
...F...
FAILED tests/test_rewrite_validator.py::test_rejects_a_status_upgrade_from_project_to_employment
AssertionError: Expected '_call_llm_validator' to have been called once. Called 0 times.
```

Confirmed and diagnosed per the task instructions before touching anything:
151 passed, 1 failed, 152 total. The failure is Task 1's scope gate
correctly intercepting a fixture whose wording ("Worked professionally...")
collides with the new forbidden-phrase wordlist before the LLM layer is ever
reached — not a bug, exactly as `task-1-report.md`'s "Concerns" section
already diagnosed and recommended fixing by rewording the fixture, which
this task's full replacement of the module does.

## GREEN evidence (after this task's changes)

```
$ .venv/bin/python -m pytest tests/test_rewrite_validator.py -rA -q
...................................................  [100%]
51 passed
```

(30 `test_validator_dataset` + 14 `test_deterministic_layers_never_call_the_llm`
+ 6 `test_llm_layer_cases_reach_the_llm` + 1 `test_dataset_is_well_formed`.)

```
$ .venv/bin/python -m pytest -q
195 passed, 0 failed, 0 errors
```

Baseline 152 (151 passed, 1 failed) minus the 8 removed hand-written tests
plus the 51 new dataset-driven tests = 152 − 8 + 51 = 195. The previously
failing test — its purpose (proving the LLM layer is load-bearing) is now
served by `test_llm_layer_cases_reach_the_llm`, using 6 fixtures confirmed
by direct layer calls to be genuinely unreachable by the two deterministic
layers, rather than one fixture that happened to collide with Task 1's new
wordlist.

## Files changed

- `/Users/macbook/AUPP_FALL_2026/FYP/tests/rewrite_cases.py` (new)
- `/Users/macbook/AUPP_FALL_2026/FYP/scripts/validator_metrics.py` (new)
- `/Users/macbook/AUPP_FALL_2026/FYP/tests/test_rewrite_validator.py`
  (rewritten: 133 insertions, 129 deletions)

`.venv/bin/ruff check tests/rewrite_cases.py tests/test_rewrite_validator.py
scripts/validator_metrics.py` → "All checks passed!" after fixing 3 findings
along the way: an `SIM103` (collapse an `if ... return True` / `return False`
pair into one `return`) in `validator_metrics.py`, and an `I001`
(unsorted import) plus an `SIM300` (Yoda condition,
`_ADVERSARIAL_CATEGORIES <= categories_present` reordered to
`categories_present >= _ADVERSARIAL_CATEGORIES`) in
`test_rewrite_validator.py`. `engine/normalize/schema.py` untouched, per the
global constraints (Person A's file, known pre-existing UP017, out of
scope).

## Self-review findings

1. **Is every `caught_by` label actually true, or just plausible?** Verified
   by direct calls to `precheck_scope_inflation` and `precheck_rewrite` (no
   mocking, no `validate_rewrite`) against all 30 cases, twice — once before
   the two bugs described above were found, and once after fixing them. The
   second run matches the final dataset exactly: 14 cases return non-`None`
   from `precheck_scope_inflation` or `precheck_rewrite` (10 `precheck` + 4
   `scope`), 16 return `None` from both (6 `llm` + 10 `legitimate`).

2. **Does the scope gate really stay silent on all 3 employment-citing
   legitimate cases?** Yes — confirmed as part of the same direct-call run;
   `legit-emp-1..3` each produce zero violations from
   `precheck_scope_inflation` despite containing "professionally"/
   "professional engineer"/"formally employed", because each cites an
   `employment`/`internship`/`part_time` record and the gate's `all(...)`
   condition over cited evidence types correctly fails to hold.

3. **Does `test_deterministic_layers_never_call_the_llm` actually cover all
   14 scope+precheck cases, not just some?** Checked directly with `pytest
   -rA` listing every parametrized test id — after the mislabelling fix, all
   14 (`mag-1..4`, `dur-1..3`, `status-1..4`, `tool-1..3`) appear; before the
   fix, only the 4 `status-*` ones did, silently.

4. **Does the metrics script's `--live` path genuinely make no network call
   when the guard trips?** Ran it with `ANTHROPIC_API_KEY` unset; it printed
   the skip message and exited 0 without hanging or erroring — `anthropic.Anthropic()`
   was never constructed since `live_predicts_reject` (which calls
   `validate_rewrite`, which could reach `_call_llm_validator` →
   `_get_client()`) is never invoked inside the `if args.live` branch unless
   the key check passes first.

5. **Full-suite count arithmetic.** 152 baseline − 8 removed tests (the old
   module's hand-written functions) + 51 new tests = 195; matches the
   observed `195 passed, 0 failed`.

## Concerns

None blocking. Two things worth flagging for whoever reads the report:

- **Recall of 0.700 for the deterministic layers is the honest number, not
  a shortfall to explain away.** It is reported as-is in both the script's
  output and this report, per the brief's explicit instruction not to tune
  the dataset toward a nicer table. The report's framing should present this
  as the empirical justification for the third (LLM) layer's existence, not
  as a weakness in Task 1/this task's work — a wordlist and a regex cannot,
  by construction, see a claim that introduces no new token.
- **The two bugs caught during self-review** (10 cases silently defaulting
  to `caught_by="none"`; one duration-inflation case's false pass from a
  stale `source_line`) did not affect the final dataset or metrics — both
  were found and fixed before this report was written — but they are worth
  naming explicitly here because they are precisely the kind of error the
  brief's "verify by running, not by assuming" instruction exists to catch,
  and both were in fact only caught by running the code, not by reviewing it.

## Commit

Per the brief's Step 5: `test(engine): grow the validator suite to 30
labelled cases with a metrics table`.
