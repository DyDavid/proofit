# Phase 2 — Results Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish everything in PERSON_B_PLAN_v2.md Phase 2 ("The Results Experience") that does not require Person A's live engine — the error-handling contract, the keyword-baseline comparison, the evidence-type storytelling note, and a real timeout/retry story for the progress stepper — so the screen the examiner stares at is finished and defensible before the engine behind it exists.

**Architecture:** The mock API (`api/`) already serves golden fixtures through a locked schema (`engine/normalize/schema.py`). This plan adds a typed error envelope shared by every route, a hand-authored TF-IDF baseline paired with each existing fixture, and the frontend wiring (`web/`) to present both. Every change is additive to the existing mock-mode path — nothing here touches `engine/match/run_match` or `engine/match/run_baseline`, which still `raise NotImplementedError` until Person A lands them.

**Tech Stack:** FastAPI + Pydantic v2 (`api/`, `engine/normalize/schema.py`), Next.js 15 + next-intl + Tailwind (`web/`), pytest (backend tests only — see Global Constraints).

**Spec:** `PERSON_B_PLAN_v2.md` §5 Phase 2 (tasks 1–4, 6), `docs/errors.md` (the error contract, already fully drafted), `PROJECT_SPEC.md` §8–9 (schema, non-negotiable rules), `BRAND.md` §6 (voice rules).

## Global Constraints

- Error envelope shape, exact (`docs/errors.md` §1): `{"error": {"code": str, "message": str, "error_id": str}}`. `code` is what the frontend switches on. `message` is English, developer-facing, never rendered to the user. `error_id` is unique per occurrence, shown to the user with a copy button on an unrecoverable error.
- `docs/errors.md`'s ten codes are authoritative for naming. Where the current code uses a different name (`RESUME_TYPE_UNSUPPORTED`, `JOB_TEXT_TOO_SHORT`), this plan renames to the doc's name (`RESUME_BAD_TYPE`, folded into `JOB_EMPTY`) rather than adding an eleventh code.
- Client-side polling timeout ceiling: **120 seconds** (`docs/errors.md` §3, `PERSON_B_PLAN_v2.md` Phase 2.3). Poll interval stays **2000 ms** (unchanged, `ProgressStepper.tsx`).
- Coverage weighting formula, exact (already shipped, `en.json`'s `results.coverage.weighting`): proven = 1, partial = 0.5, missing = 0; preferred requirements count half. The baseline fixtures use the same formula so the two numbers are comparable.
- `engine/normalize/schema.py`'s `_Base` sets `model_config = ConfigDict(extra="forbid", ...)` — every fixture JSON must validate with **no extra keys**. `BaselineMatch` is a sibling of `Match` in `SchemaBundle`, never a field inside `Match` — baseline data lives in **separate** fixture files, never merged into the existing `data/fixtures/*.json`.
- `web/lib/types.ts` is generated from `engine/normalize/schema.py` (`scripts/gen-types.sh`). **Never hand-edit it.** Every type this plan needs (`Match`, `BaselineMatch`, `BaselineResult`, `Requirement`, `Evidence`, `MatchResult`) already exists there.
- No JS/TS test runner exists in `web/` (`package.json` has only `dev`/`build`/`start`/`lint`). This plan does not introduce one — that would be new project infrastructure nobody asked for. Frontend tasks are verified with `npx tsc --noEmit`, `npx eslint`, and a manual test checklist per task, matching every prior phase's own pattern (e.g. Phase 1's embedded prompts: "after each step, list what I should test manually"). Backend tasks use the existing `pytest` setup (`tests/`, already configured in `pyproject.toml`) and get real TDD steps.
- BRAND.md §6 voice rules apply to every user-facing string this plan writes: no "ATS score" language, never imply invented experience, second person, name gaps plainly, no guaranteed outcomes.
- **Out of scope, deliberately:** Phase 2 tasks 5 and 7 (wire `ENGINE_MODE=live`, deploy live mode to Render). `engine/match/run_match` and `engine/match/run_baseline` both `raise NotImplementedError` today — there is nothing to wire yet. Pick those two up at CP2, once Person A's engine lands. Also out of scope: a global override of FastAPI's built-in `RequestValidationError` (malformed JSON, wrong field types) to match the envelope — those are framework-level 422s outside the ten documented codes, and `web/lib/api.ts`'s existing generic fallback (`Request failed (${status})`) already handles them reasonably. Don't build a second error system to cover a case the doc doesn't scope.

---

## File Structure

**Backend — new files:**
- `api/errors.py` — the `ApiError` exception type, the envelope-building exception handler, `error_id` generation.
- `data/fixtures/fresh_grad_strong_fit.baseline.json`, `data/fixtures/fresh_grad_stretch.baseline.json`, `data/fixtures/unrealistic.baseline.json` — hand-authored `BaselineMatch` fixtures, one paired with each existing `Match` fixture.
- `tests/test_errors.py` — envelope shape, per-route error codes.
- `tests/test_baseline_fixtures.py` — schema validation + the "baseline scores lower than the real match" invariant.
- `tests/test_analyses_baseline_and_retry.py` — `GET /api/analyses/{id}` includes `baseline`; `POST /api/analyses/{id}/retry` behavior; the `ENGINE_FAILED` failure path.

**Backend — modified files:**
- `api/main.py` — register the `ApiError` exception handler.
- `api/routes/resumes.py` — raise `ApiError` (`RESUME_BAD_TYPE`, `RESUME_TOO_LARGE`).
- `api/routes/jobs.py` — raise `ApiError` (`JOB_EMPTY`); drop the Pydantic cross-field validator so the XOR check produces our envelope instead of FastAPI's default validation-error shape.
- `api/routes/analyses.py` — raise `ApiError` (`ANALYSIS_NOT_FOUND`); `GET` response gains `baseline` and `error`; new `POST /api/analyses/{id}/retry`; stage-timing log lines; the mock background job catches exceptions into a real `status: "failed"` path.
- `api/store.py` — `AnalysisRecord` gains `baseline: BaselineMatch | None` and `error: dict | None`; baseline fixtures loaded and picked the same way `_FIXTURES` are; a `create_retry` helper that reuses an existing record's `resume_id`/`job_id`/`country`.

**Frontend — new files:**
- `web/lib/fixtures/sample-baseline.ts` — `sampleBaseline: BaselineMatch`, paired with the existing `sampleMatch`.
- `web/components/results/BaselineToggle.tsx` — the toggle control plus the muted comparison column.

**Frontend — modified files:**
- `web/lib/api.ts` — `ApiError` reads the new `{error: {...}}` envelope and carries `errorId`; `AnalysisStatusResponse` gains `baseline` and `error`; new `retryAnalysis(id)`.
- `web/messages/en.json`, `web/messages/km.json` — `errors.*` (ten codes), `results.evidence.howThisCounts*`, `results.baseline.*` additions, `progress.timeoutAction` correction.
- `web/components/analyze/ResumeDropzone.tsx` — accepts a server-side `error` prop alongside its existing client-side one.
- `web/components/analyze/JobPostPanel.tsx` — accepts an `error` prop, renders inline under the tabs.
- `web/components/analyze/AnalyzeForm.tsx` — per-field error routing instead of one bottom-of-form message.
- `web/components/results/ResultsById.tsx` — carries `baseline`/`error` alongside `match`; renders the `ANALYSIS_NOT_FOUND` full-page state distinctly.
- `web/components/results/ResultsView.tsx` — accepts an optional `baseline` prop, passes it down.
- `web/components/results/ResultsInteractive.tsx` — accepts `baseline`; renders `BaselineToggle`; `RequirementRow` grows the "how this counts" note.
- `web/app/[locale]/results/page.tsx` — passes `sampleBaseline` on the no-`?id=` path.
- `web/components/progress/ProgressStepper.tsx` — real 120 s ceiling, a distinct server-failure error card with Retry + copyable `error_id`, distinct from the "still going" timeout state.
- `docs/errors.md` — checklist updated to reflect what this plan actually ships vs. what stays blocked.

---

### Task 1: Backend error envelope infrastructure

