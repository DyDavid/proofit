import { getLocale, getTranslations } from "next-intl/server";

import { Card } from "@/components/ui/Card";
import { ProgressStepper } from "@/components/progress/ProgressStepper";
import { redirect } from "@/i18n/routing";

export interface ProgressPageProps {
  searchParams: Promise<{ id?: string }>;
}

/** No `?id=` means this page was reached directly rather than via a
 * submitted analysis — there is nothing to poll, so send the user back to
 * start one. */
export default async function ProgressPage({ searchParams }: ProgressPageProps) {
  const { id } = await searchParams;
  if (!id) {
    redirect({ href: "/analyze", locale: await getLocale() });
  }

  const t = await getTranslations("progress");
  const tc = await getTranslations("common");

  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-md items-center px-4 py-16 sm:px-6">
      <Card padding="lg" className="w-full">
        <p className="mb-1 font-mono text-xs uppercase tracking-wide text-ink-3">
          {t("title")}
        </p>
        <h1 className="mb-6 font-serif text-2xl text-ink">{tc("loading")}</h1>
        <ProgressStepper analysisId={id as string} />
      </Card>
    </div>
  );
}
