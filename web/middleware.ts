import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

/**
 * Locale negotiation + redirect. `/` becomes `/en` (or `/km` when the
 * Accept-Language header or the NEXT_LOCALE cookie says so).
 */
export default createMiddleware(routing);

export const config = {
  /**
   * Run on everything except:
   *  - `/api/*`     — proxied straight through to FastAPI (see next.config.ts)
   *  - `/_next/*`   — Next.js build output
   *  - `/_vercel/*` — Vercel internals
   *  - any path containing a dot (favicon.ico, /file.svg, robots.txt, …)
   */
  matcher: "/((?!api|_next|_vercel|.*\\..*).*)",
};