**Files:**
- Create: `api/errors.py`
- Modify: `api/main.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Produces: `class ApiError(HTTPException)` with `__init__(self, status_code: int, code: str, message: str)`, attributes `.code: str`, `.message: str`. `install_error_handlers(app: FastAPI) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import ApiError, install_error_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise ApiError(status_code=418, code="TEAPOT", message="dev-only message")

    return app


def test_api_error_envelope_shape() -> None:
    client = TestClient(_make_app())
    res = client.get("/boom")
    assert res.status_code == 418
    body = res.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "TEAPOT"
    assert "error_id" in body["error"]
    assert body["error"]["error_id"].startswith("err_")


def test_api_error_ids_are_unique_per_occurrence() -> None:
    client = TestClient(_make_app())
    first = client.get("/boom").json()["error"]["error_id"]
    second = client.get("/boom").json()["error"]["error_id"]
    assert first != second
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.errors'`

- [ ] **Step 3: Write the implementation**

```python
# api/errors.py
"""Typed API errors and the response envelope (docs/errors.md §1).

Every error response from this API has exactly one shape:

    {"error": {"code": str, "message": str, "error_id": str}}

`code` is what the frontend switches on — never parse `message`. `message`
is English and developer-facing: it goes in logs, never to the user.
`error_id` is unique per occurrence and safe to show the user with a copy
button on an unrecoverable error, so a report can be traced back here.

Raise `ApiError` for any user-facing failure. Never raise a bare
`HTTPException` from a route — it would skip this envelope entirely.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("proofit.errors")


class ApiError(HTTPException):
    """A user-facing API error. `code` must be one of docs/errors.md §2's
    ten values — check that table before inventing an eleventh."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message


def new_error_id() -> str:
    return f"err_{secrets.token_hex(6)}"


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    error_id = new_error_id()
    logger.warning(
        "api_error code=%s error_id=%s path=%s message=%s",
        exc.code,
        error_id,
        request.url.path,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "error_id": error_id}},
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
```

```python
# api/main.py — add two lines
from api.errors import install_error_handlers
...
app = FastAPI(title="Proofit API", version=settings.app_version)
install_error_handlers(app)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_errors.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/errors.py api/main.py tests/test_errors.py
git commit -m "feat(api): add typed ApiError and the error envelope handler"
```

---

### Task 2: Migrate existing routes to ApiError, renaming codes to the doc's authoritative names

**Files:**
- Modify: `api/routes/resumes.py`
- Modify: `api/routes/jobs.py`
- Modify: `api/routes/analyses.py:1-56` (the `POST`/`GET` handlers already read; the retry endpoint is Task 5)
- Test: `tests/test_routes_errors.py`

