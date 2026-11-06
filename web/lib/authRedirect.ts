/** Return a canonical local path suitable for both router navigation and redirects. */
export function sanitizeNextPath(raw: string | null): string {
  const fallback = "/analyze";
  if (!raw || Array.from(raw).some((char) =>
    char === "\\" || char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
  )) return fallback;
  const path = raw.trim();
  if (!path.startsWith("/") || path.startsWith("//")) return fallback;
  try {
    const base = "https://local.invalid";
    const url = new URL(path, base);
    if (url.origin !== base || url.pathname.startsWith("//")) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
