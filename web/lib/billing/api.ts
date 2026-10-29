import { createClient } from "@/lib/supabase/client";

export type PlanId = "free" | "pass" | "campus";
export type CheckoutSessionStatus = "unpaid" | "paid" | "expired";

export interface PlanLimits {
  analyses: number | null;
  analyses_label: string;
  rewrites: number | null;
  rewrites_label: string;
  saved_resumes: number | null;
  saved_resumes_label: string;
  support_label: string;
}

export interface PlanDefinition {
  id: PlanId;
  name: string;
  recommended: boolean;
  price_cents: number | null;
  price_display: string;
  price_suffix: string;
  currency: string;
  period_days: number;
  description: string;
  limits: PlanLimits;
  features: string[];
}

export interface UsageBucket {
  used: number;
  limit: number | null;
}

export interface SubscriptionSummary {
  plan_id: PlanId;
  active_until: string | null;
  usage: {
    analysis: UsageBucket;
    rewrite: UsageBucket;
  };
}

export interface CheckoutCreatedResponse {
  session_id: string;
  bill_number: string;
  amount_minor: number;
  amount_cents: number;
  currency: "USD" | "KHR";
  recipient_name: string;
  recipient_bakong_id: string;
  qr_payload: string;
  qr_md5: string;
  status: CheckoutSessionStatus;
  expires_at: string;
}

export interface CheckoutStatusResponse {
  session_id: string;
  plan_id: string;
  bill_number: string;
  amount_minor: number;
  amount_cents: number;
  currency: "USD" | "KHR";
  recipient_name: string;
  qr_payload: string;
  qr_md5: string;
  status: CheckoutSessionStatus;
  expires_at: string;
  paid_at: string | null;
  active_until: string | null;
  nbc_transaction_hash?: string | null;
  verification_error?: string | null;
  verification_message?: string | null;
}

export const DEFAULT_PLANS: PlanDefinition[] = [
  {
    id: "free",
    name: "Free",
    recommended: false,
    price_cents: 0,
    price_display: "$0",
    price_suffix: "forever",
    currency: "USD",
    period_days: 30,
    description: "For trying the matcher on your first applications.",
    limits: {
      analyses: 3,
      analyses_label: "3 per 30 days",
      rewrites: 1,
      rewrites_label: "1 per 30 days",
      saved_resumes: 1,
      saved_resumes_label: "1",
      support_label: "Community",
    },
    features: [
      "Requirement-level match report",
      "Non-work evidence mapping",
    ],
  },
  {
    id: "pass",
    name: "Job Hunt Pass",
    recommended: true,
    price_cents: 500,
    price_display: "$5",
    price_suffix: "per 30 days, one-time",
    currency: "USD",
    period_days: 30,
    description: "For an active job search with many applications.",
    limits: {
      analyses: 50,
      analyses_label: "50 per pass",
      rewrites: 30,
      rewrites_label: "30 per pass",
      saved_resumes: 10,
      saved_resumes_label: "10",
      support_label: "Email",
    },
    features: [
      "Everything in Free",
      "AI rewrite suggestions with fact check",
      "Priority processing (Coming soon)",
    ],
  },
  {
    id: "campus",
    name: "Campus",
    recommended: false,
    price_cents: null,
    price_display: "Custom",
    price_suffix: "billed annually",
    currency: "USD",
    period_days: 365,
    description: "For universities and career centres supporting many students.",
    limits: {
      analyses: null,
      analyses_label: "Unlimited",
      rewrites: null,
      rewrites_label: "Unlimited",
      saved_resumes: null,
      saved_resumes_label: "Unlimited",
      support_label: "Dedicated",
    },
    features: [
      "Everything in Pass",
      "Cohort dashboard (Coming soon)",
      "Bulk student onboarding (Coming soon)",
    ],
  },
];

async function getBearerHeaders(
  extra?: Record<string, string>,
): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  try {
    const supabase = createClient();
    if (supabase) {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (session?.access_token) {
        headers.Authorization = `Bearer ${session.access_token}`;
      }
    }
  } catch {
    // Proceed without auth header
  }
  return headers;
}

async function readBillingError(res: Response): Promise<Error> {
  try {
    const body = (await res.json()) as {
      detail?: { message?: string } | string;
      error?: { message?: string };
    };
    if (typeof body.detail === "string") return new Error(body.detail);
    if (body.detail && typeof body.detail.message === "string") {
      return new Error(body.detail.message);
    }
    if (body.error && typeof body.error.message === "string") {
      return new Error(body.error.message);
    }
  } catch {
    // Ignore parse error
  }
  return new Error(`Request failed (${res.status})`);
}

export async function fetchPlans(): Promise<PlanDefinition[]> {
  try {
    const res = await fetch("/api/billing/plans", { cache: "no-store" });
    if (!res.ok) return DEFAULT_PLANS;
    const data = (await res.json()) as PlanDefinition[];
    return Array.isArray(data) && data.length > 0 ? data : DEFAULT_PLANS;
  } catch {
    return DEFAULT_PLANS;
  }
}

let _cachedSubscription: SubscriptionSummary | null = null;
let _cachedSubExpiresAt = 0;
let _inFlightSubPromise: Promise<SubscriptionSummary | null> | null = null;

export async function fetchSubscription(
  force = false,
): Promise<SubscriptionSummary | null> {
  const now = Date.now();
  if (!force && _cachedSubscription && now < _cachedSubExpiresAt) {
    return _cachedSubscription;
  }
  if (!force && _inFlightSubPromise) {
    return _inFlightSubPromise;
  }

  _inFlightSubPromise = (async () => {
    try {
      const headers = await getBearerHeaders();
      if (!headers.Authorization) return null;
      const res = await fetch("/api/billing/subscription", {
        headers,
        cache: "no-store",
      });
      if (!res.ok) return null;
      const data = (await res.json()) as SubscriptionSummary;
      _cachedSubscription = data;
      _cachedSubExpiresAt = Date.now() + 4000; // 4s TTL to eliminate duplicate calls on same page
      return data;
    } catch {
      return null;
    } finally {
      _inFlightSubPromise = null;
    }
  })();

  return _inFlightSubPromise;
}

export async function createCheckoutSession(
  planId: "pass" = "pass",
): Promise<CheckoutCreatedResponse> {
  const headers = await getBearerHeaders({ "Content-Type": "application/json" });
  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers,
    body: JSON.stringify({ plan_id: planId }),
  });
  if (!res.ok) throw await readBillingError(res);
  return (await res.json()) as CheckoutCreatedResponse;
}

export async function getCheckoutSession(
  sessionId: string,
): Promise<CheckoutStatusResponse> {
  const headers = await getBearerHeaders();
  const res = await fetch(
    `/api/billing/checkout/${encodeURIComponent(sessionId)}`,
    {
      headers,
      cache: "no-store",
    },
  );
  if (!res.ok) throw await readBillingError(res);
  return (await res.json()) as CheckoutStatusResponse;
}

export async function recheckCheckoutSession(
  sessionId: string,
): Promise<CheckoutStatusResponse> {
  const headers = await getBearerHeaders();
  const res = await fetch(
    `/api/billing/checkout/${encodeURIComponent(sessionId)}/recheck`,
    {
      method: "POST",
      headers,
    },
  );
  if (!res.ok) throw await readBillingError(res);
  return (await res.json()) as CheckoutStatusResponse;
}

export function notifySubscriptionUpdated(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("proofit:subscription-updated"));
  }
}
