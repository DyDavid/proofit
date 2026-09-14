# Proofit — Deployment Runbook

> Prove your fit · បញ្ជាក់ភាពសក្តិសមរបស់អ្នក
>
> Everything needed to stand the stack up, keep it awake, and survive a demo.
> Source of truth: `PERSON_B_PLAN_v2.md` §8. Owner: Person B.

**Topology.** Two halves, two platforms, one contract.

```
                 browser
                    │
                    │  https://<your-domain>            (all requests, incl. /api/*)
                    ▼
        ┌───────────────────────┐
        │  Vercel               │   Next.js 15, root directory `web`
        │  proofit (web)        │   next.config.ts rewrites /api/:path*
        └───────────┬───────────┘        → ${NEXT_PUBLIC_API_URL}/api/:path*
                    │  server-side fetch (no CORS, no second origin)
                    ▼
        ┌───────────────────────┐
        │  Render (free)        │   FastAPI, Docker, region singapore
        │  proofit-api          │   health: /api/health
        └───────────┬───────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
    Anthropic API        Supabase (free)
```

The browser never holds a key and never talks to Supabase or Anthropic. That is
the whole security story, and it is worth one sentence at the defense.

---

## 1. Local development

Prerequisites: Docker Desktop running, repo cloned. Nothing else — no Node, no
Python, no keys.

```bash
cd /Users/macbook/AUPP_FALL_2026/FYP

# Validate the compose file without starting anything (safe at any time).
docker compose -f deploy/docker-compose.yml config

# Build and run both services.
docker compose -f deploy/docker-compose.yml up --build

# In a second terminal — the two acceptance checks from §5 Phase 0 task 3:
curl -s http://localhost:8000/api/health      # → {"status":"ok","engine_mode":"mock",...}
open http://localhost:3000                    # → bilingual landing shell, locale switcher

# Follow logs / stop / wipe.
docker compose -f deploy/docker-compose.yml logs -f api
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml down -v --rmi local
```

Compose runs the API in **mock mode**: every analysis returns a fixture from
`data/fixtures/` after `MOCK_DELAY_SECONDS`, so no Anthropic key is burned and
no Supabase row is written while screens are being built. `../data` is bind
mounted read-only, so editing a fixture takes effect on the next request with no
rebuild.

**Running without Docker** (faster inner loop, and the only way to exercise
`ENGINE_MODE=live` locally):

```bash
# Terminal 1 — API
cd /Users/macbook/AUPP_FALL_2026/FYP
cp .env.example .env          # then fill in real values; .env is gitignored
.venv/bin/python -m uvicorn api.main:app --reload --port 8000

# Terminal 2 — web
cd /Users/macbook/AUPP_FALL_2026/FYP/web
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Note the hostname difference and why it is not a bug:

| Who is asking | Correct API address | Why |
|---|---|---|
| Browser on your host | `http://localhost:8000` | published container port / local uvicorn |
| Next.js **server** inside Compose | `http://api:8000` | Docker DNS resolves the service name on the Compose network |
| Next.js **server** on Vercel | `https://<service>.onrender.com` | public URL |
| Browser, in every environment | **its own origin**, `/api/...` | `next.config.ts` rewrites it server-side |

`NEXT_PUBLIC_*` is inlined into the client bundle **at build time**, so
`web/Dockerfile` deliberately builds with `NEXT_PUBLIC_API_URL=""`. Client code
then falls back to the relative `/api/...` path and the Next server proxies it.
Baking `http://api:8000` into the bundle would ship a hostname no browser can
resolve.

---

## 2. Vercel setup (the `web` half)

1. **Import.** Vercel → Add New → Project → import the GitHub repo.
2. **Root Directory: `web`.** This is the one setting people get wrong. It is a
   monorepo; without it Vercel builds the repository root, finds no
   `package.json`, and fails.
3. Framework preset: **Next.js** (auto-detected). Build command, output
   directory and install command: leave on defaults.
4. **Environment Variables** (Settings → Environment Variables), set for
   Production, Preview *and* Development:

   | Key | Value | Note |
   |---|---|---|
   | `NEXT_PUBLIC_API_URL` | `https://proofit-api.onrender.com` | the Render service URL, **no trailing slash** |
   | `NEXT_TELEMETRY_DISABLED` | `1` | optional, quieter builds |

   No Anthropic or Supabase key ever goes into Vercel. If one is there, it is in
   the browser bundle — rotate it.
5. **Domain.** Settings → Domains → add the domain, follow the DNS records
   Vercel prints. Vercel issues the TLS certificate automatically.
6. **Preview deploys** are on by default: every pull request gets its own URL.
   Preview builds inherit the same `NEXT_PUBLIC_API_URL`, so they point at the
   one production API — which is intentional on a free plan.
7. Verify: open the deployment URL, switch `en ⇄ km` in the header, then check
   that `https://<vercel-url>/api/health` returns the API's JSON (that proves the
   rewrite is wired, not just the page).

