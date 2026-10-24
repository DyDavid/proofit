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
