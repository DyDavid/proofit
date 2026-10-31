import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AnalysisHistory } from "@/components/analyze/AnalysisHistory";
import { UsageMeter } from "@/components/billing/UsageMeter";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = {
  title: "Your Account",
  description: "Manage your subscription limits, active pass duration, and saved match reports.",
  robots: {
    index: false,
    follow: false,
  },
};

export default async function AccountPage() {
  const supabase = await createClient();
  if (!supabase) {
    redirect("/login?next=/account");
  }

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/account");
  }

  const emailInitial = (user.email?.[0] || "U").toUpperCase();

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-12 sm:px-8 sm:py-16">
      {/* Page Header */}
      <div className="mb-8">
        <p className="font-mono text-xs uppercase tracking-widest text-accent font-semibold">
          Account &amp; Subscription
        </p>
        <h1 className="mt-1 font-serif text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
          Your Account
        </h1>
        <p className="mt-2 text-sm text-ink-2">
          Manage your subscription limits, active pass duration, and saved match reports.
        </p>
      </div>

      <div className="grid gap-6">
        {/* User Profile & Actions Card */}
        <Card padding="lg" className="shadow-xs">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            {/* User Profile Info */}
            <div className="flex items-center gap-3.5 min-w-0">
              <div
                aria-hidden="true"
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-accent/20 bg-accent-tint font-serif text-xl font-bold text-accent shadow-xs"
              >
                {emailInitial}
              </div>
              <div className="min-w-0">
                <p className="font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                  Signed in as
                </p>
                <p className="truncate font-medium text-ink text-base sm:text-lg">
                  {user.email}
                </p>
              </div>
            </div>

            {/* Action Buttons Toolbar with responsive spacing & visual hierarchy */}
            <div className="flex flex-wrap items-center gap-2.5 pt-2 sm:pt-0">
              <Button
                as="a"
                href="/analyze"
                size="sm"
                icon="arrow"
                className="shrink-0"
              >
                Go to Analyzer
              </Button>

              <Button
                as="a"
                href="/pricing"
                variant="ghost"
                size="sm"
                className="shrink-0 hover:bg-paper-2"
              >
                View Pricing
              </Button>

              <form action="/auth/signout" method="post" className="shrink-0">
                <Button
                  type="submit"
                  variant="ghost"
                  size="sm"
                  className="text-ink-2 hover:border-danger hover:bg-danger/5 hover:text-danger"
                >
                  Sign out
                </Button>
              </form>
            </div>
          </div>
        </Card>

        {/* Subscription & Usage Limits */}
        <UsageMeter />

        {/* Saved Past Analyses */}
        <AnalysisHistory showEmpty className="mt-0 shadow-xs" />
      </div>
    </div>
  );
}
