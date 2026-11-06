# Six-phase security rollout

Code and tests are prepared locally. No migration was applied, no deployment was
made, and existing credentials and `.env` values were not changed.

## Deployment order

1. Confirm migrations 001–008 are installed. Review and apply
   `data/migrations/009_security_coordination.sql` in a test database first.
2. Configure the **Render backend**, using the settings in `.env.example` and
   below. These settings do not belong on the Vercel frontend.
3. Drain old workers, then deploy every API worker with identical settings.
   Old code does not enforce the new protections. Missing RPCs fail closed with
   safe 503 responses. Leave the additive migration in place on code rollback;
   rolling back code reintroduces the reviewed risks.
4. Exercise normal and rejected flows using mocked services. Verify real database
   permissions: only `service_role` can execute the three new RPCs or access
   `resource_request_buckets`. `anon` and `authenticated` must have no access.
5. Before production approval, verify actual Render/Vercel settings and RLS,
   validate the SQL in PostgreSQL, and test the Linux container's memory ceiling.
   Mocked tests do not replace these operational checks.

## Phase 1: document resources

`PARSER_MEMORY_LIMIT_MB=256` limits each child process in MiB: Linux uses
`RLIMIT_AS` (virtual address space), Windows a Job Object (process commit).
Unsupported platforms or failed isolation reject parsing. A ready handshake
occurs only after isolation is installed. `PARSER_STARTUP_TIMEOUT_SECONDS=20`
bounds startup separately from `PARSER_TIMEOUT_SECONDS=8` for execution.
Timeouts and resource failures discard workers; later requests can recover.

`MAX_PDF_DECOMPRESSED_BYTES=10485760` limits cumulative PDF Flate stream output.
Text is bounded while produced; other intermediate allocations remain inside the
OS ceiling. Resource rejection never falls back to raw decoding. DOCX validation
also runs in the isolated child. The Render blueprint uses one parser at 192 MiB
on its 512 MiB instance. Size **all** parser workers plus API memory against the
container limit. Native-library virtual memory on Linux may require tuning.

## Phase 2: mock payments

Simulation defaults off. Local/demo simulation requires
`APP_ENVIRONMENT=local` or `demo`, `ALLOW_MOCK_PAYMENTS=true`, and
`BILLING_PROVIDER=mock`, plus an authenticated owner and a mock checkout.
Expired, canceled, and Stripe-backed records are rejected. Repetition is idempotent.

Production requires `APP_ENVIRONMENT=production`, `ALLOW_MOCK_PAYMENTS=false`,
`BILLING_PROVIDER=stripe_sandbox`, and existing Stripe **test** credentials.
Production also requires `ENGINE_MODE=live` and `PERSISTENCE_MODE=required` so mock
engine mode cannot silently switch coordination to local memory. This activates
the existing live AI flow after deployment; it does not switch Stripe to live mode.
Startup also detects Render/Vercel platform flags. Live Stripe keys stay forbidden.
The blueprint declares secret names with `sync: false`, never values. Public
production simulation cannot be enabled by changing only the billing provider.

## Phase 3: webhook recovery

One RPC commits event completion, checkout mutation, and idempotent pass activation
together. Crashes/errors roll back; redelivery remains eligible. Row/advisory locks
coordinate concurrent workers, with the same subscription lock order as polling.
Expiry cannot overwrite paid status. Signature, provider, owner, amount, and any
supplied currency are checked. Missing checkouts return 503 to permit retry when
delivery races checkout creation.

Migration 009 adds nullable `stripe_events.processed_at`. Legacy markers have
unknown outcomes: redelivery runs them once through idempotent activation and
stamps completion. The migration does not replay events itself; reconcile previous
failed Stripe test deliveries separately. New completion markers are written only
on transaction success. There are no durable partial claims to expire.

Offline handling uses one local lock and records completion only after success.
`WEBHOOK_CACHE_MAX_ENTRIES=1000` bounds its markers. Evicted duplicates may run
again; granting remains idempotent. Offline persistence requires one worker.

## Phase 4: job storage

