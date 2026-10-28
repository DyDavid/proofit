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
import { PricingCard } from "@/components/billing/PricingCard";

const CAMPUS_CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_CAMPUS_CONTACT_EMAIL || "campus@proofit.app";

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
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(false);
  const [authChecked, setAuthChecked] = useState<boolean>(false);
  const [subscription, setSubscription] = useState<SubscriptionSummary | null>(
    null,
  );
  const [checkoutNotice, setCheckoutNotice] = useState<string | null>(null);
  const [autoTriggered, setAutoTriggered] = useState<boolean>(false);

  useEffect(() => {
    let mounted = true;

    async function load() {
      const [loadedPlans, supabase] = await Promise.all([
        fetchPlans(),
        Promise.resolve(createClient()),
      ]);
      if (!mounted) return;
      setPlans(loadedPlans);

      if (!supabase) {
        setIsLoggedIn(false);
        setAuthChecked(true);
        return;
      }

      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!mounted) return;

      if (user) {
        setIsLoggedIn(true);
        const sub = await fetchSubscription();
        if (!mounted) return;
        setSubscription(
          sub ?? {
            plan_id: "free",
            active_until: null,
            usage: {
              analysis: { used: 0, limit: 3 },
              rewrite: { used: 0, limit: 1 },
            },
          },
        );
      } else {
        setIsLoggedIn(false);
        setSubscription(null);
      }
      setAuthChecked(true);
    }

    void load();
    return () => {
      mounted = false;
    };
  }, []);

  const startPassCheckout = useCallback(
    (passPlan: PlanDefinition) => {
      if (onStartCheckout) {
        onStartCheckout(passPlan);
        return;
      }
      setCheckoutNotice(
        `Checkout for ${passPlan.name} (${passPlan.price_display} ${passPlan.price_suffix}) is ready to connect in Phase 4 (Stripe Sandbox & Mock Checkout).`,
      );
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
  }, [authChecked, isLoggedIn, autoTriggered, searchParams, plans, startPassCheckout]);

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
          window.location.href = `mailto:${CAMPUS_CONTACT_EMAIL}?subject=${encodeURIComponent(
            "Proofit Campus Inquiry",
          )}`;
        },
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
      return {
        ctaLabel: "Extend pass",
        disabled: false,
        showArrow: true,
        activeUntilText: formatActiveUntil(subscription?.active_until),
        onAction: () => {
          startPassCheckout(plan);
        },
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
      {checkoutNotice && (
        <div
          role="status"
          className="flex items-center justify-between gap-4 rounded-xl border border-accent/35 bg-accent-tint/50 px-5 py-4 text-sm text-ink"
        >
          <span>{checkoutNotice}</span>
          <button
            type="button"
            onClick={() => setCheckoutNotice(null)}
            className="shrink-0 rounded-md px-2.5 py-1 text-xs font-semibold text-ink-2 hover:bg-paper-2"
          >
            Dismiss
          </button>
        </div>
      )}

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
    </div>
  );
}

