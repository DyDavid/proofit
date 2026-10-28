# Proofit

**Prove your fit** · បញ្ជាក់ភាពសក្តិសមរបស់អ្នក

Requirement coverage analysis for Cambodian entry-level candidates. Proofit reads a
job post and a resume, normalizes both into one schema, and returns a verdict —
**proven**, **partial**, or **missing** — for every requirement, each one citing the
resume line that justifies it. It never invents experience, and it treats coursework,
class projects, and part-time work as real evidence, because that is what a fresh
graduate in Phnom Penh actually has.

AUPP Final Year Project, 2026.

## Stack

| Layer | What is actually used |
|---|---|
| Frontend | Next.js 15 (App Router) · React 19 · TypeScript (strict) · Tailwind CSS 4 — **English only** |
| API | FastAPI · pydantic-settings · `BackgroundTasks` for async analyses |
| Engine | Importable Python package (`engine/`) · Pydantic v2 schema |
| LLM | Google Gemini via `google-genai` (default model `gemini-3.1-flash-lite`; embeddings `gemini-embedding-001`, 768-d) |
| Baseline | Hand-rolled TF-IDF cosine keyword matcher (`engine/match/baseline.py`) |
| Parsing | `pdfminer.six` (PDF) · `python-docx` (DOCX) · `httpx` (URL fetch) |
| Storage | Supabase (PostgreSQL + pgvector) when configured, in-memory fallback otherwise |
| Hosting | Vercel (web) · Render free tier, Singapore (API, Docker) |

## Layout

| Path | What |
|---|---|
| `web/` | Next.js frontend — Landing, Analyze, Progress, Results, About |
| `api/` | FastAPI service — routes, settings, error envelope, store (Supabase + memory) |
| `engine/` | The analysis engine: ingest → normalize → match → rewrite, plus country rules. No web code. |
| `data/` | Golden fixtures, collected job descriptions, anonymized resumes, Supabase schema |
| `deploy/` | Docker Compose, Render blueprint, deployment runbook, pgvector schema |
| `scripts/` | Dev launchers, JSON Schema → TypeScript type generation, seeding, smoke tests |
| `tests/` | pytest suite (API, engine, rewrite validator, fixtures) |
| `eval/` | Evaluation harness — pair runner, Cohen's kappa analysis, consent form |
| `docs/` | Error contract (`errors.md`), progress log, phase plans |

See [`PROJECT_SPEC.md`](PROJECT_SPEC.md) for the product and technical spec,
[`engine/README.md`](engine/README.md) for the engine contract,
[`docs/errors.md`](docs/errors.md) for the API error codes, and
[`BRAND.md`](BRAND.md) for naming, colour, and voice.

## Running it locally

Prerequisites: Python 3.12+, Node 20+, and a virtualenv at `.venv`.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[api,parse,dev]"      # Windows: .venv\Scripts\pip ...
cd web && npm install && cd ..
cp .env.example .env                              # then fill in values (see below)
```

Start both servers:

| OS | Command | Frontend | API |
|---|---|---|---|
| macOS / Linux | `./scripts/dev.sh` | http://localhost:3000 | http://localhost:8000 |
| Windows | `dev.cmd` (runs `scripts/dev.ps1`) | http://localhost:3001 | http://localhost:8000 |

The browser only talks to its own origin: `web/next.config.ts` rewrites `/api/*` to
`NEXT_PUBLIC_API_URL` (default `http://localhost:8000`), so there is no CORS setup.

Docker alternative (API in mock mode, no keys needed):

```bash
docker compose -f deploy/docker-compose.yml up --build
```

## Configuration

All variables are documented in [`.env.example`](.env.example).

| Variable | Purpose |
|---|---|
| `ENGINE_MODE` | `mock` (default) returns golden fixtures after `MOCK_DELAY_SECONDS`; `live` calls Gemini |
| `GEMINI_API_KEY` | Required for `live`, and for F5 rewrites in **either** mode |
| `GEMINI_MODEL` | Default `gemini-3.1-flash-lite` (`GEMINI_EXTRACT_MODEL` / `GEMINI_ANALYSIS_MODEL` override per stage) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Optional persistence; ignored in mock mode |
| `MAX_UPLOAD_BYTES` | Resume upload ceiling (default 5 MB) |
| `NEXT_PUBLIC_API_URL` | Where the Next.js rewrite sends `/api/*` |

## API at a glance

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness, engine mode, version |
| `POST /api/resumes` | Upload PDF/DOCX → `resume_id` |
| `POST /api/jobs` | `{text}` or `{url}` → `job_id`, `cached` (content-hash dedupe) |
| `POST /api/jobs/fetch-url` | Fetch a job URL and return its text (preview helper) |
| `POST /api/analyses` | `{resume_id, job_id, country}` → `analysis_id` (202, runs in background) |
| `GET /api/analyses/{id}` | Poll status, stage, `match`, `baseline` |
| `GET /api/analyses?resume_id=` | History for one resume |
| `POST /api/analyses/{id}/retry` | Re-run with the same inputs |
| `POST /api/analyses/{id}/rewrites` | F5 hidden strengths + validated rewrites |
| `GET /api/countries`, `GET /api/countries/{dest}` | F6 destination resume conventions |

Every error uses one envelope: `{"error": {"code", "message", "error_id"}}`.

## Checks

```bash
pytest                       # Python tests (forced into mock mode by tests/conftest.py)
ruff check .                 # lint
cd web && npx tsc --noEmit   # typecheck
bash scripts/gen-types.sh    # regenerate web/lib/types.ts from engine/normalize/schema.py
```

CI (`.github/workflows/ci.yml`) runs ruff + pytest, a Docker-extras import check,
the web typecheck + build, and fails if `web/lib/types.ts` is stale against the schema.

## Deployment

Web on Vercel, API on Render (`deploy/render.yaml`, Docker, `ENGINE_MODE=mock` by
default). `.github/workflows/keepalive.yml` pings `/api/health` to keep the free
instance warm. Full guide: [`deploy/runbook.md`](deploy/runbook.md).
