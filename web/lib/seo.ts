const DEFAULT_SITE_URL = "http://localhost:3001";

/**
 * Resolves the canonical public site URL from environment variables
 * (`NEXT_PUBLIC_SITE_URL` -> `SITE_URL` -> `VERCEL_PROJECT_PRODUCTION_URL` -> `http://localhost:3000`).
 * Always returns a valid origin string without trailing slashes.
 */
export function getSiteUrl(): string {
  const raw =
    process.env.NEXT_PUBLIC_SITE_URL?.trim() ||
    process.env.SITE_URL?.trim() ||
    (process.env.VERCEL_PROJECT_PRODUCTION_URL
      ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL.trim()}`
      : "") ||
    DEFAULT_SITE_URL;

  try {
    const parsed = new URL(raw.startsWith("http") ? raw : `https://${raw}`);
    return parsed.origin;
  } catch {
    return DEFAULT_SITE_URL;
  }
}

