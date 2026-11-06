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
GEMINI_API_KEY=...        # matching, embeddings AND rewrites
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_KEY=eyJ...
GUEST_IP_SALT=...         # random secret salt for SHA-256 guest IP hashing
TRUSTED_PROXIES=          # comma-separated trusted proxy IPs/CIDRs (default empty)
```

### Proxy Configuration & Client IP Trust (Phase 4)
1. **Application Server (`uvicorn`)**:
   - Uvicorn **must** be started with `--no-proxy-headers` (configured in `api/Dockerfile`, `scripts/dev.ps1`, and `scripts/dev.sh`).
   - Why: Uvicorn enables `ProxyHeadersMiddleware` by default with `forwarded_allow_ips="127.0.0.1,::1"`, which rewrites `scope["client"]` before FastAPI runs and would bypass application-level proxy validation.
2. **Application Trust (`TRUSTED_PROXIES`)**:
   - `api/auth.py:get_client_ip` only inspects `X-Forwarded-For` when the direct TCP connection peer (`request.client.host`) belongs to `TRUSTED_PROXIES`.
   - When trusted, `X-Forwarded-For` is parsed right-to-left (closest hop to furthest), selecting the first valid IP that is **not** in `TRUSTED_PROXIES`.
   - If the connection peer is untrusted, or if `X-Forwarded-For` is missing or contains a malformed hop in the trusted chain, `get_client_ip` falls back to the connection peer IP.
   - Raw client IPs are never stored or logged; guest quotas and rate limits use salted SHA-256 (`hash_guest_ip`).
3. **Hosting Assumptions & Unverified Deployment Facts**:
   - **Header Sanitization**: We do **not** assume Render or Vercel strip or sanitize client-supplied `X-Forwarded-For` headers. We assume proxies append the connecting client IP to the right of any existing header values.
   - **Unverified Render Internal Proxy CIDRs**: Render does not document fixed internal load-balancer IP ranges for free-tier containers. Leaving `TRUSTED_PROXIES` empty treats the immediate peer as the client IP until the operator verifies and configures the exact proxy CIDRs.
   - **Unverified Vercel Server-Side Rewrite Hop**: Next.js `rewrites()` in `web/next.config.ts` proxy `/api/*` from Vercel to Render server-side. Unless both Render's load balancer and Vercel's dynamic egress IPs are verified and listed in `TRUSTED_PROXIES` (or requests go through a single verified edge proxy with static CIDRs like Cloudflare), the rightmost untrusted hop seen by Render will be the Vercel rewrite egress IP rather than the end browser IP.

### Vercel Environment (Next.js Frontend)
```ini
NEXT_PUBLIC_API_URL=https://api.spean.app
```

Then, in the browser:

1. Open the site. Click **Try a sample** — this must render a full result with
   zero uploads and zero LLM calls.
2. Run **one real analysis** (a real resume + a real JD) all the way to results.
   This is what actually proves Gemini, Supabase and the engine are alive.
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

## Analysis admission limits

Outbound job fetching uses `FETCH_TIMEOUT_SECONDS` (default 15 seconds) across DNS,
redirects and response reads, with `MAX_CONCURRENT_FETCHES=4` per API process.
AI rewrites use `REWRITE_TIMEOUT_SECONDS=60` and `MAX_CONCURRENT_REWRITES=2`.
These operations reject overload with 429 and report expired workflow deadlines
with 504. Capacity stays occupied until the underlying local work really stops;
a timeout or disconnected client does not free a still-running worker. SDK calls
use the remaining workflow budget and disable automatic retries. Process limits
multiply with worker count; account quotas remain database-coordinated.

Live mode defaults to `PERSISTENCE_MODE=required`. Set a valid `SUPABASE_URL` and
service-role credential before startup; missing, partial, or placeholder settings
prevent startup. Client initialization and later database failures return a safe
503 response on affected requests and never switch enforcement to local memory.
Initialization is retried on a subsequent request after a failure; database query
failures keep using persisted accounting and its idempotent reservation IDs.

For intentional local use without a database, explicitly set
`PERSISTENCE_MODE=offline` and run only one worker. Offline mode ignores Supabase
credentials and resets local accounting on restart. `ENGINE_MODE=mock` is always
offline. Do not use either offline option to recover from a production outage.

Before deploying the API with the analysis attempt budget, apply
`data/migrations/005_analysis_attempt_limits.sql` after the existing migrations.
It adds a server-only RPC and a rolling one-hour attempt ledger shared by workers.
If the RPC is missing or unavailable, live analysis admission returns 503 rather
than falling back to a fresh local budget.

Before deploying the saved-resume upload fix, also apply
`data/migrations/006_resume_upload_slots.sql`. With `ENFORCE_QUOTAS=true`, each
limited-plan upload reserves a slot before parsing. Saved resumes and pending
uploads count toward the same limit across workers. Saving consumes the slot in
the same database transaction; failed uploads release it. Abandoned reservations
expire after `RESERVATION_TTL_SECONDS` (default 600). Expired uploads cannot save
late and must be uploaded again. A missing or unavailable RPC returns 503.

Before deploying the renewal and checkout protections, apply
`data/migrations/007_billing_safety.sql` after migration 006. It coordinates
pending checkout creation and paid pass grants across workers. An early renewal
queues a new period after existing purchases; usage continues counting against
the current period until the next one starts. Repeated payment notifications
grant the same checkout only once.

`REWRITE_ATTEMPTS_PER_HOUR=10` and `CHECKOUT_ATTEMPTS_PER_HOUR=10` are independent,
non-refundable account safety budgets, including for admins. They apply in mock
engine mode too, because rewrites can still call the real AI service. Cached
rewrite results do not spend another attempt. Failed rewrites refund the normal
plan quota but keep their attempt. The budgets use migration 005's existing
server-only admission ledger with separate namespaces; a database failure
returns 503. Offline operation uses local counters and requires one worker.

Checkout requests reuse an unexpired pending session. Simultaneous requests
while it is being created return 409 and can retry shortly; requests beyond the
hourly budget return 429. A failed provider creation cancels its pending record
but keeps its attempt. Abandoned creation claims expire after 30 minutes.
`CHECKOUT_CACHE_MAX_ENTRIES=500` bounds the process cache. Persisted sessions can
be reloaded after eviction; offline mode preserves pending sessions and rejects
new checkouts if they fill the cache. Expired and completed offline sessions may
be evicted to make room for new checkouts.

Before deploying the payment-status polling fix, review and apply
`data/migrations/008_checkout_status_polling.sql` after 007. This additive migration
adds server-only admission and refresh RPCs, a request bucket table with RLS, and
cache/lease columns on existing checkouts. Leave previously applied migrations
unchanged. Apply 008 first, then roll out the API to every worker with the same
settings; older workers do not enforce the new polling protection. No frontend
change or credential rotation is needed. For a code rollback, leave the additive
schema in place and remember that older code does not protect status polling.

Both authenticated GET routes, `/api/billing/checkout/{session_id}` and
`/api/billing/checkout/by-ref/{provider_ref}`, consume the same rolling 60-second
account budget: `CHECKOUT_STATUS_REQUESTS_PER_MIN=30` (0 blocks polling; maximum
10000). Cached responses, paid sessions, missing sessions, and ownership failures
count too, including for admins. Changing route, reference, checkout, or worker
cannot reset the account budget. Excess requests return 429 `RATE_LIMITED`.
Checkout creation and webhooks use their existing paths and budgets.

`CHECKOUT_STATUS_CACHE_SECONDS=5` (1..300) is the shared provider refresh cooldown,
measured from completion. Pending provider results and provider failures are cached.
A single worker claims the refresh; concurrent readers return the current stored
status without contacting Stripe. Cached provider failures return safe 503
`SERVICE_UNAVAILABLE` responses until the cooldown ends. Webhooks update the
checkout immediately, even during a cooldown or an in-flight refresh. A refresh
cannot overwrite a webhook's terminal status. Paid status reads retry the
idempotent pass grant, so transient activation failures can recover without another
Stripe call or another subscription. Pending sessions still expire locally; a
refresh that discovers payment at expiry grants it, and paid webhooks can activate
an expired checkout as before.

`CHECKOUT_STATUS_PROVIDER_TIMEOUT_SECONDS=10` (1..30) sets the Stripe status HTTP
timeout, with SDK network retries disabled. The refresh lease lasts twice this
timeout plus 30 seconds (50 seconds by default) to cover connect/read timeouts and
scheduling margin. A crashed worker's lease recovers automatically. Lease tokens
fence stale refresh completions after another worker takes over. If admission,
claim, completion, checkout lookup, or grant persistence fails (including a missing
RPC), return safe 503 responses; never fall back to process memory. An uncertain
completion keeps its claim until the lease expires, avoiding an immediate retry
storm. HTTP timeouts and leases cannot cancel work already accepted by Stripe.

Storage stays bounded: the provider cache uses a fixed set of columns per checkout;
the database limiter keeps at most one bucket per account, with at most the
configured number of accepted timestamps, and prunes expired buckets in batches
of up to 1000 per admission. Rejected polls add no rows or timestamps. There is no
per-poll status-cache history. The local checkout cache retains its existing
`CHECKOUT_CACHE_MAX_ENTRIES` bound. Explicit offline mode uses a bounded local
limiter (5000 account buckets, active buckets are not evicted) and local refresh
claims stored in those checkout records; it requires one worker and resets on
restart. Offline mode never contacts Supabase.

Before release, run the mocked polling/billing tests and full regression suite:
`python -m pytest tests/test_checkout_status_polling.py tests/test_phase4_billing.py
tests/test_billing_security.py tests/test_multiworker_concurrency.py`, then
`python -m pytest`, `ruff check .`, and the frontend checks listed in the README.
Tests block Stripe HTTP requests and simulate two independent worker caches/locks
against a shared database double. They do not apply the SQL migration or call paid
services. After an operator applies 008 in a test environment, verify RPC grants
and exercise both routes with mocked payment responses before production rollout.

New analyses and retries share `ANALYSIS_ATTEMPTS_PER_HOUR` (default 10 per account)
or `GUEST_ANALYSIS_ATTEMPTS_PER_HOUR` (default 3 per salted guest IP). These safety
limits also apply to admins and are separate from plan quotas. Failures can refund
the normal quota but never refund an admitted attempt. Adjust these settings to
the service's expected load and AI budget. Intentionally offline operation uses
an in-memory budget and must run with a single worker; it resets on restart.

Timed-out work retains its concurrency slot until local execution ends. SDK and
model fallbacks share the remaining timeout budget and SDK retries are disabled.
Ending a local request does not guarantee cancellation of a request already
accepted by the remote AI provider.

## 11. Rehearsal checklist

- [ ] Render `/api/health` returns 200 OK.
- [ ] Vercel landing page loads cleanly (English only — Khmer/i18n was removed).
- [ ] Sample analysis button loads results without delay.
- [ ] Hidden Strengths rewrite generator displays validated diffs and safety counter.
- [ ] Baseline comparison toggle functions properly.
- [ ] Country selector re-renders format rules and visa signal sentences.
