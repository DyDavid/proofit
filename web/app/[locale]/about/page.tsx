import { getTranslations } from "next-intl/server";

const SECTIONS = ["method", "limits", "team", "legality"] as const;

export default async function AboutPage() {
  const t = await getTranslations("about");

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-14 sm:px-6">
      <p className="mb-2 font-mono text-xs uppercase tracking-wide text-ink-3">
        {t("eyebrow")}
      </p>
      <h1 className="mb-8 font-serif text-4xl text-ink sm:text-5xl">{t("title")}</h1>
      <div className="grid gap-6">
        {SECTIONS.map((key) => (
          <p key={key} className="text-base leading-[1.75] text-ink-2">
            {t(key)}
          </p>
        ))}
      </div>
    </div>
  );
}