**`output: 'standalone'` and Vercel.** `web/next.config.ts` sets it for the
Docker image. Vercel ignores the setting and uses its own build output — it is
safe to leave on.

---

## 3. Render setup (the `api` half)

**Option A — Blueprint (preferred).** Render → New → Blueprint → select the repo.
Render reads `deploy/render.yaml`, shows the service and prompts for every
`sync: false` variable. Fill them in and create.

**Option B — manual**, if the Blueprint importer misbehaves:

1. New → **Web Service** → connect the repo.
2. Runtime **Docker**. Dockerfile path `./api/Dockerfile`, Docker build context
   **`.`** (the repository root, *not* `./api` — the image installs the `engine`
   package and needs the root `pyproject.toml` and `engine/`).
3. Region **Singapore**. Instance type **Free**. Branch `main`. Auto-Deploy on.
4. Health Check Path **`/api/health`**.
5. Environment variables:

   | Key | Value | Secret? |
   |---|---|---|
   | `ENGINE_MODE` | `mock` → `live` at CP2 | no |
   | `ANTHROPIC_API_KEY` | *(paste)* | **yes** |
   | `SUPABASE_URL` | `https://<ref>.supabase.co` | **yes** |
   | `SUPABASE_SERVICE_KEY` | *(paste)* | **yes** |
   | `CORS_ORIGINS` | `https://<your-domain>,https://*.vercel.app,http://localhost:3000` | no |
   | `APP_VERSION` | `0.1.0` | no |
   | `MAX_UPLOAD_BYTES` | `5242880` | no |
   | `MOCK_DELAY_SECONDS` | `1.5` | no |

   **Do not set `PORT`.** Render injects it; `api/Dockerfile` binds uvicorn to
   `0.0.0.0:$PORT`. Hardcoding it produces "no open ports detected" and the
   deploy hangs.
6. Verify: `curl -s https://proofit-api.onrender.com/api/health`.
7. Copy that URL into Vercel's `NEXT_PUBLIC_API_URL` and redeploy the web app.

**Custom domain on Render.** If the free plan still allows it the day you sign
up, add `api.<your-domain>` and update `NEXT_PUBLIC_API_URL` accordingly.
Otherwise the `*.onrender.com` URL is fine — users never see it.

---

## 4. Supabase setup

1. New project, region **Southeast Asia (Singapore)**.
2. SQL editor: `create extension if not exists vector;` before any embedding
   column exists (`PROJECT_SPEC.md` §7).
3. Copy Project URL and the **service_role** key into Render only.
4. The free project **pauses after ~1 week of inactivity**. The weekly job in
   `.github/workflows/keepalive.yml` exists solely to prevent that. Check the
   dashboard says *Active* before any demo.

---

## 5. Keep-alive

`.github/workflows/keepalive.yml` runs two jobs:

| Job | Schedule | Purpose |
|---|---|---|
| `ping-render` | `*/10 * * * *` | keeps the Render free instance out of its ~15 min idle sleep |
| `ping-supabase` | weekly, Monday | keeps the Supabase free project from pausing |

Configuration is a **repository variable**, not a secret (a health URL is public):

- GitHub → Settings → Secrets and variables → Actions → **Variables** → New
- `KEEPALIVE_URL` = `https://proofit-api.onrender.com/api/health`
- optional `SUPABASE_PING_URL` — point it at a DB-touching endpoint once one
  exists; it falls back to `KEEPALIVE_URL`.

Both jobs **fail softly**: an unreachable API turns the run into a notice, not a
red ✗. A permanently red keep-alive badge trains you to ignore CI, which is the
actual risk.

