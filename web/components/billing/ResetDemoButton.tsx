"use client";

import { useEntitlement } from "@/lib/billing/entitlement";

export function ResetDemoButton() {
  const { isPassActive, isDemoPayments, clearDemo } = useEntitlement();

  if (!isDemoPayments || !isPassActive) return null;

  return (
    <button
      type="button"
      onClick={clearDemo}
      className="inline-flex items-center gap-1 font-mono text-xs text-accent underline underline-offset-4 transition-colors hover:text-accent-2"
      title="Reset demo Job Hunt Pass back to Free tier"
    >
      <span>Reset demo purchase</span>
      <span aria-hidden="true">↺</span>
    </button>
  );
}

