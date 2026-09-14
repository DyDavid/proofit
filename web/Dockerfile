# ═══════════════════════════════════════════════════════════════════════════
# Proofit — Next.js 15 (App Router) production image.
#
# LOCAL DEV / OFFLINE-FALLBACK ONLY. Production `web` deploys to Vercel with root
# directory `web` (deploy/runbook.md §2). This image exists so that
# `docker compose -f deploy/docker-compose.yml up` gives Person A a one-command
# stack, and so the laptop fallback at the defense is a real production build
# rather than `next dev` (PERSON_B_PLAN_v2.md §5 Phase 7 task 2b).
#
# Build context is web/ (see deploy/docker-compose.yml: context ../web).
#
# Three stages, so the shipped layer contains no source, no dev dependencies and
# no build cache:
#   deps    → node_modules from a lockfile
#   builder → `next build`, emitting .next/standalone
#   runner  → the standalone server + static assets, running as a non-root user
# ═══════════════════════════════════════════════════════════════════════════

# ─── Stage 1: dependencies ────────────────────────────────────────────────
FROM node:22-alpine AS deps
# libc6-compat: Alpine is musl, and some of Next.js's optional native binaries
# (SWC, sharp) are built against glibc. Without it the build fails with an
# opaque "Error loading shared library ld-linux-x86-64.so.2".
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Only the manifests, so this layer is cached until a dependency actually
# changes — not on every source edit.
COPY package.json package-lock.json ./
# `npm ci` (not `npm install`): installs exactly the locked tree and fails loudly
# if package.json and package-lock.json disagree.
RUN npm ci

# ─── Stage 2: build ───────────────────────────────────────────────────────
FROM node:22-alpine AS builder
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# ── THIS ARG IS BUILD-TIME AND CANNOT BE OVERRIDDEN AT RUNTIME. READ THIS. ──
#
# next.config.ts uses NEXT_PUBLIC_API_URL as the destination of its /api/:path*
# rewrite. Next.js calls `rewrites()` during `next build` and freezes the result
# into .next/routes-manifest.json — the standalone server then serves that
# manifest and never re-reads the environment. So setting NEXT_PUBLIC_API_URL in
# `docker run -e` or in Compose's `environment:` does NOT change where /api/* is
# proxied. Only this build arg does. (Compose therefore passes it under
# `build.args`, and repeats it under `environment:` only for server code that
# reads it at request time.)
#
# It must also be non-empty: next.config.ts guards with `?? "http://localhost:8000"`,
# and `??` does not treat "" as absent — an empty value would bake the
# destination "/api/:path*", i.e. a rewrite pointing at the Next app itself, and
# every API call would 404.
#
# The default below matches next.config.ts's own default, so a bare
# `docker build .` behaves like local development. Compose overrides it with
# http://api:8000 (Docker DNS on the Compose network).
#
# One consequence worth knowing: NEXT_PUBLIC_* is also inlined into the CLIENT
# bundle, so whatever is set here is visible to the browser — and a browser
# cannot resolve "api". That is harmless because client code must call the
# relative path /api/... and let the server rewrite forward it (the whole point
# of PERSON_B_PLAN_v2.md §8.3: the browser never deals with a second origin).
# Client code that interpolates NEXT_PUBLIC_API_URL into a fetch() URL breaks
# this contract — keep browser fetches relative.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# Requires `output: 'standalone'` in next.config.ts — it makes Next emit
# .next/standalone with a self-contained server.js and only the node_modules that
# are actually reachable, which is what keeps this image small.
RUN npm run build

# ─── Stage 3: runtime ─────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
# .next/standalone/server.js binds to HOSTNAME, defaulting to localhost — which
# inside a container refuses every connection arriving on the published port.
ENV HOSTNAME=0.0.0.0

# Run as an unprivileged user. A remote-code-execution bug in a dependency then
# lands on a user that owns nothing, instead of on root.
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 --ingroup nodejs nextjs

# public/ holds static assets (favicon, images). Owned by root and world-readable:
# the server only ever reads them, so nextjs must not be able to overwrite them.
COPY --from=builder /app/public ./public

# The standalone server and its pruned node_modules. `./` because the trace
# output is already rooted at the app directory.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
# Static chunks are NOT included in the standalone trace and must be copied
# separately, or every page loads unstyled with a wall of 404s in the console.
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

# Exec form: node becomes PID 1 and receives SIGTERM directly, so
# `docker compose down` stops the container in a second rather than after the
# 10-second kill timeout.
CMD ["node", "server.js"]
