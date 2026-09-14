import { createNavigation } from "next-intl/navigation";
import { defineRouting } from "next-intl/routing";

/**
 * Proofit locale routing.
 *
 * PERSON_B_PLAN_v2.md §5 Phase 0 task 4: routes live under `app/[locale]/`
 * for `en` (default) and `km`. Every route is locale-prefixed so a Khmer URL
 * is shareable and the middleware never has to guess.
 */
export const routing = defineRouting({
  locales: ["en", "km"],
  defaultLocale: "en",
});

/** The two locales Proofit ships, as a union type: `"en" | "km"`. */
export type AppLocale = (typeof routing.locales)[number];

/**
 * Locale-aware navigation helpers. Always import `Link` from here (never from
 * `next/link`) so hrefs stay locale-prefixed automatically.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