Both job routes share `JOB_REQUESTS_PER_MIN=20` per client IP hash and
`JOB_GLOBAL_REQUESTS_PER_MIN=120` across clients/workers. Cached requests and
invalid submissions reaching the route count. Zero blocks work. Existing local
endpoint limits remain additional safeguards. Configure `TRUSTED_PROXIES` only
from verified deployment facts; arbitrary forwarding headers are not trusted.

Durable insertion, deduplication, cleanup, and capacity checking are atomic,
including after worker-cache hits. `JOB_UNUSED_MAX_ENTRIES=500` caps unreferenced
rows; full storage returns 429. `JOB_UNUSED_RETENTION_HOURS=24` expires unused
jobs; each insertion removes up to 1000 expired unused rows. Jobs referenced by
retained analyses are protected. Retained user history requires its own business
retention policy; this is not a cap on all application data.

Offline capacity and retention are bounded too. Unused jobs can be evicted;
referenced authoritative jobs cannot. Full referenced storage rejects new work.
Durable worker caches may evict referenced jobs because they can reload them.

## Phase 5: authentication

Malformed/oversized tokens, unsupported algorithms, missing/expired claims, and
oversized key IDs are rejected locally. Unverified claims never grant access;
normal signature, audience, subject, and expiration verification still runs.

`AUTH_REQUESTS_PER_MIN=120` per client and `AUTH_GLOBAL_REQUESTS_PER_MIN=1200`
are shared rolling-minute budgets. `MAX_CONCURRENT_AUTH=4` bounds running work
per process. `AUTH_TIMEOUT_SECONDS=5` bounds the caller's wait; timed-out work
keeps its slot until it actually ends. Capacity/budget exhaustion returns 429;
provider outages and required coordination failures return safe 503 responses.

`AUTH_PROVIDER_TIMEOUT_SECONDS=3` bounds JWKS/fallback HTTP operations.
`AUTH_JWKS_REFRESH_SECONDS=30` serializes/cools down successful and failed key
fetches; random key IDs cannot trigger a fetch storm. New key rotation may wait
this interval. JWKS/email caches are bounded; signing keys are read from the
current JWKS rather than an indefinite per-key cache. Removed keys stop working
after refresh. Tokens are still validated on every request.

Each scope's admission table has at most 5000 buckets and at most the configured
accepted timestamp count per bucket (maximum 10000). Expired buckets are pruned;
active buckets are not evicted to reset limits. Offline budgets are local and
require one worker. Asymmetric Auth still needs its configured endpoint, as before.
Use edge ingress controls alongside these application budgets; they do not promise
availability against distributed network floods.

## Phase 6: checks

Run `python -m pytest`, `ruff check .`, and in `web/`: `npm run lint`,
`node --test tests/authRedirect.test.mjs`, and `npx tsc --noEmit`.
Security tests use constrained child allocations, small PDF fixtures, mocked
providers, and shared database doubles with independent worker locks/caches.
No test applies SQL or calls paid services.

The parser readiness handshake separates startup from execution timing. Picklable
parser fixtures live in a lightweight module so deserialization does not import
the whole test suite. The slow-drip test warms its HTTP client before starting
the synthetic server and timed request; it also asserts a request actually reached
the server. Its deadline and socket-cleanup assertions remain intact.

### Local verification on 2026-11-06

| Check | Result |
| --- | --- |
| Full Python regression suite | 693 passed; 3 dependency deprecation warnings |
| Ruff and whitespace check | Passed |
| Frontend regression tests | 2 passed |
| TypeScript | Passed |
| ESLint | No errors; one existing generated-types warning |
| Python installed-runtime OSV audit | 81 packages checked; no known advisories |
| Python dependency consistency (`pip check`) | Passed |
| npm production dependency audit | No known advisories |

The Python advisory audit covers the installed Windows runtime dependency closure,
not the unbuilt Linux image's platform-specific packages. Repeat the audit against
the final deployment image. No migration was executed and real production state
was not inspected; database integration and Linux memory enforcement remain rollout
verification steps. No credential or local `.env` value was changed.
