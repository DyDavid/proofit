# Pre-Demo Warm-Up & Deployment Runbook

> **Spean (Proofit)** — Defense & Presentation Runbook

---

## 1. Pre-Demo Warm-Up Procedure (15 Minutes Before Defense)

Render free web services enter a sleep state after ~15 minutes of inactivity. To prevent a 30–60 second cold-start delay during your presentation, run the pre-demo warm-up protocol:

### Step 1: Hit Health Endpoint
Open a terminal or browser and ping the live backend service:
```bash
curl https://api.spean.app/api/health
```
*(Or hit the `*.onrender.com/api/health` fallback URL).*

# Validate the compose file without starting anything (safe at any time).
docker compose -f deploy/docker-compose.yml config

# Build and run both services.
docker compose -f deploy/docker-compose.yml up --build

# In a second terminal — the two acceptance checks from §5 Phase 0 task 3:
curl -s http://localhost:8000/api/health      # → {"status":"ok","engine_mode":"mock",...}
open http://localhost:3000                    # → landing shell

# Follow logs / stop / wipe.
docker compose -f deploy/docker-compose.yml logs -f api
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml down -v --rmi local
```

### Step 2: Run Warm-Up Analysis
Run one live analysis to pre-warm the LLM client, cache, and database connection pool:
```powershell
.\.venv\Scripts\python scripts/test_live_flow.py
```
Confirm the script prints:
```text
=== LIVE MATCH COMPLETED ===
```

### Step 3: Keep Tab Active
Open `https://spean.app` (or Vercel preview URL) in your browser and leave the tab open.

---

## 2. Standby Offline Fallback (If Network or Render Fails)

If the venue WiFi drops or Render is unresponsive during your defense, switch immediately to the **zero-network offline fallback**:

### Local Standby Stack
Run the monorepo locally in mock mode:
```powershell
# In PowerShell:
.\scripts\dev.ps1
```
This launches:
- **FastAPI backend** on `http://localhost:8000` (or `3001`) with `ENGINE_MODE=mock`.
- **Next.js frontend** on `http://localhost:3000`.

### Instant Demo Mode (`?demo=1`)
Open `http://localhost:3000/results` or click **"Try a Sample Analysis"** on the landing page.
- Loads pre-compiled golden fixtures (`fresh_grad_stretch.json`) instantaneously.
- Requires **zero file uploads**, **zero network calls**, and **zero LLM API tokens**.

---

## 3. Environment Variables Reference

### Render Environment (FastAPI Backend)
```ini
ENGINE_MODE=live
APP_VERSION=0.1.0
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_KEY=eyJ...
```

### Vercel Environment (Next.js Frontend)
```ini
NEXT_PUBLIC_API_URL=https://api.spean.app
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
5. **Leave the results tab open.** A warm tab is your fastest fallback.
6. Do not push to `main` after this point. Auto-deploy would rebuild the service
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

---

## 9. Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | What it guards |
|---|---|
| `python` | `ruff check` + `pytest` — engine and API correctness |
| `web` | `tsc --noEmit` and `next build` |
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

---

## 11. Rehearsal checklist

- [ ] Render `/api/health` returns 200 OK.
- [ ] Vercel landing page loads cleanly (English only — Khmer/i18n was removed).
- [ ] Sample analysis button loads results without delay.
- [ ] Hidden Strengths rewrite generator displays validated diffs and safety counter.
- [ ] Baseline comparison toggle functions properly.
- [ ] Country selector re-renders format rules and visa signal sentences.
