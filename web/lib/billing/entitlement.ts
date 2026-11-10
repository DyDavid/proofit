"use client";

import { useEffect, useState } from "react";
import { notifySubscriptionUpdated } from "./api";

export const DEMO_STORAGE_KEY = "proofit:demo-entitlement";

export interface DemoEntitlement {
  plan: "pass";
  planName: string;
  activatedAt: string; // ISO
  expiresAt: string; // ISO
  analysesRemaining: number;
  rewritesRemaining: number;
  analysesLimit: number;
  rewritesLimit: number;
  last4: string;
  amountCents: number;
  currency: string;
}

/** Check if demo payments are enabled via NEXT_PUBLIC_DEMO_PAYMENTS (defaults to true). */
export function isDemoPaymentsEnabled(): boolean {
  if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_DEMO_PAYMENTS === "false") {
    return false;
  }
  return true;
}

/** Safe localStorage getter for demo entitlement. Automatically purges expired passes. */
export function getDemoEntitlement(): DemoEntitlement | null {
  if (typeof window === "undefined") return null;
  if (!isDemoPaymentsEnabled()) return null;

  try {
    const raw = window.localStorage.getItem(DEMO_STORAGE_KEY);
    if (!raw) return null;

    const data = JSON.parse(raw) as Partial<DemoEntitlement>;
    if (
      data?.plan === "pass" &&
      typeof data?.expiresAt === "string" &&
      typeof data?.analysesRemaining === "number" &&
      typeof data?.rewritesRemaining === "number"
    ) {
      // Check expiration
      const expiresTime = new Date(data.expiresAt).getTime();
      if (!Number.isNaN(expiresTime) && expiresTime <= Date.now()) {
        clearDemoEntitlement();
        return null;
      }

      return data as DemoEntitlement;
    }
    return null;
  } catch {
    return null;
  }
}

/** Activates or extends a 30-day Job Hunt Pass in demo storage. */
export function saveDemoEntitlement(params: {
  last4?: string;
  amountCents?: number;
  currency?: string;
}): DemoEntitlement {
  const now = new Date();
  const existing = getDemoEntitlement();

  // If already active, extending pushes the expiry out by 30 days from existing expiration
  const baseTime = existing ? new Date(existing.expiresAt).getTime() : now.getTime();
  const expiresAt = new Date(baseTime + 30 * 24 * 60 * 60 * 1000).toISOString();

  const entitlement: DemoEntitlement = {
    plan: "pass",
    planName: "Job Hunt Pass",
    activatedAt: existing?.activatedAt || now.toISOString(),
    expiresAt,
    analysesRemaining: (existing?.analysesRemaining ?? 0) + 50,
    rewritesRemaining: (existing?.rewritesRemaining ?? 0) + 30,
    analysesLimit: (existing?.analysesLimit ?? 0) + 50,
    rewritesLimit: (existing?.rewritesLimit ?? 0) + 30,
    last4: params.last4 || "4242",
    amountCents: params.amountCents || 500,
    currency: params.currency || "USD",
  };

  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(entitlement));
      notifySubscriptionUpdated();
      window.dispatchEvent(new CustomEvent("proofit:entitlement-changed"));
    } catch {
      // Non-fatal if storage disabled
    }
  }

  return entitlement;
}

/** Clears demo entitlement from storage and notifies listeners. */
export function clearDemoEntitlement(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(DEMO_STORAGE_KEY);
    notifySubscriptionUpdated();
    window.dispatchEvent(new CustomEvent("proofit:entitlement-changed"));
  } catch {
    // Non-fatal
  }
}

/** Decrements the demo analysis counter by 1 if a demo pass is active. */
export function consumeDemoAnalysis(): boolean {
  const current = getDemoEntitlement();
  if (!current) return false;

  if (current.analysesRemaining > 0) {
    current.analysesRemaining -= 1;
    try {
      window.localStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(current));
      notifySubscriptionUpdated();
      window.dispatchEvent(new CustomEvent("proofit:entitlement-changed"));
    } catch {
      // Non-fatal
    }
    return true;
  }

  return false;
}

/** Decrements the demo rewrite counter by 1 if a demo pass is active. */
export function consumeDemoRewrite(): boolean {
  const current = getDemoEntitlement();
  if (!current) return false;

  if (current.rewritesRemaining > 0) {
    current.rewritesRemaining -= 1;
    try {
      window.localStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(current));
      notifySubscriptionUpdated();
      window.dispatchEvent(new CustomEvent("proofit:entitlement-changed"));
    } catch {
      // Non-fatal
    }
    return true;
  }

  return false;
}

/** Hook for reactive entitlement updates across components. */
export function useEntitlement() {
  const [entitlement, setEntitlement] = useState<DemoEntitlement | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const sync = () => setEntitlement(getDemoEntitlement());
    sync();

    window.addEventListener("proofit:entitlement-changed", sync);
    window.addEventListener("proofit:subscription-updated", sync);
    window.addEventListener("storage", sync);

    return () => {
      window.removeEventListener("proofit:entitlement-changed", sync);
      window.removeEventListener("proofit:subscription-updated", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return {
    entitlement: mounted ? entitlement : null,
    isPassActive: mounted && Boolean(entitlement && entitlement.analysesRemaining > 0),
    isDemoPayments: isDemoPaymentsEnabled(),
    consumeAnalysis: consumeDemoAnalysis,
    consumeRewrite: consumeDemoRewrite,
    clearDemo: clearDemoEntitlement,
  };
}