**GitHub throttles scheduled workflows on low-activity repositories** — a
`*/10` cron can silently degrade to hourly, or stop entirely after 60 days
without a push. Treat it as best-effort and add a free backup pinger at
[cron-job.org](https://cron-job.org) hitting the same URL every 10 minutes
(`PERSON_B_PLAN_v2.md` §8.4). Belt and braces cost nothing here.

---

## 6. Free-tier limits to design around

| Platform | Limit | Consequence | Mitigation |
|---|---|---|---|
| Render free | sleeps after **~15 min** idle | first request takes **30–60 s** | keep-alive workflow + cron-job.org + pre-demo warm-up |
| Render free | **~512 MB RAM** | a local embedding model OOMs the service | embeddings via API, never a local model — raise with Person A at CP2 |
| Render free | slow cold builds | a push before a demo can leave you mid-build | freeze deploys on demo day; deploy the night before |
| Render free | limited monthly instance hours | service can stop late in the month | check the dashboard in Week 12 and again in Week 15 |
| Vercel free | short serverless function timeout | fine — all heavy work is on Render; Next.js only renders and proxies | async job pattern (§5 Phase 1 task 4) |
| Vercel free | non-commercial use only | a student FYP qualifies | do not put ads on it |
| Supabase free | pauses after **~1 week** idle | the demo dies the morning of | weekly ping job + check the dashboard |
| Supabase free | 500 MB database | irrelevant at our scale | — |
| Anthropic API | per-minute rate limits | a burst during the demo returns 429 | content-hash cache; demo mode needs zero LLM calls |
| GitHub Actions | throttles cron on quiet repos | keep-alive degrades silently | cron-job.org backup |

Long LLM runs are handled by the async job pattern, not by raising timeouts:
`POST /api/analyses` returns `202 {"analysis_id","status":"queued"}` immediately
and the browser polls `GET /api/analyses/{id}`. Nothing ever waits on a single
HTTP request.

**If the budget ever allows $7/month:** upgrade Render to the Starter plan and
delete the keep-alive workflow. Nothing else changes.

---

## 7. Pre-demo warm-up

Run this **15–30 minutes** before any presentation, proposal defense or final
defense. It takes about three minutes.

```bash
API=https://proofit-api.onrender.com

# 1. Wake Render and time the cold start. First call may take 30-60 s.
time curl -s -o /dev/null -w '%{http_code} in %{time_total}s\n' "$API/api/health"

# 2. Hit it again — must now be well under a second.
curl -s "$API/api/health"
#    Expect: {"status":"ok","engine_mode":"live","version":"1.0.0","uptime_seconds":…}
#    Check engine_mode is what you intend to demo.

# 3. Wake the web half and confirm the rewrite proxy works end to end.
curl -s https://<your-domain>/api/health
```

Then, in the browser:

1. Open the site. Click **Try a sample** — this must render a full result with
   zero uploads and zero LLM calls.
2. Run **one real analysis** (a real resume + a real JD) all the way to results.
   This is what actually proves Anthropic, Supabase and the engine are alive.
3. Open the Render dashboard → Logs, and confirm your request appears there.
4. Open the Supabase dashboard and confirm the project shows **Active**, not
   Paused. If paused, click Restore and wait for it to come back — this can take
   a couple of minutes, which is exactly why this happens 30 minutes early.
5. Switch the locale to **km** and back. Check the Khmer glyphs are not clipped.
6. **Leave the results tab open.** A warm tab is your fastest fallback.
7. Do not push to `main` after this point. Auto-deploy would rebuild the service
   and hand you a cold start on stage.

---

## 8. If Render is asleep (or dead) during a demo

Escalate in order. Do not skip to the bottom — each step is faster than the next.

**1. It is just cold (most likely).** The first request is 30–60 s. Say out
loud: *"free tier, the service is waking — this is the trade-off we documented."*
That is a competent answer, not an excuse. Keep talking; it will come up.

**2. Force a wake and watch it.**

```bash
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' \
  https://proofit-api.onrender.com/api/health
```

Repeat until it returns `200`. Render's dashboard Logs tab shows the boot.

**3. Switch to demo mode on the deployed site.** `?demo=1`, or the **Try a
sample** button on the landing page, renders a fixture analysis with no API call
on the critical path. The results screen — the thing the examiner is there to
see — is fully intact.

**4. Switch to the laptop.** Have this already running, before the session
starts, on a second desktop:

```bash
cd /Users/macbook/AUPP_FALL_2026/FYP
docker compose -f deploy/docker-compose.yml up --build   # ENGINE_MODE=mock
# → http://localhost:3000
```

Mock mode needs no network beyond the laptop itself. This survives a dead venue
Wi-Fi, which is the failure that actually happens.

**5. Play the screen recording.** A 3-minute recorded run-through, exported to
the laptop (not streamed), is the last resort. Test all four fallbacks the day
before — a fallback you have not run is not a fallback.

**Render service failing to start at all?** Dashboard → Logs, then check in this
order: (a) a missing `sync: false` env var — the app raises on boot; (b) `PORT`
manually set, giving "no open ports detected"; (c) an OOM kill at ~512 MB, which
means a heavy import crept into `engine/`; (d) a Docker build failure, usually a
build context set to `./api` instead of `.`.

---

## 9. Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | What it guards |
|---|---|
| `python` | `ruff check` + `pytest` — engine and API correctness |
| `web` | `tsc --noEmit`, `next build`, and `scripts/i18n-check.mjs` (fails on any key present in `en.json` but missing from `km.json`, or vice versa) |
| `types` | regenerates `web/lib/types.ts` via `scripts/gen-types.sh` and fails if it differs from what is committed |

The `types` job is the schema-drift guard from `PERSON_B_PLAN_v2.md` §5 Phase 1
task 2: `web/lib/types.ts` is **generated** from `engine/normalize/schema.py` and
must never be hand-edited. When it fails, the fix is to run the generator and
commit the result — and, if a screen breaks, to change the fixture, not the UI.

---

## 10. Secrets policy

- `.env` is gitignored. Only `.env.example` is committed, and it contains
  placeholders only.
- Real values live in exactly two places: **Render → Environment** (all secrets)
  and **Vercel → Environment Variables** (`NEXT_PUBLIC_API_URL` only, which is
  not a secret).
- `deploy/render.yaml` declares secrets with `sync: false` so Render prompts for
  them instead of reading them from the repo.
- If a key is ever committed: rotate it first, then rewrite history. Rotating is
  the fix; deleting the commit is housekeeping.
