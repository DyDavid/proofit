import { useTranslations } from "next-intl";
import LocaleSwitcher from "@/components/layout/LocaleSwitcher";
import { Button } from "@/components/ui/Button";
import { Link } from "@/i18n/routing";

const NAV_ITEMS = [
  { href: "/", key: "nav.home" },
  { href: "/analyze", key: "nav.analyze" },
  { href: "/about", key: "nav.about" },
] as const;

/**
 * Site header: Proofit wordmark, the three primary routes, the locale
 * switcher, and a primary CTA. Server component — the only interactive part
 * is the switcher.
 */
export default function Header() {
  const t = useTranslations("common");

  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper-3/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-7 gap-y-3 px-4 py-3.5 sm:px-6">
        <Link href="/" className="shrink-0 font-serif text-2xl italic text-ink">
          {t("appName")}
        </Link>

        <nav className="order-3 flex w-full flex-wrap items-center gap-x-6 gap-y-2 sm:order-none sm:w-auto">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="border-b-2 border-transparent py-1 font-medium text-ink-2 transition-colors hover:border-rule hover:text-ink"
            >
              {t(item.key)}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-4">
          <LocaleSwitcher />
          <Button as="a" href="/analyze" size="sm" className="hidden sm:inline-flex">
            {t("action.analyze")}
          </Button>
        </div>
      </div>
    </header>
  );
}
