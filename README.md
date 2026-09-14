# Proofit

**Prove your fit** · បញ្ជាក់ភាពសក្តិសមរបស់អ្នក

Requirement coverage analysis for Cambodian entry-level candidates. Proofit reads a
job post and a resume, normalizes both into one schema, and returns a verdict —
**proven**, **partial**, or **missing** — for every single requirement, each one
citing the exact resume line that justifies it. It never invents experience, and it
treats coursework, class projects, and part-time work as real evidence, because that
is what a fresh graduate in Phnom Penh actually has.

AUPP Final Year Project, 2026.

## Layout

| Path | What |
|---|---|
| `web/` | Next.js 15 frontend (bilingual `en`/`km`) |
| `api/` | FastAPI service — routes, config, in-memory store |
| `engine/` | The analysis engine: normalize → match → rewrite, importable, no web code |
| `data/` | Fixtures, collected job descriptions, anonymized resumes |
| `deploy/` | Docker Compose, Render blueprint, the deployment runbook |
| `scripts/` | Schema/type generation, i18n parity check |
| `tests/`, `eval/` | Automated tests and the human evaluation protocol |

See `PROJECT_SPEC.md` for the product spec, `PERSON_B_PLAN_v2.md` for the build plan
and ownership split, and `BRAND.md` for naming, color, and voice.

## Running it locally

```bash
./scripts/dev.sh
```

Starts the FastAPI backend (`:8000`) and the Next.js frontend (`:3000`) together.
Open `http://localhost:3000`. See `deploy/runbook.md` for the Docker Compose
alternative and the full deployment guide (Vercel + Render).
