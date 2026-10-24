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