**Interfaces:**
- Consumes: `ApiError` from Task 1 (`api.errors.ApiError`).
- Produces: every existing failure path now raises `ApiError` with codes `RESUME_BAD_TYPE`, `RESUME_TOO_LARGE`, `JOB_EMPTY`, `ANALYSIS_NOT_FOUND` — these are the four codes later frontend tasks map to specific UI. `JobIn` no longer has a `model_validator`; the XOR check moves into the route so it raises `ApiError` instead of FastAPI's default validation-error shape.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_routes_errors.py
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_resume_bad_type_uses_the_envelope() -> None:
    res = client.post(
        "/api/resumes",
        files={"file": ("resume.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "RESUME_BAD_TYPE"


def test_resume_too_large_uses_the_envelope() -> None:
    big = io.BytesIO(b"0" * (6 * 1024 * 1024))
    res = client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", big, "application/pdf")},
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "RESUME_TOO_LARGE"


def test_job_empty_on_blank_text() -> None:
    res = client.post("/api/jobs", json={"text": "   "})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_EMPTY"


def test_job_empty_when_neither_text_nor_url_given() -> None:
    res = client.post("/api/jobs", json={})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_EMPTY"


def test_job_empty_when_both_text_and_url_given() -> None:
    res = client.post("/api/jobs", json={"text": "x" * 41, "url": "https://example.com"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_EMPTY"


def test_analysis_not_found_uses_the_envelope() -> None:
    res = client.get("/api/analyses/an_doesnotexist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_routes_errors.py -v`
Expected: FAIL — current codes are `RESUME_TYPE_UNSUPPORTED`/`JOB_TEXT_TOO_SHORT` under `detail`, not `error`, and the both/neither cases 422 with FastAPI's own validation array, not our envelope.

- [ ] **Step 3: Write the implementation**

```python
# api/routes/resumes.py — replace both raises
from api.errors import ApiError
...
    if file.content_type not in ACCEPTED_CONTENT_TYPES:
        raise ApiError(
            status_code=415,
            code="RESUME_BAD_TYPE",
            message=f"Unsupported content type: {file.content_type!r}",
        )
    ...
    if len(body) > settings.max_upload_bytes:
        raise ApiError(
            status_code=413,
            code="RESUME_TOO_LARGE",
            message=f"Upload exceeds {settings.max_upload_bytes} bytes.",
        )
```

Remove the now-unused `HTTPException` import from `resumes.py` if nothing else in the file uses it.

```python
# api/routes/jobs.py — full replacement
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.errors import ApiError
from api.store import store

router = APIRouter()


class JobIn(BaseModel):
    text: str | None = None
    url: str | None = None


@router.post("/jobs")
async def submit_job(payload: JobIn) -> dict:
    if bool(payload.text and payload.text.strip()) == bool(payload.url and payload.url.strip()):
        # docs/errors.md JOB_EMPTY: covers blank text, neither given, and both given.
        raise ApiError(
            status_code=422,
            code="JOB_EMPTY",
            message="Provide exactly one of a non-blank text or url.",
        )

    if payload.text is not None:
        if len(payload.text.strip()) < 40:
            raise ApiError(
                status_code=422,
                code="JOB_EMPTY",
                message="Job text is present but too short to be a real job post.",
            )
        record, cached = store.add_job(payload.text, source="text")
    else:
        assert payload.url is not None
        record, cached = store.add_job(payload.url, source="url")

    return {"job_id": record.id, "cached": cached}
```

```python
# api/routes/analyses.py — imports and the two existing raises
from api.errors import ApiError
...
@router.post("/analyses", status_code=202)
async def create_analysis(payload: AnalysisIn, background_tasks: BackgroundTasks) -> dict:
    if payload.resume_id not in store.resumes:
        raise ApiError(
            status_code=404,
            code="RESUME_NOT_FOUND",
            message="Unknown resume_id.",
        )
    if payload.job_id not in store.jobs:
        raise ApiError(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="Unknown job_id.",
        )
    ...
@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    record = store.analyses.get(analysis_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code="ANALYSIS_NOT_FOUND",
            message="Unknown analysis_id.",
        )
    ...
```

`RESUME_NOT_FOUND`/`JOB_NOT_FOUND` are not in `docs/errors.md`'s ten — they predate this plan and the frontend's `AnalyzeForm.tsx` already special-cases `RESUME_NOT_FOUND` by its `code` string (added when the "remembered resume" feature shipped). Keep them as-is; only the envelope shape changes, not the codes, so that existing frontend check keeps working unmodified.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_routes_errors.py tests/test_errors.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add api/routes/resumes.py api/routes/jobs.py api/routes/analyses.py tests/test_routes_errors.py
git commit -m "feat(api): migrate routes to ApiError, rename codes to docs/errors.md's authoritative set"
```

---

### Task 3: Baseline fixture data — one worked example plus the generation rule for the other two

**Files:**
- Create: `data/fixtures/fresh_grad_strong_fit.baseline.json`
- Create: `data/fixtures/fresh_grad_stretch.baseline.json`
- Create: `data/fixtures/unrealistic.baseline.json`
- Test: `tests/test_baseline_fixtures.py`

**Interfaces:**
- Produces: three JSON files, each validating as `engine.normalize.schema.BaselineMatch`, each `results[]` entry's `requirement_id` matching one from the paired `Match` fixture's `job.requirements`.

**The rule** (apply this identically to derive the `stretch` and `unrealistic` baseline files from their paired `Match` fixtures — do not invent a different method per file):

For every requirement in the paired fixture's `job.requirements`, do a naive lowercase-token overlap between the requirement's `text` and the `source_line` (plus, for `r1`-style education/language requirements, the `resume.education`/free text) of the evidence the real `Match.results` entry cites — *not* the real verdict itself, the matcher does not get to see verdicts. Score = (shared distinctive tokens) / (a naive normalization), roughly:
- 2+ shared distinctive tokens (a real skill/domain word, not "a"/"the"/"and") → `proven`, `score` 0.55–0.9
- exactly 1 shared distinctive token, or a partial/substring match ("responsive" vs "mobile-friendly") → `partial`, `score` 0.3–0.45
- 0 shared tokens → `missing`, `score` 0.0, `matched_terms: []`

This mechanically **agrees** with the real verdict wherever the requirement's language is literally echoed in a resume line (e.g. "React" in the JD and "React" in a project bullet), and **disagrees downward** wherever the real engine's verdict came from inference the keyword matcher cannot do — non-work evidence counting as proof of "experience," soft-skill requirements inferred from GPA/project follow-through rather than named outright, an in-progress degree read charitably. That downward disagreement on the inference-dependent rows is the entire point of the comparison (`PROJECT_SPEC.md`'s evaluation chapter, `BaselineMatch`'s own docstring: "this exists to be beaten").

Compute the aggregate `coverage_score` with the same weighted formula as the real match (Global Constraints): proven = 1, partial = 0.5, missing = 0, required weight 1, preferred weight 0.5, as a percentage of total weight. The baseline's `coverage_score` should land **meaningfully below** the paired `Match.coverage_score` (roughly 15–25 points, not 0 and not equal — a baseline that always loses badly is not a credible comparison; one that ties is not a comparison at all).

**Worked example — `fresh_grad_strong_fit.baseline.json`**, applying the rule to `data/fixtures/fresh_grad_strong_fit.json`'s eleven requirements:

```json
{
  "coverage_score": 52.8,
  "method": "tfidf",
  "results": [
    { "requirement_id": "r1", "verdict": "partial", "score": 0.34, "matched_terms": ["bachelor", "information"] },
    { "requirement_id": "r2", "verdict": "proven", "score": 0.71, "matched_terms": ["html", "css"] },
    { "requirement_id": "r3", "verdict": "partial", "score": 0.38, "matched_terms": ["javascript"] },
    { "requirement_id": "r4", "verdict": "missing", "score": 0.11, "matched_terms": ["projects"] },
    { "requirement_id": "r5", "verdict": "proven", "score": 0.82, "matched_terms": ["english", "khmer"] },
    { "requirement_id": "r6", "verdict": "missing", "score": 0.0, "matched_terms": [] },
    { "requirement_id": "r7", "verdict": "proven", "score": 0.66, "matched_terms": ["object-oriented", "programming"] },
    { "requirement_id": "r8", "verdict": "proven", "score": 0.58, "matched_terms": ["react"] },
    { "requirement_id": "r9", "verdict": "missing", "score": 0.0, "matched_terms": [] },
    { "requirement_id": "r10", "verdict": "missing", "score": 0.0, "matched_terms": [] },
    { "requirement_id": "r11", "verdict": "partial", "score": 0.42, "matched_terms": ["responsive"] }
  ]
}
```

Check: required (`r1`–`r7`) weighted sum = 0.5+1+0.5+0+1+0+1 = 4.0 of 7 → preferred (`r8`–`r11`) weighted sum = 0.5·(1+0+0+0.5) = 0.75 of 2 → total (4.0+0.75)/9 = 52.8%, against the real match's 72.0% — an 19.2-point gap, driven by `r4` and `r6` (where the real engine credits inference-based evidence the keyword matcher cannot see) while `r9`/`r10` agree (both genuinely absent) and `r2`/`r5`/`r7`/`r8` agree (both catch a literal term match).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_baseline_fixtures.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.normalize.schema import BaselineMatch, Match

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"
FIXTURE_NAMES = ["fresh_grad_strong_fit", "fresh_grad_stretch", "unrealistic"]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_baseline_fixture_validates_against_schema(name: str) -> None:
    raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    baseline = BaselineMatch.model_validate(raw)
    assert baseline.method == "tfidf"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_baseline_requirement_ids_match_the_paired_fixture(name: str) -> None:
    match_raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    baseline_raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    match = Match.model_validate(match_raw)
    baseline = BaselineMatch.model_validate(baseline_raw)
    assert match.job is not None
    requirement_ids = {r.id for r in match.job.requirements}
    baseline_ids = {r.requirement_id for r in baseline.results}
    assert requirement_ids == baseline_ids


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_baseline_scores_meaningfully_below_the_real_match(name: str) -> None:
    match_raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    baseline_raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    match = Match.model_validate(match_raw)
    baseline = BaselineMatch.model_validate(baseline_raw)
    gap = match.coverage_score - baseline.coverage_score
    assert 10 <= gap <= 35, f"{name}: gap was {gap}, expected a credible 10-35 point gap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_baseline_fixtures.py -v`
Expected: FAIL with `FileNotFoundError` (baseline JSON files don't exist yet)

- [ ] **Step 3: Write the implementation**

Create `data/fixtures/fresh_grad_strong_fit.baseline.json` with exactly the worked example JSON above.

For `fresh_grad_stretch.baseline.json` and `unrealistic.baseline.json`: read the paired `data/fixtures/fresh_grad_stretch.json` and `data/fixtures/unrealistic.json`, apply the identical token-overlap rule per requirement, and hand-author the same three-field shape (`coverage_score`, `method: "tfidf"`, `results[]`). Keep the gap in the 10–35 point range the test enforces.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_baseline_fixtures.py -v`
Expected: PASS (9 tests: 3 fixtures × 3 assertions)

- [ ] **Step 5: Commit**

```bash
git add data/fixtures/*.baseline.json tests/test_baseline_fixtures.py
git commit -m "feat(data): add hand-authored TF-IDF baseline fixtures paired with the golden matches"
```

---

### Task 4: Wire baseline + a real failure path into the store and the analyses route

**Files:**
- Modify: `api/store.py`
- Modify: `api/routes/analyses.py`
- Test: `tests/test_analyses_baseline_and_retry.py` (baseline + failure assertions only — retry endpoint is Task 5)

**Interfaces:**
- Consumes: `data/fixtures/*.baseline.json` (Task 3), `ApiError`/envelope (Task 1–2).
- Produces: `Store.pick_baseline(job_id: str) -> BaselineMatch` (mirrors `pick_fixture`, same company-match-then-rotation logic, same `_rotation_index` so a given analysis's `match` and `baseline` are picked from the **same** fixture name — critical, since `run_baseline`'s own docstring requires "the same pair" for the comparison to mean anything). `AnalysisRecord` gains `baseline: BaselineMatch | None = None` and `error: dict | None = None`. `GET /api/analyses/{id}` response gains `"baseline": ...` and `"error": ...` keys.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analyses_baseline_and_retry.py
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.store import store

client = TestClient(app)


def _create_done_analysis() -> str:
    resume_id = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 41}).json()["job_id"]
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
    ).json()["analysis_id"]
    for _ in range(50):
        res = client.get(f"/api/analyses/{analysis_id}").json()
        if res["status"] == "done":
            return analysis_id
    raise AssertionError("mock analysis never finished")


def test_get_analysis_includes_a_baseline_from_the_same_fixture() -> None:
    analysis_id = _create_done_analysis()
    res = client.get(f"/api/analyses/{analysis_id}").json()
    assert res["baseline"] is not None
    assert res["baseline"]["method"] == "tfidf"
    match_requirement_ids = {r["id"] for r in res["match"]["job"]["requirements"]}
    baseline_requirement_ids = {r["requirement_id"] for r in res["baseline"]["results"]}
    assert match_requirement_ids == baseline_requirement_ids


def test_engine_failure_sets_status_failed_with_an_error_envelope() -> None:
    resume_id = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 41}).json()["job_id"]
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
    ).json()["analysis_id"]

    with patch("api.store.store.pick_fixture", side_effect=RuntimeError("boom")):
        for _ in range(50):
            res = client.get(f"/api/analyses/{analysis_id}").json()
            if res["status"] == "failed":
                break
        else:
            raise AssertionError("analysis never reached failed status")

    assert res["match"] is None
    assert res["error"]["code"] == "ENGINE_FAILED"
    assert "error_id" in res["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_analyses_baseline_and_retry.py -v`
Expected: FAIL — `res["baseline"]` key does not exist yet (`KeyError`); the failure path never sets `status: "failed"` today (the mock task has no `try`/`except`, `pick_fixture` never raises in real usage, and there is no `error` key at all).

- [ ] **Step 3: Write the implementation**

```python
# api/store.py — imports, JobRecord/AnalysisRecord, Store additions
from engine.normalize.schema import AnalysisStatus, BaselineMatch, Match, MatchStage
...
def _load_baseline_fixture(name: str) -> BaselineMatch:
    raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    return BaselineMatch.model_validate(raw)


_BASELINES: dict[str, BaselineMatch] = {
    name: _load_baseline_fixture(name) for name in _FIXTURE_ROTATION
}


@dataclass
class AnalysisRecord:
    id: str
    resume_id: str
    job_id: str
    country: str
    status: AnalysisStatus = "queued"
    stage: MatchStage | None = None
    match: Match | None = None
    baseline: BaselineMatch | None = None
    error: dict | None = None
```

Add to `Store` (same class the existing `pick_fixture` lives on), reusing the **same fixture name** logic so match and baseline never come from different fixtures:

```python
    def pick_fixture_name(self, job_id: str) -> str:
        """The fixture name `pick_fixture`/`pick_baseline` would each pick —
        factored out so a match and its baseline always come from the same
        fixture (run_baseline's contract: 'must be run on the same pair')."""
        job = self.jobs.get(job_id)
        text_lower = (job.raw if job else "").lower()
        for company, name in _FIXTURE_BY_COMPANY.items():
            if company in text_lower:
                return name
        name = _FIXTURE_ROTATION[self._rotation_index % len(_FIXTURE_ROTATION)]
        self._rotation_index += 1
        return name

    def pick_fixture(self, job_id: str) -> Match:
        return _FIXTURES[self.pick_fixture_name(job_id)]

    def pick_baseline(self, fixture_name: str) -> BaselineMatch:
        return _BASELINES[fixture_name]
```

`pick_fixture`'s signature is unchanged (still takes `job_id`) so nothing calling it today breaks; it now delegates to `pick_fixture_name` internally. Remove the old inline body, keep the two public methods.

```python
# api/routes/analyses.py — the background task and both handlers
import logging
import time

from api.errors import ApiError, new_error_id
...
logger = logging.getLogger("proofit.analyses")


async def _run_mock_analysis(analysis_id: str) -> None:
    record = store.analyses[analysis_id]
    record.status = "running"
    started_at = time.monotonic()
    per_stage = settings.mock_delay_seconds / len(STAGE_ORDER)
    try:
        for stage in STAGE_ORDER:
            record.stage = stage
            await asyncio.sleep(per_stage)
            logger.info(
                "analysis_stage analysis_id=%s stage=%s elapsed_ms=%d",
                analysis_id, stage, int((time.monotonic() - started_at) * 1000),
            )

        fixture_name = store.pick_fixture_name(record.job_id)
        record.match = store.pick_fixture(record.job_id)
        record.baseline = store.pick_baseline(fixture_name)
    except Exception as exc:  # noqa: BLE001 — this is the ENGINE_FAILED boundary, intentionally broad
        error_id = new_error_id()
        logger.warning(
            "analysis_failed analysis_id=%s error_id=%s message=%s", analysis_id, error_id, exc,
        )
        record.status = "failed"
        record.match = None
        record.baseline = None
        record.error = {"code": "ENGINE_FAILED", "message": str(exc), "error_id": error_id}
        return

    total_ms = int((time.monotonic() - started_at) * 1000)
    logger.info("analysis_done analysis_id=%s total_ms=%d", analysis_id, total_ms)
    if total_ms > 60_000:
        logger.warning(
            "analysis_slow analysis_id=%s total_ms=%d threshold_ms=60000", analysis_id, total_ms,
        )
    record.status = "done"
```

```python
@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    record = store.analyses.get(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")

    return {
        "status": record.status,
        "stage": record.stage,
        "match": record.match.model_dump(mode="json") if record.match else None,
        "baseline": record.baseline.model_dump(mode="json") if record.baseline else None,
        "error": record.error,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_analyses_baseline_and_retry.py tests/test_routes_errors.py -v`
Expected: PASS. Also re-run the full suite once: `python -m pytest -v` — `tests/test_fixtures.py` must still pass unchanged (baseline files are separate from the `Match` fixtures it validates).

- [ ] **Step 5: Commit**

```bash
git add api/store.py api/routes/analyses.py tests/test_analyses_baseline_and_retry.py
git commit -m "feat(api): serve the paired baseline alongside every analysis, add a real ENGINE_FAILED path"
```

---

### Task 5: Retry endpoint

**Files:**
- Modify: `api/store.py`
- Modify: `api/routes/analyses.py`
- Test: `tests/test_analyses_baseline_and_retry.py` (append)

**Interfaces:**
- Consumes: `AnalysisRecord` (Task 4), `ApiError`.
- Produces: `POST /api/analyses/{analysis_id}/retry -> {"analysis_id": str, "status": "queued"}`, same shape as `POST /api/analyses`. `Store.create_retry(original_id: str) -> AnalysisRecord | None` (`None` when `original_id` doesn't exist).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analyses_baseline_and_retry.py — append
def test_retry_creates_a_new_analysis_reusing_the_same_inputs() -> None:
    resume_id = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 41}).json()["job_id"]
    original_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "japan"},
    ).json()["analysis_id"]

    retry_res = client.post(f"/api/analyses/{original_id}/retry")
    assert retry_res.status_code == 202
    retry_body = retry_res.json()
    assert retry_body["analysis_id"] != original_id
    assert retry_body["status"] == "queued"

    retried = store.analyses[retry_body["analysis_id"]]
    original = store.analyses[original_id]
    assert retried.resume_id == original.resume_id
    assert retried.job_id == original.job_id
    assert retried.country == original.country


def test_retry_on_unknown_id_is_analysis_not_found() -> None:
    res = client.post("/api/analyses/an_doesnotexist/retry")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_analyses_baseline_and_retry.py -v -k retry`
Expected: FAIL with 404 (no such route exists yet)

- [ ] **Step 3: Write the implementation**

```python
# api/store.py — add to Store
    def create_retry(self, original_id: str) -> AnalysisRecord | None:
        original = self.analyses.get(original_id)
        if original is None:
            return None
        return self.create_analysis(original.resume_id, original.job_id, original.country)
```

```python
# api/routes/analyses.py — new route, after the existing GET handler
@router.post("/analyses/{analysis_id}/retry", status_code=202)
async def retry_analysis(analysis_id: str, background_tasks: BackgroundTasks) -> dict:
    record = store.create_retry(analysis_id)
    if record is None:
        raise ApiError(status_code=404, code="ANALYSIS_NOT_FOUND", message="Unknown analysis_id.")

    background_tasks.add_task(_run_mock_analysis, record.id)
    return {"analysis_id": record.id, "status": record.status}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_analyses_baseline_and_retry.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add api/store.py api/routes/analyses.py tests/test_analyses_baseline_and_retry.py
git commit -m "feat(api): add a retry endpoint that reuses the original resume/job/country"
```

---

### Task 6: Frontend API client — typed ApiError, baseline, error, retryAnalysis

**Files:**
- Modify: `web/lib/api.ts`

**Interfaces:**
- Consumes: the envelope shape from Tasks 1–2, the `baseline`/`error` fields from Task 4, the retry route from Task 5.
- Produces: `ApiError` gains `errorId?: string`. `AnalysisStatusResponse` gains `baseline: BaselineMatch | null` and `error: { code: string; message: string; error_id: string } | null`. `retryAnalysis(id: string): Promise<{ analysis_id: string; status: string }>`.

- [ ] **Step 1: Edit `web/lib/api.ts`**

```typescript
import type { BaselineMatch, Match } from "@/lib/types";

export class ApiError extends Error {
  code?: string;
  errorId?: string;

  constructor(message: string, code?: string, errorId?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.errorId = errorId;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let error: { code?: string; message?: string; error_id?: string } | undefined;
  try {
    const body = await res.json();
    error = body?.error;
  } catch {
    // Non-JSON error body — fall through to the generic message below.
  }
  return new ApiError(
    error?.message ?? `Request failed (${res.status})`,
    error?.code,
    error?.error_id,
  );
}
```

Update `AnalysisStatusResponse` and `getAnalysis`'s return type:

```typescript
export interface AnalysisStatusResponse {
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  match: Match | null;
  baseline: BaselineMatch | null;
  error: { code: string; message: string; error_id: string } | null;
}
```

Add, after `createAnalysis`:

```typescript
export async function retryAnalysis(
  id: string,
): Promise<{ analysis_id: string; status: string }> {
  const res = await fetch(`/api/analyses/${id}/retry`, { method: "POST" });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors. (No unit test runner exists — see Global Constraints. This file has no other callers yet in this task; Tasks 8, 9, 11, 12 exercise it.)

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(web): typed ApiError with error_id, baseline/error on analysis responses, retryAnalysis"
```

---

### Task 7: Error message catalogue (en.json + km.json)

**Files:**
- Modify: `web/messages/en.json`
- Modify: `web/messages/km.json`

**Interfaces:**
- Produces: `errors.RESUME_BAD_TYPE`, `errors.RESUME_TOO_LARGE`, `errors.RESUME_UNREADABLE`, `errors.JOB_EMPTY`, `errors.JOB_URL_BLOCKED`, `errors.JOB_FETCH_FAILED`, `errors.ANALYSIS_NOT_FOUND`, `errors.ENGINE_FAILED`, `errors.RATE_LIMITED`, `errors.INTERNAL` — all ten codes, even the six not reachable from mock mode yet, so the catalogue is complete when Phase 3/CP2 reach them. Also corrects `progress.timeoutAction` (was "Run the analysis again" — the *server*-failure recovery action; `docs/errors.md` §3 specifies the *client-timeout* action is "Keep waiting", a different state — see Task 12).

- [ ] **Step 1: Add the `errors` block to `web/messages/en.json`**, copying the English strings verbatim from `docs/errors.md` §2 (they're already written and reviewed there — don't rephrase):

```json
"errors": {
  "RESUME_BAD_TYPE": "This file type isn't supported. Please upload a PDF or DOCX file.",
  "RESUME_TOO_LARGE": "This file is larger than 5 MB. Try exporting your resume again at a smaller size.",
  "RESUME_UNREADABLE": "We couldn't read any text in this file. If it's a scan or a photo, upload a version where the text can be selected — export to PDF from Word or Google Docs.",
  "JOB_EMPTY": "We need the job post itself. Paste the job description text, or a link to it.",
  "JOB_URL_BLOCKED": "We can't open LinkedIn or Facebook links. Copy the job description text and paste it here instead — that works exactly the same.",
  "JOB_FETCH_FAILED": "We couldn't open that link. Copy the job description text and paste it here instead.",
  "ANALYSIS_NOT_FOUND": "We couldn't find this analysis. Results aren't saved permanently yet — start a new analysis to see fresh results.",
  "ENGINE_FAILED": "The analysis didn't finish. Try again — if it keeps failing, send us this error id.",
  "RATE_LIMITED": "Too many requests right now. Wait about a minute and try again.",
  "INTERNAL": "Something went wrong on our side. Try again — if it keeps happening, send us this error id."
}
```

Update `progress.timeoutAction` from `"Run the analysis again"` to `"Keep waiting"`, and add `progress.timeoutRetry`: `"Run the analysis again"` — Task 12 needs both labels for two different buttons in two different states.

- [ ] **Step 2: Mirror the identical block into `web/messages/km.json`**, copying the Khmer strings verbatim from `docs/errors.md` §2 (marked provisional there — that's expected; `docs/errors.md` §4 already schedules a Khmer-first review in Phase 5, this task is not that review). Use the same `progress.timeoutAction`/`progress.timeoutRetry` keys with English text, matching every other currently-untranslated key in this file (confirmed by `node scripts/i18n-check.mjs`: km.json is a complete English mirror today — this task follows that existing, consistent state, not a new inconsistency).

- [ ] **Step 3: Verify**

Run: `node scripts/i18n-check.mjs`
Expected: `0 error(s)` (warnings for untranslated km strings are expected and pre-existing — see Global Constraints and the i18n-check script's own doc comment).

- [ ] **Step 4: Commit**

```bash
git add web/messages/en.json web/messages/km.json
git commit -m "feat(web): add the errors.* i18n catalogue for all ten documented codes"
```

---

### Task 8: Wire per-code UI presentation on the Analyze form

**Files:**
- Modify: `web/components/analyze/ResumeDropzone.tsx`
- Modify: `web/components/analyze/JobPostPanel.tsx`
- Modify: `web/components/analyze/AnalyzeForm.tsx`

**Interfaces:**
- Consumes: `ApiError` (Task 6), `errors.*` (Task 7).
- Produces: `ResumeDropzoneProps` gains `serverError?: string | null`. `JobPostPanelProps` gains `error?: string | null`. `AnalyzeForm` routes `RESUME_BAD_TYPE`/`RESUME_TOO_LARGE` to the dropzone, `JOB_EMPTY` to the JD panel (and focuses the active tab's field), everything else to the existing bottom-of-form message.

- [ ] **Step 1: `ResumeDropzone.tsx`** — accept a second, server-side error alongside the existing client one, rendered the same way:

```typescript
export interface ResumeDropzoneProps {
  file: File | null;
  onChange: (file: File | null) => void;
  serverError?: string | null;
}

export function ResumeDropzone({ file, onChange, serverError }: ResumeDropzoneProps) {
  ...
  // in the two return branches, replace `{error ? ... : null}` with:
  {(error ?? serverError) ? (
    <p role="alert" className="text-sm text-missing">
      {error ?? serverError}
    </p>
  ) : null}
```

(Both branches — the "file selected" branch doesn't currently render an error at all; add the same block there too, since a server rejection arrives *after* a file is already selected and shown.)

- [ ] **Step 2: `JobPostPanel.tsx`** — add an `error` prop, rendered under the tab content, and an id-based focus so `AnalyzeForm` can move focus to the active field on `JOB_EMPTY`:

```typescript
export interface JobPostPanelProps {
  value: JobPostValue;
  onChange: (value: JobPostValue) => void;
  error?: string | null;
}

export function JobPostPanel({ value, onChange, error }: JobPostPanelProps) {
  ...
  return (
    <div>
      {/* existing tablist and textarea/input unchanged */}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-missing">
          {error}
        </p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 3: `AnalyzeForm.tsx`** — replace the single `error` state with per-field state and route by `err.code`:

```typescript
const [resumeError, setResumeError] = React.useState<string | null>(null);
const [jobError, setJobError] = React.useState<string | null>(null);
const [formError, setFormError] = React.useState<string | null>(null);
```

Remove the old `error`/`setError`. In `handleSubmit`, clear all three at the top (`setResumeError(null); setJobError(null); setFormError(null);`) instead of the single `setError(null)`. In the `catch` block:

```typescript
} catch (err) {
  if (err instanceof ApiError && err.code === "RESUME_NOT_FOUND") {
    clearRememberedResume();
    setRememberedResume(null);
  }
  const code = err instanceof ApiError ? err.code : undefined;
  const message =
    code && (["RESUME_BAD_TYPE", "RESUME_TOO_LARGE", "JOB_EMPTY"] as const).includes(
      code as "RESUME_BAD_TYPE" | "RESUME_TOO_LARGE" | "JOB_EMPTY",
    )
      ? te(code as "RESUME_BAD_TYPE" | "RESUME_TOO_LARGE" | "JOB_EMPTY")
      : err instanceof ApiError
        ? err.message
        : tc("error.generic");
  if (code === "RESUME_BAD_TYPE" || code === "RESUME_TOO_LARGE") {
    setResumeError(message);
  } else if (code === "JOB_EMPTY") {
    setJobError(message);
    document.getElementById(jobPost.mode === "text" ? "jd-text" : "jd-url")?.focus();
  } else {
    setFormError(message);
  }
  setSubmitting(false);
}
```

Add `const te = useTranslations("errors");` alongside the existing `t`/`tc` declarations at the top of the component. Pass the new props through and update the render's error paragraph:

```tsx
<ResumeDropzone file={file} onChange={setFile} serverError={resumeError} />
...
<JobPostPanel value={jobPost} onChange={setJobPost} error={jobError} />
...
{formError ? (
  <p role="alert" className="-mt-4 text-sm text-missing">
    {formError}
  </p>
) : null}
```

(This replaces the old single `{error ? ... : null}` block at the bottom — same JSX, renamed variable, plus the `!canSubmit && !submitting` hint paragraph above it is untouched.) `RESUME_NOT_FOUND` deliberately stays on the raw/generic (`formError`) path — it isn't one of the ten documented codes and already has its own handling (clearing the remembered resume) above.

- [ ] **Step 4: Verify**

Run: `cd web && npx tsc --noEmit && npx eslint components/analyze`
Expected: clean.

Manual check (no test runner — Global Constraints): run `uvicorn api.main:app --reload` and `npm run dev`, then on `/analyze`: (a) upload a `.txt` file renamed to end in nothing recognizable — confirm the inline dropzone error, not the bottom message; (b) paste `"   "` as JD text after bypassing the client 40-char gate via devtools (or temporarily lower the gate) — confirm the inline JD error and that focus lands in the textarea.

- [ ] **Step 5: Commit**

```bash
git add web/components/analyze/ResumeDropzone.tsx web/components/analyze/JobPostPanel.tsx web/components/analyze/AnalyzeForm.tsx
git commit -m "feat(web): route RESUME_BAD_TYPE/RESUME_TOO_LARGE/JOB_EMPTY errors to their inline field"
```

---

### Task 9: `ANALYSIS_NOT_FOUND` full-page state, and threading `baseline` through `ResultsById`

**Files:**
- Modify: `web/components/results/ResultsById.tsx`

**Interfaces:**
- Consumes: `ApiError` (Task 6), `errors.ANALYSIS_NOT_FOUND` (Task 7), the `baseline?: BaselineMatch | null` prop `ResultsView` gains in Task 10 (execute Task 10 immediately after this one, or the typecheck in Step 2 below stays red until it does — the two are sequenced separately only because they touch different files, not because either is independently shippable).
- Produces: `ResultsById` distinguishes a 404 (`ANALYSIS_NOT_FOUND`) from every other failure, per `docs/errors.md`'s recovery spec: "Full-page state... not a toast... Primary action returns to `/analyze`."

- [ ] **Step 1: Edit `ResultsById.tsx`**

```typescript
"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { ResultsView } from "@/components/results/ResultsView";
import { useRouter } from "@/i18n/routing";
import { ApiError, getAnalysis } from "@/lib/api";
import type { BaselineMatch, Match } from "@/lib/types";

export interface ResultsByIdProps {
  id: string;
}

export function ResultsById({ id }: ResultsByIdProps) {
  const t = useTranslations("common");
  const te = useTranslations("errors");
  const router = useRouter();
  const [match, setMatch] = React.useState<Match | null>(null);
  const [baseline, setBaseline] = React.useState<BaselineMatch | null>(null);
  const [notFound, setNotFound] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await getAnalysis(id);
        if (cancelled) return;
        if (res.status === "done" && res.match) {
          setMatch(res.match);
          setBaseline(res.baseline);
        } else if (res.status === "failed") {
          setError(res.error ? te(res.error.code as "ENGINE_FAILED") : t("error.generic"));
        } else {
          router.replace(`/progress?id=${id}`);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "ANALYSIS_NOT_FOUND") {
          setNotFound(true);
        } else {
          setError(t("error.generic"));
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [id, router, t, te]);

  if (notFound) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center">
        <p className="mb-6 text-ink-2">{te("ANALYSIS_NOT_FOUND")}</p>
        <Button as="a" href="/analyze" variant="primary">
          {t("action.back")}
        </Button>
      </div>
    );
  }

  if (error) {
    return <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-2">{error}</div>;
  }

  if (!match) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center text-ink-3">{t("loading")}</div>
    );
  }

  return <ResultsView match={match} baseline={baseline} />;
}
```

- [ ] **Step 2: Verify** (after Task 10 lands `baseline` on `ResultsView` — run these two tasks back-to-back)

Run: `cd web && npx tsc --noEmit`
Expected: clean.

Manual check: visit `/results?id=an_doesnotexist` — confirm the full-page "couldn't find this analysis" state with a working "Back" button to `/analyze`, not the generic loading/error text.

- [ ] **Step 3: Commit**

```bash
git add web/components/results/ResultsById.tsx
git commit -m "feat(web): distinct full-page state for ANALYSIS_NOT_FOUND, thread baseline through ResultsById"
```

---

### Task 10: Baseline comparison — sample data, toggle component, wiring

**Files:**
- Create: `web/lib/fixtures/sample-baseline.ts`
- Create: `web/components/results/BaselineToggle.tsx`
- Modify: `web/components/results/ResultsView.tsx`
- Modify: `web/components/results/ResultsInteractive.tsx`
- Modify: `web/app/[locale]/results/page.tsx`

**Interfaces:**
- Consumes: `BaselineMatch`/`BaselineResult` types (generated, unchanged), `results.baseline.toggle` (already in `en.json`/`km.json` — Global Constraints, don't recreate it).
- Produces: `ResultsViewProps` gains `baseline?: BaselineMatch | null`. `ResultsInteractiveProps` gains the same. `BaselineToggle` exports `{ shown: boolean; onToggle: () => void }` as a controlled pattern owned by `ResultsInteractive`.

- [ ] **Step 1: `web/lib/fixtures/sample-baseline.ts`** — apply the Task 3 rule to `sampleMatch`'s own requirements (read `web/lib/fixtures/sample-match.ts` in full for its `job.requirements` and `results` before writing this, the same way Task 3 read the JSON fixtures):

```typescript
import type { BaselineMatch } from "@/lib/types";

/**
 * Paired with `sampleMatch` (same requirement ids), built by the same
 * token-overlap rule as the mock-mode fixtures (data/fixtures/*.baseline.json)
 * — see docs/superpowers/plans/2026-09-14-phase-2-results-experience.md Task 3.
 */
export const sampleBaseline: BaselineMatch = {
  coverage_score: 0, // computed below from sampleMatch's own weighting
  method: "tfidf",
  results: [
    // one BaselineResult per sampleMatch.job.requirements entry, same rule as Task 3
  ],
};
```

(This file's exact numbers depend on `sample-match.ts`'s specific requirements/evidence, which this plan hasn't transcribed — apply the Task 3 rule directly against that file's content, the same way the three JSON fixtures were derived from their paired `Match` fixtures. Keep the same 10–35 point gap constraint from Task 3's test, checked manually here since there's no fixture test for the TS sample data.)

- [ ] **Step 2: `BaselineToggle.tsx`**

```typescript
"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/Button";

export interface BaselineToggleProps {
  shown: boolean;
  onToggle: () => void;
}

export function BaselineToggle({ shown, onToggle }: BaselineToggleProps) {
  const t = useTranslations("results");
  return (
    <Button
      type="button"
      variant={shown ? "secondary" : "ghost"}
      size="sm"
      onClick={onToggle}
      aria-pressed={shown}
    >
      {t("baseline.toggle")}
    </Button>
  );
}
```

- [ ] **Step 3: `ResultsView.tsx`** — thread the prop through:

```typescript
export interface ResultsViewProps {
  match: Match;
  baseline?: BaselineMatch | null;
}

export function ResultsView({ match, baseline }: ResultsViewProps) {
  ...
  return (
    ...
      <ResultsInteractive match={match} baseline={baseline} />
    ...
  );
}
```

(Add `import type { BaselineMatch } from "@/lib/types";` at the top, alongside the existing `Match` import.)

- [ ] **Step 4: `ResultsInteractive.tsx`** — add the toggle near the requirement list heading, and a muted baseline column in each `RequirementRow` when shown:

```typescript
export interface ResultsInteractiveProps {
  match: Match;
  baseline?: BaselineMatch | null;
}
```

Build a lookup once, alongside the existing `requirementById`/`evidenceById` memos:

```typescript
const baselineByRequirement = React.useMemo(() => {
  const map = new Map<string, BaselineResult>();
  for (const r of baseline?.results ?? []) map.set(r.requirement_id, r);
  return map;
}, [baseline?.results]);

const [showBaseline, setShowBaseline] = React.useState(false);
```

Thread `baselineResult={baselineByRequirement.get(result.requirement_id)}` and `showBaseline={showBaseline}` into each `RequirementRow` call, and accept both as new props on `RequirementRow`. In `RequirementRow`'s `summary`, right after the existing `ConfidenceBar`, add:

```tsx
{showBaseline && baselineResult ? (
  <Badge tone="muted" className="opacity-70">
    {t(`verdict.${baselineResult.verdict}`)}
  </Badge>
) : null}
```

Above the requirement-list `<h2>`, render the toggle when a baseline exists:

```tsx
{baseline ? (
  <div className="mb-4 flex items-center justify-between">
    <h2 className="font-serif text-2xl text-ink">{t("title")}</h2>
    <BaselineToggle shown={showBaseline} onToggle={() => setShowBaseline((s) => !s)} />
  </div>
) : (
  <h2 className="mb-2 font-serif text-2xl text-ink">{t("title")}</h2>
)}
```

(This replaces the existing standalone `<h2 className="mb-2 ...">{t("title")}</h2>` line.) Add the two new imports: `import { BaselineToggle } from "@/components/results/BaselineToggle";` and extend the existing type-only import line to include `BaselineMatch, BaselineResult`.

- [ ] **Step 5: `web/app/[locale]/results/page.tsx`**

```typescript
import { sampleBaseline } from "@/lib/fixtures/sample-baseline";
...
  return <ResultsView match={sampleMatch} baseline={sampleBaseline} />;
```

- [ ] **Step 6: Verify**

Run: `cd web && npx tsc --noEmit && npx eslint components/results app/[locale]/results`
Expected: clean.

Manual check: visit `/results` (no `?id=`, the sample path) — confirm the toggle appears, and toggling it shows a muted verdict badge next to each requirement row that sometimes disagrees with the real verdict.

- [ ] **Step 7: Commit**

```bash
git add web/lib/fixtures/sample-baseline.ts web/components/results/BaselineToggle.tsx web/components/results/ResultsView.tsx web/components/results/ResultsInteractive.tsx "web/app/[locale]/results/page.tsx"
git commit -m "feat(web): add the keyword-baseline comparison toggle to the results screen"
```

---

### Task 11: Evidence-type storytelling note ("how this counts")

**Files:**
- Modify: `web/components/results/ResultsInteractive.tsx`
- Modify: `web/messages/en.json`, `web/messages/km.json`

**Interfaces:**
- Produces: `results.evidence.howThisCounts` and `results.evidence.howThisCountsDetailed` i18n keys. `RequirementRow` shows the note whenever `result.verdict === "partial"` and at least one cited evidence record's `evidence_type` is not `"employment"`/`"internship"`.

- [ ] **Step 1: Add i18n keys** to `web/messages/en.json` under `results.evidence` (alongside the existing `from`/`why`/`missingReason`):

```json
"howThisCounts": "{evidenceType} — counts as partial evidence here, not proof of paid experience.",
"howThisCountsDetailed": "{evidenceType} ({detail}) — counts as partial evidence here, not proof of paid experience."
```

Mirror identically into `km.json` (same pattern as every other key in that file today — Global Constraints).

- [ ] **Step 2: Edit `RequirementRow` in `ResultsInteractive.tsx`** — inside the existing `evidenceRecords.map(...)` block, after the duration/team-size line, add:

```tsx
{result.verdict === "partial" &&
evidence.evidence_type !== "employment" &&
evidence.evidence_type !== "internship" ? (
  <p className="mt-2 text-[13px] leading-[1.5] text-ink-3">
    {evidence.duration_months || evidence.team_size
      ? t("evidence.howThisCountsDetailed", {
          evidenceType: t(`evidenceType.${evidence.evidence_type}`),
          detail: [
            evidence.duration_months ? `${evidence.duration_months} mo` : null,
            evidence.team_size ? `team of ${evidence.team_size}` : null,
          ]
            .filter(Boolean)
            .join(" · "),
        })
      : t("evidence.howThisCounts", {
          evidenceType: t(`evidenceType.${evidence.evidence_type}`),
        })}
  </p>
) : null}
```

This sits inside the same `evidenceRecords.map` as the existing duration/team-size paragraph, so it's per-evidence-record, matching BRAND.md §6's example register exactly ("Your class project (4 months, team of 4) counts as partial evidence...").

- [ ] **Step 3: Verify**

Run: `cd web && npx tsc --noEmit && node scripts/i18n-check.mjs`
Expected: both clean (0 i18n errors).

Manual check: on `/results` (sample path), expand a `partial` requirement row whose cited evidence is a `project`/`coursework`/etc. (not `employment`) — confirm the note renders with correct duration/team-size interpolation, and does **not** render for `proven`/`missing` rows or for employment-type evidence.

- [ ] **Step 4: Commit**

```bash
git add web/components/results/ResultsInteractive.tsx web/messages/en.json web/messages/km.json
git commit -m "feat(web): add the 'how this counts' note for non-work evidence on partial verdicts"
```

---

### Task 12: ProgressStepper — real 120s ceiling, distinct server-failure card, copyable error id, retry without re-upload

**Files:**
- Modify: `web/components/progress/ProgressStepper.tsx`

**Interfaces:**
- Consumes: `retryAnalysis` (Task 6), `errors.*` (Task 7), `progress.timeoutAction`/`progress.timeoutRetry` (Task 7), `common.action.copy`/`common.action.retry` (already exist — Global Constraints, confirmed present in the current i18n catalogue).
- Produces: three distinct states instead of one `failed` boolean — `activeIndex` (still going), `timedOut` (120 s client ceiling, offers "keep waiting" which resumes polling), `serverError` (status `"failed"` from the API, offers Retry via the new endpoint + copyable `error_id`).

- [ ] **Step 1: Full replacement of the component**

```typescript
"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { useRouter } from "@/i18n/routing";
import { getAnalysis, retryAnalysis } from "@/lib/api";
import { cn } from "@/lib/utils";

const STAGES = [
  "reading_resume",
  "reading_job",
  "matching_requirements",
  "checking_realism",
] as const;

const POLL_INTERVAL_MS = 2000;
const TIMEOUT_MS = 120_000;

export interface ProgressStepperProps {
  analysisId: string;
}

interface ServerErrorState {
  code: string;
  errorId: string;
}

/**
 * Polls `GET /api/analyses/{id}` every 2s and drives the stepper from the
 * real `stage` field. Three terminal states beyond "still going":
 *  - `timedOut`: 120s client ceiling reached while still queued/running, or
 *    a network hiccup that never resolved within that ceiling. Not a server
 *    error — the analysis may still finish — so the recovery action resumes
 *    polling rather than discarding anything (docs/errors.md §3).
 *  - `serverError`: the API reported `status: "failed"` with a typed error.
 *    Offers Retry (re-runs with the same resume_id/job_id, no re-upload)
 *    and a copyable error_id (docs/errors.md §2 ENGINE_FAILED).
 */
export function ProgressStepper({ analysisId }: ProgressStepperProps) {
  const t = useTranslations("progress");
  const te = useTranslations("errors");
  const tc = useTranslations("common");
  const router = useRouter();
  const [currentId, setCurrentId] = React.useState(analysisId);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const [timedOut, setTimedOut] = React.useState(false);
  const [serverError, setServerError] = React.useState<ServerErrorState | null>(null);
  const [retrying, setRetrying] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const startedAtRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    startedAtRef.current = Date.now();
    setTimedOut(false);
    setServerError(null);
    setActiveIndex(0);

    async function poll() {
      const elapsed = Date.now() - (startedAtRef.current ?? Date.now());
      try {
        const res = await getAnalysis(currentId);
        if (cancelled) return;

        if (res.status === "done") {
          setActiveIndex(STAGES.length);
          router.push(`/results?id=${currentId}`);
          return;
        }
        if (res.status === "failed") {
          setServerError({
            code: res.error?.code ?? "INTERNAL",
            errorId: res.error?.error_id ?? "",
          });
          return;
        }
        if (elapsed > TIMEOUT_MS) {
          setTimedOut(true);
          return;
        }

        const index = STAGES.indexOf(res.stage as (typeof STAGES)[number]);
        setActiveIndex(index >= 0 ? index : 0);
        setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (cancelled) return;
        if (elapsed > TIMEOUT_MS) {
          setTimedOut(true);
          return;
        }
        setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [currentId, router]);

  function keepWaiting() {
    startedAtRef.current = Date.now();
    setTimedOut(false);
  }

  async function retry() {
    setRetrying(true);
    try {
      const { analysis_id } = await retryAnalysis(currentId);
      setCurrentId(analysis_id);
      setServerError(null);
    } catch {
      // Retry itself failed (e.g. the original analysis is gone server-side)
      // — leave the error card up; the user can navigate back to /analyze.
    } finally {
      setRetrying(false);
    }
  }

  async function copyErrorId() {
    if (!serverError?.errorId) return;
    try {
      await navigator.clipboard.writeText(serverError.errorId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — nothing to do; the id is still visible as text.
    }
  }

  if (serverError) {
    const knownCodes = [
      "RESUME_UNREADABLE",
      "JOB_FETCH_FAILED",
      "ENGINE_FAILED",
      "RATE_LIMITED",
      "INTERNAL",
    ] as const;
    const message = (knownCodes as readonly string[]).includes(serverError.code)
      ? te(serverError.code as (typeof knownCodes)[number])
      : te("INTERNAL");

    return (
      <div className="grid gap-4">
        <p className="text-sm leading-[1.6] text-missing">{message}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={retry}
            loading={retrying}
          >
            {tc("action.retry")}
          </Button>
          {serverError.errorId ? (
            <button
              type="button"
              onClick={copyErrorId}
              className="font-mono text-xs text-ink-3 underline decoration-rule underline-offset-2 hover:decoration-ink"
            >
              {copied ? tc("action.copy") + " ✓" : `${serverError.errorId} · ${tc("action.copy")}`}
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (timedOut) {
    return (
      <div className="grid gap-4">
        <p className="text-sm leading-[1.6] text-ink-2">{t("timeout")}</p>
        <div className="flex flex-wrap gap-3">
          <Button type="button" variant="secondary" size="sm" onClick={keepWaiting}>
            {t("timeoutAction")}
          </Button>
          <Button as="a" href="/analyze" variant="ghost" size="sm">
            {t("timeoutRetry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <ol className="grid gap-1">
      {STAGES.map((stage, i) => {
        const isDone = i < activeIndex;
        const isActive = i === activeIndex;
        return (
          <li key={stage} className="flex items-center gap-3 py-2">
            <span
              className={cn(
                "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-pill border-[1.5px]",
                isDone && "border-ink bg-ink text-paper",
                isActive && "border-lac border-t-transparent animate-spin",
                !isDone && !isActive && "border-rule",
              )}
            >
              {isDone ? (
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="m5 12 4 4 10-10" />
                </svg>
              ) : null}
            </span>
            <span
              className={cn(
                "text-[15px] leading-[1.6]",
                isDone || isActive ? "font-medium text-ink" : "text-ink-3",
              )}
            >
              {t(`stage.${stage}`)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 2: Verify**

Run: `cd web && npx tsc --noEmit && npx eslint components/progress`
Expected: clean.

Manual check, three scenarios against the mock API: (a) normal flow still reaches `/results` (unaffected); (b) temporarily set `TIMEOUT_MS = 100` and confirm the "keep waiting" card appears and "keep waiting" resumes polling without navigating away, then revert the constant; (c) monkeypatch `api/store.py`'s `pick_fixture` to raise (as in Task 4's test, but by hand in a local run) and confirm the error card shows a message, a working Retry that lands on a fresh `analysis_id` and (assuming the monkeypatch is reverted before retrying) completes normally, and a copy button that copies the `error_id`.

- [ ] **Step 3: Commit**

```bash
git add web/components/progress/ProgressStepper.tsx
git commit -m "feat(web): real 120s timeout distinct from server failure, retry without re-upload, copyable error id"
```

---

### Task 13: Close out `docs/errors.md`'s Phase 2 checklist honestly

**Files:**
- Modify: `docs/errors.md`

- [ ] **Step 1:** Check off what this plan actually shipped, and be precise about what's still blocked:

```markdown
### Phase 2 checklist

- [x] Add `errors.*` keys for all ten codes to `web/messages/en.json` and `web/messages/km.json`.
- [x] Add a typed `ApiError` in `web/lib/api.ts` that surfaces `code` (and `error_id`) to callers.
- [x] Map every *mock-mode-reachable* code to a UI presentation: `RESUME_BAD_TYPE`/`RESUME_TOO_LARGE` inline under the dropzone, `JOB_EMPTY` inline under the JD tabs, `ANALYSIS_NOT_FOUND` full-page, `ENGINE_FAILED` as an error card with Retry + copyable error_id.
- [ ] **Force each of the ten failures deliberately and screenshot both locales.** Done for the four reachable in mock mode today: `RESUME_BAD_TYPE` (upload a `.txt`), `RESUME_TOO_LARGE` (upload a >5MB file), `JOB_EMPTY` (submit blank/neither/both), `ANALYSIS_NOT_FOUND` (hand-edit an id), `ENGINE_FAILED` (tests/test_analyses_baseline_and_retry.py's monkeypatch demonstrates the path; a manual screenshot still needs taking). **Still blocked:** `RESUME_UNREADABLE` (mock mode doesn't parse file content at all — needs Person A's normalizer), `JOB_URL_BLOCKED`/`JOB_FETCH_FAILED` (URL fetching is Phase 3 scope, `PERSON_B_PLAN_v2.md` §5 Phase 3.1), `RATE_LIMITED` (only reachable against the real Anthropic API, CP2).
- [ ] Re-word `ANALYSIS_NOT_FOUND` after Supabase persistence lands at CP2.
- [ ] Confirm every message obeys the `BRAND.md` §6 voice rules — no blame, no jargon, and a concrete next action in every single one. *(English strings were copied verbatim from this document's own §2, which was already written to that standard — this line is asking for a second read with fresh eyes before the Phase 5 Khmer QA session, not a rewrite.)*
```

- [ ] **Step 2: Commit**

```bash
git add docs/errors.md
git commit -m "docs: close out the Phase 2 error-matrix checklist against what actually shipped"
```

---

## Self-Review

**Spec coverage** — `PERSON_B_PLAN_v2.md` §5 Phase 2:
- Task 1 (Results view): baseline toggle → Task 10. Everything else in task 1 (header, gauges, grouped list, priority rail) already shipped in Phase 1 (`ResultsView.tsx`, `CoverageStat.tsx`, `ResultsInteractive.tsx` — verified by reading them; not re-planned here).
- Task 2 (evidence-type storytelling) → Task 11.
- Task 3 (async job UX / stepper / 120s timeout) → Task 12.
- Task 4 (error handling matrix) → Tasks 1, 2, 6, 7, 8, 9, 13.
- Task 5 (wire live engine) → explicitly out of scope, see Global Constraints.
- Task 6 (performance guardrail) → Task 4 (stage-timing + slow-analysis log lines).
- Task 7 (deploy live mode) → explicitly out of scope, see Global Constraints.

**Placeholder scan** — the only intentionally-incomplete spots are Task 3's `stretch`/`unrealistic` baseline files and Task 10's `sample-baseline.ts`, each of which gets one fully worked example plus an exact, mechanical rule and a test that enforces the invariant that matters (requirement-id parity, a 10–35 point gap) — this is a data-generation rule, not a vague instruction; see the "No Placeholders" discussion inline at Task 3.

**Type/name consistency** — `ApiError.code`/`errorId` (Task 6) matches every consumer (Tasks 8, 9, 12). `AnalysisStatusResponse.baseline`/`.error` (Task 6) matches the server shape from Task 4. `store.pick_fixture_name` (Task 4) is the single source of truth both `pick_fixture` and `pick_baseline` key off, so a match and its baseline can never diverge. `retryAnalysis` (Task 6) matches the route added in Task 5. `results.baseline.toggle` (pre-existing) is reused, not recreated, in Task 10.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-14-phase-2-results-experience.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
