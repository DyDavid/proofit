import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

/**
 * PERSON_B_PLAN_v2.md §8.3: the browser only ever talks to its own origin.
 * `/api/*` is rewritten to the FastAPI service, so there is no CORS
 * configuration and no second origin in the client code.
 *
 * Locally this defaults to the uvicorn dev server; on Vercel it is set to the
 * Render service URL via the NEXT_PUBLIC_API_URL environment variable.
 */
const apiBaseUrl = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Emits .next/standalone: a self-contained server.js plus only the
  // node_modules actually reachable at runtime. Required by web/Dockerfile's
  // runner stage, which powers `docker compose up` and the offline laptop
  // fallback at the defense (PERSON_B_PLAN_v2.md §5 Phase 7 task 2b).
  // Vercel ignores this and uses its own build output, so it is safe in both.
  output: "standalone",

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBaseUrl}/api/:path*`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
