import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

/**
 * Per-request i18n configuration, loaded by the next-intl plugin
 * (`createNextIntlPlugin('./i18n/request.ts')` in `next.config.ts`).
 *
 * `requestLocale` is the `[locale]` segment matched by the middleware. It can
 * be `undefined` (a render outside the `[locale]` segment) or an unknown value
 * (the segment acts as a catch-all), so it is always validated before use.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
