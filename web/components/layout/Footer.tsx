import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";

/**
 * Site footer: wordmark, tagline, and the link to the About page where the
 * method, limits and legality statement live.
 */
export default function Footer() {
  const t = useTranslations("common");

  return (
    <footer className="border-t border-rule bg-paper-3">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-6 text-sm leading-[1.75] sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-ink-3">
          <span className="font-semibold text-ink">{t("appName")}</span>
          <span>{t("tagline")}</span>
          <Link
            href="/about"
            className="font-medium text-ink-2 underline-offset-4 transition-colors hover:text-ink hover:underline"
          >
            {t("nav.about")}
          </Link>
        </p>
        <p className="font-mono text-xs text-ink-3">{t("footerMeta")}</p>
      </div>
    </footer>
  );
}
