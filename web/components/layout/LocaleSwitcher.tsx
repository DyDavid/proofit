"use client";

import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";
import { routing, usePathname, useRouter } from "@/i18n/routing";

/**
 * Switches between `en` and `km` on the current page.
 *
 * `usePathname()` from `@/i18n/routing` returns the pathname *without* the
 * locale prefix, so replacing it with a different `locale` keeps the user on
 * the same screen. Query parameters are read at click time from
 * `window.location.search` and carried over — deliberately not via
 * `useSearchParams()`, which would force every page rendering the header out
 * of static generation.
 */
export default function LocaleSwitcher() {
  const t = useTranslations("common");
  const activeLocale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function selectLocale(nextLocale: string) {
    if (nextLocale === activeLocale) return;

    const search =
      typeof window === "undefined" ? "" : window.location.search;
    const query = Object.fromEntries(new URLSearchParams(search).entries());

    startTransition(() => {
      router.replace({ pathname, query }, { locale: nextLocale });
    });
  }

  return (
    <div
      role="group"
      aria-label={t("localeSwitcher.label")}
      className="inline-flex items-center rounded-pill border border-ink p-0.5"
    >
      {routing.locales.map((locale) => {
        const isActive = locale === activeLocale;
        return (
          <button
            key={locale}
            type="button"
            lang={locale}
            aria-pressed={isActive}
            disabled={isPending}
            onClick={() => selectLocale(locale)}
            className={[
              "rounded-pill px-2.5 py-1 text-xs font-medium leading-[1.6] transition-colors",
              "disabled:cursor-progress disabled:opacity-60",
              isActive ? "bg-ink text-paper" : "text-ink-2 hover:text-ink",
            ].join(" ")}
          >
            {t(`locale.${locale}`)}
          </button>
        );
      })}
    </div>
  );
}
