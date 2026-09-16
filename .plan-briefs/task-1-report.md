# Task 1 report: deterministic scope-inflation gate

## What was implemented

Per `.plan-briefs/task-1-brief.md`, added a third, first-run deterministic
layer to the F5 rewrite validator, enforcing PROJECT_SPEC.md §9 rule 2 ("no
scope inflation") as code:

- **`engine/rewrite/forbidden.json`** (new) — the exact wordlist from the
  brief: `version`, `applies_to_evidence_types` (`coursework`, `project`,
  `competition`, `volunteer`), and five `forbidden_phrases` entries
  (`professional`, `employed`, `worked at`, `years of experience`,
  `engineer at`), each with `reason_en`/`reason_km` (mirrored, per the
  brief's note that Khmer QA is a scheduled Phase 5 pass).

- **`engine/rewrite/validate.py`** (modified) — added verbatim, per the
  brief:
  - `ForbiddenPhrase` / `ForbiddenConfig` Pydantic models (`extra="forbid"`,
    `str_strip_whitespace=True`, `frozen=True`) and `load_forbidden()`
    (`lru_cache`-d, reads `forbidden.json`).
  - `precheck_scope_inflation(rewrite, evidence_records) -> ValidationResult
    | None` — fires only when every record cited in `facts_used` has an
    `evidence_type` in the forbidden set *and* `suggested_phrasing` matches a
    forbidden phrase on a leading-only word boundary (`\bphrase`, so
    "professionally" matches "professional" but "professor" does not).
    Returns `None` on a clean rewrite or when any cited record is
    `employment`/`internship`/`part_time`.
  - `validate_rewrite` now calls `precheck_scope_inflation` first, then
    `precheck_rewrite`, then `_call_llm_validator` — short-circuiting at the
    first non-`None` result.
  - `__all__` extended with `precheck_scope_inflation`, `load_forbidden`,
    `ForbiddenConfig`, `ForbiddenPhrase`.
  - Module docstring rewritten to describe three layers instead of two
    (scope gate → pre-check → LLM), keeping the "why three layers"
    justification the report quotes from.

- **`tests/test_rewrite_scope_gate.py`** (new) — 14 tests, written first
  (strict TDD), covering every case Step 1 of the brief lists.

## RED evidence

```
$ .venv/bin/python -m pytest tests/test_rewrite_scope_gate.py -q
==================================== ERRORS ====================================
______________ ERROR collecting tests/test_rewrite_scope_gate.py _______________
ImportError while importing test module '.../tests/test_rewrite_scope_gate.py'.
tests/test_rewrite_scope_gate.py:32: in <module>
    from engine.rewrite.validate import precheck_scope_inflation, validate_rewrite
E   ImportError: cannot import name 'precheck_scope_inflation' from 'engine.rewrite.validate' (.../engine/rewrite/validate.py)
=========================== short test summary info ============================
ERROR tests/test_rewrite_scope_gate.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

Failed for the expected reason: `precheck_scope_inflation` did not exist yet.

## GREEN evidence

```
$ .venv/bin/python -m pytest tests/test_rewrite_scope_gate.py -v
collected 14 items
tests/test_rewrite_scope_gate.py ..............                          [100%]
============================== 14 passed in 0.29s ==============================
```

All 14 new tests pass:
- fires on a project-only rewrite containing "professional"
- fires for each of the 5 wordlist phrases (parametrized)
- does not fire when the single cited record is `employment`
- does not fire when one of two cited records is `employment` (the other
  `project`) — proves the "every cited record" requirement, not just "any"
- does not fire when the cited record is `internship`
- does not fire when the cited record is `part_time`
- does not fire on the substring "professor"
- does not fire on a clean rewrite
- returns `None` (not `ValidationResult(ok=True, ...)`) on success
- `validate_rewrite` never calls `_call_llm_validator` when the gate fires

## Full-suite result

```
$ .venv/bin/python -m pytest
...
FAILED tests/test_rewrite_validator.py::test_rejects_a_status_upgrade_from_project_to_employment
1 failed, 151 passed, 2 warnings in 12.67s
```

138 pre-existing + 14 new = 152 total. 151 pass; 1 pre-existing test now
fails. See "Concerns" below — this is a real, investigated signal, not a
flaky result, and I did not edit the failing test to force it green (per the
brief's explicit instruction).

## Files changed

- `/Users/macbook/AUPP_FALL_2026/FYP/engine/rewrite/forbidden.json` (new)
- `/Users/macbook/AUPP_FALL_2026/FYP/engine/rewrite/validate.py` (modified)
- `/Users/macbook/AUPP_FALL_2026/FYP/tests/test_rewrite_scope_gate.py` (new)

`ruff check engine/rewrite tests/test_rewrite_scope_gate.py` → "All checks
passed!" (scoped per the global constraints; `engine/normalize/schema.py`'s
pre-existing UP017 error was left untouched, out of scope).

## Self-review findings

1. **Does the gate genuinely not fire when one cited record is
   `employment`?** Proved by test, not just by reading:
   `test_does_not_fire_when_a_cited_record_is_employment` (single employment
   record) and `test_does_not_fire_when_one_of_several_cited_records_is_employment`
   (one `project` + one `employment`, phrasing citing both) — both assert
   `precheck_scope_inflation(...) is None`. Both pass.

2. **Does `\b` on the leading edge only actually let "professionally" match
   while "professor" does not?** Confirmed by running it directly, not just
   by reading:
   ```
   >>> re.compile(r"\bprofessional").search("worked professionally on this")
   True
   >>> re.compile(r"\bprofessional").search("worked with a professor on this")
   None (bool -> False)
   ```
   Also covered by `test_does_not_fire_on_a_substring_professor`.

3. **Does `validate_rewrite` still short-circuit correctly — gate, then
   precheck, then LLM — with the LLM never reached when an earlier layer
   fails?** Yes: `test_validate_rewrite_never_reaches_the_llm_when_the_gate_fires`
   patches `_call_llm_validator` and asserts `assert_not_called()` after the
   gate fires. This is also exactly what caused the one full-suite failure
   below — independent, unintended confirmation that the short-circuit is
   real, not just tested in isolation.

4. **Is the module docstring updated to describe three layers?** Yes,
   rewritten in full (scope gate → pre-check → LLM), each layer's role and
   the "why layered" rationale kept intact and extended.

## Concerns

**One pre-existing test now fails, and I deliberately did not edit it.**

`tests/test_rewrite_validator.py::test_rejects_a_status_upgrade_from_project_to_employment`
uses the rewrite text *"Worked professionally as a software engineer,
delivering production features independently."* against project-only
evidence, and asserts `_call_llm_validator` **is** called (it was written in
Phase 3 to demonstrate that a "quiet" status upgrade — one that invents no
new number or proper noun — can only be caught by the LLM layer).

Root cause: that fixture's wording contains "professionally", which matches
the brief's own `professional` forbidden-phrase entry, cited evidence is
project-only (no `employment`/`internship`/`part_time` record), so per the
brief's rule — stated precisely, and implemented verbatim — the new gate is
*required* to fire and intercept before the LLM is ever reached. This is not
a bug: it is `precheck_scope_inflation` behaving exactly as specified,
applied to a fixture that (coincidentally, from Phase 3, before this
wordlist existed) happens to use one of the five now-forbidden phrases.

I did not edit `test_rewrite_validator.py`:
- The brief's Step 4 gives `precheck_scope_inflation` and the wordlist
  verbatim, to be followed rather than redesigned — I did not soften the
  gate or drop "professional" from the wordlist to dodge the collision.
- The brief explicitly says: "If any of them now fail, that is a real
  signal: investigate rather than editing those tests to match." I
  investigated (see root cause above) and concluded the fix, if any, belongs
  in that test's *fixture wording* (e.g. swapping in a status-upgrade
  phrasing that uses none of the five forbidden phrases, so it again
  exercises only the LLM layer) — not in loosening the new gate's logic or
  its assertions. `tests/test_rewrite_validator.py` is outside Task 1's
  declared file scope (`forbidden.json`, `validate.py`,
  `test_rewrite_scope_gate.py` only), so I left it for the plan owner to
  decide rather than unilaterally editing a file I wasn't asked to touch.

Recommendation for whoever owns that file next: reword that one test's
`suggested_phrasing` to a status-upgrade claim that avoids all five
forbidden phrases (e.g. drop "professionally", "worked", "engineer" +
"at" collisions) while still overstating the evidence semantically, so the
test again demonstrates the LLM layer catching what neither deterministic
layer can. No other test in that file, and none of the 3 remaining pre-
existing "accepts" tests, were affected — only this one "quiet failure"
fixture collided with the new wordlist.

No other concerns. The gate, the config loader, and the short-circuit order
all behave exactly as specified and are proven by test, not just by
inspection.
