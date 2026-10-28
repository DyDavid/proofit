import { redirect } from "next/navigation";
import { UsageMeter } from "@/components/billing/UsageMeter";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { createClient } from "@/lib/supabase/server";

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

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-14 sm:px-8">
      <div className="mb-8">
        <p className="font-mono text-xs uppercase tracking-widest text-ink-3">
          Account &amp; Plan
        </p>
        <h1 className="mt-1.5 font-serif text-3xl font-bold text-ink">
          Your Account
        </h1>
      </div>

      <div className="grid gap-6">
        <UsageMeter />

        <Card padding="lg" className="grid gap-6">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule pb-5">
            <div>
              <p className="font-mono text-xs uppercase tracking-wider text-ink-3">
                Signed in as
              </p>
              <p className="mt-1 text-lg font-medium text-ink">{user.email}</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <Button as="a" href="/analyze" size="sm" icon="arrow">
                Go to Analyzer
              </Button>
              <Button as="a" href="/pricing" variant="secondary" size="sm">
                View Pricing
              </Button>
            </div>

            <form action="/auth/signout" method="post">
              <Button type="submit" variant="secondary" size="sm">
                Sign out
              </Button>
            </form>
          </div>
        </Card>
      </div>
    </div>
  );
}
