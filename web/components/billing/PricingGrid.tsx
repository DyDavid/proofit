"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import {
  DEFAULT_PLANS,
  fetchPlans,
  fetchSubscription,
  type PlanDefinition,
  type SubscriptionSummary,
} from "@/lib/billing/api";
import { CampusContactDialog } from "@/components/billing/CampusContactDialog";
import { CheckoutDialog } from "@/components/billing/CheckoutDialog";
import { PricingCard } from "@/components/billing/PricingCard";

const CAMPUS_CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_CAMPUS_CONTACT_EMAIL || "dydavid168@gmail.com";

function formatActiveUntil(isoDate: string | null | undefined): string | null {
  if (!isoDate) return null;
  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) return null;
  return `Active until ${parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })}`;
}

export interface PricingGridProps {
  onStartCheckout?: (plan: PlanDefinition) => void;
}

export function PricingGrid({ onStartCheckout }: PricingGridProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [plans, setPlans] = useState<PlanDefinition[]>(DEFAULT_PLANS);
  // undefined means the browser session is still being restored.
  const [userId, setUserId] = useState<string | null | undefined>(undefined);
  const authChecked = userId !== undefined;
  const isLoggedIn = Boolean(userId);
  const [subscription, setSubscription] = useState<SubscriptionSummary | null>(
    null,
  );
  const [checkoutPlan, setCheckoutPlan] = useState<PlanDefinition | null>(null);
  const [campusModalOpen, setCampusModalOpen] = useState<boolean>(false);
  const [autoTriggered, setAutoTriggered] = useState<boolean>(false);
  const [subscriptionVersion, setSubscriptionVersion] = useState(0);

  useEffect(() => {
    let mounted = true;

    void fetchPlans().then((loadedPlans) => {
      if (mounted) setPlans(loadedPlans);
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const supabase = createClient();
    if (!supabase) {
      setUserId(null);
      return;
    }

    // INITIAL_SESSION arrives after session restoration; later events keep
    // pricing in sync with sign-in, sign-out, and token refresh across tabs.
    const {
      data: { subscription: authSubscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUserId(session?.user.id ?? null);
      if (!session) {
        setCheckoutPlan(null);
        setAutoTriggered(false);
      }
    });

    return () => authSubscription.unsubscribe();
  }, []);

  useEffect(() => {
    let mounted = true;
    setSubscription(null);
    if (userId) {
      // Keep network/auth calls outside the auth event callback.
      void fetchSubscription().then((sub) => {
        if (mounted) setSubscription(sub);
      });
    }
    return () => {
      mounted = false;
    };
  }, [userId, subscriptionVersion]);

  const startPassCheckout = useCallback(
    (passPlan: PlanDefinition) => {
      if (onStartCheckout) {
        onStartCheckout(passPlan);
        return;
      }
      setCheckoutPlan(passPlan);
    },
    [onStartCheckout],
  );

  // After login, if the URL has ?plan=pass, start checkout automatically (§3.3)
  useEffect(() => {
    if (!authChecked || !isLoggedIn || autoTriggered) return;
    if (searchParams.get("plan") === "pass") {
      const passPlan = plans.find((p) => p.id === "pass");
      if (passPlan) {
        setAutoTriggered(true);
        startPassCheckout(passPlan);
      }
    }
  }, [
    authChecked,
    isLoggedIn,
    autoTriggered,
    searchParams,
    plans,
    startPassCheckout,
  ]);

  const activePlanId = isLoggedIn ? (subscription?.plan_id ?? "free") : null;
  const isPassActive =
    isLoggedIn && (activePlanId === "pass" || activePlanId === "campus");

  function getCardConfig(plan: PlanDefinition): {
    ctaLabel: string;
    disabled: boolean;
    showArrow: boolean;
    activeUntilText: string | null;
    onAction: () => void;
  } {
    if (plan.id === "campus") {
      return {
        ctaLabel: "Contact us",
        disabled: false,
        showArrow: true,
        activeUntilText: null,
        onAction: () => {
          setCampusModalOpen(true);
        },
      };
    }

    if (!authChecked) {
      return {
        ctaLabel: "Checking account…",
        disabled: true,
        showArrow: false,
        activeUntilText: null,
        onAction: () => {},
      };
    }

    if (plan.id === "free") {
      if (!isLoggedIn) {
        return {
          ctaLabel: "Get started",
          disabled: false,
          showArrow: true,
          activeUntilText: null,
          onAction: () => {
            router.push("/login?next=/pricing");
          },
        };
      }
      if (isPassActive) {
        return {
          ctaLabel: "Free after pass ends",
          disabled: true,
          showArrow: false,
          activeUntilText: null,
          onAction: () => {},
        };
      }
      return {
        ctaLabel: "Current plan",
        disabled: true,
        showArrow: false,
        activeUntilText: null,
        onAction: () => {},
      };
    }

    // plan.id === "pass"
    if (!isLoggedIn) {
      return {
        ctaLabel: "Get Pass",
        disabled: false,
        showArrow: true,
        activeUntilText: null,
        onAction: () => {
          router.push(
            `/login?next=${encodeURIComponent("/pricing?plan=pass")}`,
          );
        },
      };
    }

    if (isPassActive) {
      const daysLeft = subscription?.active_until
        ? Math.max(
            0,
            Math.ceil(
              (new Date(subscription.active_until).getTime() - Date.now()) /
                (1000 * 60 * 60 * 24),
            ),
          )
        : 30;
      return {
        ctaLabel: `Active · ${daysLeft} ${daysLeft === 1 ? "day" : "days"} left`,
        disabled: true,
        showArrow: false,
        activeUntilText: formatActiveUntil(subscription?.active_until),
        onAction: () => {},
      };
    }

    return {
      ctaLabel: "Get Pass",
      disabled: false,
      showArrow: true,
      activeUntilText: null,
      onAction: () => {
        startPassCheckout(plan);
      },
    };
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 items-stretch gap-6 md:grid-cols-3">
        {plans.map((plan) => {
          const cfg = getCardConfig(plan);
          return (
            <PricingCard
              key={plan.id}
              plan={plan}
              ctaLabel={cfg.ctaLabel}
              disabled={cfg.disabled}
              showArrow={cfg.showArrow}
              activeUntilText={cfg.activeUntilText}
              onAction={cfg.onAction}
            />
          );
        })}
      </div>

      {checkoutPlan && (
        <CheckoutDialog
          open={Boolean(checkoutPlan)}
          plan={checkoutPlan}
          isExtending={isPassActive}
          onClose={() => setCheckoutPlan(null)}
          onCompleted={() => {
            setSubscriptionVersion((version) => version + 1);
          }}
        />
      )}

      <CampusContactDialog
        open={campusModalOpen}
        onClose={() => setCampusModalOpen(false)}
        email={CAMPUS_CONTACT_EMAIL}
      />
    </div>
  );
}
