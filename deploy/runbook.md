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

Verify the response:
```json
{"status": "ok", "version": "0.1.0"}
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

---

## 4. Rehearsal Checklist
- [ ] Render `/api/health` returns 200 OK.
- [ ] Vercel landing page loads cleanly in English and Khmer (`en`/`km`).
- [ ] Sample analysis button loads results without delay.
- [ ] Hidden Strengths rewrite generator displays validated diffs and safety counter.
- [ ] Baseline comparison toggle functions properly.
- [ ] Country selector re-renders format rules and visa signal sentences.
