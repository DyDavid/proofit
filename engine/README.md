# `engine/` — the Proofit analysis engine

Proofit performs **requirement coverage analysis** for Cambodian entry-level
candidates. This package is the analysis half: an importable Python package with no
web code in it. `api/` imports it; it never imports `api/`.

The architecture in one line, and it is the line to defend:

> A job description and a resume are both normalized into **the one schema**, and
> the match compares **schema against schema — never text against text**.
> (`PROJECT_SPEC.md` §6)

`engine/normalize/schema.py` is that schema. It is law. Nothing anywhere — not the
API, not the fixtures, not the TypeScript — invents a field name that is not in it.

---

## Ownership

Two people build this. The split is `PERSON_B_PLAN_v2.md` §2.

| Subpackage        | Owner        | Contents                                                                 | Phase |
| ----------------- | ------------ | ------------------------------------------------------------------------ | ----- |
| `engine.normalize`| **Person A** | `schema.py` (the locked models) + the JD and resume normalizers           | CP1   |
| `engine.match`    | **Person A** | Embedding shortlist, LLM judge, F4 rules, coverage, realism, TF-IDF baseline | CP2 |
| `engine.ingest`   | **Person A** | ATS clients, aggregator, URL path, local board module, content-hash cache | CP2   |
| `engine.rewrite`  | **Person B** | F5 — hidden-strengths detector, rewrite generator, hallucination validator, rejection log | Phase 3 |
| `engine.country`  | **Person B** | F6 — country-rules config (`rules.json`) loader + visa-signal handling    | Phase 4 |

Person A also owns the DB migrations. Person B also owns `web/`, `api/`,
`data/fixtures/`, `deploy/` and `eval/`.

`engine.rewrite` and `engine.country` are empty right now, on purpose. They carry a
docstring and `__all__ = []` — no stubs, because a stub would promise behaviour that
has not been designed yet.

---

## The five contract callables

These are the only functions that cross the ownership boundary
(`PERSON_B_PLAN_v2.md` §2, "The contract between you", item 2). Person A exposes
exactly these; Person B calls exactly these.

```python
engine.normalize.normalize_jd(text: str) -> Job
engine.normalize.normalize_resume(file_bytes: bytes, filename: str) -> Resume
engine.ingest.fetch_jd(url: str) -> str            # raw text, cache-aware
engine.match.run_match(job: Job, resume: Resume) -> Match
engine.match.run_baseline(job: Job, resume: Resume) -> BaselineMatch
```

All five exist today as typed stubs that raise `NotImplementedError` with a message
naming their owner and their checkpoint. That is deliberate: the signatures, the
type hints and the docstrings are real, so `api/`, the tests and mypy can all be
written against them before a single line of Person A's implementation lands.

How the five compose in one analysis:

```
POST /api/jobs     {"url": …}  ──▶ ingest.fetch_jd ──┐
                   {"text": …} ───────────────────────┴─▶ normalize.normalize_jd ──▶ Job
POST /api/resumes  file bytes  ─────────────────────────▶ normalize.normalize_resume ─▶ Resume
                                                                      │
POST /api/analyses {resume_id, job_id}                                ▼
                                          match.run_match(job, resume)     ──▶ Match
                                          match.run_baseline(job, resume)  ──▶ BaselineMatch
                                                                      │
GET /api/analyses/{id} ───────────────────────────────────────────────┴─▶ {match, baseline}
```

`run_baseline` is the control condition. It exists **to be beaten** — it is the
comparison column in the evaluation chapter and the "Compare with keyword baseline"
toggle on the results screen, the one control that makes the argument visible
instead of narrated.

---

## The internals rule

**`api/` calls the five callables above and nothing else in this package.**

No `from engine.match.judge import _score_requirement`. No poking at a normalizer's
prompt template. No importing a helper because it happens to be convenient. If the
API needs something the five functions do not give it, that is a conversation with
Person A and a change to the contract — not a reach through the boundary.

Two reasons, and both are load-bearing:

1. **Parallel work.** Person B built every screen and the whole API against golden
   fixtures while `engine/match/` did not exist. That only works while the surface
   between them is five functions wide.
2. **Person A can rewrite freely.** Swap the embedding model, restructure the judge,
   replace the cache — as long as the five signatures and the schema hold, nothing
   downstream notices.

The same rule points the other way: nothing in `engine/` imports FastAPI, reads an
HTTP request, or knows what a locale is.

---

## Until the engine is live: `ENGINE_MODE=mock`

The API reads `ENGINE_MODE`:

- **`mock`** — every analysis returns a golden fixture from `data/fixtures/` after a
  1.5 s artificial delay, so loading states are honest. This is the mode to use
  until **Checkpoint 2**.
- **`live`** — the routes call the five callables above. Not implemented in Phase 1;
  it raises `NotImplementedError` with a message saying so.

Golden fixtures are contract item 3: every one of the five functions has a fixture
in `data/fixtures/`, and Person A keeps them current when the schema changes.
Screens are built against fixtures first, live engine second.

Checkpoints (`PERSON_B_PLAN_v2.md` §4): **CP1** end of Week 3 — schema locked.
**CP2** end of Week 7 — live engine wired. **CP3** end of Week 11 — F5/F6 merged.
**CP4** end of Week 12 — freeze.

---

## The schema, and the types generated from it

`engine/normalize/schema.py` is the single source of truth, and it enforces the
non-negotiable rules from `PROJECT_SPEC.md` §9 **in code**, because the examiner will
test them:

- **Rule 3 — every verdict is traceable.** A `MatchResult` cannot exist without
  either a non-empty `evidence_ids` or an explicit `missing_reason`. A `missing`
  verdict may cite no evidence; a `proven` or `partial` one must.
- **Rule 2 — no scope inflation (F4).** An `experience` requirement can never be
  `proven` by coursework, a project, a competition or volunteering alone. `partial`
  is exactly what those records are for.

Both raise `ValidationError` at parse time, so a violation cannot reach the
database, the API response, or the screen. `extra="forbid"` is set on every model,
so a typo in a fixture fails loudly instead of rendering as `undefined` in a browser.

TypeScript types are **generated**, never hand-written:

```
schema.py  ──▶  scripts/export_schema.py  ──▶  JSON Schema  ──▶  web/lib/types.ts
```

A CI staleness check fails the build if `web/lib/types.ts` no longer matches the
schema, so drift is caught on the pull request rather than at demo time.

---

## Installing and importing

Flat layout: the package lives at `./engine`, so `api/`, `scripts/` and Person A's
notebooks all import it the same way, with no `sys.path` games.

```bash
/Users/macbook/AUPP_FALL_2026/FYP/.venv/bin/python -c "from engine.normalize.schema import Match, Job, Resume"
```

`import engine` on its own is cheap by design — it exposes `__version__` and nothing
else, pulling in neither pydantic nor any parser. The API runs on a 512 MB Render
free instance, so anything heavy (a local embedding model, torch) belongs behind an
API call rather than inside this package (`PERSON_B_PLAN_v2.md` §9).
