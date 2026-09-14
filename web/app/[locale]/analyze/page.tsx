import { getTranslations } from "next-intl/server";

import { AnalyzeForm } from "@/components/analyze/AnalyzeForm";

export default async function AnalyzePage() {
  const t = await getTranslations("analyze");

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
      <div className="mb-8">
        <p className="mb-2 font-mono text-xs uppercase tracking-wide text-ink-3">
          {t("eyebrow")}
        </p>
        <h1 className="font-serif text-4xl text-ink sm:text-5xl">{t("title")}</h1>
        <p className="mt-2 max-w-2xl text-base leading-[1.7] text-ink-2">
          {t("subtitle")}
        </p>
      </div>

      <div className="mb-10 flex max-w-xl gap-3 border border-rule bg-surface-raised p-4">
        <svg
          aria-hidden="true"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          className="mt-0.5 shrink-0 text-lac"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
        </svg>
        <div>
          <h2 className="mb-2 font-medium text-ink">{t("onboarding.title")}</h2>
          <ul className="grid gap-1.5 text-sm leading-[1.6] text-ink-2">
            <li>{t("onboarding.line1")}</li>
            <li>{t("onboarding.line2")}</li>
            <li>{t("onboarding.line3")}</li>
          </ul>
        </div>
      </div>

      <AnalyzeForm />
    </div>
  );
}
